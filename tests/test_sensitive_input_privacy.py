import asyncio
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from agents.persona_validator import (
    SensitiveInputError,
    reject_sensitive_graph_input,
    reject_sensitive_input,
)
from agents.supervisor import InputValidator
from app import api
from app.auth import AuthenticatedHousehold, authenticated_household
from graph.agent_workflow import build_agent_graph
from graph.workflow import build_graph
from graph.tools import budget_graph
from tests.test_api_approval import make_agents


FAKE_AADHAAR = "1234 5678 9012"
FAKE_IFSC = "ABCD0123456"


def test_supervisor_does_not_send_rejected_text_to_router():
    router = Mock()
    result = InputValidator(router=router).validate_request(f"My Aadhaar is {FAKE_AADHAAR}")
    assert not result.passed
    router.classify.assert_not_called()


@pytest.mark.parametrize("text", [FAKE_AADHAAR, FAKE_IFSC, "123456789012345"])
def test_chat_rejects_sensitive_input_before_workflow_or_history(monkeypatch, text):
    service = Mock()
    monkeypatch.setattr(api, "get_workflow_service", lambda: service)
    application = api.create_api(service=object())
    application.dependency_overrides[authenticated_household] = lambda: AuthenticatedHousehold(
        "household", "test|household"
    )
    response = TestClient(application).post("/api/chat", json={"message": f"My details: {text}"})
    assert response.status_code == 422
    assert text not in response.text
    service.execute_workflow.assert_not_called()


def test_graph_rejects_sensitive_request_before_checkpoint():
    saver = MemorySaver()
    graph = build_agent_graph(make_agents(), checkpointer=saver)
    config = {"configurable": {"thread_id": "privacy-test"}}
    with pytest.raises(ValueError, match="Sensitive"):
        graph.invoke({"request": f"My Aadhaar is {FAKE_AADHAAR}", "actor_id": "household"}, config)
    assert list(saver.list(config)) == []


@pytest.mark.parametrize("value", [
    {"nested": [{"note": FAKE_IFSC.lower()}]},
    {"account_number": 123456789},
    {"other": 123456789012},
    {"otp": "4321"},
])
def test_structured_identifiers_are_rejected(value):
    with pytest.raises(SensitiveInputError):
        reject_sensitive_input(value)


def test_normal_facts_are_not_rejected():
    reject_sensitive_input({
        "income": 123456789,
        "has_individual_bank_or_post_office_account": True,
        "age": 35,
        "description": "I have an IFSC code",
    })


@pytest.mark.parametrize("text", [
    "aadhaar 2345.6789.0123",
    "aadhaar 2345\u200b6789\u200b0123",
    "call me on +91 98765 43210",
    "my otp is 482913",
    "password: hunter2",
])
def test_obfuscated_identifiers_and_secrets_are_rejected(text):
    with pytest.raises(SensitiveInputError):
        reject_sensitive_input(text)


@pytest.mark.parametrize("build", [build_graph, lambda checkpointer: build_agent_graph(make_agents(), checkpointer)])
def test_graph_rejects_resume_and_stream_before_checkpoint(build):
    saver = MemorySaver()
    graph = build(saver)
    config = {"configurable": {"thread_id": "stream-privacy"}}
    with pytest.raises(SensitiveInputError):
        list(graph.stream(Command(resume={"changes": {"account_number": 123456789}}), config))
    assert list(saver.list(config)) == []


def test_guard_covers_async_and_batch_execution():
    underlying = Mock()
    graph = budget_graph(underlying, input_guard=reject_sensitive_graph_input)
    with pytest.raises(SensitiveInputError):
        asyncio.run(graph.ainvoke(input={"request": FAKE_AADHAAR}))
    with pytest.raises(SensitiveInputError):
        graph.batch([{"request": "Hello"}, {"request": FAKE_AADHAAR}])
    with pytest.raises(SensitiveInputError):
        asyncio.run(graph.abatch([{"request": FAKE_AADHAAR}]))

    async def consume_stream():
        return [item async for item in graph.astream({"request": FAKE_AADHAAR})]

    with pytest.raises(SensitiveInputError):
        asyncio.run(consume_stream())
    underlying.invoke.assert_not_called()
    underlying.batch.assert_not_called()


def test_graph_rejects_command_update_before_checkpoint():
    saver = MemorySaver()
    graph = build_agent_graph(make_agents(), checkpointer=saver)
    config = {"configurable": {"thread_id": "command-privacy"}}
    with pytest.raises(SensitiveInputError):
        graph.invoke(Command(update={"request": FAKE_AADHAAR}), config)
    assert list(saver.list(config)) == []


def test_direct_service_rejects_before_thread_creation():
    service = api.AgentWorkflowService()
    with pytest.raises(SensitiveInputError):
        service.execute_workflow(FAKE_AADHAAR, "household")
    assert service.conversations == {}


@pytest.mark.parametrize(("path", "body"), [
    ("/api/chat", {"message": "Help me", "known_facts": {"note": FAKE_IFSC}}),
    ("/api/chat/legacy", {"user_input": FAKE_AADHAAR}),
    ("/api/analyze", {"citizen": {"bank_account": 123456789}}),
    ("/api/chat/some-thread/decision", {"action": "edit", "changes": {"otp": "4321"}}),
    ("/api/threads/some-thread/decision", {"action": "edit", "changes": {"note": FAKE_IFSC}}),
])
def test_api_rejects_sensitive_values_without_calling_services(path, body, monkeypatch, caplog):
    demo = Mock()
    service = Mock()
    monkeypatch.setattr(api, "get_workflow_service", lambda: service)
    application = api.create_api(service=demo)
    application.dependency_overrides[authenticated_household] = lambda: AuthenticatedHousehold(
        "household", "test|household"
    )
    response = TestClient(application).post(path, json=body)
    assert response.status_code == 422
    assert FAKE_AADHAAR not in response.text and FAKE_IFSC not in response.text
    assert FAKE_AADHAAR not in caplog.text and FAKE_IFSC not in caplog.text
    service.execute_workflow.assert_not_called()
    service.submit_decision.assert_not_called()
    demo.chat_turn.assert_not_called()
    demo.analyze.assert_not_called()
    demo.decide.assert_not_called()


def test_invalid_request_does_not_echo_sensitive_text():
    application = api.create_api(service=Mock())
    application.dependency_overrides[authenticated_household] = lambda: AuthenticatedHousehold(
        "household", "test|household"
    )
    response = TestClient(application).post("/api/chat", json={"message": FAKE_AADHAAR * 500})
    assert response.status_code == 422
    assert FAKE_AADHAAR not in response.text


def test_upload_rejects_sensitive_filename_before_storage():
    demo = Mock()
    application = api.create_api(service=demo)
    application.dependency_overrides[authenticated_household] = lambda: AuthenticatedHousehold(
        "household", "test|household"
    )
    response = TestClient(application).post(
        "/api/threads/thread-1/documents/upload",
        data={"scheme_id": "C01", "document_type": "proof", "sensitive_ids_masked": "true"},
        files={"file": (f"{FAKE_AADHAAR}.pdf", b"%PDF-1.0", "application/pdf")},
    )
    assert response.status_code == 422
    assert FAKE_AADHAAR not in response.text
    demo.upload_document.assert_not_called()
