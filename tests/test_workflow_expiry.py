"""Workflow thread ownership and expiry: after a restart, when idle, and past the absolute limit."""

import time
from datetime import timedelta
from typing import TypedDict

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app import api
from app.business_logic import ChatSession, DemoService, SessionNotFoundError, ThreadAccessError as DemoAccessError
from app.document_storage import LocalDocumentStore
from app.thread_registry import ThreadRegistry


class State(TypedDict, total=False):
    actor_id: str
    request: str


class Clock:
    def __init__(self):
        self.now = time.time()

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta).total_seconds()


@pytest.fixture
def clock():
    return Clock()


def graph_with_runs(saver, runs):
    builder = StateGraph(State)
    builder.add_node("n", lambda state: {})
    builder.add_edge(START, "n")
    builder.add_edge("n", END)
    graph = builder.compile(checkpointer=saver)
    for thread_id, household_id in runs.items():
        graph.invoke({"actor_id": household_id, "request": "x"}, {"configurable": {"thread_id": thread_id}})
    return graph


def saved_threads(saver):
    return {item.config["configurable"]["thread_id"] for item in saver.list(None)}


# Agent conversations


def test_a_restarted_service_still_refuses_another_households_thread(clock):
    registry = ThreadRegistry("agent", clock=clock)
    api.AgentWorkflowService(registry=registry).create_thread("hh1", "t1")

    restarted = api.AgentWorkflowService(registry=registry)

    with pytest.raises(api.ThreadAccessError):
        restarted.execute_workflow("hello", "hh2", "t1")
    with pytest.raises(api.ThreadAccessError):
        restarted.submit_decision("t1", "hh2", "approve", None, {})
    assert "t1" not in restarted.conversations


def test_a_restarted_service_gives_the_owner_their_thread_back(clock):
    saver = MemorySaver()
    registry = ThreadRegistry("agent", clock=clock)
    api.AgentWorkflowService(registry=registry).create_thread("hh1", "t1")
    restarted = api.AgentWorkflowService(checkpointer=saver, registry=registry)
    restarted._agent_graph = graph_with_runs(saver, {"t1": "hh1"})

    with pytest.raises(api.NoPendingApprovalError):  # past the lookup and the owner check
        restarted.submit_decision("t1", "hh1", "approve", None, {})

    assert restarted.conversations["t1"]["actor_id"] == "hh1"


def test_a_thread_nobody_knows_is_not_found(clock):
    service = api.AgentWorkflowService(registry=ThreadRegistry("agent", clock=clock))
    with pytest.raises(api.ThreadNotFoundError):
        service.submit_decision("nope", "hh1", "approve", None, {})


def test_an_idle_conversation_is_deleted_with_its_saved_state(clock):
    saver = MemorySaver()
    service = api.AgentWorkflowService(checkpointer=saver, registry=ThreadRegistry("agent", clock=clock))
    service._agent_graph = graph_with_runs(saver, {"old": "hh1", "new": "hh1"})
    service.create_thread("hh1", "old")
    clock.advance(hours=20)
    service.create_thread("hh1", "new")
    clock.advance(hours=6)

    assert service.expire_idle() == 1

    assert set(service.conversations) == {"new"} and set(service.session_contexts) == {"new"}
    assert saved_threads(saver) == {"new"}
    assert service.registry.owner_of("old") is None
    assert service.expire_idle() == 0


def test_a_conversation_in_use_expires_only_at_the_absolute_limit(clock):
    service = api.AgentWorkflowService(registry=ThreadRegistry("agent", clock=clock))
    service.create_thread("hh1", "t1")
    for _ in range(7):
        clock.advance(hours=23)
        service.registry.touch("t1", "hh1")
    assert service.expire_idle() == 0

    clock.advance(hours=23)
    assert service.expire_idle() == 1
    assert service.conversations == {}


# Application workflows


@pytest.fixture
def application_service(tmp_path, clock):
    store = LocalDocumentStore(tmp_path / "documents", start_maintenance=False)
    registry = ThreadRegistry("application", clock=clock)
    return DemoService(document_store=store, registry=registry), store


def own(service, thread_id, household_id):
    service._thread_owners[thread_id] = household_id
    service.registry.touch(thread_id, household_id)


def upload(store, thread_id):
    store.store(
        thread_id=thread_id,
        scheme_id="C01",
        document_type="id-proof",
        filename="doc.pdf",
        content_type="application/pdf",
        content=b"%PDF-1.4 masked",
    )


def test_a_restarted_service_still_knows_who_owns_an_application_thread(application_service, clock):
    service, _ = application_service
    own(service, "t1", "hh1")

    restarted = DemoService(registry=service.registry)

    restarted._check_thread_owner("t1", "hh1")
    with pytest.raises(DemoAccessError):
        restarted._check_thread_owner("t1", "hh2")
    with pytest.raises(SessionNotFoundError):
        restarted._check_thread_owner("unknown", "hh1")


def test_an_idle_application_thread_goes_with_its_uploads(application_service, clock):
    service, store = application_service
    own(service, "old", "hh1")
    upload(store, "old")
    clock.advance(hours=20)
    own(service, "new", "hh1")
    upload(store, "new")
    clock.advance(hours=6)

    assert service.expire_idle() == 1

    assert store.list_documents("old") == [] and len(store.list_documents("new")) == 1
    assert "old" not in service._thread_owners and "new" in service._thread_owners
    assert service.registry.owner_of("old") is None


def test_stale_chat_sessions_expire_and_fresh_ones_stay(application_service, clock):
    service, _ = application_service
    now = clock()
    service._chat_sessions["idle"] = ChatSession([], {}, {}, "hh1", created_at=now, last_used=now)
    service._chat_sessions["old"] = ChatSession([], {}, {}, "hh1", created_at=now, last_used=now)
    clock.advance(hours=20)
    service._chat_sessions["old"].last_used = clock()
    service._chat_sessions["fresh"] = ChatSession([], {}, {}, "hh1", created_at=clock(), last_used=clock())
    clock.advance(hours=6)

    assert service.expire_idle() == 1
    assert set(service._chat_sessions) == {"old", "fresh"}

    clock.advance(days=7)
    assert service.expire_idle() == 2
    assert service._chat_sessions == {}


def test_expiry_with_nothing_to_expire_does_not_open_the_document_store(tmp_path, monkeypatch, clock):
    monkeypatch.setenv("SCHEME_SAATHI_DOCUMENT_STORE_DIR", str(tmp_path / "never"))
    service = DemoService(registry=ThreadRegistry("application", clock=clock))

    assert service.expire_idle() == 0

    assert not (tmp_path / "never").exists()
