"""Forgetting a household across every session: workflow state, conversations and uploaded documents."""

import json
from typing import TypedDict

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app import api
from app.business_logic import ChatSession, DemoService
from app.document_storage import LocalDocumentStore
from app.forget import all_deleted, household_threads, run_forgetting, unfinished


class State(TypedDict, total=False):
    actor_id: str
    request: str


def graph_with_runs(runs):
    """A tiny graph that has already run once for each {thread_id: household_id}."""
    builder = StateGraph(State)
    builder.add_node("n", lambda state: {})
    builder.add_edge(START, "n")
    builder.add_edge("n", END)
    graph = builder.compile(checkpointer=MemorySaver())
    for thread_id, household_id in runs.items():
        graph.invoke({"actor_id": household_id, "request": "x"}, {"configurable": {"thread_id": thread_id}})
    return graph


def threads_in(graph):
    return {item.config["configurable"]["thread_id"] for item in graph.checkpointer.list(None)}


def put(store, thread_id, household_id=None, scheme_id="C01", document_type="id-proof"):
    return store.store(
        thread_id=thread_id,
        scheme_id=scheme_id,
        document_type=document_type,
        filename="doc.pdf",
        content_type="application/pdf",
        content=b"%PDF-1.4 masked",
        household_id=household_id,
    )


@pytest.fixture
def store(tmp_path):
    return LocalDocumentStore(tmp_path / "documents", start_maintenance=False)


# Finding a household's workflow state


def test_threads_are_found_by_the_household_named_in_their_saved_state():
    graph = graph_with_runs({"t1": "hh1", "t2": "hh2", "t3": "hh1"})
    assert household_threads(graph.checkpointer, "hh1") == {"t1", "t3"}
    assert household_threads(graph.checkpointer, "nobody") == set()
    assert household_threads(None, "hh1") == set()


# Agent conversations


def test_every_conversation_of_the_household_goes_even_one_nothing_else_names():
    service = api.AgentWorkflowService()
    service._agent_graph = graph_with_runs({"t1": "hh1", "t2": "hh2", "t3": "hh1"})
    service.create_thread("hh1", "t1")
    service.create_thread("hh2", "t2")  # t3 has saved state but no conversation record

    assert service.forget_household("hh1") == 2

    assert set(service.conversations) == {"t2"} and set(service.session_contexts) == {"t2"}
    assert threads_in(service._agent_graph) == {"t2"}


def test_forgetting_works_before_any_graph_was_built():
    service = api.AgentWorkflowService()
    service.create_thread("hh1", "t1")
    service.create_thread("hh2", "t2")
    assert service.forget_household("hh1") == 1
    assert set(service.conversations) == {"t2"}


def test_deleting_a_conversation_also_deletes_its_saved_workflow_state():
    service = api.AgentWorkflowService()
    service._agent_graph = graph_with_runs({"t1": "hh1", "t2": "hh1"})
    service.create_thread("hh1", "t1")
    service.create_thread("hh1", "t2")

    service.delete_conversation("t1")

    assert threads_in(service._agent_graph) == {"t2"}
    assert set(service.conversations) == {"t2"}


# The document store


def test_the_household_is_recorded_with_an_upload_but_not_shown_to_callers(store):
    shown = put(store, "t1", "hh1")
    assert "household_id" not in shown and "file_id" not in shown
    assert all("household_id" not in item for item in store.list_documents("t1"))
    recorded = json.loads(store.manifest_path.read_text())
    assert [record["household_id"] for record in recorded.values()] == ["hh1"]


def test_an_upload_without_a_household_records_none(store):
    put(store, "t1")
    [record] = json.loads(store.manifest_path.read_text()).values()
    assert "household_id" not in record


def test_a_household_is_deleted_from_every_session_by_its_recorded_id(store):
    put(store, "session-1", "hh1")
    put(store, "session-2", "hh1", scheme_id="C02")
    put(store, "other", "hh2")

    assert store.delete_household("hh1") == 2

    assert [d["thread_id"] for d in store.list_documents("other")] == ["other"]
    assert store.list_documents("session-1") == [] and store.list_documents("session-2") == []
    assert len(list(store.root.glob("*.bin"))) == 1


def test_uploads_from_before_the_household_was_recorded_go_with_their_known_threads(store):
    put(store, "old-thread")  # no household on record
    put(store, "someone-elses")
    assert store.delete_household("hh1", ["old-thread"]) == 1
    assert store.list_documents("old-thread") == [] and len(store.list_documents("someone-elses")) == 1


def test_deleting_a_household_with_no_uploads_changes_nothing(store):
    put(store, "t1", "hh2")
    before = store.manifest_path.read_bytes()
    assert store.delete_household("hh1", ["nope"]) == 0
    assert store.manifest_path.read_bytes() == before


# The application-workflow service


def demo_with(store, runs, owners):
    demo = DemoService(document_store=store)
    demo.workflow = graph_with_runs(runs)
    demo._thread_owners.update(owners)
    return demo


def test_documents_of_the_household_go_from_this_session_earlier_ones_and_legacy_uploads(store):
    demo = demo_with(
        store,
        runs={"t1": "hh1", "t2": "hh1", "t9": "hh2"},
        owners={"t1": "hh1", "t2": "hh1", "t9": "hh2"},
    )
    put(store, "t-from-before-a-restart", "hh1")
    put(store, "t1", "hh1")
    put(store, "t2")  # made before the household was recorded, but the thread is known to be hers
    put(store, "t9", "hh2")

    assert demo.forget_household_documents("hh1") == 3

    assert [d["thread_id"] for d in store.list_documents("t9")] == ["t9"]
    assert len(list(store.root.glob("*.bin"))) == 1


def test_documents_recorded_with_a_household_are_found_after_a_restart(store, tmp_path):
    put(store, "last-weeks-thread", "hh1")
    restarted = LocalDocumentStore(store.root, start_maintenance=False)
    demo = DemoService(document_store=restarted)  # no memory of any thread

    assert demo.forget_household_documents("hh1") == 1
    assert restarted.list_documents("last-weeks-thread") == []


def test_no_document_store_is_opened_when_none_exists(tmp_path, monkeypatch):
    monkeypatch.setenv(LocalDocumentStore.DIRECTORY_ENV, str(tmp_path / "never-created"))
    demo = DemoService()
    assert demo.forget_household_documents("hh1") == 0
    assert demo._document_store is None


def test_workflows_owners_subjects_and_chat_sessions_of_the_household_are_forgotten(store):
    demo = demo_with(
        store,
        runs={"t1": "hh1", "t2": "hh1", "t9": "hh2"},
        owners={"t1": "hh1", "t2": "hh1", "t9": "hh2"},
    )
    demo._thread_subjects.update({"t1": ("other", "mother"), "t9": ("self", None)})
    demo._chat_sessions["c1"] = ChatSession(required_fields=[], scheme_names={}, field_types={}, actor_id="hh1")
    demo._chat_sessions["c2"] = ChatSession(required_fields=[], scheme_names={}, field_types={}, actor_id="hh2")

    assert demo.forget_household_workflows("hh1") == 3  # two threads and one chat session

    assert demo._thread_owners == {"t9": "hh2"}
    assert threads_in(demo.workflow) == {"t9"}
    assert set(demo._chat_sessions) == {"c2"}
    assert demo.thread_subject("t1") == ("self", None) and demo.thread_subject("t9") == ("self", None)


def test_a_thread_only_its_saved_state_names_is_still_forgotten(store):
    demo = demo_with(store, runs={"orphan": "hh1", "t9": "hh2"}, owners={"t9": "hh2"})
    assert demo.forget_household_workflows("hh1") == 1
    assert threads_in(demo.workflow) == {"t9"}


def test_forgetting_a_household_with_nothing_held_deletes_nothing_and_is_repeatable(store):
    demo = demo_with(store, runs={"t9": "hh2"}, owners={"t9": "hh2"})
    for _ in range(2):
        assert demo.forget_household_documents("hh1") == 0
        assert demo.forget_household_workflows("hh1") == 0
    assert threads_in(demo.workflow) == {"t9"}


# Running the steps


def test_every_step_runs_and_is_reported():
    results = run_forgetting([("a", lambda: 3), ("b", lambda: None)])
    assert results == {"a": {"status": "deleted", "count": 3}, "b": {"status": "deleted"}}
    assert all_deleted(results) and unfinished(results) == []


def test_a_failing_step_does_not_stop_the_others_and_is_never_called_deleted():
    def boom():
        raise RuntimeError("down")

    results = run_forgetting([("a", boom), ("b", lambda: 1)])

    assert results == {"a": {"status": "failed"}, "b": {"status": "deleted", "count": 1}}
    assert not all_deleted(results) and unfinished(results) == ["a"]


def test_a_step_waits_for_the_one_it_depends_on():
    def boom():
        raise RuntimeError("down")

    ran = []
    results = run_forgetting(
        [("documents", boom), ("workflows", lambda: ran.append(1))], {"workflows": "documents"}
    )

    assert results["workflows"] == {"status": "skipped"} and ran == []
    assert unfinished(results) == ["documents", "workflows"]


def test_the_failure_log_carries_no_exception_text(caplog):
    private = "1234 5678 9012"

    def boom():
        raise RuntimeError(private)

    with caplog.at_level("ERROR", logger="app.forget"):
        run_forgetting([("documents", boom)])

    assert "documents" in caplog.text
    assert "RuntimeError" in caplog.text
    assert private not in caplog.text
