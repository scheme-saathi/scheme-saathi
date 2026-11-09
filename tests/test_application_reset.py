"""Resetting leaves no application workflow behind, including in a durable checkpoint file."""

import sqlite3
import time
from datetime import timedelta
from typing import TypedDict

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from streamlit.testing.v1 import AppTest

from app import app_new
from app.api import create_api
from app.auth import AuthenticatedHousehold, authenticated_household
from app.business_logic import DemoService, SessionNotFoundError, ThreadAccessError
from app.document_storage import LocalDocumentStore
from app.thread_registry import ThreadRegistry


class State(TypedDict, total=False):
    actor_id: str
    simulated_citizen: dict


class Clock:
    def __init__(self):
        self.now = time.time()

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta).total_seconds()


def threads_on_disk(path):
    """The thread ids the checkpoint file holds, read through a fresh connection."""
    connection = sqlite3.connect(str(path))
    try:
        rows = connection.execute(
            "SELECT thread_id FROM checkpoints UNION SELECT thread_id FROM writes"
        ).fetchall()
    finally:
        connection.close()
    return {row[0] for row in rows}


def put_document(store, thread_id):
    store.store(
        thread_id=thread_id,
        scheme_id="C01",
        document_type="id-proof",
        filename="doc.pdf",
        content_type="application/pdf",
        content=b"%PDF-1.4 masked",
        household_id="hh1",
    )


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def durable(tmp_path, clock):
    """An application service over a real SQLite checkpoint file with workflows for two households."""
    path = tmp_path / "state" / "workflow.sqlite"
    path.parent.mkdir()
    saver = SqliteSaver(sqlite3.connect(str(path), check_same_thread=False))
    store = LocalDocumentStore(tmp_path / "documents", start_maintenance=False)
    demo = DemoService(document_store=store, checkpointer=saver, registry=ThreadRegistry("application", clock=clock))

    builder = StateGraph(State)
    builder.add_node("n", lambda state: {})
    builder.add_edge(START, "n")
    builder.add_edge("n", END)
    demo.workflow = builder.compile(checkpointer=saver)
    for thread_id, household_id in {"t1": "hh1", "t2": "hh1", "t9": "hh2"}.items():
        demo.workflow.invoke(
            {"actor_id": household_id, "simulated_citizen": {"age": 62}},
            {"configurable": {"thread_id": thread_id}},
        )
        demo._thread_owners[thread_id] = household_id
        demo.registry.touch(thread_id, household_id)
    demo._thread_subjects.update({"t1": ("other", "mother"), "t2": ("self", None)})
    put_document(store, "t1")
    assert threads_on_disk(path) == {"t1", "t2", "t9"}
    yield demo, store, path
    saver.conn.close()


# The service


def test_deleting_a_workflow_removes_its_saved_state_from_the_durable_file(durable):
    demo, store, path = durable

    deleted = demo.delete_workflow("t1", "hh1")

    assert deleted == 1
    assert threads_on_disk(path) == {"t2", "t9"}  # read from the file, not from memory
    assert store.list_documents("t1") == []
    assert "t1" not in demo._thread_owners and demo.registry.owner_of("t1") is None
    assert demo.thread_subject("t1") == ("self", None)


def test_the_deletion_survives_reopening_the_file(durable):
    demo, _, path = durable
    demo.delete_workflow("t1", "hh1")

    reopened = SqliteSaver(sqlite3.connect(str(path), check_same_thread=False))
    try:
        assert {item.config["configurable"]["thread_id"] for item in reopened.list(None)} == {"t2", "t9"}
    finally:
        reopened.conn.close()


def test_the_callers_other_workflows_and_other_households_are_left_alone(durable):
    demo, _, path = durable
    demo.delete_workflow("t1", "hh1")
    assert threads_on_disk(path) == {"t2", "t9"}
    assert demo._thread_owners == {"t2": "hh1", "t9": "hh2"}
    assert demo.thread_subject("t2") == ("self", None)


def test_another_household_cannot_delete_a_workflow(durable):
    demo, store, path = durable
    with pytest.raises(ThreadAccessError):
        demo.delete_workflow("t1", "hh2")
    assert threads_on_disk(path) == {"t1", "t2", "t9"}
    assert len(store.list_documents("t1")) == 1


def test_an_unknown_or_already_deleted_workflow_is_not_found(durable):
    demo, _, _ = durable
    with pytest.raises(SessionNotFoundError):
        demo.delete_workflow("nope", "hh1")
    demo.delete_workflow("t1", "hh1")
    with pytest.raises(SessionNotFoundError):
        demo.delete_workflow("t1", "hh1")


def test_an_expired_workflow_is_not_found_and_is_deleted_too(durable, clock):
    demo, _, path = durable
    clock.advance(hours=25)

    with pytest.raises(SessionNotFoundError):
        demo.delete_workflow("t1", "hh1")

    assert "t1" not in threads_on_disk(path)


def test_deleting_only_the_documents_keeps_the_workflow_which_is_why_reset_needs_the_new_call(durable):
    demo, store, path = durable

    assert demo.delete_uploaded_documents("t1", "hh1") == 1

    assert store.list_documents("t1") == []
    assert "t1" in threads_on_disk(path)  # the profile and draft are still in the file


# The API


@pytest.fixture
def client(durable):
    demo, _, _ = durable
    who = {"household": "hh1"}
    application = create_api(demo)
    application.dependency_overrides[authenticated_household] = lambda: AuthenticatedHousehold(
        who["household"], "sub-1"
    )
    test_client = TestClient(application)
    test_client.who = who
    return test_client


def test_the_api_deletes_the_workflow_and_reports_the_documents_removed(client, durable):
    _, _, path = durable

    response = client.delete("/api/threads/t1")

    assert response.status_code == 200
    assert response.json() == {"status": "success", "deleted_documents": 1}
    assert threads_on_disk(path) == {"t2", "t9"}


def test_the_api_reports_a_second_deletion_as_not_found(client):
    assert client.delete("/api/threads/t1").status_code == 200
    assert client.delete("/api/threads/t1").status_code == 404


def test_the_api_refuses_another_households_workflow(client, durable):
    _, _, path = durable
    client.who["household"] = "hh2"

    assert client.delete("/api/threads/t1").status_code == 403
    assert threads_on_disk(path) == {"t1", "t2", "t9"}


def test_the_api_needs_a_signed_in_person(durable):
    demo, _, path = durable
    anonymous = TestClient(create_api(demo))
    assert anonymous.delete("/api/threads/t1").status_code == 401
    assert threads_on_disk(path) == {"t1", "t2", "t9"}


def test_the_documents_endpoint_still_leaves_the_workflow(client, durable):
    _, _, path = durable
    assert client.delete("/api/threads/t1/documents").status_code == 200
    assert "t1" in threads_on_disk(path)


# The screen


def reset_screen():
    import streamlit as st
    from app import app_new

    st.session_state["application_result"] = {"thread_id": "app-thread"}
    st.session_state["chat_session_id"] = "chat-1"
    st.session_state["chat_messages"] = [{"role": "user", "content": "hello"}]
    st.session_state["reset_ok"] = app_new._reset_chat()


def withdraw_screen():
    import streamlit as st
    from app import app_new

    st.session_state["application_result"] = {"thread_id": "app-thread"}
    st.session_state["chat_session_id"] = "chat-1"
    st.session_state["reset_ok"] = app_new._withdraw_consent()


def no_application_screen():
    import streamlit as st
    from app import app_new

    st.session_state["application_result"] = None
    st.session_state["chat_session_id"] = "chat-1"
    st.session_state["reset_ok"] = app_new._reset_chat()


def documents_only_screen():
    from app import app_new

    app_new._delete_uploaded_documents("app-thread", "http://api")


@pytest.fixture
def requests(monkeypatch):
    calls = []

    def fake(url, method="GET", body=None, headers=None):
        calls.append((url, method))
        return {"status": "success"}

    monkeypatch.setattr(app_new, "_api_request", fake)
    monkeypatch.setattr(app_new, "_api_base_url", lambda: "http://api")
    return calls


def test_a_reset_deletes_the_application_workflow_and_the_chat_conversation(requests):
    app = AppTest.from_function(reset_screen).run()

    assert not app.exception
    assert requests == [
        ("http://api/api/threads/app-thread", "DELETE"),
        ("http://api/api/chat/chat-1", "DELETE"),
    ]
    assert app.session_state["reset_ok"] is True
    assert app.session_state["application_result"] is None and app.session_state["chat_session_id"] is None


def test_withdrawing_consent_deletes_the_application_workflow_too(requests):
    app = AppTest.from_function(withdraw_screen).run()

    assert not app.exception
    assert ("http://api/api/threads/app-thread", "DELETE") in requests
    assert app.session_state["reset_ok"] is True


def test_a_reset_with_no_application_only_deletes_the_conversation(requests):
    app = AppTest.from_function(no_application_screen).run()

    assert requests == [("http://api/api/chat/chat-1", "DELETE")]
    assert app.session_state["reset_ok"] is True


def test_a_workflow_that_is_already_gone_does_not_block_the_reset(monkeypatch):
    calls = []

    def fake(url, method="GET", body=None, headers=None):
        calls.append(url)
        if "/api/threads/" in url:
            raise RuntimeError("The application session was not found.")
        return {}

    monkeypatch.setattr(app_new, "_api_request", fake)
    monkeypatch.setattr(app_new, "_api_base_url", lambda: "http://api")

    app = AppTest.from_function(reset_screen).run()

    assert app.session_state["reset_ok"] is True
    assert any("/api/chat/chat-1" in url for url in calls)
    assert app.session_state["application_result"] is None


def test_when_the_workflow_cannot_be_deleted_the_reset_stops_and_keeps_the_screen_state(monkeypatch):
    calls = []

    def fake(url, method="GET", body=None, headers=None):
        calls.append(url)
        raise RuntimeError("The checkpoint database is locked.")

    monkeypatch.setattr(app_new, "_api_request", fake)
    monkeypatch.setattr(app_new, "_api_base_url", lambda: "http://api")

    app = AppTest.from_function(reset_screen).run()

    assert app.session_state["reset_ok"] is False
    assert calls == ["http://api/api/threads/app-thread"]  # nothing else was attempted
    assert app.session_state["application_result"] == {"thread_id": "app-thread"}
    assert any("locked" in str(item.value) for item in app.error)


def test_the_forget_documents_button_still_deletes_only_the_documents(requests):
    app = AppTest.from_function(documents_only_screen).run()
    assert not app.exception
    assert requests == [("http://api/api/threads/app-thread/documents", "DELETE")]
