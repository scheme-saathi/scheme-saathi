from langgraph.types import Command

from graph.workflow import build_graph


def approve(graph, config):
    h = graph.get_state(config).tasks[0].interrupts[0].value["payload_hash"]
    return Command(resume={"action": "approve", "payload_hash": h})


def test_eligible_citizen_pauses_then_submits_after_approval():
    graph = build_graph()
    config = {"configurable": {"thread_id": "approve"}}
    state = graph.invoke({"simulated_citizen": {"age": 62, "is_widow": True, "income": 250000}}, config)
    assert state["__interrupt__"]
    final = graph.invoke(approve(graph, config), config)
    assert final["submission"]["status"].startswith("submitted")


def test_rejected_form_is_not_submitted():
    graph = build_graph()
    config = {"configurable": {"thread_id": "reject"}}
    graph.invoke({"simulated_citizen": {"age": 62, "is_widow": True, "income": 250000}}, config)
    final = graph.invoke(Command(resume={"action": "reject"}), config)
    assert final.get("submission") is None


def test_ineligible_citizen_never_reaches_approval():
    graph = build_graph()
    config = {"configurable": {"thread_id": "ineligible"}}
    state = graph.invoke({"simulated_citizen": {"age": 59, "is_widow": True, "income": 250000}}, config)
    assert "__interrupt__" not in state
    assert state.get("application") in (None, {})


def test_sqlite_checkpoint_resumes_with_a_fresh_graph(tmp_path):
    from graph.workflow import sqlite_checkpointer

    db = tmp_path / "checkpoints.sqlite3"
    config = {"configurable": {"thread_id": "persist"}}
    citizen = {"age": 62, "is_widow": True, "income": 250000}
    with sqlite_checkpointer(db) as saver:
        state = build_graph(saver).invoke({"simulated_citizen": citizen}, config)
        assert state["__interrupt__"]
    with sqlite_checkpointer(db) as saver:
        graph = build_graph(saver)
        assert graph.get_state(config).next == ("approval",)
        final = graph.invoke(approve(graph, config), config)
    assert final["submission"]["status"].startswith("submitted")
