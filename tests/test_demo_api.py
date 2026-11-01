import json

from fastapi.testclient import TestClient

from agents.contracts import CandidateFact, IntakeResult
from app import business_logic
from app.api import create_api
from app.business_logic import ChatIntakeInput, DemoService


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
    client = TestClient(create_api(DemoService()))
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
    client = TestClient(create_api(DemoService()))

    response = client.post(
        "/api/analyze",
        json={
            "citizen": {"age": 62, "income": 250000, "is_widow": True},
            "scheme_ids": ["unknown-scheme"],
        },
    )

    assert response.status_code == 422
    assert "unknown-scheme" in response.json()["detail"]


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
    evaluated_schemes = []
    evaluate_scheme = business_logic.tools.evaluate_scheme

    def track_evaluation(profile, scheme_id):
        evaluated_schemes.append(scheme_id)
        return evaluate_scheme(profile, scheme_id)

    monkeypatch.setattr(business_logic.tools, "evaluate_scheme", track_evaluation)
    client = TestClient(create_api(DemoService(FakeChatIntakeAgent())))

    first_response = client.post(
        "/api/chat",
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

    second_response = client.post(
        "/api/chat",
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
    client = TestClient(create_api(DemoService(FakeChatIntakeAgent())))

    response = client.post(
        "/api/chat",
        json={"user_input": "I am 62.", "session_id": "expired-session"},
    )

    assert response.status_code == 200
    events = parse_events(response.content)
    error = next(payload for name, payload in events if name == "error")
    assert "chat session was not found" in error["detail"]
