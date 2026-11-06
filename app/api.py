"""FastAPI endpoints for the Streamlit Scheme Saathi demo and GPT agent orchestration."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from functools import lru_cache
from typing import Any, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Header, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from urllib.parse import quote

from app.document_storage import DocumentStorageError
from graph.tools import ToolCallError
from graph.agent_workflow import build_agent_graph, AgentSet, AgentWorkflowState
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from agents.supervisor import SupervisorAgent
from agents.contracts import Language
from app.auth import AuthenticatedHousehold, authenticated_household

if __package__:
    from .business_logic import (
        DemoService,
        SessionNotFoundError,
        ThreadAccessError as DemoThreadAccessError,
        WorkflowConflictError,
    )
else:
    from business_logic import (
        DemoService,
        SessionNotFoundError,
        ThreadAccessError as DemoThreadAccessError,
        WorkflowConflictError,
    )

logger = logging.getLogger(__name__)


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
        state = AgentWorkflowState(request=request, actor_id=actor_id)
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
        return {
            "thread_id": thread_id,
            "status": status,
            "response": response,
            "data": data,
            "language": result.get("language", "unknown"),
            "intent": result.get("intent", "other"),
        }

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


def _owned_conversation(
    workflow: AgentWorkflowService, thread_id: str, household_id: str
) -> dict[str, Any]:
    conversation = workflow.get_conversation(thread_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    if conversation.get("actor_id") != household_id:
        raise HTTPException(
            status_code=403, detail="This conversation belongs to another household."
        )
    return conversation


def _tool_call_http_error(error: ToolCallError) -> HTTPException:
    if error.code == "scheme_not_found":
        return HTTPException(status_code=422, detail="The selected scheme is not available.")
    return HTTPException(
        status_code=503,
        detail="A required workflow tool call could not be completed.",
    )


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

    @application.post(
        "/api/chat",
        response_model=SupervisorChatResponse,
        responses={400: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
        tags=["Agent Workflow"],
    )
    def chat_with_supervisor(
        request: SupervisorChatRequest,
        principal: AuthenticatedHousehold = Depends(authenticated_household),
        x_thread_id: str | None = Header(None),
    ) -> SupervisorChatResponse:
        """Send message through supervisor agent for intelligent routing."""
        try:
            thread_id = x_thread_id or request.thread_id
            
            # Get workflow service (lazy-loaded on first call)
            workflow = get_workflow_service()
            
            # Execute workflow
            result = workflow.execute_workflow(
                request=request.message,
                actor_id=principal.household_id,
                thread_id=thread_id,
                known_facts=request.known_facts,
                selected_scheme_id=request.selected_scheme_id,
                confirmed_facts=request.confirmed_facts,
            )
            
            return SupervisorChatResponse(
                status="success",
                thread_id=result["thread_id"],
                language=result.get("language") or request.language or "unknown",
                intent=result.get("intent") or "other",
                next_step=result.get("status", "completed"),
                response=result.get("response", ""),
                data=result.get("data", {}),
                rate_limit=RateLimit(remaining_requests=9, reset_in_seconds=60),
            )
        except ThreadAccessError:
            raise HTTPException(status_code=403, detail="This conversation belongs to another user.")
        except ApprovalPendingError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except ToolCallError as error:
            category = "budget_exceeded" if error.code == "budget_exceeded" else "tool_error"
            logger.warning("Agent workflow tool call failed (%s).", category)
            raise HTTPException(
                status_code=503, detail="A required workflow tool call could not be completed."
            ) from error
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
        principal: AuthenticatedHousehold = Depends(authenticated_household),
    ) -> SupervisorChatResponse:
        """Approve, edit or reject the exact form the graph is waiting on."""
        try:
            result = get_workflow_service().submit_decision(
                thread_id,
                principal.household_id,
                decision.action,
                decision.payload_hash,
                decision.changes,
            )
        except ThreadNotFoundError:
            raise HTTPException(status_code=404, detail="Thread not found")
        except ThreadAccessError:
            raise HTTPException(status_code=403, detail="This conversation belongs to another user.")
        except NoPendingApprovalError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except ToolCallError as error:
            category = "budget_exceeded" if error.code == "budget_exceeded" else "tool_error"
            logger.warning("Agent workflow tool call failed (%s).", category)
            raise HTTPException(
                status_code=503, detail="A required workflow tool call could not be completed."
            ) from error
        except Exception:
            logger.exception("Error resuming approval")
            raise HTTPException(status_code=500, detail="The decision could not be processed.")
        return SupervisorChatResponse(
            status="success",
            thread_id=result["thread_id"],
            language=result.get("language", "unknown"),
            intent=result.get("intent", "other"),
            next_step=result["status"],
            response=result["response"],
            data=result["data"],
            rate_limit=RateLimit(remaining_requests=9, reset_in_seconds=60),
        )

    @application.get(
        "/api/chat/{thread_id}",
        response_model=SupervisorChatResponse,
        tags=["Agent Workflow"],
    )
    def get_chat_response(
        thread_id: str,
        principal: AuthenticatedHousehold = Depends(authenticated_household),
    ) -> dict[str, Any]:
        """Get latest response from conversation thread."""
        workflow = get_workflow_service()
        conversation = _owned_conversation(workflow, thread_id, principal.household_id)
        
        if not conversation["turns"]:
            raise HTTPException(status_code=404, detail="No turns in conversation")
        
        latest_turn = conversation["turns"][-1]
        return {
            "status": "success",
            "thread_id": thread_id,
            "response": latest_turn["result"].get("response", ""),
            "timestamp": latest_turn["timestamp"],
        }

    @application.get(
        "/api/chat/{thread_id}/history",
        response_model=ConversationHistory,
        tags=["Agent Workflow"],
    )
    def get_conversation_history(
        thread_id: str,
        limit: int = 50,
        offset: int = 0,
        principal: AuthenticatedHousehold = Depends(authenticated_household),
    ) -> ConversationHistory:
        """Get full conversation history."""
        workflow = get_workflow_service()
        conversation = _owned_conversation(workflow, thread_id, principal.household_id)
        
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

    @application.get(
        "/api/chat/{thread_id}/context",
        response_model=SessionContext,
        tags=["Agent Workflow"],
    )
    def get_session_context(
        thread_id: str,
        principal: AuthenticatedHousehold = Depends(authenticated_household),
    ) -> SessionContext:
        """Get current session context and collected facts."""
        workflow = get_workflow_service()
        _owned_conversation(workflow, thread_id, principal.household_id)
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

    @application.post(
        "/api/chat/{thread_id}/restart",
        tags=["Agent Workflow"],
    )
    def restart_session_context(
        thread_id: str,
        principal: AuthenticatedHousehold = Depends(authenticated_household),
    ) -> dict[str, Any]:
        """Reset session context but keep conversation history."""
        workflow = get_workflow_service()
        _owned_conversation(workflow, thread_id, principal.household_id)
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

    @application.delete(
        "/api/chat/{thread_id}",
        tags=["Agent Workflow"],
    )
    def delete_chat_conversation(
        thread_id: str,
        principal: AuthenticatedHousehold = Depends(authenticated_household),
    ) -> dict[str, Any]:
        """Delete entire conversation (GDPR compliance)."""
        workflow = get_workflow_service()
        conversation = _owned_conversation(workflow, thread_id, principal.household_id)
        
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
            raise _tool_call_http_error(error) from error

    @application.post("/api/analyze", tags=["Demo"])
    def analyze(
        payload: AnalysisRequest,
        principal: AuthenticatedHousehold = Depends(authenticated_household),
    ) -> StreamingResponse:
        try:
            events = demo.analyze(
                payload.citizen, payload.scheme_ids, principal.household_id
            )
        except ToolCallError as error:
            raise _tool_call_http_error(error) from error
        return _event_stream(events)

    @application.post("/api/chat/legacy", tags=["Demo"])
    def chat_legacy(
        payload: ChatRequest,
        principal: AuthenticatedHousehold = Depends(authenticated_household),
    ) -> StreamingResponse:
        return _event_stream(
            demo.chat_turn(
                payload.user_input, payload.session_id, principal.household_id
            )
        )

    @application.post("/api/threads/{thread_id}/documents/upload", tags=["Demo"])
    async def upload_document(
        thread_id: str,
        scheme_id: str = Form(...),
        document_type: str = Form(...),
        sensitive_ids_masked: bool = Form(False),
        file: UploadFile = File(...),
        principal: AuthenticatedHousehold = Depends(authenticated_household),
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
                principal.household_id,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except SessionNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except WorkflowConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except DemoThreadAccessError:
            raise HTTPException(
                status_code=403,
                detail="This application belongs to another household.",
            )
        except DocumentStorageError as error:
            logger.exception("Could not store a supporting document.")
            raise HTTPException(
                status_code=500, detail="Could not securely store the document."
            ) from error
        finally:
            await file.close()

    @application.get(
        "/api/threads/{thread_id}/documents/{scheme_id}/{document_type}",
        tags=["Demo"],
    )
    def download_document(
        thread_id: str,
        scheme_id: str,
        document_type: str,
        principal: AuthenticatedHousehold = Depends(authenticated_household),
    ) -> Response:
        try:
            content, metadata = demo.get_uploaded_document(
                thread_id, scheme_id, document_type, principal.household_id
            )
        except DemoThreadAccessError:
            raise HTTPException(
                status_code=403,
                detail="This application belongs to another household.",
            )
        except SessionNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
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
    def delete_documents(
        thread_id: str,
        principal: AuthenticatedHousehold = Depends(authenticated_household),
    ) -> dict[str, Any]:
        try:
            deleted = demo.delete_uploaded_documents(
                thread_id, principal.household_id
            )
        except DemoThreadAccessError:
            raise HTTPException(
                status_code=403,
                detail="This application belongs to another household.",
            )
        except SessionNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except DocumentStorageError as error:
            logger.exception("Could not delete supporting documents.")
            raise HTTPException(
                status_code=500,
                detail="Could not securely delete supporting documents.",
            ) from error
        return {"status": "success", "deleted_documents": deleted}

    @application.post("/api/threads/{thread_id}/decision", tags=["Demo"])
    def decide(
        thread_id: str,
        payload: DecisionRequest,
        principal: AuthenticatedHousehold = Depends(authenticated_household),
    ) -> StreamingResponse:
        try:
            events = demo.decide(
                thread_id,
                payload.action,
                payload.payload_hash,
                payload.changes,
                principal.household_id,
            )
        except DemoThreadAccessError:
            raise HTTPException(
                status_code=403,
                detail="This application belongs to another household.",
            )
        except SessionNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except WorkflowConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except ToolCallError as error:
            raise _tool_call_http_error(error) from error
        except DocumentStorageError as error:
            logger.exception("Could not check stored supporting documents.")
            raise HTTPException(
                status_code=500, detail="Could not check stored documents."
            ) from error
        return _event_stream(events)

    return application


app = create_api()
