import json

from fastapi.testclient import TestClient

from agents.contracts import CandidateFact, IntakeResult
from app import app_new, business_logic
from app.auth import AuthenticatedHousehold, authenticated_household
from app.api import create_api
from app.business_logic import ChatIntakeInput, DemoService
from servers.rule_engine import server as rule_server


def authenticated_client(application, household_id="household-1"):
    application.dependency_overrides[authenticated_household] = lambda: AuthenticatedHousehold(
        household_id, f"test|{household_id}"
    )
    return TestClient(application)


def test_local_api_url_reuses_an_existing_demo_api(monkeypatch):
    api_base = "http://127.0.0.1:8766"
    monkeypatch.delenv("SCHEME_SAATHI_API_URL", raising=False)
    monkeypatch.setenv("SCHEME_SAATHI_CHAT_API_PORT", "8766")
    monkeypatch.setattr(app_new, "_is_scheme_saathi_api", lambda url: url == api_base)

    def fail_if_started(port):
        raise AssertionError(f"Should reuse the API already on port {port}.")

    monkeypatch.setattr(app_new, "_start_local_api", fail_if_started)

    assert app_new._api_base_url() == api_base


def parse_events(body):
    events = []
    for block in body.decode("utf-8").split("\n\n"):
        if not block.strip():
            continue
        name = "message"
        data = []
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        if data:
            events.append((name, json.loads("\n".join(data))))
    return events


def test_streamed_demo_workflow_requires_documents_before_approval():
    application = create_api(DemoService())
    client = authenticated_client(application)
    scheme_id = "SYNTH-PENSION-001"
    response = client.post(
        "/api/analyze",
        json={
            "citizen": {"age": 62, "income": 250000, "is_widow": True},
            "scheme_ids": [scheme_id],
        },
    )

    assert response.status_code == 200
    events = parse_events(response.content)
    assert any(name == "progress" for name, _ in events)
    result = next(payload for name, payload in events if name == "result")
    assert result["verdicts"][scheme_id]["verdict"] == "eligible"
    assert result["approval"]["payload_hash"]

    thread_id = result["thread_id"]
    approval = result["approval"]
    application.dependency_overrides[authenticated_household] = lambda: AuthenticatedHousehold(
        "household-2", "test|household-2"
    )
    unauthorized = client.post(
        f"/api/threads/{thread_id}/decision",
        json={"action": "approve", "payload_hash": approval["payload_hash"]},
    )
    assert unauthorized.status_code == 403
    application.dependency_overrides[authenticated_household] = lambda: AuthenticatedHousehold(
        "household-1", "test|household-1"
    )
    blocked = client.post(
        f"/api/threads/{thread_id}/decision",
        json={"action": "approve", "payload_hash": approval["payload_hash"]},
    )
    assert blocked.status_code == 409
    assert "required documents" in blocked.json()["detail"]

    for document_type in result["documents"][scheme_id]:
        uploaded = client.post(
            f"/api/threads/{thread_id}/documents/upload",
            data={"scheme_id": scheme_id, "document_type": document_type},
            files={"file": ("sample.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        )
        assert uploaded.status_code == 200

    submitted = client.post(
        f"/api/threads/{thread_id}/decision",
        json={"action": "approve", "payload_hash": approval["payload_hash"]},
    )
    assert submitted.status_code == 200
    final_events = parse_events(submitted.content)
    final_result = next(payload for name, payload in final_events if name == "result")
    assert final_result["submission"]["status"].startswith("submitted")


def test_unknown_scheme_is_rejected_before_streaming():
    client = authenticated_client(create_api(DemoService()))

    response = client.post(
        "/api/analyze",
        json={
            "citizen": {"age": 62, "income": 250000, "is_widow": True},
            "scheme_ids": ["unknown-scheme"],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "The selected scheme is not available."


def test_tool_errors_in_legacy_stream_do_not_expose_exception_text():
    private_marker = "1234 5678 9012"

    class FailedWorkflow:
        def stream(self, *_args, **_kwargs):
            raise business_logic.ToolCallError(
                "rule-engine", "evaluate_profile", "tool_error", private_marker
            )
            yield

    service = DemoService()
    service.workflow = FailedWorkflow()
    events = list(
        service._stream_run({}, {"configurable": {"thread_id": "test"}}, "test")
    )

    error = next(payload for name, payload in events if name == "error")
    assert private_marker not in error["detail"]
    assert error["detail"] == "A required workflow tool call could not be completed."


class FakeChatIntakeAgent:
    def invoke(self, payload: ChatIntakeInput) -> IntakeResult:
        candidates = []
        request = payload.request.lower()
        if "62" in request:
            candidates.append(
                CandidateFact(
                    field="age",
                    value=62,
                    confidence="high",
                )
            )
        if "widow" in request:
            candidates.append(
                CandidateFact(
                    field="is_widow",
                    value=True,
                    confidence="high",
                )
            )
        if "income" in request:
            candidates.append(
                CandidateFact(
                    field="income",
                    value=250000,
                    confidence="high",
                )
            )
        return IntakeResult(
            language="en",
            intent="eligibility",
            candidate_facts=candidates,
        )


def test_chat_requests_missing_details_before_checking_eligibility(monkeypatch):
    monkeypatch.setattr(rule_server, "RULE_DIRS", [rule_server.SCHEME_DIR])
    evaluated_schemes = []
    evaluate_scheme = business_logic.tools.evaluate_scheme

    def track_evaluation(profile, scheme_id):
        evaluated_schemes.append(scheme_id)
        return evaluate_scheme(profile, scheme_id)

    monkeypatch.setattr(business_logic.tools, "evaluate_scheme", track_evaluation)
    application = create_api(DemoService(FakeChatIntakeAgent()))
    client = authenticated_client(application)

    first_response = client.post(
        "/api/chat/legacy",
        json={"user_input": "I am 62 and a widow. What schemes can I get?"},
    )
    assert first_response.status_code == 200
    first_events = parse_events(first_response.content)
    first_result = next(
        payload for name, payload in first_events if name == "result"
    )
    chat_id = next(
        payload["session_id"]
        for name, payload in first_events
        if name == "session"
    )
    assert first_result["status"] == "needs_details"
    assert "income" in first_result["missing_fields"]
    assert evaluated_schemes == []

    application.dependency_overrides[authenticated_household] = lambda: AuthenticatedHousehold(
        "household-2", "test|household-2"
    )
    unauthorized = client.post(
        "/api/chat/legacy",
        json={"user_input": "Our annual household income is 250000 INR.", "session_id": chat_id},
    )
    assert unauthorized.status_code == 200
    assert next(payload for name, payload in parse_events(unauthorized.content) if name == "error")[
        "detail"
    ] == "The chat session was not found."
    application.dependency_overrides[authenticated_household] = lambda: AuthenticatedHousehold(
        "household-1", "test|household-1"
    )

    second_response = client.post(
        "/api/chat/legacy",
        json={
            "user_input": "Our annual household income is 250000 INR.",
            "session_id": chat_id,
        },
    )
    assert second_response.status_code == 200
    second_events = parse_events(second_response.content)
    final_result = next(
        payload for name, payload in second_events if name == "result"
    )
    assert final_result["status"] == "eligibility_checked"
    assert final_result["verdicts"]
    assert evaluated_schemes == list(final_result["verdicts"])


def test_chat_reports_unknown_session_in_stream():
    client = authenticated_client(create_api(DemoService(FakeChatIntakeAgent())))

    response = client.post(
        "/api/chat/legacy",
        json={"user_input": "I am 62.", "session_id": "expired-session"},
    )

    assert response.status_code == 200
    events = parse_events(response.content)
    error = next(payload for name, payload in events if name == "error")
    assert "chat session was not found" in error["detail"]
