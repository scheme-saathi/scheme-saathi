import json

from fastapi.testclient import TestClient

from agents.contracts import CandidateFact, IntakeResult
from app import api, app_new
from app.api import ChatIntakeInput, DemoService, create_api
from app.document_storage import LocalDocumentStore


def test_local_api_url_reuses_an_existing_demo_api(monkeypatch):
    api_base = "http://127.0.0.1:8766"
    monkeypatch.delenv("SCHEME_SAATHI_API_URL", raising=False)
    monkeypatch.setenv("SCHEME_SAATHI_CHAT_API_PORT", "8766")
    monkeypatch.setattr(app_new, "_is_scheme_saathi_api", lambda url: url == api_base)

    def fail_if_started(port):
        raise AssertionError(f"Should reuse the API already on port {port}.")

    monkeypatch.setattr(app_new, "_start_local_api", fail_if_started)

    assert app_new._api_base_url() == api_base


def test_streamlit_chat_client_uses_legacy_sse_endpoint(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            return iter(
                [
                    b"event: session\n",
                    b'data: {"session_id": "demo-session"}\n',
                    b"\n",
                    b"event: assistant\n",
                    b'data: {"content": "Please share your annual income."}\n',
                    b"\n",
                    b"event: result\n",
                    b'data: {"status": "needs_details"}\n',
                    b"\n",
                ]
            )

    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        assert timeout == 300
        return FakeResponse()

    monkeypatch.setattr(app_new, "urlopen", fake_urlopen)
    progress = type("Progress", (), {"write": lambda self, _message: None})()

    session_id, reply, result = app_new._send_chat(
        "http://127.0.0.1:8766",
        "I am 62 and a widow.",
        None,
        progress,
    )

    assert requests[0].full_url == "http://127.0.0.1:8766/api/chat/legacy"
    assert json.loads(requests[0].data) == {
        "user_input": "I am 62 and a widow.",
        "session_id": None,
    }
    assert session_id == "demo-session"
    assert reply == "Please share your annual income."
    assert result == {"status": "needs_details"}


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


def test_streamed_demo_workflow_requires_documents_before_approval(tmp_path):
    document_store = LocalDocumentStore(tmp_path, start_maintenance=False)
    client = TestClient(
        create_api(DemoService(document_store=document_store))
    )
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

    for index, document_type in enumerate(result["documents"][scheme_id]):
        if index == 0:
            unredacted = client.post(
                f"/api/threads/{thread_id}/documents/upload",
                data={"scheme_id": scheme_id, "document_type": document_type},
                files={
                    "file": (
                        "sample.pdf",
                        b"%PDF-1.4\n%%EOF",
                        "application/pdf",
                    )
                },
            )
            assert unredacted.status_code == 422

        uploaded = client.post(
            f"/api/threads/{thread_id}/documents/upload",
            data={
                "scheme_id": scheme_id,
                "document_type": document_type,
                "sensitive_ids_masked": "true",
            },
            files={"file": ("sample.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        )
        assert uploaded.status_code == 200
        assert uploaded.json()["expires_at"]

        downloaded = client.get(
            f"/api/threads/{thread_id}/documents/{scheme_id}/{document_type}"
        )
        assert downloaded.status_code == 200
        assert downloaded.content == b"%PDF-1.4\n%%EOF"
        assert downloaded.headers["content-type"] == "application/pdf"

    submitted = client.post(
        f"/api/threads/{thread_id}/decision",
        json={"action": "approve", "payload_hash": approval["payload_hash"]},
    )
    assert submitted.status_code == 200
    final_events = parse_events(submitted.content)
    final_result = next(payload for name, payload in final_events if name == "result")
    assert final_result["submission"]["status"].startswith("submitted")

    forgotten = client.delete(f"/api/threads/{thread_id}/documents")
    assert forgotten.status_code == 200
    assert forgotten.json()["deleted_documents"] == len(
        result["documents"][scheme_id]
    )
    unavailable = client.get(
        f"/api/threads/{thread_id}/documents/"
        f"{scheme_id}/{result['documents'][scheme_id][0]}"
    )
    assert unavailable.status_code == 404
    document_store.close()


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
    evaluate_scheme = api.tools.evaluate_scheme

    def track_evaluation(profile, scheme_id):
        evaluated_schemes.append(scheme_id)
        return evaluate_scheme(profile, scheme_id)

    monkeypatch.setattr(api.tools, "evaluate_scheme", track_evaluation)
    client = TestClient(create_api(DemoService(FakeChatIntakeAgent())))

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
    client = TestClient(create_api(DemoService(FakeChatIntakeAgent())))

    response = client.post(
        "/api/chat/legacy",
        json={"user_input": "I am 62.", "session_id": "expired-session"},
    )

    assert response.status_code == 200
    events = parse_events(response.content)
    error = next(payload for name, payload in events if name == "error")
    assert "chat session was not found" in error["detail"]
