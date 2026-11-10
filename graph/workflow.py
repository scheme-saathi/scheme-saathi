import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from graph import tools

MAX_DRAFT_ATTEMPTS = 3
MAX_TOOL_CALLS_PER_RUN = 1200


class GraphState(TypedDict, total=False):
    simulated_citizen: dict[str, Any]
    actor_id: str
    scheme_ids: list[str]
    include_draft: bool
    profile: dict[str, Any]
    questions_asked: int
    last_asked: str  # the field intake just filled; only verdicts waiting on it can change
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
    with tools.acting_as("intake"):
        fields = tools.required_fields(
            state.get("scheme_ids"), state.get("include_draft", False)
        )
    return [field for field in fields if field not in state["profile"]]


def plan_node(state: GraphState) -> dict[str, Any]:
    return {
        "plan": ["build profile", "find candidate schemes", "check rules", "list documents", "draft application"],
        "profile": {},
        "questions_asked": 0,
    }


def _next_field(state: GraphState) -> str | None:
    """The field that settles the most open verdicts; fields already asked are skipped."""
    return tools.next_question(state["verdicts"], declined=list(state["profile"]))


def intake_node(state: GraphState) -> dict[str, Any]:
    if state.get("verdicts"):
        field = _next_field(state)
    else:  # first question, before any verdict exists
        field = next(iter(unanswered(state)), None)
    if field is None:
        return {}
    profile = {**state["profile"], field: state["simulated_citizen"].get(field)}
    return {"profile": profile, "questions_asked": state["questions_asked"] + 1, "last_asked": field}


def eligibility_node(state: GraphState) -> dict[str, Any]:
    preview = state.get("include_draft", False)
    with tools.acting_as("eligibility"):
        schemes = tools.search_schemes(
            state["profile"], state.get("scheme_ids"), preview
        )
    # Answers only add facts: a decided verdict stays decided, and an open one can change
    # only if it was waiting on the field just asked. An edit clears verdicts, forcing a full check.
    earlier = state.get("verdicts") or {}
    asked = state.get("last_asked")

    def stale(scheme: str) -> bool:
        verdict = earlier.get(scheme)
        return verdict is None or (
            verdict["verdict"] == "cant_tell" and asked in verdict.get("unresolved_fields", [])
        )

    verdicts = {}
    for scheme in schemes:
        if not stale(scheme):
            verdicts[scheme] = earlier[scheme]
            continue
        actor = "rule_reviewer" if preview else "eligibility"
        with tools.acting_as(actor):
            verdicts[scheme] = tools.evaluate_scheme(state["profile"], scheme, preview)
    return {"verdicts": verdicts}


def route_after_eligibility(state: GraphState) -> str:
    return "intake" if _next_field(state) else "documents"


def documents_node(state: GraphState) -> dict[str, Any]:
    eligible = [s for s, v in state["verdicts"].items() if v["verdict"] == "eligible"]
    with tools.acting_as("document_checker"):
        documents = {scheme: tools.list_documents(scheme) for scheme in eligible}
    return {"documents": documents}


def route_after_documents(state: GraphState) -> str:
    # Verdicts from unreviewed draft rules are a preview only: never draft, approve or submit from them.
    return END if state.get("include_draft") else "draft"


def draft_node(state: GraphState) -> dict[str, Any]:
    eligible = [s for s, v in state["verdicts"].items() if v["verdict"] == "eligible"]
    if not eligible:
        return {"application": {}}
    return {
        "application": tools.draft_application(state["profile"], eligible[0]),
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
    with tools.acting_as("application"):
        required_fields = (
            tools.required_fields([scheme_id])
            if scheme_id in state["verdicts"]
            else []
        )
    for field in required_fields:
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
    scheme_id = state.get("application", {}).get("scheme_id", "unknown")
    authenticated = bool(state.get("actor_id"))
    if action == "approve":
        if decision.get("payload_hash") == current:
            tools.audit_approval_event("approve", "accepted", authenticated)
            return {
                "approved": True,
                "approved_hash": current,
                "approval_status": "approved",
            }
        tools.audit_approval_event("approve", "invalid", authenticated)
        return {"approved": False, "approval_status": "invalid"}
    if action == "edit" and isinstance(decision.get("changes"), dict):
        if not _valid_profile_edits(decision["changes"]):
            tools.audit_approval_event("edit", "invalid", authenticated)
            return {"approved": False, "approval_status": "invalid"}
        tools.audit_approval_event("edit", "accepted", authenticated)
        # An edit can change an answer, so earlier verdicts no longer hold.
        return {"profile": {**state["profile"], **decision["changes"]}, "verdicts": {}, "approved": False,
                "approved_hash": "", "approval_status": "edited", "draft_attempts": 0}
    tools.audit_approval_event(
        "reject" if action == "reject" else "invalid",
        "rejected" if action == "reject" else "invalid",
        authenticated,
    )
    return {"approved": False, "approval_status": "rejected" if action == "reject" else "invalid"}


def _valid_profile_edits(changes: dict[str, Any]) -> bool:
    with tools.acting_as("application"):
        scheme_ids = tools.search_schemes({})
        specs = tools.field_specs(scheme_ids)
    specs.setdefault("income", {"type": "number"})
    specs.setdefault("occupation", {"type": "str"})
    for field, value in changes.items():
        spec = specs.get(field)
        if spec is None:
            return False
        kind = spec["type"]
        if kind == "bool" and not isinstance(value, bool):
            return False
        if kind == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
            return False
        if kind == "str" and not isinstance(value, str):
            return False
    return True


def route_after_approval(state: GraphState) -> str:
    if state["approval_status"] == "approved":
        return "submit"
    return "eligibility" if state["approval_status"] == "edited" else END


def submit_node(state: GraphState) -> dict[str, Any]:
    if application_hash(state["application"]) != state.get("approved_hash"):
        return {"approved": False, "approval_status": "invalid"}
    with tools.acting_as("application"):
        return {
            "submission": tools.submit_application(
                state["application"],
                write_capability=tools.issue_submission_capability(
                    state["application"],
                    state["approved_hash"],
                    household_id=state.get("actor_id"),
                ),
                household_id=state.get("actor_id"),
            )
        }


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
    from agents.persona_validator import reject_sensitive_graph_input

    return tools.budget_graph(
        builder.compile(checkpointer=checkpointer or MemorySaver()),
        limit=MAX_TOOL_CALLS_PER_RUN,
        input_guard=reject_sensitive_graph_input,
    )


@contextmanager
def sqlite_checkpointer(path: str | Path):
    """Open a SQLite-backed checkpointer so runs survive process restarts."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(path)) as saver:
        yield saver
