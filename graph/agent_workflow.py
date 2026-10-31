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


def _intake_node(agents: AgentSet, state: AgentWorkflowState) -> dict[str, Any]:
    result = agents.intake.invoke(
        IntakeInput(
            request=state["request"],
            known_facts=state.get("known_facts", {}),
        )
    )
    return {"intake": result}


def _route_after_intake(state: AgentWorkflowState) -> str:
    if state["intake"].clarifying_questions:
        return "clarification"
    return "supervisor"


def _clarification_node(state: AgentWorkflowState) -> dict[str, str]:
    questions = state["intake"].clarifying_questions
    return {
        "status": "needs_clarification",
        "response": "\n".join(questions),
    }


def _supervisor_node(
    agents: AgentSet, state: AgentWorkflowState
) -> dict[str, Any]:
    plan = agents.supervisor.invoke(
        SupervisorInput(
            request=state["request"],
            intake=state["intake"],
            selected_scheme_id=state.get("selected_scheme_id"),
        )
    )
    return {"plan": plan.model_dump(mode="json")}


def _route_after_supervisor(state: AgentWorkflowState) -> str:
    return state["plan"]["next_agent"]


def _eligibility_node(
    agents: AgentSet, state: AgentWorkflowState
) -> dict[str, Any]:
    scheme_id = state.get("selected_scheme_id")
    raw_evaluation = state.get("deterministic_evaluation")
    if not scheme_id or raw_evaluation is None:
        return {
            "eligibility": {
                "verdict": "cant_tell",
                "reason": "A deterministic rule evaluation was not provided.",
                "missing_fields": [],
                "unresolved_fields": [],
                "citations": [],
            }
        }

    evaluation = Evaluation.model_validate(raw_evaluation)
    evaluation_data = evaluation.model_dump(mode="json")
    narrative = agents.eligibility.invoke(
        EligibilityInput(scheme_id=scheme_id, evaluation=evaluation_data)
    )
    return {
        "eligibility": {
            **evaluation_data,
            "explanation": narrative.explanation,
            "clarifying_questions": narrative.clarifying_questions,
        }
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
    """Build the agent skeleton; no durable checkpointer is selected by default."""
    runtime = agents or AgentSet.from_environment()
    builder = StateGraph(AgentWorkflowState)
    builder.add_node("intake", lambda state: _intake_node(runtime, state))
    builder.add_node("clarification", _clarification_node)
    builder.add_node("supervisor", lambda state: _supervisor_node(runtime, state))
    builder.add_node("eligibility", lambda state: _eligibility_node(runtime, state))
    builder.add_node(
        "document_checker", lambda state: _document_checker_node(runtime, state)
    )
    builder.add_node("application", lambda state: _application_node(runtime, state))
    builder.add_node("finish", _finish_node)
    builder.add_edge(START, "intake")
    builder.add_conditional_edges(
        "intake",
        _route_after_intake,
        {"clarification": "clarification", "supervisor": "supervisor"},
    )
    builder.add_edge("clarification", END)
    builder.add_conditional_edges(
        "supervisor",
        _route_after_supervisor,
        {
            "eligibility": "eligibility",
            "document_checker": "document_checker",
            "application": "eligibility",
            "respond": "finish",
        },
    )
    builder.add_conditional_edges(
        "eligibility",
        _route_after_eligibility,
        {"document_checker": "document_checker", "finish": "finish"},
    )
    builder.add_conditional_edges(
        "document_checker",
        _route_after_documents,
        {"application": "application", "finish": "finish"},
    )
    builder.add_edge("application", "finish")
    builder.add_edge("finish", END)
    return builder.compile(checkpointer=checkpointer)
