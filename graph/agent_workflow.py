"""GPT agent orchestration skeleton, separate from the deterministic demo graph."""

from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from agents.application import ApplicationAgent
from agents.contracts import (
    ApplicationInput,
    DocumentCheckInput,
    EligibilityInput,
    FactMap,
    IntakeInput,
    IntakeResult,
    SupervisorInput,
)
from agents.document_checker import DocumentCheckerAgent
from agents.eligibility import EligibilityAgent
from agents.intake import IntakeAgent
from agents.model_factory import create_chat_model
from agents.supervisor import SupervisorAgent
from graph.tools import evaluate_scheme
from servers.rule_engine.rules import Evaluation


class AgentWorkflowState(TypedDict, total=False):
    request: str
    known_facts: FactMap
    confirmed_facts: FactMap
    selected_scheme_id: str
    deterministic_evaluation: dict[str, Any]
    required_documents: list[str]
    available_documents: list[str]
    application_required_fields: list[str]
    application_field_mapping: dict[str, str]
    intake: IntakeResult
    plan: dict[str, str]
    eligibility: dict[str, Any]
    document_check: dict[str, Any]
    application_draft: dict[str, Any]
    status: str
    response: str


@dataclass
class AgentSet:
    intake: IntakeAgent
    supervisor: SupervisorAgent
    eligibility: EligibilityAgent
    document_checker: DocumentCheckerAgent
    application: ApplicationAgent

    @classmethod
    def from_environment(cls) -> "AgentSet":
        supervisor_model = create_chat_model("supervisor")
        specialist_model = create_chat_model("specialist")
        return cls(
            intake=IntakeAgent(specialist_model),
            supervisor=SupervisorAgent(supervisor_model),
            eligibility=EligibilityAgent(specialist_model),
            document_checker=DocumentCheckerAgent(specialist_model),
            application=ApplicationAgent(specialist_model),
        )


def _supervisor_node(
    agents: AgentSet, state: AgentWorkflowState
) -> dict[str, Any]:
    """Entry point: Validate input, detect language & intent, route intelligently.
    
    Supervisor runs FIRST on all requests to:
    1. Validate input (no sensitive data, rate limiting, format)
    2. Detect language (en, hi, mr) and intent in single gpt-4o-mini call
    3. Route to appropriate specialist or pause for clarification
    """
    # Supervisor validates input and decides routing
    # Note: intake parameter is None because Intake hasn't run yet
    plan = agents.supervisor.invoke(
        SupervisorInput(
            request=state["request"],
            intake=state.get("intake"),  # None on first call
            selected_scheme_id=state.get("selected_scheme_id"),
        )
    )
    return {"plan": plan.model_dump(mode="json")}


def _route_after_supervisor(state: AgentWorkflowState) -> str:
    """Route based on Supervisor's decision.
    
    Returns:
    - "intake" if need to collect facts
    - "eligibility", "document_checker", "application" if direct routing
    - "finish" if responding without specialist
    """
    return state["plan"]["next_agent"]


def _intake_node(agents: AgentSet, state: AgentWorkflowState) -> dict[str, Any]:
    """Collect household information (only called if Supervisor routes here)."""
    result = agents.intake.invoke(
        IntakeInput(
            request=state["request"],
            known_facts=state.get("known_facts", {}),
        )
    )
    return {"intake": result}


def _route_after_intake(state: AgentWorkflowState) -> str:
    """After Intake, check if clarification needed or ready to route to specialist."""
    if state["intake"].clarifying_questions:
        return "respond"  # Pause and ask clarifying questions
    # If supervisor already decided next step, go there
    next_agent = state["plan"]["next_agent"]
    if next_agent in ["eligibility", "document_checker", "application"]:
        return next_agent
    return "finish"


def _clarification_node(state: AgentWorkflowState) -> dict[str, str]:
    """Respond with clarifying questions from Intake."""
    questions = state["intake"].clarifying_questions
    return {
        "status": "needs_clarification",
        "response": "\n".join(questions),
    }


def _resolve_deterministic_evaluation(state: AgentWorkflowState) -> dict[str, Any] | None:
    """Use the project rule engine as the source of truth when a scheme and facts are known."""
    scheme_id = state.get("selected_scheme_id")
    if not scheme_id:
        return None

    facts = state.get("confirmed_facts") or state.get("known_facts") or {}
    if not isinstance(facts, dict) or not facts:
        return None

    try:
        return evaluate_scheme(facts, scheme_id)
    except Exception:
        return {
            "verdict": "cant_tell",
            "reason": "The deterministic rule engine could not evaluate this scheme with the current facts.",
            "missing_fields": [],
            "unresolved_fields": [],
            "conditions": [],
            "citations": [],
        }


def _eligibility_node(
    agents: AgentSet, state: AgentWorkflowState
) -> dict[str, Any]:
    scheme_id = state.get("selected_scheme_id")
    raw_evaluation = state.get("deterministic_evaluation")
    facts = state.get("confirmed_facts") or state.get("known_facts") or {}

    if raw_evaluation is None:
        raw_evaluation = _resolve_deterministic_evaluation(state)

    if raw_evaluation is None:
        failed = {
            "verdict": "cant_tell",
            "reason": "A deterministic rule evaluation was not provided.",
            "missing_fields": [],
            "unresolved_fields": [],
            "conditions": [],
            "citations": [],
        }
        if not scheme_id:
            failed["reason"] = "A scheme was not selected for eligibility evaluation."
        elif not facts:
            failed["reason"] = "There is no complete, fully reviewed rule set for this scheme."
        return {"eligibility": failed}

    evaluation = Evaluation.model_validate(raw_evaluation)
    evaluation_data = evaluation.model_dump(mode="json")
    narrative = agents.eligibility.invoke(
        EligibilityInput(scheme_id=scheme_id, evaluation=evaluation_data)
    )
    return {
        "deterministic_evaluation": evaluation_data,
        "eligibility": {
            **evaluation_data,
            "explanation": narrative.explanation,
            "clarifying_questions": narrative.clarifying_questions,
        },
    }


def _route_after_eligibility(state: AgentWorkflowState) -> str:
    is_application = state["plan"]["next_agent"] == "application"
    eligible = state["eligibility"]["verdict"] == "eligible"
    return "document_checker" if is_application and eligible else "finish"


def _document_checker_node(
    agents: AgentSet, state: AgentWorkflowState
) -> dict[str, Any]:
    result = agents.document_checker.invoke(
        DocumentCheckInput(
            scheme_id=state["selected_scheme_id"],
            required_documents=state.get("required_documents", []),
            available_documents=state.get("available_documents", []),
        )
    )
    return {"document_check": result.model_dump(mode="json")}


def _route_after_documents(state: AgentWorkflowState) -> str:
    if state["plan"]["next_agent"] == "application":
        return "application"
    return "finish"


def _application_node(
    agents: AgentSet, state: AgentWorkflowState
) -> dict[str, Any]:
    if state["eligibility"]["verdict"] != "eligible":
        raise ValueError("Application drafting requires an eligible rule-engine result.")
    if not state.get("selected_scheme_id"):
        raise ValueError("Application drafting requires a selected scheme.")
    draft = agents.application.invoke(
        ApplicationInput(
            scheme_id=state["selected_scheme_id"],
            confirmed_facts=state.get("confirmed_facts", {}),
            required_fields=state.get("application_required_fields", []),
            field_mapping=state.get("application_field_mapping", {}),
        )
    )
    return {"application_draft": draft.model_dump(mode="json")}


def _finish_node(state: AgentWorkflowState) -> dict[str, str]:
    if state.get("application_draft") is not None:
        incomplete = bool(state["application_draft"]["missing_fields"])
        return {
            "status": "draft_needs_information" if incomplete else "draft_ready_for_review",
            "response": state["application_draft"]["review_summary"],
        }
    if state.get("document_check") is not None:
        missing = state["document_check"]["missing_documents"]
        response = (
            "Missing documents: " + ", ".join(missing)
            if missing
            else "Document checklist complete; authenticity is not verified."
        )
        return {"status": "documents_checked", "response": response}
    if state.get("eligibility") is not None:
        return {
            "status": "eligibility_checked",
            "response": state["eligibility"].get(
                "explanation", state["eligibility"]["reason"]
            ),
        }
    return {"status": "responded", "response": state["plan"]["reason"]}


def build_agent_graph(
    agents: AgentSet | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
):
    """Build agent workflow with Supervisor as entry point.
    
    Graph Flow:
    START → Supervisor (validate, detect language/intent, route)
            ├→ intake (collect facts if needed)
            │   └→ eligibility/document_checker/application/respond
            ├→ eligibility (direct routing if Supervisor decides)
            ├→ document_checker
            ├→ application
            └→ respond (direct response without specialist)
    → finish (format response)
    → END
    """
    runtime = agents or AgentSet.from_environment()
    builder = StateGraph(AgentWorkflowState)
    
    # Add all nodes
    builder.add_node("supervisor", lambda state: _supervisor_node(runtime, state))
    builder.add_node("intake", lambda state: _intake_node(runtime, state))
    builder.add_node("eligibility", lambda state: _eligibility_node(runtime, state))
    builder.add_node(
        "document_checker", lambda state: _document_checker_node(runtime, state)
    )
    builder.add_node("application", lambda state: _application_node(runtime, state))
    builder.add_node("finish", _finish_node)
    # Respond node handles: direct responses and clarifying questions from Intake
    def _respond_node_impl(state: AgentWorkflowState) -> dict[str, str]:
        # If Intake has clarifying questions, return those
        intake_data = state.get("intake")
        if intake_data:
            if hasattr(intake_data, "clarifying_questions"):
                clarifying_qs = intake_data.clarifying_questions
            elif isinstance(intake_data, dict):
                clarifying_qs = intake_data.get("clarifying_questions", [])
            else:
                clarifying_qs = []
            
            if clarifying_qs:
                return {
                    "status": "needs_clarification",
                    "response": "\n".join(clarifying_qs),
                }
        # Otherwise return the plan reason (direct response)
        return {"status": "responded", "response": state["plan"]["reason"]}
    
    builder.add_node("respond", _respond_node_impl)
    
    # Entry point: Supervisor ALWAYS first
    builder.add_edge(START, "supervisor")
    
    # After Supervisor routes to: intake, eligibility, document_checker, application, or finish
    builder.add_conditional_edges(
        "supervisor",
        _route_after_supervisor,
        {
            "intake": "intake",
            "eligibility": "eligibility",
            "document_checker": "document_checker",
            "application": "eligibility",  # application flow starts with eligibility eval
            "respond": "respond",  # direct response without specialist
        },
    )
    
    # After Intake, route to specialist or respond with clarification
    builder.add_conditional_edges(
        "intake",
        _route_after_intake,
        {
            "eligibility": "eligibility",
            "document_checker": "document_checker",
            "application": "eligibility",
            "respond": "respond",
            "finish": "finish",
        },
    )
    
    # Eligibility → Document Checker (if application) → Finish
    builder.add_conditional_edges(
        "eligibility",
        _route_after_eligibility,
        {"document_checker": "document_checker", "finish": "finish"},
    )
    
    # Document Checker → Application (if needed) → Finish
    builder.add_conditional_edges(
        "document_checker",
        _route_after_documents,
        {"application": "application", "finish": "finish"},
    )
    
    # Application → Finish
    builder.add_edge("application", "finish")
    
    # Respond → END (respond node handles its own final output)
    builder.add_edge("respond", END)
    
    # Finish → END
    builder.add_edge("finish", END)
    
    return builder.compile(checkpointer=checkpointer)
