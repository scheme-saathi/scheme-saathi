from langgraph.types import Command

from graph.workflow import build_graph


def test_eligible_citizen_pauses_then_submits_after_approval():
    graph = build_graph()
    config = {"configurable": {"thread_id": "approve"}}
    state = graph.invoke({"simulated_citizen": {"age": 62, "is_widow": True, "income": 250000}}, config)
    assert state["__interrupt__"]
    final = graph.invoke(Command(resume={"approved": True}), config)
    assert final["submission"]["status"].startswith("submitted")


def test_rejected_form_is_not_submitted():
    graph = build_graph()
    config = {"configurable": {"thread_id": "reject"}}
    graph.invoke({"simulated_citizen": {"age": 62, "is_widow": True, "income": 250000}}, config)
    final = graph.invoke(Command(resume={"approved": False}), config)
    assert final.get("submission") is None


def test_ineligible_citizen_never_reaches_approval():
    graph = build_graph()
    config = {"configurable": {"thread_id": "ineligible"}}
    state = graph.invoke({"simulated_citizen": {"age": 59, "is_widow": True, "income": 250000}}, config)
    assert "__interrupt__" not in state
    assert state.get("application") in (None, {})
