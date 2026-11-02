"""Adapters between the demo API and Scheme Saathi's existing rule workflow."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Iterator
from uuid import uuid4

from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agents.base import StructuredGPTAgent
from agents.contracts import IntakeResult
from agents.model_factory import create_chat_model
from graph import tools
from graph.tools import ToolCallError
from graph.workflow import build_graph
from servers.rule_engine.scheme import SchemeRecord, live_conditions

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_DOCUMENT_SIZE = 10 * 1024 * 1024
ALLOWED_DOCUMENTS = {
    ".pdf": ("application/pdf", b"%PDF-"),
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
    ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
}
NODE_LABELS = {
    "plan": "Preparing the eligibility check",
    "intake": "Checking profile details",
    "eligibility": "Evaluating reviewed scheme rules",
    "documents": "Finding required documents",
    "draft": "Preparing an application draft",
    "validate": "Validating the draft",
    "approval": "Waiting for your approval",
    "submit": "Recording the mock submission",
    "escalate": "Flagging the case for human review",
}
CHAT_INTAKE_INSTRUCTIONS = """You are Scheme Saathi's conversational intake specialist.
Extract only facts directly stated in the current user message. The required_fields
list contains the exact rule-engine field names you may return; never invent or rename
fields. Use expected_fields to interpret a short answer to the last question. The
income field means annual household income in INR; convert an explicitly monthly
amount to annual income by multiplying by 12, but never guess a time period. Treat
known_facts as context and only update a fact when the current message states it.
Every candidate fact must require user confirmation. Do not determine eligibility,
claim that data was saved, or request Aadhaar, bank-account numbers, or other
sensitive identifiers."""

FIELD_QUESTIONS = {
    "age": "What is your age in years?",
    "income": "What is your annual household income in INR? If you know only the monthly amount, please say that.",
    "is_widow": "Are you a widow or widower? Please answer yes or no.",
}


class ChatIntakeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: str = Field(min_length=1)
    known_facts: dict[str, Any] = Field(default_factory=dict)
    required_fields: list[str]
    expected_fields: list[str]


@dataclass
class ChatSession:
    required_fields: list[str]
    scheme_names: dict[str, str]
    field_types: dict[str, tuple[type, ...]]
    facts: dict[str, Any] = field(default_factory=dict)
    lock: Lock = field(default_factory=Lock)
    completed: bool = False


class SessionNotFoundError(LookupError):
    """Raised when an API request refers to an unknown workflow session."""


class WorkflowConflictError(RuntimeError):
    """Raised when a workflow action is not valid for its current state."""


class DemoService:
    """Run reviewed rules and mock application workflows for the local demo."""

    def __init__(self, intake_agent: Any | None = None) -> None:
        self.workflow = build_graph()
        self._uploads: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
        self._uploads_lock = Lock()
        self._intake_agent = intake_agent
        self._intake_agent_lock = Lock()
        self._chat_sessions: dict[str, ChatSession] = {}
        self._chat_sessions_lock = Lock()

    def chat_turn(
        self, user_input: str, session_id: str | None = None
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        """Gather rule facts conversationally, then stream a deterministic rule check."""
        yield "progress", {"label": "Reading your message"}
        try:
            chat_id, session = self._get_or_create_chat_session(session_id)
            yield "session", {"session_id": chat_id}
            with session.lock:
                if session.completed:
                    yield "assistant", {
                        "content": "This eligibility check is complete. Start a new chat to check another profile."
                    }
                    return

                missing_before = [
                    name
                    for name in session.required_fields
                    if name not in session.facts or session.facts[name] is None
                ]
                yield "progress", {"label": "Understanding the details you shared"}
                intake = self._get_intake_agent().invoke(
                    ChatIntakeInput(
                        request=user_input,
                        known_facts=session.facts,
                        required_fields=session.required_fields,
                        expected_fields=missing_before,
                    )
                )

                rejected_fields: list[str] = []
                for candidate in intake.candidate_facts:
                    if candidate.field not in session.required_fields:
                        continue
                    if candidate.value is None or not self._valid_fact_value(
                        candidate.value, session.field_types.get(candidate.field, ())
                    ):
                        rejected_fields.append(candidate.field)
                        continue
                    session.facts[candidate.field] = candidate.value

                missing = [
                    name
                    for name in session.required_fields
                    if name not in session.facts or session.facts[name] is None
                ]
                if missing:
                    response = self._missing_facts_reply(missing, rejected_fields)
                    yield "assistant", {"content": response}
                    yield "result", {
                        "session_id": chat_id,
                        "status": "needs_details",
                        "missing_fields": missing,
                    }
                    return

                yield "progress", {
                    "label": "Thanks. I have the details needed; checking reviewed scheme rules now."
                }
                scheme_ids = list(session.scheme_names)
                verdicts: dict[str, dict[str, Any]] = {}
                for scheme_id in scheme_ids:
                    yield "progress", {
                        "label": f"Checking {session.scheme_names[scheme_id]}"
                    }
                    verdicts[scheme_id] = tools.evaluate_scheme(
                        session.facts, scheme_id
                    )

                result = {
                    "session_id": chat_id,
                    "status": "eligibility_checked",
                    "profile": dict(session.facts),
                    "verdicts": verdicts,
                    "scheme_names": dict(session.scheme_names),
                }
                session.completed = True
                yield "assistant", {
                    "content": self._eligibility_reply(verdicts, session.scheme_names)
                }
                yield "result", result
        except (
            SessionNotFoundError,
            ToolCallError,
            RuntimeError,
            ValueError,
            ValidationError,
        ) as error:
            logger.exception("The conversational eligibility flow failed.")
            yield "error", {"detail": str(error)}

    def _get_or_create_chat_session(
        self, session_id: str | None
    ) -> tuple[str, ChatSession]:
        if session_id:
            with self._chat_sessions_lock:
                session = self._chat_sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError("The chat session was not found.")
            return session_id, session

        schemes = self.available_schemes()
        if not schemes:
            raise RuntimeError("No schemes with reviewed eligibility rules are available.")
        session = ChatSession(
            required_fields=list(
                dict.fromkeys(
                    field_name
                    for scheme in schemes
                    for field_name in scheme["required_fields"]
                )
            ),
            scheme_names={
                scheme["scheme_id"]: scheme["name"] for scheme in schemes
            },
            field_types=self._rule_field_types(
                [scheme["scheme_id"] for scheme in schemes]
            ),
        )
        chat_id = str(uuid4())
        with self._chat_sessions_lock:
            self._chat_sessions[chat_id] = session
        return chat_id, session

    def _get_intake_agent(self) -> Any:
        if self._intake_agent is None:
            with self._intake_agent_lock:
                if self._intake_agent is None:
                    self._intake_agent = StructuredGPTAgent(
                        create_chat_model("specialist"),
                        ChatIntakeInput,
                        IntakeResult,
                        CHAT_INTAKE_INSTRUCTIONS,
                    )
        return self._intake_agent

    @staticmethod
    def _rule_field_types(scheme_ids: list[str]) -> dict[str, tuple[type, ...]]:
        expected: dict[str, set[type]] = {}
        for directory in (
            PROJECT_ROOT / "data" / "schemes",
            PROJECT_ROOT / "data" / "rules",
        ):
            for path in directory.glob("*.json"):
                payload = json.loads(path.read_text(encoding="utf-8"))
                if "rules" not in payload or "sections" in payload:
                    continue
                scheme = SchemeRecord.model_validate(payload)
                if scheme.scheme_id not in scheme_ids:
                    continue
                for rule in live_conditions(scheme).rules:
                    operand = rule.value[0] if rule.op in {"in", "not_in"} else rule.value
                    expected.setdefault(rule.field, set()).add(type(operand))
        return {
            field_name: tuple(field_types)
            for field_name, field_types in expected.items()
        }

    @staticmethod
    def _valid_fact_value(value: Any, expected_types: tuple[type, ...]) -> bool:
        for expected_type in expected_types:
            if expected_type is bool and isinstance(value, bool):
                return True
            if expected_type in (int, float) and isinstance(
                value, (int, float)
            ) and not isinstance(value, bool):
                return True
            if type(value) is expected_type:
                return True
        return False

    @staticmethod
    def _missing_facts_reply(
        missing: list[str], rejected_fields: list[str]
    ) -> str:
        questions = [
            FIELD_QUESTIONS.get(
                field_name,
                f"What is your {field_name.replace('_', ' ')}?",
            )
            for field_name in missing
        ]
        if rejected_fields:
            intro = (
                "I could not use that answer for "
                + ", ".join(dict.fromkeys(rejected_fields)).replace("_", " ")
                + ". Please provide the missing details:"
            )
        else:
            intro = "I need a little more information before checking eligibility:"
        return intro + "\n\n" + "\n".join(
            f"- {question}" for question in questions
        )

    @staticmethod
    def _eligibility_reply(
        verdicts: dict[str, dict[str, Any]], scheme_names: dict[str, str]
    ) -> str:
        eligible = [
            scheme_id
            for scheme_id, verdict in verdicts.items()
            if verdict.get("verdict") == "eligible"
        ]
        cannot_tell = [
            scheme_id
            for scheme_id, verdict in verdicts.items()
            if verdict.get("verdict") == "cant_tell"
        ]
        if eligible:
            names = ", ".join(
                f"{scheme_names.get(scheme_id, scheme_id)} ({scheme_id})"
                for scheme_id in eligible
            )
            response = f"Based on the details you shared, you may be eligible for: {names}."
        elif cannot_tell:
            response = (
                "I could not determine eligibility for every scheme because "
                "some rule information is incomplete or could not be matched."
            )
        else:
            response = (
                "Based on the details you shared, none of the reviewed schemes "
                "checked appear to match their eligibility rules."
            )
        return (
            response
            + " These results use reviewed rules and are informational, not an official decision."
        )

    def available_schemes(self) -> list[dict[str, Any]]:
        """Return schemes with reviewed rules and their intake/document requirements."""
        scheme_ids = tools.search_schemes({})
        names = {scheme_id: scheme_id for scheme_id in scheme_ids}
        for directory in (
            PROJECT_ROOT / "data" / "schemes",
            PROJECT_ROOT / "data" / "rules",
        ):
            for path in directory.glob("*.json"):
                record = json.loads(path.read_text(encoding="utf-8"))
                scheme_id = record.get("scheme_id")
                if scheme_id in names:
                    names[scheme_id] = record.get("name", scheme_id)

        return [
            {
                "scheme_id": scheme_id,
                "name": names[scheme_id],
                "required_fields": tools.required_fields([scheme_id]),
                "required_documents": tools.list_documents(scheme_id),
            }
            for scheme_id in scheme_ids
        ]

    def analyze(
        self, citizen: dict[str, Any], scheme_ids: list[str] | None = None
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        """Validate schemes and return a stream for a new eligibility workflow."""
        tools.search_schemes({}, scheme_ids)
        thread_id = str(uuid4())
        config = {"configurable": {"thread_id": thread_id}}
        run_input: dict[str, Any] = {"simulated_citizen": citizen}
        if scheme_ids:
            run_input["scheme_ids"] = scheme_ids
        return self._stream_run(run_input, config, thread_id)

    def decide(
        self, thread_id: str, action: str, payload_hash: str | None, changes: dict[str, Any]
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        """Validate an application decision and resume the matching workflow."""
        snapshot = self._get_snapshot(thread_id)
        if "approval" not in snapshot.next:
            raise WorkflowConflictError(
                "This application is not waiting for approval."
            )

        config = {"configurable": {"thread_id": thread_id}}
        decision: dict[str, Any] = {"action": action}
        if action == "approve":
            if not payload_hash:
                raise ValueError("Approving requires the current application hash.")
            application = snapshot.values.get("application", {})
            scheme_id = application.get("scheme_id")
            missing = self._missing_documents(thread_id, scheme_id)
            if missing:
                raise WorkflowConflictError(
                    "Upload all required documents before submitting: "
                    + ", ".join(missing)
                )
            decision["payload_hash"] = payload_hash
        elif action == "edit":
            decision["changes"] = changes
        return self._stream_run(Command(resume=decision), config, thread_id)

    def upload_document(
        self,
        thread_id: str,
        scheme_id: str,
        document_type: str,
        filename: str,
        content_type: str | None,
        content: bytes,
    ) -> dict[str, Any]:
        """Validate a required document and retain upload metadata only."""
        if not content or len(content) > MAX_DOCUMENT_SIZE:
            raise ValueError("Choose a non-empty document smaller than 10 MB.")

        safe_filename = Path(filename.replace("\\", "/")).name
        extension = Path(safe_filename).suffix.lower()
        expected = ALLOWED_DOCUMENTS.get(extension)
        mime_type = (content_type or "").split(";", maxsplit=1)[0].strip().lower()
        if (
            expected is None
            or (mime_type not in (expected[0], "application/octet-stream", ""))
            or not content.startswith(expected[1])
        ):
            raise ValueError("Upload a valid PDF, PNG, or JPEG document.")

        snapshot = self._get_snapshot(thread_id)
        if "approval" not in snapshot.next:
            raise WorkflowConflictError(
                "This application is not waiting for approval."
            )
        required_documents = snapshot.values.get("documents", {}).get(scheme_id)
        if required_documents is None:
            raise ValueError("That scheme is not part of this application.")
        if document_type not in required_documents:
            raise ValueError("That document is not required for the selected scheme.")

        upload = {
            "document_type": document_type,
            "filename": safe_filename,
            "file_size": len(content),
        }
        with self._uploads_lock:
            self._uploads.setdefault(thread_id, {}).setdefault(scheme_id, {})[
                document_type
            ] = upload
            uploaded_documents = list(self._uploads[thread_id][scheme_id])

        return {
            "status": "success",
            **upload,
            "uploaded_documents": uploaded_documents,
            "required_documents": required_documents,
        }

    def _missing_documents(self, thread_id: str, scheme_id: str | None) -> list[str]:
        if not scheme_id:
            return []
        snapshot = self._get_snapshot(thread_id)
        required = snapshot.values.get("documents", {}).get(scheme_id, [])
        with self._uploads_lock:
            uploaded = self._uploads.get(thread_id, {}).get(scheme_id, {})
            return [document for document in required if document not in uploaded]

    def _get_snapshot(self, thread_id: str) -> Any:
        snapshot = self.workflow.get_state(
            {"configurable": {"thread_id": thread_id}}
        )
        if not snapshot.values:
            raise SessionNotFoundError("The application session was not found.")
        return snapshot

    def _stream_run(
        self, run_input: Any, config: dict[str, Any], thread_id: str
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        yield "progress", {"node": "start", "label": "Starting the workflow"}
        try:
            for update in self.workflow.stream(
                run_input, config, stream_mode="updates"
            ):
                for node in update:
                    yield "progress", {
                        "node": node,
                        "label": NODE_LABELS.get(
                            node, node.replace("_", " ").title()
                        ),
                    }
            yield "result", self._snapshot_payload(
                thread_id, self.workflow.get_state(config)
            )
        except ToolCallError as error:
            logger.exception("A Scheme Saathi workflow tool failed.")
            yield "error", {"detail": str(error)}

    @staticmethod
    def _snapshot_payload(thread_id: str, snapshot: Any) -> dict[str, Any]:
        values = snapshot.values
        approval = next(
            (
                interrupt.value
                for task in snapshot.tasks
                for interrupt in task.interrupts
            ),
            None,
        )
        return {
            "thread_id": thread_id,
            "profile": values.get("profile", {}),
            "verdicts": values.get("verdicts", {}),
            "documents": values.get("documents", {}),
            "application": values.get("application", {}),
            "approval": approval,
            "approval_status": values.get("approval_status"),
            "submission": values.get("submission"),
            "needs_human": values.get("needs_human", False),
            "critique": values.get("critique", []),
        }
