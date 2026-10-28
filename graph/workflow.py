from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from graph import mock_tools

REQUIRED_FIELDS = ["age", "is_widow", "income"]


class GraphState(TypedDict, total=False):
    simulated_citizen: dict[str, Any]
    profile: dict[str, Any]
    questions_asked: int
    plan: list[str]
    verdicts: dict[str, dict[str, Any]]
    documents: dict[str, list[str]]
    application: dict[str, Any]
    approved: bool
    submission: dict[str, Any]


def unanswered(state: GraphState) -> list[str]:
    return [f for f in REQUIRED_FIELDS if f not in state["profile"]]


def plan_node(state: GraphState) -> dict[str, Any]:
    return {
        "plan": ["build profile", "find candidate schemes", "check rules", "list documents", "draft application"],
        "profile": {},
        "questions_asked": 0,
    }


def intake_node(state: GraphState) -> dict[str, Any]:
    field = unanswered(state)[0]
    profile = {**state["profile"], field: state["simulated_citizen"].get(field)}
    return {"profile": profile, "questions_asked": state["questions_asked"] + 1}


def eligibility_node(state: GraphState) -> dict[str, Any]:
    schemes = mock_tools.search_schemes(state["profile"])
    return {"verdicts": {s: mock_tools.evaluate_scheme(state["profile"], s) for s in schemes}}


def route_after_eligibility(state: GraphState) -> str:
    unresolved = any(v["verdict"] == "cant_tell" for v in state["verdicts"].values())
    return "intake" if unresolved and unanswered(state) else "documents"


def documents_node(state: GraphState) -> dict[str, Any]:
    eligible = [s for s, v in state["verdicts"].items() if v["verdict"] == "eligible"]
    return {"documents": {s: mock_tools.list_documents(s) for s in eligible}}


def draft_node(state: GraphState) -> dict[str, Any]:
    eligible = [s for s, v in state["verdicts"].items() if v["verdict"] == "eligible"]
    if not eligible:
        return {"application": {}}
    return {"application": mock_tools.draft_application(state["profile"], eligible[0])}


def route_after_draft(state: GraphState) -> str:
    return "approval" if state["application"] else END


def approval_node(state: GraphState) -> dict[str, Any]:
    decision = interrupt({"form": state["application"]})
    return {"approved": bool(decision.get("approved"))}


def route_after_approval(state: GraphState) -> str:
    return "submit" if state["approved"] else END


def submit_node(state: GraphState) -> dict[str, Any]:
    return {"submission": mock_tools.submit_application(state["application"])}


def build_graph(checkpointer=None):
    builder = StateGraph(GraphState)
    builder.add_node("plan", plan_node)
    builder.add_node("intake", intake_node)
    builder.add_node("eligibility", eligibility_node)
    builder.add_node("documents", documents_node)
    builder.add_node("draft", draft_node)
    builder.add_node("approval", approval_node)
    builder.add_node("submit", submit_node)
    builder.add_edge(START, "plan")
    builder.add_edge("plan", "intake")
    builder.add_edge("intake", "eligibility")
    builder.add_conditional_edges("eligibility", route_after_eligibility, ["intake", "documents"])
    builder.add_edge("documents", "draft")
    builder.add_conditional_edges("draft", route_after_draft, ["approval", END])
    builder.add_conditional_edges("approval", route_after_approval, ["submit", END])
    builder.add_edge("submit", END)
    return builder.compile(checkpointer=checkpointer or MemorySaver())


@contextmanager
def sqlite_checkpointer(path: str | Path):
    """Open a SQLite-backed checkpointer so runs survive process restarts."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(path)) as saver:
        yield saver
