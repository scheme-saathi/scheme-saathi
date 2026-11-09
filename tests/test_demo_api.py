import json
from pathlib import Path

from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from agents.contracts import CandidateFact, IntakeResult
from app import app_new, business_logic
from app.auth import AuthenticatedHousehold, authenticated_household
from app.api import create_api
from app.business_logic import ChatIntakeInput, DemoService
from app.document_storage import LocalDocumentStore
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


def test_streamlit_chat_client_uses_supervisor_chat_endpoint(monkeypatch):
    class FakeResponse:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.body

    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        assert timeout == 300
        return FakeResponse(
            json.dumps(
                {
                    "status": "success",
                    "thread_id": "conversation-1",
                    "next_step": "needs_clarification",
                    "response": "Please share your annual income.",
                    "data": {"status": "needs_clarification"},
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr(app_new, "urlopen", fake_urlopen)
    progress_messages = []
    progress = type(
        "Progress",
        (),
        {"write": lambda self, message: progress_messages.append(message)},
    )()

    session_id, reply, result = app_new._send_chat(
        "http://127.0.0.1:8766",
        "I am 62 and a widow.",
        None,
        "citizen-session",
        progress,
    )

    assert requests[0].full_url == "http://127.0.0.1:8766/api/chat"
    assert json.loads(requests[0].data) == {
        "message": "I am 62 and a widow.",
        "actor_id": "citizen-session",
        "thread_id": None,
    }
    assert session_id == "conversation-1"
    assert reply == "Please share your annual income."
    assert result == {
        "status": "needs_clarification",
        "data": {"status": "needs_clarification"},
    }
    assert progress_messages == ["Sending your message"]


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


def document_upload_screen():
    import streamlit as st
    from app import app_new

    app_new._render_document_step("http://testserver", st.session_state["application_result"])
    st.write(f"Current step: {app_new._journey_step()[0]}")


def test_document_screen_uploads_to_real_api_and_advances_to_review(tmp_path, monkeypatch):
    class Upload:
        name = "redacted.pdf"
        type = "application/pdf"

        def getvalue(self):
            return b"%PDF-1.4\n%%EOF"

    class Response:
        def __init__(self, content):
            self.content = content

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.content

    store = LocalDocumentStore(tmp_path, start_maintenance=False)
    client = authenticated_client(create_api(DemoService(document_store=store)))
    response = client.post(
        "/api/analyze",
        json={
            "citizen": {  # C04 is live and needs exactly one document
                "age": 35, "has_savings_account": True, "consents_to_auto_debit": True,
                "is_or_was_income_tax_payer": False,
            },
            "scheme_ids": ["C04"],
        },
    )
    result = next(payload for name, payload in parse_events(response.content) if name == "result")
    assert result["approval"]

    def request_url(request, timeout):
        response = client.request(
            request.get_method(), request.full_url, content=request.data, headers=dict(request.header_items())
        )
        assert response.status_code == 200, response.text
        return Response(response.content)

    monkeypatch.setattr(app_new, "urlopen", request_url)
    monkeypatch.setattr(app_new.st, "file_uploader", lambda *args, **kwargs: Upload())
    ui = AppTest.from_function(document_upload_screen)
    ui.session_state["application_result"] = result
    ui.session_state["application_uploads"] = {}
    ui.session_state["chat_eligibility_result"] = {"status": "eligibility_checked"}
    ui.session_state["application_outcome"] = None
    ui.run()
    assert not ui.exception
    assert ui.button[0].disabled
    ui.checkbox[0].check().run()
    ui.button[0].click().run()
    assert not ui.exception
    assert len(ui.session_state["application_uploads"]) == 1
    assert any("Current step: 4" in text.value for text in ui.markdown)
    store.close()


def test_streamed_demo_workflow_requires_documents_before_approval(tmp_path):
    document_store = LocalDocumentStore(tmp_path, start_maintenance=False)
    application = create_api(DemoService(document_store=document_store))
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


def test_missing_mock_portal_secret_does_not_consume_approval(monkeypatch):
    monkeypatch.setattr(
        business_logic, "load_dotenv",
        lambda: monkeypatch.delenv("MOCK_PORTAL_AUTH_SECRET", raising=False),
    )
    monkeypatch.delenv("MOCK_PORTAL_AUTH_SECRET", raising=False)
    service = DemoService()
    client = authenticated_client(create_api(service))
    analyzed = client.post(
        "/api/analyze",
        json={"citizen": {"age": 30, "has_individual_bank_or_post_office_account": True},
              "scheme_ids": ["C01"]},
    )
    result = next(payload for name, payload in parse_events(analyzed.content) if name == "result")
    thread_id = result["thread_id"]
    decision = {"action": "approve", "payload_hash": result["approval"]["payload_hash"]}
    monkeypatch.delenv("MOCK_PORTAL_AUTH_SECRET", raising=False)

    blocked = client.post(f"/api/threads/{thread_id}/decision", json=decision)

    assert blocked.status_code == 409
    assert "MOCK_PORTAL_AUTH_SECRET" in blocked.json()["detail"]
    assert service._get_snapshot(thread_id).next == ("approval",)
    monkeypatch.setattr(business_logic, "load_dotenv", lambda: None)
    monkeypatch.setenv("MOCK_PORTAL_AUTH_SECRET", "test-only-mock-portal-secret")
    approved = client.post(f"/api/threads/{thread_id}/decision", json=decision)
    final = next(payload for name, payload in parse_events(approved.content) if name == "result")
    assert final["submission"]["status"] == "submitted (mock)"
    assert client.post(f"/api/threads/{thread_id}/decision", json=decision).status_code == 409


def test_profile_edit_creates_new_approval_and_rechecks_eligibility(tmp_path):
    store = LocalDocumentStore(tmp_path, start_maintenance=False)
    client = authenticated_client(create_api(DemoService(document_store=store)))
    analyzed = client.post(
        "/api/analyze",
        json={"citizen": {
            "is_widow": True, "age": 55, "household_below_bpl": True,
            "is_remarried": False,
        }, "scheme_ids": ["C06"]},
    )
    initial = next(payload for name, payload in parse_events(analyzed.content) if name == "result")
    thread_id = initial["thread_id"]
    old_hash = initial["approval"]["payload_hash"]
    edited = client.post(
        f"/api/threads/{thread_id}/decision",
        json={"action": "edit", "changes": {"age": 56}},
    )
    updated = next(payload for name, payload in parse_events(edited.content) if name == "result")
    assert updated["application"]["applicant"]["age"] == 56
    assert updated["verdicts"]["C06"]["verdict"] == "eligible"
    assert updated["approval"]["payload_hash"] != old_hash
    for document in updated["documents"]["C06"]:
        uploaded = client.post(
            f"/api/threads/{thread_id}/documents/upload",
            data={"scheme_id": "C06", "document_type": document, "sensitive_ids_masked": "true"},
            files={"file": ("sample.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        )
        assert uploaded.status_code == 200
    response = client.post(
        f"/api/threads/{thread_id}/decision", json={"action": "approve", "payload_hash": old_hash}
    )
    final = next(payload for name, payload in parse_events(response.content) if name == "result")
    assert final["approval_status"] == "invalid"
    assert not final["submission"]
    store.close()


def test_submission_tool_failure_reports_uncertain_outcome(monkeypatch):
    def fail_submission(*args, **kwargs):
        raise business_logic.ToolCallError("mock-portal", "create_application", "tool_error", "private")

    monkeypatch.setattr(business_logic.tools, "submit_application", fail_submission)
    client = authenticated_client(create_api(DemoService()))
    analyzed = client.post(
        "/api/analyze",
        json={"citizen": {"age": 30, "has_individual_bank_or_post_office_account": True},
              "scheme_ids": ["C01"]},
    )
    result = next(payload for name, payload in parse_events(analyzed.content) if name == "result")
    response = client.post(
        f"/api/threads/{result['thread_id']}/decision",
        json={"action": "approve", "payload_hash": result["approval"]["payload_hash"]},
    )
    error = next(payload for name, payload in parse_events(response.content) if name == "error")
    assert "outcome may be unknown" in error["detail"]
    assert "private" not in error["detail"]


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
    monkeypatch.setattr(rule_server, "RULE_DIRS", [rule_server.SCHEME_DIR, Path(__file__).resolve().parent / "fixtures"])
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
