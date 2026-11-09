"""Adapters between the demo API and Scheme Saathi's existing rule workflow."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Iterator
from uuid import uuid4

from langgraph.types import Command
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agents.base import StructuredGPTAgent
from agents.contracts import IntakeResult
from agents.model_factory import create_chat_model
from app.document_storage import DocumentStorageError, LocalDocumentStore
from app.forget import household_threads
from app.thread_registry import ThreadRegistry, TouchResult
from graph import tools
from graph.tools import ToolCallError
from graph.workflow import build_graph
from observability.hooks import note_run_error, record_thread_expired

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
    actor_id: str | None = None
    facts: dict[str, Any] = field(default_factory=dict)
    lock: Lock = field(default_factory=Lock)
    completed: bool = False
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)


class SessionNotFoundError(LookupError):
    """Raised when an API request refers to an unknown workflow session."""


class WorkflowConflictError(RuntimeError):
    """Raised when a workflow action is not valid for its current state."""


class ThreadAccessError(PermissionError):
    """The authenticated household does not own this demo workflow."""


class DemoService:
    """Run reviewed rules and mock application workflows for the local demo."""

    def __init__(
        self,
        intake_agent: Any | None = None,
        document_store: LocalDocumentStore | None = None,
        checkpointer: Any | None = None,
        registry: ThreadRegistry | None = None,
    ) -> None:
        self.workflow = build_graph(checkpointer=checkpointer)
        self.registry = registry or ThreadRegistry("application")
        self._uploads: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
        self._uploads_lock = Lock()
        self._document_store = document_store
        self._document_store_lock = Lock()
        self._intake_agent = intake_agent
        self._intake_agent_lock = Lock()
        self._chat_sessions: dict[str, ChatSession] = {}
        self._chat_sessions_lock = Lock()
        self._thread_owners: dict[str, str] = {}
        self._thread_owners_lock = Lock()
        self._thread_subjects: dict[str, tuple[str, str | None]] = {}

    def chat_turn(
        self,
        user_input: str,
        session_id: str | None = None,
        actor_id: str | None = None,
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        """Gather rule facts conversationally, then stream a deterministic rule check."""
        yield "progress", {"label": "Reading your message"}
        try:
            chat_id, session = self._get_or_create_chat_session(session_id, actor_id)
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
            ThreadAccessError,
            ToolCallError,
            RuntimeError,
            ValueError,
            ValidationError,
        ) as error:
            note_run_error(error)
            if isinstance(error, ThreadAccessError):
                yield "error", {"detail": "The chat session was not found."}
            elif isinstance(error, ToolCallError):
                logger.warning("A conversational workflow tool call failed.")
                yield "error", {
                    "detail": "A required workflow tool call could not be completed."
                }
            else:
                logger.exception("The conversational eligibility flow failed.")
                yield "error", {"detail": str(error)}

    def _get_or_create_chat_session(
        self, session_id: str | None, actor_id: str | None = None
    ) -> tuple[str, ChatSession]:
        if session_id:
            with self._chat_sessions_lock:
                session = self._chat_sessions.get(session_id)
                if session is not None and self._chat_session_expired(session):
                    del self._chat_sessions[session_id]  # expired: never revived by use
                    record_thread_expired("chat_session", "on_use")
                    session = None
            if session is None:
                raise SessionNotFoundError("The chat session was not found.")
            if session.actor_id != actor_id:
                raise ThreadAccessError("The chat session belongs to another household.")
            session.last_used = self.registry.now()
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
            actor_id=actor_id,
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
        # Ask the rule engine (live rules only) rather than re-reading its folders here.
        kinds = {"number": (int, float), "bool": (bool,), "str": (str,)}
        return {name: kinds[spec["type"]] for name, spec in tools.field_specs(scheme_ids).items()}

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
        self,
        citizen: dict[str, Any],
        scheme_ids: list[str] | None = None,
        actor_id: str | None = None,
        subject: str = "self",
        relation: str | None = None,
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        """Validate schemes and return a stream for a new eligibility workflow.

        `subject` and `relation` say whose application this is, so a saved reference can
        later be listed as the person's own or as someone else's.
        """
        tools.search_schemes({}, scheme_ids)
        thread_id = str(uuid4())
        if actor_id is not None:
            with self._thread_owners_lock:
                self._thread_owners[thread_id] = actor_id
            self.registry.touch(thread_id, actor_id)
            self.registry.set_subject(thread_id, actor_id, subject, relation)  # kept with the thread, so a restart keeps it
        self._thread_subjects[thread_id] = (subject, relation)
        config = {"configurable": {"thread_id": thread_id}}
        run_input: dict[str, Any] = {"simulated_citizen": citizen}
        if actor_id is not None:
            run_input["actor_id"] = actor_id
        if scheme_ids:
            run_input["scheme_ids"] = scheme_ids
        return self._stream_run(run_input, config, thread_id)

    def thread_subject(self, thread_id: str) -> tuple[str, str | None]:
        """Whose application a thread is for: ("self", None), or ("other", a relation word).

        After a restart it is read back from the thread record kept with the workflow, so a
        family member's application is not taken for the signed-in person's own.
        """
        subject = self._thread_subjects.get(thread_id)
        if subject is None:
            subject = self.registry.subject_of(thread_id)
            if subject is not None:
                self._thread_subjects[thread_id] = subject
        return subject or ("self", None)

    def decide(
        self,
        thread_id: str,
        action: str,
        payload_hash: str | None,
        changes: dict[str, Any],
        actor_id: str | None = None,
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        """Validate an application decision and resume the matching workflow."""
        self._check_thread_owner(thread_id, actor_id)
        self._touch(thread_id, actor_id)
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
            load_dotenv()
            if not os.getenv("MOCK_PORTAL_AUTH_SECRET"):
                raise WorkflowConflictError(
                    "Mock submission is not configured. Set MOCK_PORTAL_AUTH_SECRET "
                    "in the API environment before approving; this draft is still awaiting approval."
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
        sensitive_ids_masked: bool,
        actor_id: str | None = None,
    ) -> dict[str, Any]:
        """Validate and retain a required document in local storage."""
        self._check_thread_owner(thread_id, actor_id)
        self._touch(thread_id, actor_id)
        if not sensitive_ids_masked:
            raise ValueError(
                "Mask full Aadhaar, bank-account, and other ID numbers before upload."
            )
        if not content or len(content) > MAX_DOCUMENT_SIZE:
            raise ValueError("Choose a non-empty document smaller than 10 MB.")

        safe_filename = Path(filename.replace("\\", "/")).name
        safe_filename = (
            safe_filename.replace('"', "_")
            .replace("\r", "_")
            .replace("\n", "_")
        )
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

        upload = self._get_document_store().store(
            thread_id=thread_id,
            scheme_id=scheme_id,
            document_type=document_type,
            filename=safe_filename,
            content_type=mime_type or expected[0],
            content=content,
            household_id=actor_id,
        )
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

    def _check_thread_owner(self, thread_id: str, actor_id: str | None) -> None:
        if actor_id is None:
            return
        if self.registry.is_expired(thread_id):
            record_thread_expired("application", "on_use")
            self._delete_expired({thread_id})  # delete it now, and report it as unknown
            raise SessionNotFoundError("The application session was not found.")
        with self._thread_owners_lock:
            owner = self._thread_owners.get(thread_id)
        if owner is None:
            owner = self.registry.owner_of(thread_id)  # a thread from before a restart
        if owner is None:
            raise SessionNotFoundError("The application session was not found.")
        if owner != actor_id:
            raise ThreadAccessError("The application session belongs to another household.")

    def _touch(self, thread_id: str, actor_id: str | None) -> None:
        """Note that the thread was used, which keeps it from expiring as idle.

        A thread that expired in the meantime is deleted and refused instead of being revived.
        """
        if actor_id is None:
            return
        outcome = self.registry.touch(thread_id, actor_id)
        if outcome is TouchResult.EXPIRED:
            record_thread_expired("application", "on_use")
            self._delete_expired({thread_id})
            raise SessionNotFoundError("The application session was not found.")
        if outcome is TouchResult.NOT_OWNER:
            raise ThreadAccessError("The application session belongs to another household.")

    def _missing_documents(self, thread_id: str, scheme_id: str | None) -> list[str]:
        if not scheme_id:
            return []
        snapshot = self._get_snapshot(thread_id)
        required = snapshot.values.get("documents", {}).get(scheme_id, [])
        uploaded_documents = self._list_uploaded_documents(thread_id, scheme_id)
        uploaded = {item["document_type"] for item in uploaded_documents}
        return [document for document in required if document not in uploaded]

    def get_uploaded_document(
        self,
        thread_id: str,
        scheme_id: str,
        document_type: str,
        actor_id: str | None = None,
    ) -> tuple[bytes, dict[str, Any]]:
        """Retrieve an upload belonging to the caller's household."""
        self._check_thread_owner(thread_id, actor_id)
        return self._get_document_store().get_document(
            thread_id, scheme_id, document_type
        )

    def delete_uploaded_documents(
        self, thread_id: str, actor_id: str | None = None
    ) -> int:
        """Delete every retained upload belonging to one workflow thread."""
        self._check_thread_owner(thread_id, actor_id)
        manifest_path = (
            LocalDocumentStore.configured_directory() / "manifest.json"
        )
        if self._document_store is None and not manifest_path.exists():
            with self._uploads_lock:
                self._uploads.pop(thread_id, None)
            return 0
        deleted = self._get_document_store().delete_thread(thread_id)
        with self._uploads_lock:
            self._uploads.pop(thread_id, None)
        return deleted

    def _household_threads(self, household_id: str) -> set[str]:
        """Threads the household owns, from the owner table, the registry and the saved workflow state."""
        with self._thread_owners_lock:
            threads = {thread for thread, owner in self._thread_owners.items() if owner == household_id}
        threads |= self.registry.threads_of(household_id)
        return threads | household_threads(getattr(self.workflow, "checkpointer", None), household_id)

    def _existing_document_store(self) -> LocalDocumentStore | None:
        """The document store, or None when nothing was ever stored and none is open."""
        manifest_path = LocalDocumentStore.configured_directory() / "manifest.json"
        if self._document_store is None and not manifest_path.exists():
            return None
        return self._get_document_store()

    def _drop_threads(self, threads: set[str]) -> None:
        """Remove the in-process and saved state of threads, and their owners."""
        saver = getattr(self.workflow, "checkpointer", None)
        if saver is not None:
            for thread_id in threads:
                saver.delete_thread(thread_id)
        with self._thread_owners_lock:
            for thread_id in threads:
                self._thread_owners.pop(thread_id, None)
        for thread_id in threads:
            self._thread_subjects.pop(thread_id, None)
        with self._uploads_lock:
            for thread_id in threads:
                self._uploads.pop(thread_id, None)
        self.registry.forget(threads)

    def forget_household_documents(self, household_id: str) -> int:
        """Delete every retained upload of the household, from this session and from earlier ones."""
        threads = self._household_threads(household_id)
        store = self._existing_document_store()
        deleted = store.delete_household(household_id, threads) if store is not None else 0
        with self._uploads_lock:
            for thread_id in threads:
                self._uploads.pop(thread_id, None)
        return deleted

    def forget_household_workflows(self, household_id: str) -> int:
        """Forget the household's application workflows: saved state, owners and chat sessions."""
        threads = self._household_threads(household_id)
        self._drop_threads(threads)
        with self._chat_sessions_lock:
            sessions = [key for key, session in self._chat_sessions.items() if session.actor_id == household_id]
            for key in sessions:
                del self._chat_sessions[key]
        return len(threads) + len(sessions)

    def _delete_expired(self, threads: set[str]) -> int:
        """Delete workflows with their uploads, saved state and owners; returns the uploads deleted."""
        deleted = 0
        store = self._existing_document_store()
        if store is not None:
            for thread_id in threads:
                deleted += store.delete_thread(thread_id)
        self._drop_threads(threads)
        return deleted

    def delete_workflow(self, thread_id: str, actor_id: str | None = None) -> int:
        """Delete one application workflow the caller owns: saved state, uploads, owner and subject.

        An unknown or expired thread is reported as not found, and another household's is refused.
        Returns how many uploaded documents were deleted.
        """
        self._check_thread_owner(thread_id, actor_id)
        return self._delete_expired({thread_id})

    def _chat_session_expired(self, session: ChatSession) -> bool:
        now = self.registry.now()
        return (
            now - session.last_used > self.registry.idle_seconds
            or now - session.created_at > self.registry.absolute_seconds
        )

    def expire_idle(self) -> int:
        """Delete workflows idle for 24 hours or started 7 days ago, with their uploads and chat sessions."""
        threads = set(self.registry.expired())
        if threads:
            self._delete_expired(threads)
            record_thread_expired("application", "cleanup", len(threads))
        with self._chat_sessions_lock:
            stale = [key for key, session in self._chat_sessions.items() if self._chat_session_expired(session)]
            for key in stale:
                del self._chat_sessions[key]
        record_thread_expired("chat_session", "cleanup", len(stale))
        return len(threads) + len(stale)

    def _list_uploaded_documents(
        self, thread_id: str, scheme_id: str
    ) -> list[dict[str, Any]]:
        if self._document_store is not None:
            return self._document_store.list_documents(thread_id, scheme_id)

        manifest_path = (
            LocalDocumentStore.configured_directory() / "manifest.json"
        )
        if manifest_path.exists():
            return self._get_document_store().list_documents(thread_id, scheme_id)

        with self._uploads_lock:
            uploads = self._uploads.get(thread_id, {}).get(scheme_id, {})
            return list(uploads.values())

    def _get_document_store(self) -> LocalDocumentStore:
        if self._document_store is None:
            with self._document_store_lock:
                if self._document_store is None:
                    self._document_store = LocalDocumentStore.from_environment()
        return self._document_store

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
            note_run_error(error)
            logger.warning("A Scheme Saathi workflow tool failed.")
            if isinstance(run_input, Command) and self.workflow.get_state(config).next == ("submit",):
                yield "error", {
                    "detail": (
                        "Approval was recorded, but mock submission did not complete successfully. "
                        "The submission outcome may be unknown; check the mock portal before "
                        "starting another application."
                    )
                }
                return
            yield "error", {
                "detail": "A required workflow tool call could not be completed."
            }

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


# ============================================================================
# DEMO API MODELS (Legacy)
# ============================================================================
