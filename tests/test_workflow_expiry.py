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


# Expired threads are refused when they are used, not only when the timer next runs


def agent_service(clock):
    saver = MemorySaver()
    service = api.AgentWorkflowService(checkpointer=saver, registry=ThreadRegistry("agent", clock=clock))
    service._agent_graph = graph_with_runs(saver, {"t1": "hh1"})
    return service, saver


def test_an_expired_conversation_cannot_be_continued_before_cleanup_runs(clock):
    service, saver = agent_service(clock)
    service.create_thread("hh1", "t1")
    clock.advance(hours=25)

    with pytest.raises(api.ThreadNotFoundError):
        service.execute_workflow("hello", "hh1", "t1")

    assert "t1" not in service.conversations and "t1" not in service.session_contexts
    assert saved_threads(saver) == set()  # deleted at the moment it was refused
    assert service.registry.threads_of("hh1") == set()


def test_an_expired_conversation_cannot_be_decided_on(clock):
    service, saver = agent_service(clock)
    service.create_thread("hh1", "t1")
    clock.advance(hours=25)

    with pytest.raises(api.ThreadNotFoundError):
        service.submit_decision("t1", "hh1", "approve", "h", {})

    assert saved_threads(saver) == set()


def restarted_after_expiry(clock):
    saver = MemorySaver()
    registry = ThreadRegistry("agent", clock=clock)
    first = api.AgentWorkflowService(checkpointer=saver, registry=registry)
    first._agent_graph = graph_with_runs(saver, {"t1": "hh1"})
    first.create_thread("hh1", "t1")
    clock.advance(hours=25)

    restarted = api.AgentWorkflowService(checkpointer=saver, registry=registry)
    restarted._agent_graph = first._agent_graph
    return restarted, saver


def test_an_expired_conversation_is_not_continued_after_a_restart(clock):
    restarted, saver = restarted_after_expiry(clock)

    with pytest.raises(api.ThreadNotFoundError):
        restarted.execute_workflow("hello", "hh1", "t1")

    assert "t1" not in restarted.conversations and saved_threads(saver) == set()


def test_an_expired_conversation_is_not_decided_on_after_a_restart(clock):
    restarted, saver = restarted_after_expiry(clock)

    with pytest.raises(api.ThreadNotFoundError):
        restarted.submit_decision("t1", "hh1", "approve", "h", {})

    assert "t1" not in restarted.conversations and saved_threads(saver) == set()
    assert restarted.registry.threads_of("hh1") == set()


def test_another_household_is_told_an_expired_conversation_does_not_exist(clock):
    service, _ = agent_service(clock)
    service.create_thread("hh1", "t1")
    clock.advance(hours=25)

    with pytest.raises(api.ThreadNotFoundError):
        service.execute_workflow("hello", "hh2", "t1")


def test_creating_a_conversation_under_an_expired_id_is_refused(clock):
    service, _ = agent_service(clock)
    service.create_thread("hh1", "t1")
    clock.advance(hours=25)
    with pytest.raises(api.ThreadNotFoundError):
        service.create_thread("hh1", "t1")


def test_using_a_conversation_in_date_keeps_it_alive(clock):
    service, _ = agent_service(clock)
    service.create_thread("hh1", "t1")
    clock.advance(hours=23)
    service._use_thread("t1", "hh1")
    clock.advance(hours=23)

    assert service.expire_idle() == 0
    service._use_thread("t1", "hh1")  # still usable


def test_the_api_reports_an_expired_conversation_as_not_found(monkeypatch, clock):
    from fastapi.testclient import TestClient

    from app.auth import AuthenticatedHousehold, authenticated_household

    service = api.AgentWorkflowService(registry=ThreadRegistry("agent", clock=clock))
    service.create_thread("hh1", "t1")
    clock.advance(hours=25)
    monkeypatch.setattr(api, "get_workflow_service", lambda: service)
    application = api.create_api(service=object())
    application.dependency_overrides[authenticated_household] = lambda: AuthenticatedHousehold("hh1", "user-1")
    client = TestClient(application)

    assert client.post("/api/chat", json={"message": "hello", "thread_id": "t1"}).status_code == 404
    assert client.post("/api/chat/t1/decision", json={"action": "approve", "payload_hash": "h"}).status_code == 404


def test_an_expired_application_thread_is_refused_and_deleted_on_the_spot(application_service, clock):
    service, store = application_service
    own(service, "t1", "hh1")
    upload(store, "t1")
    clock.advance(hours=25)

    with pytest.raises(SessionNotFoundError):
        service._check_thread_owner("t1", "hh1")

    assert store.list_documents("t1") == []
    assert "t1" not in service._thread_owners and service.registry.threads_of("hh1") == set()


@pytest.mark.parametrize("action", ["decide", "upload"])
def test_an_expired_application_thread_cannot_be_decided_on_or_uploaded_to(application_service, clock, action):
    service, store = application_service
    own(service, "t1", "hh1")
    upload(store, "t1")
    clock.advance(hours=25)

    with pytest.raises(SessionNotFoundError):
        if action == "decide":
            service.decide("t1", "approve", "h", {}, "hh1")
        else:
            service.upload_document("t1", "C01", "id-proof", "d.pdf", "application/pdf", b"%PDF-1.4", True, "hh1")

    assert store.list_documents("t1") == []


def test_touching_an_expired_application_thread_does_not_revive_it(application_service, clock):
    service, store = application_service
    own(service, "t1", "hh1")
    upload(store, "t1")
    clock.advance(hours=25)

    with pytest.raises(SessionNotFoundError):
        service._touch("t1", "hh1")

    assert service.registry.owner_of("t1") is None and store.list_documents("t1") == []


def test_touching_another_households_application_thread_is_refused(application_service):
    service, _ = application_service
    own(service, "t1", "hh1")
    with pytest.raises(DemoAccessError):
        service._touch("t1", "hh2")


def test_an_unknown_application_thread_is_not_created_by_looking_it_up(application_service):
    service, _ = application_service
    with pytest.raises(SessionNotFoundError):
        service._check_thread_owner("nope", "hh1")
    assert service.registry.owner_of("nope") is None


def test_an_application_thread_in_date_is_found_and_kept_alive(application_service, clock):
    service, _ = application_service
    own(service, "t1", "hh1")
    clock.advance(hours=23)
    service._check_thread_owner("t1", "hh1")
    service._touch("t1", "hh1")
    clock.advance(hours=23)
    assert service.expire_idle() == 0


def test_an_expired_chat_session_is_not_revived_by_use(application_service, clock):
    service, _ = application_service
    now = clock()
    service._chat_sessions["s1"] = ChatSession([], {}, {}, "hh1", created_at=now, last_used=now)
    clock.advance(hours=25)

    with pytest.raises(SessionNotFoundError):
        service._get_or_create_chat_session("s1", "hh1")

    assert "s1" not in service._chat_sessions


def test_a_chat_session_in_date_is_refreshed_by_use_until_the_absolute_limit(application_service, clock):
    service, _ = application_service
    now = clock()
    service._chat_sessions["s1"] = ChatSession([], {}, {}, "hh1", created_at=now, last_used=now)
    for _ in range(7):
        clock.advance(hours=23)
        service._get_or_create_chat_session("s1", "hh1")
    assert service._chat_sessions["s1"].last_used == clock()

    clock.advance(hours=23)  # 7 days and 2 hours old, though used a day ago
    with pytest.raises(SessionNotFoundError):
        service._get_or_create_chat_session("s1", "hh1")


def test_another_household_cannot_use_an_in_date_chat_session(application_service):
    service, _ = application_service
    now = time.time()
    service._chat_sessions["s1"] = ChatSession([], {}, {}, "hh1", created_at=now, last_used=now)
    with pytest.raises(DemoAccessError):
        service._get_or_create_chat_session("s1", "hh2")
