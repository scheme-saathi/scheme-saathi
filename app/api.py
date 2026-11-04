"""FastAPI endpoints for the Streamlit Scheme Saathi demo and GPT agent orchestration."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any, Iterator, Literal
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Header, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from urllib.parse import quote

from agents.base import StructuredGPTAgent
from agents.contracts import IntakeResult
from agents.model_factory import create_chat_model
from graph import tools
from graph.tools import ToolCallError
from graph.workflow import build_graph
from servers.rule_engine.scheme import SchemeRecord, live_conditions
from graph.agent_workflow import build_agent_graph, AgentSet, AgentWorkflowState
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from agents.supervisor import SupervisorAgent
from agents.contracts import Language
from app.document_storage import (
    DocumentStorageError,
    LocalDocumentStore,
)

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

    def __init__(
        self,
        intake_agent: Any | None = None,
        document_store: LocalDocumentStore | None = None,
    ) -> None:
        self.workflow = build_graph()
        self._uploads: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
        self._uploads_lock = Lock()
        self._document_store = document_store
        self._document_store_lock = Lock()
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
        sensitive_ids_masked: bool,
    ) -> dict[str, Any]:
        """Validate and retain a required document in local storage."""
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

    def _missing_documents(self, thread_id: str, scheme_id: str | None) -> list[str]:
        if not scheme_id:
            return []
        snapshot = self._get_snapshot(thread_id)
        required = snapshot.values.get("documents", {}).get(scheme_id, [])
        uploaded_documents = self._list_uploaded_documents(thread_id, scheme_id)
        uploaded = {item["document_type"] for item in uploaded_documents}
        return [document for document in required if document not in uploaded]

    def get_uploaded_document(
        self, thread_id: str, scheme_id: str, document_type: str
    ) -> tuple[bytes, dict[str, Any]]:
        """Retrieve an upload by its unguessable workflow thread ID."""
        return self._get_document_store().get_document(
            thread_id, scheme_id, document_type
        )

    def delete_uploaded_documents(self, thread_id: str) -> int:
        """Delete every retained upload belonging to one workflow thread."""
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


# ============================================================================
# DEMO API MODELS (Legacy)
# ============================================================================

class AnalysisRequest(BaseModel):
    citizen: dict[str, Any]
    scheme_ids: list[str] | None = Field(default=None, min_length=1)


class DecisionRequest(BaseModel):
    action: Literal["approve", "edit", "reject"]
    payload_hash: str | None = None
    changes: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    user_input: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None


# ============================================================================
# SUPERVISOR AGENT API MODELS
# ============================================================================

class SupervisorChatRequest(BaseModel):
    """Request to send message through supervisor agent."""
    message: str = Field(min_length=1, max_length=5000, description="User message")
    actor_id: str = Field(min_length=1, description="Household/user identifier")
    thread_id: str | None = Field(None, description="Conversation thread ID")
    language: Language | None = Field(None, description="Language hint (en, hi, mr)")
    known_facts: dict[str, Any] = Field(
        default_factory=dict, description="Previously collected facts"
    )
    confirmed_facts: dict[str, Any] = Field(
        default_factory=dict, description="Facts the person has confirmed; only these fill the application form"
    )
    selected_scheme_id: str | None = Field(None, description="Selected scheme ID")
    include_draft: bool = Field(False, description="Include draft rules")


class ApprovalDecisionRequest(BaseModel):
    """A person's decision on the exact form that is waiting for approval."""
    action: Literal["approve", "edit", "reject"]
    payload_hash: str | None = Field(None, description="Hash of the form being approved")
    changes: dict[str, Any] = Field(default_factory=dict, description="Fact changes for an edit")


class Plan(BaseModel):
    """Supervisor routing plan."""
    next_agent: str
    reason: str


class RateLimit(BaseModel):
    """Rate limit information."""
    remaining_requests: int
    reset_in_seconds: int


class SupervisorChatResponse(BaseModel):
    """Response from supervisor agent."""
    status: Literal["success"]
    thread_id: str
    language: Language
    intent: str
    next_step: str
    response: str
    data: dict[str, Any] = Field(default_factory=dict)
    rate_limit: RateLimit


class ErrorResponse(BaseModel):
    """Error response."""
    status: Literal["validation_error", "routing_error", "agent_error", "rate_limited"]
    error_code: str
    message: str
    language: str
    details: dict[str, Any] = Field(default_factory=dict)
    thread_id: str | None = None


class SessionContext(BaseModel):
    """Session context and collected facts."""
    thread_id: str
    actor_id: str
    known_facts: dict[str, Any]
    selected_scheme_id: str | None = None
    eligibility_verdicts: dict[str, Any] | None = None
    documents_required: list[str] | None = None
    application_draft: dict[str, Any] | None = None
    last_interaction: datetime


class ConversationTurn(BaseModel):
    """Single turn in conversation."""
    turn_number: int
    user_message: str
    user_language: Language
    detected_intent: str
    supervisor_plan: dict[str, Any]
    agent_called: str
    agent_response: dict[str, Any]
    timestamp: datetime


class ConversationHistory(BaseModel):
    """Full conversation history."""
    thread_id: str
    actor_id: str
    turns: list[ConversationTurn]
    created_at: datetime
    last_interaction: datetime


class LanguageInfo(BaseModel):
    """Supported languages info."""
    code: Language
    name: str
    native_name: str


# ============================================================================
# DEMO SERVICE
# ============================================================================

@lru_cache(maxsize=1)
def get_service() -> DemoService:
    """Share one in-memory demo workflow across requests."""
    return DemoService()


# ============================================================================
# AGENT WORKFLOW SERVICE
# ============================================================================

class ThreadNotFoundError(LookupError):
    """The conversation thread does not exist."""


class ThreadAccessError(PermissionError):
    """The caller does not own this conversation thread."""


class NoPendingApprovalError(RuntimeError):
    """A decision was sent but no draft is waiting for approval."""


class ApprovalPendingError(RuntimeError):
    """A new message was sent while a draft is waiting for approval."""


class AgentWorkflowService:
    """Service to manage agent workflow execution."""
    
    def __init__(self):
        self._agent_graph = None  # Lazy-loaded on first use
        self.conversations: dict[str, dict[str, Any]] = {}  # thread_id -> conversation data
        self.session_contexts: dict[str, dict[str, Any]] = {}  # thread_id -> context
    
    @property
    def agent_graph(self):
        """Lazy-load the agent graph on first access."""
        if self._agent_graph is None:
            logger.info("Initializing agent graph (lazy-loaded)...")
            self._agent_graph = build_agent_graph(checkpointer=MemorySaver())
            logger.info("Agent graph initialized successfully")
        return self._agent_graph
        
    def create_thread(self, actor_id: str, thread_id: str | None = None) -> str:
        """Create new conversation thread."""
        thread_id = thread_id or f"conv_{uuid4().hex[:12]}"
        self.conversations[thread_id] = {
            "thread_id": thread_id,
            "actor_id": actor_id,
            "created_at": datetime.now(),
            "turns": [],
        }
        self.session_contexts[thread_id] = {
            "thread_id": thread_id,
            "actor_id": actor_id,
            "known_facts": {},
            "selected_scheme_id": None,
        }
        return thread_id
    
    def execute_workflow(
        self,
        request: str,
        actor_id: str,
        thread_id: str | None = None,
        known_facts: dict[str, Any] | None = None,
        selected_scheme_id: str | None = None,
        confirmed_facts: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute agent workflow."""
        if thread_id is None:
            thread_id = self.create_thread(actor_id)
        elif thread_id not in self.conversations:
            self.create_thread(actor_id, thread_id)
        self._check_owner(thread_id, actor_id)

        config = self._config(thread_id)
        if self._pending_approval(config) is not None:
            raise ApprovalPendingError(
                "This conversation is waiting for you to approve, edit or reject what was shown."
            )

        # Keep facts and the chosen scheme from earlier turns unless this turn supplies new ones.
        state = AgentWorkflowState(request=request)
        if known_facts:
            state["known_facts"] = known_facts
        if confirmed_facts:
            state["confirmed_facts"] = confirmed_facts
        if selected_scheme_id:
            state["selected_scheme_id"] = selected_scheme_id

        return self._finish_run(thread_id, request, self.agent_graph.invoke(state, config))

    def _check_owner(self, thread_id: str, actor_id: str) -> None:
        if self.conversations[thread_id].get("actor_id") != actor_id:
            raise ThreadAccessError(thread_id)

    def submit_decision(
        self,
        thread_id: str,
        actor_id: str,
        action: str,
        payload_hash: str | None,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        """Resume the paused graph with the person's decision on the exact form."""
        if thread_id not in self.conversations:
            raise ThreadNotFoundError(thread_id)
        self._check_owner(thread_id, actor_id)
        config = self._config(thread_id)
        if self._pending_approval(config) is None:
            raise NoPendingApprovalError("There is no draft waiting for approval in this conversation.")

        decision = {"action": action, "payload_hash": payload_hash, "changes": changes}
        result = self.agent_graph.invoke(Command(resume=decision), config)
        return self._finish_run(thread_id, f"[decision: {action}]", result)

    def _config(self, thread_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": thread_id}}

    def _pending_approval(self, config: dict[str, Any]) -> dict[str, Any] | None:
        """The form waiting for a person, or None when the graph is not paused."""
        for task in self.agent_graph.get_state(config).tasks:
            for pending in task.interrupts:
                return pending.value
        return None

    def _finish_run(self, thread_id: str, request: str, result: dict[str, Any]) -> dict[str, Any]:
        pending = self._pending_approval(self._config(thread_id))
        data = {key: value for key, value in result.items() if key != "__interrupt__"}
        if pending is not None and pending.get("kind") == "confirm_facts":
            data["confirmation"] = pending
            status = "awaiting_confirmation"
            response = "Please check these details. The final answer uses only the details you confirm."
        elif pending is not None:
            data["approval"] = pending
            status = "awaiting_approval"
            response = "Please review the draft application. Nothing is submitted until you approve."
        else:
            status = result.get("status", "completed")
            response = result.get("response", "")

        self._store_turn(thread_id, request, {**data, "status": status, "response": response})
        return {"thread_id": thread_id, "status": status, "response": response, "data": data}

    def _store_turn(
        self, thread_id: str, user_message: str, result: dict[str, Any]
    ) -> None:
        """Store conversation turn."""
        if thread_id not in self.conversations:
            self.conversations[thread_id] = {"turns": []}
        
        turn = {
            "turn_number": len(self.conversations[thread_id]["turns"]) + 1,
            "user_message": user_message,
            "timestamp": datetime.now(),
            "result": result,
        }
        self.conversations[thread_id]["turns"].append(turn)
    
    def get_conversation(self, thread_id: str) -> dict[str, Any] | None:
        """Get conversation by thread ID."""
        return self.conversations.get(thread_id)
    
    def get_context(self, thread_id: str) -> dict[str, Any] | None:
        """Get session context by thread ID."""
        return self.session_contexts.get(thread_id)
    
    def reset_context(self, thread_id: str) -> None:
        """Reset context but keep history."""
        if thread_id in self.session_contexts:
            self.session_contexts[thread_id] = {
                "thread_id": thread_id,
                "actor_id": self.session_contexts[thread_id]["actor_id"],
                "known_facts": {},
                "selected_scheme_id": None,
            }
    
    def delete_conversation(self, thread_id: str) -> None:
        """Delete conversation (GDPR)."""
        if thread_id in self.conversations:
            del self.conversations[thread_id]
        if thread_id in self.session_contexts:
            del self.session_contexts[thread_id]


@lru_cache(maxsize=1)
def get_workflow_service() -> AgentWorkflowService:
    """Get singleton workflow service."""
    return AgentWorkflowService()


# ============================================================================
# EVENT STREAMING HELPER
# ============================================================================

def _event_stream(
    events: Any,
) -> StreamingResponse:
    def encode_events():
        for name, payload in events:
            data = json.dumps(payload, ensure_ascii=False, default=str)
            yield f"event: {name}\ndata: {data}\n\n"

    return StreamingResponse(
        encode_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ============================================================================
# API FACTORY
# ============================================================================

def create_api(service: DemoService | None = None) -> FastAPI:
    """Create the API app; a service can be injected by endpoint tests."""
    demo = service or get_service()
    
    # Don't initialize workflow service here - it will be lazily loaded on first use
    # This allows app import to complete quickly without initializing models
    
    application = FastAPI(
        title="Scheme Saathi Agent API",
        version="1.0.0",
        description="GPT agent orchestration for government scheme assistance",
    )

    # ========================================================================
    # HEALTH & METADATA ENDPOINTS
    # ========================================================================

    @application.get("/health", tags=["System"])
    def health() -> dict[str, str]:
        """Health check endpoint."""
        return {"status": "ok"}

    @application.get("/api/languages", tags=["Metadata"])
    def get_languages() -> dict[str, list[LanguageInfo]]:
        """Get supported languages."""
        return {
            "languages": [
                LanguageInfo(code="en", name="English", native_name="English"),
                LanguageInfo(code="hi", name="Hindi", native_name="हिंदी"),
                LanguageInfo(code="mr", name="Marathi", native_name="मराठी"),
            ]
        }

    # ========================================================================
    # SUPERVISOR AGENT ENDPOINTS
    # ========================================================================

    @application.post("/api/chat", response_model=SupervisorChatResponse, responses={400: {"model": ErrorResponse}, 429: {"model": ErrorResponse}}, tags=["Agent Workflow"],)
    def chat_with_supervisor(
        request: SupervisorChatRequest,
        x_actor_id: str | None = Header(None),
        x_thread_id: str | None = Header(None),
    ) -> SupervisorChatResponse:
        """Send message through supervisor agent for intelligent routing."""
        try:
            actor_id = x_actor_id or request.actor_id
            thread_id = x_thread_id or request.thread_id
            
            # Get workflow service (lazy-loaded on first call)
            workflow = get_workflow_service()
            
            # Execute workflow
            result = workflow.execute_workflow(
                request=request.message,
                actor_id=actor_id,
                thread_id=thread_id,
                known_facts=request.known_facts,
                selected_scheme_id=request.selected_scheme_id,
                confirmed_facts=request.confirmed_facts,
            )
            
            return SupervisorChatResponse(
                status="success",
                thread_id=result["thread_id"],
                language=request.language or "unknown",
                intent=request.language or "other",
                next_step=result.get("status", "completed"),
                response=result.get("response", ""),
                data=result.get("data", {}),
                rate_limit=RateLimit(remaining_requests=9, reset_in_seconds=60),
            )
        except ThreadAccessError:
            raise HTTPException(status_code=403, detail="This conversation belongs to another user.")
        except ApprovalPendingError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except Exception:
            logger.exception("Error in chat endpoint")
            raise HTTPException(status_code=500, detail="The request could not be processed.")

    @application.post(
        "/api/chat/{thread_id}/decision",
        response_model=SupervisorChatResponse,
        responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
        tags=["Agent Workflow"],
    )
    def decide_on_draft(
        thread_id: str,
        decision: ApprovalDecisionRequest,
        x_actor_id: str = Header(...),
    ) -> SupervisorChatResponse:
        """Approve, edit or reject the exact form the graph is waiting on."""
        try:
            result = get_workflow_service().submit_decision(
                thread_id, x_actor_id, decision.action, decision.payload_hash, decision.changes
            )
        except ThreadNotFoundError:
            raise HTTPException(status_code=404, detail="Thread not found")
        except ThreadAccessError:
            raise HTTPException(status_code=403, detail="This conversation belongs to another user.")
        except NoPendingApprovalError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except Exception:
            logger.exception("Error resuming approval")
            raise HTTPException(status_code=500, detail="The decision could not be processed.")
        return SupervisorChatResponse(
            status="success",
            thread_id=result["thread_id"],
            language="unknown",
            intent="other",
            next_step=result["status"],
            response=result["response"],
            data=result["data"],
            rate_limit=RateLimit(remaining_requests=9, reset_in_seconds=60),
        )

    @application.get("/api/chat/{thread_id}", response_model=SupervisorChatResponse, tags=["Agent Workflow"], )
    def get_chat_response(thread_id: str) -> dict[str, Any]:
        """Get latest response from conversation thread."""
        workflow = get_workflow_service()
        conversation = workflow.get_conversation(thread_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Thread not found")
        
        if not conversation["turns"]:
            raise HTTPException(status_code=404, detail="No turns in conversation")
        
        latest_turn = conversation["turns"][-1]
        return {
            "status": "success",
            "thread_id": thread_id,
            "response": latest_turn["result"].get("response", ""),
            "timestamp": latest_turn["timestamp"],
        }

    @application.get("/api/chat/{thread_id}/history", response_model=ConversationHistory, tags=["Agent Workflow"], )
    def get_conversation_history(
        thread_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> ConversationHistory:
        """Get full conversation history."""
        workflow = get_workflow_service()
        conversation = workflow.get_conversation(thread_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Thread not found")
        
        turns_data = conversation["turns"][offset : offset + limit]
        turns = [
            ConversationTurn(
                turn_number=t["turn_number"],
                user_message=t["user_message"],
                user_language="unknown",
                detected_intent="other",
                supervisor_plan={},
                agent_called="unknown",
                agent_response=t.get("result", {}),
                timestamp=t["timestamp"],
            )
            for t in turns_data
        ]
        
        return ConversationHistory(
            thread_id=thread_id,
            actor_id=conversation.get("actor_id", ""),
            turns=turns,
            created_at=conversation.get("created_at", datetime.now()),
            last_interaction=conversation["turns"][-1]["timestamp"]
            if conversation["turns"]
            else datetime.now(),
        )

    @application.get("/api/chat/{thread_id}/context", response_model=SessionContext, tags=["Agent Workflow"],)
    def get_session_context(thread_id: str) -> SessionContext:
        """Get current session context and collected facts."""
        workflow = get_workflow_service()
        context = workflow.get_context(thread_id)
        if not context:
            raise HTTPException(status_code=404, detail="Context not found")
        
        return SessionContext(
            thread_id=thread_id,
            actor_id=context.get("actor_id", ""),
            known_facts=context.get("known_facts", {}),
            selected_scheme_id=context.get("selected_scheme_id"),
            last_interaction=datetime.now(),
        )

    @application.post("/api/chat/{thread_id}/restart", tags=["Agent Workflow"], )
    def restart_session_context(thread_id: str) -> dict[str, Any]:
        """Reset session context but keep conversation history."""
        workflow = get_workflow_service()
        context = workflow.get_context(thread_id)
        if not context:
            raise HTTPException(status_code=404, detail="Context not found")
        
        workflow.reset_context(thread_id)
        return {
            "status": "success",
            "message": "Context reset. Conversation history preserved.",
            "thread_id": thread_id,
            "facts_cleared": list(context.get("known_facts", {}).keys()),
        }

    @application.delete("/api/chat/{thread_id}", tags=["Agent Workflow"],)
    def delete_chat_conversation(thread_id: str) -> dict[str, Any]:
        """Delete entire conversation (GDPR compliance)."""
        workflow = get_workflow_service()
        conversation = workflow.get_conversation(thread_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Thread not found")
        
        deleted_turns = len(conversation.get("turns", []))
        workflow.delete_conversation(thread_id)
        
        return {
            "status": "success",
            "message": "Conversation deleted",
            "thread_id": thread_id,
            "deleted_turns": deleted_turns,
        }

    # ========================================================================
    # DEMO API ENDPOINTS (Legacy)
    # ========================================================================

    @application.get("/api/schemes", tags=["Demo"])
    def schemes() -> dict[str, list[dict[str, Any]]]:
        try:
            return {"schemes": demo.available_schemes()}
        except ToolCallError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @application.post("/api/analyze", tags=["Demo"])
    def analyze(payload: AnalysisRequest) -> StreamingResponse:
        try:
            events = demo.analyze(payload.citizen, payload.scheme_ids)
        except ToolCallError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return _event_stream(events)

    @application.post("/api/chat/legacy", tags=["Demo"])
    def chat_legacy(payload: ChatRequest) -> StreamingResponse:
        return _event_stream(
            demo.chat_turn(payload.user_input, payload.session_id)
        )

    @application.post("/api/threads/{thread_id}/documents/upload", tags=["Demo"])
    async def upload_document(
        thread_id: str,
        scheme_id: str = Form(...),
        document_type: str = Form(...),
        sensitive_ids_masked: bool = Form(False),
        file: UploadFile = File(...),
    ) -> dict[str, Any]:
        filename = file.filename or ""
        if not filename:
            raise HTTPException(status_code=422, detail="Choose a document file.")
        content = await file.read(10 * 1024 * 1024 + 1)
        try:
            return demo.upload_document(
                thread_id,
                scheme_id,
                document_type,
                filename,
                file.content_type,
                content,
                sensitive_ids_masked,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except SessionNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except WorkflowConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except DocumentStorageError as error:
            logger.exception("Could not store a supporting document.")
            raise HTTPException(
                status_code=500, detail="Could not securely store the document."
            ) from error
        finally:
            await file.close()

    @application.get("/api/threads/{thread_id}/documents/{scheme_id}/{document_type}", tags=["Demo"],)
    def download_document(
        thread_id: str, scheme_id: str, document_type: str
    ) -> Response:
        try:
            content, metadata = demo.get_uploaded_document(
                thread_id, scheme_id, document_type
            )
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except DocumentStorageError as error:
            logger.exception("Could not retrieve a supporting document.")
            raise HTTPException(
                status_code=500,
                detail="Could not securely retrieve the document.",
            ) from error

        filename = metadata["filename"]
        ascii_filename = filename.encode("ascii", "ignore").decode("ascii")
        ascii_filename = ascii_filename.replace('"', "_").replace("\\", "_")
        content_disposition = (
            f'attachment; filename="{ascii_filename or "document"}"; '
            f"filename*=UTF-8''{quote(filename)}"
        )
        return Response(
            content=content,
            media_type=metadata["content_type"],
            headers={"Content-Disposition": content_disposition},
        )

    @application.delete("/api/threads/{thread_id}/documents", tags=["Demo"])
    def delete_documents(thread_id: str) -> dict[str, Any]:
        try:
            deleted = demo.delete_uploaded_documents(thread_id)
        except DocumentStorageError as error:
            logger.exception("Could not delete supporting documents.")
            raise HTTPException(
                status_code=500,
                detail="Could not securely delete supporting documents.",
            ) from error
        return {"status": "success", "deleted_documents": deleted}

    @application.post("/api/threads/{thread_id}/decision", tags=["Demo"])
    def decide(thread_id: str, payload: DecisionRequest) -> StreamingResponse:
        try:
            events = demo.decide(
                thread_id,
                payload.action,
                payload.payload_hash,
                payload.changes,
            )
        except SessionNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except WorkflowConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except DocumentStorageError as error:
            logger.exception("Could not check stored supporting documents.")
            raise HTTPException(
                status_code=500, detail="Could not check stored documents."
            ) from error
        return _event_stream(events)

    return application


app = create_api()
