import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from graph import mock_tools

MAX_DRAFT_ATTEMPTS = 3


class GraphState(TypedDict, total=False):
    simulated_citizen: dict[str, Any]
    scheme_ids: list[str]
    include_draft: bool
    profile: dict[str, Any]
    questions_asked: int
    plan: list[str]
    verdicts: dict[str, dict[str, Any]]
    documents: dict[str, list[str]]
    application: dict[str, Any]
    draft_attempts: int
    critique: list[str]
    needs_human: bool
    approved: bool
    approved_hash: str
    approval_status: str
    submission: dict[str, Any]


def unanswered(state: GraphState) -> list[str]:
    return [f for f in mock_tools.required_fields(state.get("scheme_ids"), state.get("include_draft", False)) if f not in state["profile"]]


def plan_node(state: GraphState) -> dict[str, Any]:
    return {
        "plan": ["build profile", "find candidate schemes", "check rules", "list documents", "draft application"],
        "profile": {},
        "questions_asked": 0,
    }


def intake_node(state: GraphState) -> dict[str, Any]:
    pending = unanswered(state)
    if not pending:
        return {}
    field = pending[0]
    profile = {**state["profile"], field: state["simulated_citizen"].get(field)}
    return {"profile": profile, "questions_asked": state["questions_asked"] + 1}


def eligibility_node(state: GraphState) -> dict[str, Any]:
    preview = state.get("include_draft", False)
    schemes = mock_tools.search_schemes(state["profile"], state.get("scheme_ids"), preview)
    return {"verdicts": {s: mock_tools.evaluate_scheme(state["profile"], s, preview) for s in schemes}}


def route_after_eligibility(state: GraphState) -> str:
    unresolved = any(v["verdict"] == "cant_tell" for v in state["verdicts"].values())
    return "intake" if unresolved and unanswered(state) else "documents"


def documents_node(state: GraphState) -> dict[str, Any]:
    eligible = [s for s, v in state["verdicts"].items() if v["verdict"] == "eligible"]
    return {"documents": {s: mock_tools.list_documents(s) for s in eligible}}


def route_after_documents(state: GraphState) -> str:
    # Verdicts from unreviewed draft rules are a preview only: never draft, approve or submit from them.
    return END if state.get("include_draft") else "draft"


def draft_node(state: GraphState) -> dict[str, Any]:
    eligible = [s for s, v in state["verdicts"].items() if v["verdict"] == "eligible"]
    if not eligible:
        return {"application": {}}
    return {
        "application": mock_tools.draft_application(state["profile"], eligible[0]),
        "draft_attempts": state.get("draft_attempts", 0) + 1,
    }


def route_after_draft(state: GraphState) -> str:
    return "validate" if state["application"] else END


def check_application(state: GraphState) -> list[str]:
    """Deterministic checker: the draft must match the evaluated facts and verdicts."""
    application = state["application"]
    problems = []
    scheme_id = application.get("scheme_id")
    if state["verdicts"].get(scheme_id, {}).get("verdict") != "eligible":
        problems.append(f"Scheme '{scheme_id}' is not an eligible scheme for this profile.")
    applicant = application.get("applicant")
    if not isinstance(applicant, dict):
        return problems + ["The application has no applicant section."]
    for field in mock_tools.required_fields([scheme_id]) if scheme_id in state["verdicts"] else []:
        if field not in applicant:
            problems.append(f"Applicant is missing required field '{field}'.")
    for field, value in applicant.items():
        if field in state["profile"] and state["profile"][field] != value:
            problems.append(f"Applicant field '{field}' differs from the collected profile.")
    return problems


def validate_node(state: GraphState) -> dict[str, Any]:
    return {"critique": check_application(state)}


def route_after_validate(state: GraphState) -> str:
    if not state["critique"]:
        return "approval"
    return "draft" if state.get("draft_attempts", 0) < MAX_DRAFT_ATTEMPTS else "escalate"


def escalate_node(state: GraphState) -> dict[str, Any]:
    return {"needs_human": True, "application": {}}


def application_hash(application: dict[str, Any]) -> str:
    canonical = json.dumps(application, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def approval_node(state: GraphState) -> dict[str, Any]:
    """Pause for a person. Approval counts only if it names the hash of this exact form."""
    current = application_hash(state["application"])
    decision = interrupt({
        "form": state["application"],
        "payload_hash": current,
        "options": ["approve", "edit", "reject"],
    })
    action = decision.get("action") if isinstance(decision, dict) else None
    if action == "approve":
        if decision.get("payload_hash") == current:
            return {"approved": True, "approved_hash": current, "approval_status": "approved"}
        return {"approved": False, "approval_status": "invalid"}
    if action == "edit" and isinstance(decision.get("changes"), dict):
        return {"profile": {**state["profile"], **decision["changes"]}, "approved": False,
                "approved_hash": "", "approval_status": "edited", "draft_attempts": 0}
    return {"approved": False, "approval_status": "rejected" if action == "reject" else "invalid"}


def route_after_approval(state: GraphState) -> str:
    if state["approval_status"] == "approved":
        return "submit"
    return "eligibility" if state["approval_status"] == "edited" else END


def submit_node(state: GraphState) -> dict[str, Any]:
    if application_hash(state["application"]) != state.get("approved_hash"):
        return {"approved": False, "approval_status": "invalid"}
    return {"submission": mock_tools.submit_application(state["application"])}


def build_graph(checkpointer=None):
    builder = StateGraph(GraphState)
    builder.add_node("plan", plan_node)
    builder.add_node("intake", intake_node)
    builder.add_node("eligibility", eligibility_node)
    builder.add_node("documents", documents_node)
    builder.add_node("draft", draft_node)
    builder.add_node("validate", validate_node)
    builder.add_node("escalate", escalate_node)
    builder.add_node("approval", approval_node)
    builder.add_node("submit", submit_node)
    builder.add_edge(START, "plan")
    builder.add_edge("plan", "intake")
    builder.add_edge("intake", "eligibility")
    builder.add_conditional_edges("eligibility", route_after_eligibility, ["intake", "documents"])
    builder.add_conditional_edges("documents", route_after_documents, ["draft", END])
    builder.add_conditional_edges("draft", route_after_draft, ["validate", END])
    builder.add_conditional_edges("validate", route_after_validate, ["approval", "draft", "escalate"])
    builder.add_edge("escalate", END)
    builder.add_conditional_edges("approval", route_after_approval, ["submit", "eligibility", END])
    builder.add_edge("submit", END)
    return builder.compile(checkpointer=checkpointer or MemorySaver())


@contextmanager
def sqlite_checkpointer(path: str | Path):
    """Open a SQLite-backed checkpointer so runs survive process restarts."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(path)) as saver:
        yield saver
