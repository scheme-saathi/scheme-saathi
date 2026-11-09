import json

import pytest
from streamlit.testing.v1 import AppTest

from app import app_new


def selection_screen():
    import streamlit as st
    from app import app_new

    result = {
        "status": "eligibility_checked",
        "profile": {"age": 35},
        "verdicts": {
            "A": {"verdict": "eligible"},
            "B": {"verdict": "not_eligible"},
            "C": {"verdict": "cant_tell"},
        },
        "scheme_names": {"A": "Scheme A", "B": "Scheme B", "C": "Scheme C"},
    }
    app_new._render_application_start("http://api", result)


def confirmation_screen():
    import streamlit as st
    from app import app_new

    st.session_state.setdefault("chat_session_id", "thread-1")
    st.session_state.setdefault("chat_messages", [])
    st.session_state.setdefault(
        "chat_confirmation",
        {"facts": {"age": 35}, "payload_hash": "exact-hash"},
    )
    app_new._render_fact_confirmation("http://api")


def chat_screen():
    import streamlit as st
    from app import app_new

    app_new._initialize_portal_state()
    app_new._render_chat_page()


def sensitive_attachment_screen():
    from types import SimpleNamespace

    import streamlit as st
    from app import app_new

    app_new._initialize_portal_state()
    st.session_state["chat_messages"] = [{"role": "assistant", "content": "Previous question"}]
    submission = SimpleNamespace(
        text="My details are 1234 5678 9012",
        files=[SimpleNamespace(name="document.pdf")],
    )
    app_new._handle_chat_submission("http://api", submission, st.container())


def header_screen():
    import streamlit as st
    from app import app_new

    app_new._initialize_portal_state()
    st.session_state.setdefault("header_fixture", True)
    if "header_fixture_loaded" not in st.session_state:
        st.session_state["header_fixture_loaded"] = True
        st.session_state["portal_stage"] = "chat"
        st.session_state["consent_given"] = True
        st.session_state["account_email"] = "citizen@example.test"
        st.session_state["chat_session_id"] = "thread-1"
        st.session_state["chat_messages"] = [{"role": "user", "content": "Hello"}]
    app_new._render_chat_header()


@pytest.mark.parametrize("prefix", ["desktop", "mobile"])
def test_header_privacy_requires_explicit_withdrawal(monkeypatch, prefix):
    calls = []
    monkeypatch.setattr(app_new, "_withdraw_consent", lambda: calls.append("withdraw") or True)
    app = AppTest.from_function(header_screen).run()
    assert not app.exception
    app.button(key=f"{prefix}-privacy").click().run()
    assert not calls
    assert any("How your information is used" in item.value for item in app.markdown)
    app.button(key="header-withdraw-consent").click().run()
    assert not calls
    app.button(key="close-header-panel").click().run()
    assert not calls
    app.button(key=f"{prefix}-privacy").click().run()
    app.button(key="header-withdraw-consent").click().run()
    app.button(key="confirm-header-withdraw").click().run()
    assert calls == ["withdraw"]


@pytest.mark.parametrize("prefix", ["desktop", "mobile"])
@pytest.mark.parametrize("action", ["new_chat", "sign_out"])
def test_header_confirms_before_clearing_session(monkeypatch, prefix, action):
    calls = []
    monkeypatch.setattr(app_new, "_reset_chat", lambda: calls.append("reset") or True)
    monkeypatch.setattr(app_new, "_sign_out", lambda: calls.append("signout"))
    app = AppTest.from_function(header_screen).run()
    app.button(key=f"{prefix}-{action}").click().run()
    assert not calls
    app.button(key="close-header-panel").click().run()
    assert not calls
    app.button(key=f"{prefix}-{action}").click().run()
    app.button(key=f"confirm-header-{action}").click().run()
    assert calls == (["reset", "signout"] if action == "sign_out" else ["reset"])


@pytest.mark.parametrize("prefix", ["desktop", "mobile"])
def test_the_saved_details_button_opens_and_closes_the_memory_panel_without_a_confirmation(prefix):
    app = AppTest.from_function(header_screen).run()
    assert app.session_state["memory_panel_open"] is False

    app.button(key=f"{prefix}-memory").click().run()
    assert app.session_state["memory_panel_open"] is True
    assert app.session_state["header_panel"] is None  # it is not one of the confirmations

    app.button(key=f"{prefix}-memory").click().run()
    assert app.session_state["memory_panel_open"] is False


@pytest.mark.parametrize("action", ["new_chat", "sign_out"])
def test_the_session_actions_say_the_application_and_its_saved_details_are_deleted(action):
    app = AppTest.from_function(header_screen).run()
    app.button(key=f"desktop-{action}").click().run()
    assert any("including its saved details and" in item.value for item in app.markdown)


def test_failed_cleanup_does_not_sign_out(monkeypatch):
    calls = []
    monkeypatch.setattr(app_new, "_reset_chat", lambda: False)
    monkeypatch.setattr(app_new, "_sign_out", lambda: calls.append("signout"))
    app = AppTest.from_function(header_screen).run()
    app.button(key="desktop-sign_out").click().run()
    app.button(key="confirm-header-sign_out").click().run()
    assert calls == []
    assert app.session_state["header_panel"] == "sign_out"
    assert app.session_state["account_email"] == "citizen@example.test"


def document_screen():
    import streamlit as st
    from app import app_new

    st.session_state.setdefault("application_uploads", {})
    result = {
        "thread_id": "thread-1",
        "application": {"scheme_id": "C02"},
        "documents": {"C02": ["Enrolment form", "Proof"]},
    }
    if app_new._render_document_step("http://api", result):
        st.success("Ready for review")


def edit_screen():
    import streamlit as st
    from app import app_new

    st.session_state.setdefault("application_editing", True)
    st.session_state.setdefault("application_edit_revision", 0)
    result = {
        "thread_id": "thread-1",
        "profile": {"is_widow": True, "age": 55, "household_below_bpl": True,
                    "is_remarried": False},
        "application": {"scheme_id": "C06", "applicant": {
            "is_widow": True, "age": 55, "household_below_bpl": True,
            "is_remarried": False,
        }},
        "approval": {"payload_hash": "test-hash"},
    }
    app_new._render_review_step("http://api", result, documents_complete=True)


def results_screen():
    import streamlit as st
    from app import app_new

    st.session_state.setdefault("chat_messages", [])
    result = {
        "status": "eligibility_checked",
        "profile": {"is_widow": True, "is_remarried": False},
        "verdicts": {
            "B": {"verdict": "not_eligible"},
            "C": {"verdict": "cant_tell", "missing_fields": ["household_below_bpl"]},
            "A": {"verdict": "eligible", "citations": [{"clause_id": "1", "text": "Reviewed rule"}]},
        },
        "scheme_names": {"A": "Scheme A", "B": "Scheme B", "C": "Scheme C"},
    }
    app_new._render_eligibility_screen(result, "http://api")


def test_edit_form_submits_changed_fields(monkeypatch):
    calls = []

    def send(api, path, payload, progress):
        calls.append(payload)
        return {"application": {}, "approval": None}

    monkeypatch.setattr(app_new, "_send_workflow", send)
    app = AppTest.from_function(edit_screen).run()
    assert not app.exception
    assert {box.label for box in app.checkbox} >= {
        "Widow", "Household below poverty line (BPL)", "Remarried",
    }
    assert not app.text_input
    next(box for box in app.checkbox if box.label == "Widow").uncheck()
    app.number_input[0].set_value(56)
    next(button for button in app.button if button.label == "Save changes and recheck eligibility").click().run()
    assert not app.exception
    assert calls == [{"action": "edit", "changes": {
        "is_widow": False, "age": 56,
    }}]


def test_results_show_readable_facts_and_prioritize_eligible_schemes():
    app = AppTest.from_function(results_screen).run()
    assert not app.exception
    assert app.table[0].value.to_dict("records") == [
        {"Field": "Widow", "Value": "Yes"},
        {"Field": "Remarried", "Value": "No"},
    ]
    headings = [item.value for item in app.markdown if item.value in {
        "**Scheme A**", "**Scheme B**", "**Scheme C**"
    }]
    assert headings == ["**Scheme A**", "**Scheme C**", "**Scheme B**"]
    assert any("Still needed: Household below poverty line (BPL)" in item.value for item in app.caption)
    assert any(item.label == "View reviewed source clauses" for item in app.expander)
    assert app.selectbox[0].options == ["Scheme A (A)"]


def test_approval_requires_review_and_uses_exact_draft_hash(monkeypatch):
    calls = []
    monkeypatch.setattr(
        app_new, "_finish_application",
        lambda api, result, decision: calls.append(decision),
    )
    app = AppTest.from_function(edit_screen).run()
    approve = next(button for button in app.button if button.label == "Approve")
    assert approve.disabled
    next(box for box in app.checkbox if box.label.startswith("I reviewed this draft")).check().run()
    approve = next(button for button in app.button if button.label == "Approve")
    assert not approve.disabled
    approve.click().run()
    assert not app.exception
    assert calls == [{"action": "approve", "payload_hash": "test-hash"}]


def operator_review_screen():
    import streamlit as st
    from app import app_new

    st.session_state["account_role"] = "operator"
    st.session_state.setdefault("application_editing", False)
    st.session_state.setdefault("application_edit_revision", 0)
    result = {
        "thread_id": "thread-1",
        "profile": {"age": 55},
        "application": {"scheme_id": "C06", "applicant": {"age": 55}},
        "approval": {"payload_hash": "test-hash"},
    }
    app_new._render_review_step("http://api", result, documents_complete=True)


def test_a_citizen_is_not_asked_for_anyone_elses_agreement(monkeypatch):
    app = AppTest.from_function(edit_screen).run()
    assert not any(box.label.startswith("The person I am helping") for box in app.checkbox)


def test_an_operator_must_choose_the_persons_agreement_each_time_and_it_starts_unticked(monkeypatch):
    calls = []
    monkeypatch.setattr(app_new, "_finish_application", lambda api, result, decision: calls.append(decision))
    app = AppTest.from_function(operator_review_screen).run()
    assert not app.exception
    agreement = next(box for box in app.checkbox if box.label.startswith("The person I am helping agrees"))
    assert agreement.value is False
    assert "90 days" in agreement.label

    next(box for box in app.checkbox if box.label.startswith("I reviewed this draft")).check().run()
    next(button for button in app.button if button.label == "Approve").click().run()

    assert calls == [{"action": "approve", "payload_hash": "test-hash", "citizen_agreed": False}]


def test_ticking_the_agreement_is_sent_with_the_approval_of_that_application(monkeypatch):
    calls = []
    monkeypatch.setattr(app_new, "_finish_application", lambda api, result, decision: calls.append(decision))
    app = AppTest.from_function(operator_review_screen).run()
    next(box for box in app.checkbox if box.label.startswith("The person I am helping agrees")).check().run()
    next(box for box in app.checkbox if box.label.startswith("I reviewed this draft")).check().run()
    next(button for button in app.button if button.label == "Approve").click().run()

    assert calls == [{"action": "approve", "payload_hash": "test-hash", "citizen_agreed": True}]


def test_edit_form_without_changes_does_not_send_decision(monkeypatch):
    calls = []
    monkeypatch.setattr(app_new, "_send_workflow", lambda *args: calls.append(args))
    app = AppTest.from_function(edit_screen).run()
    next(button for button in app.button if button.label == "Save changes and recheck eligibility").click().run()
    assert not app.exception
    assert not calls
    assert any("Change a detail before saving." in item.value for item in app.info)


def test_document_upload_requires_redaction_and_each_document(monkeypatch):
    class Upload:
        name = "redacted.pdf"

    calls = []
    monkeypatch.setattr(app_new.st, "file_uploader", lambda *args, **kwargs: Upload())
    monkeypatch.setattr(
        app_new, "_upload_document",
        lambda api, result, scheme, document, upload: (
            calls.append((scheme, document)) or {"filename": upload.name}
        ),
    )
    app = AppTest.from_function(document_screen).run()
    assert not app.exception
    assert app.button[0].disabled
    app.checkbox[0].check().run()
    assert not app.button[0].disabled
    app.button[0].click().run()
    assert calls == [("C02", "Enrolment form")]
    assert app.button[0].disabled
    assert not app.checkbox[0].value
    app.checkbox[0].check().run()
    app.button[0].click().run()
    assert calls == [("C02", "Enrolment form"), ("C02", "Proof")]
    assert any(item.value == "Ready for review" for item in app.success)


def test_document_upload_error_does_not_advance(monkeypatch):
    class Upload:
        name = "redacted.pdf"

    def reject(*args):
        raise RuntimeError("Upload unavailable")

    monkeypatch.setattr(app_new.st, "file_uploader", lambda *args, **kwargs: Upload())
    monkeypatch.setattr(app_new, "_upload_document", reject)
    app = AppTest.from_function(document_screen).run()
    app.checkbox[0].check().run()
    app.button[0].click().run()
    assert any("Upload unavailable" in item.value for item in app.error)
    assert not app.session_state["application_uploads"]
    assert not app.success


def test_operator_selects_only_an_eligible_scheme(monkeypatch):
    calls = []
    monkeypatch.setattr(
        app_new, "_start_application",
        lambda api, result, scheme_id: calls.append((api, scheme_id)),
    )
    app = AppTest.from_function(selection_screen).run()
    assert not app.exception
    assert app.selectbox[0].options == ["Scheme A (A)"]
    assert app.button[0].disabled
    app.selectbox[0].select("A").run()
    assert not app.button[0].disabled
    app.button[0].click().run()
    assert calls == [("http://api", "A")]


@pytest.mark.parametrize("status,verdict", [
    ("intake_stopped", "eligible"),
    ("eligibility_checked", "not_eligible"),
    ("eligibility_checked", "cant_tell"),
])
def test_application_cannot_start_without_confirmed_eligibility(status, verdict):
    result = {"status": status, "profile": {}, "verdicts": {"A": {"verdict": verdict}}}
    with pytest.raises(ValueError, match="confirmed eligible"):
        app_new._start_application("http://api", result, "A")


@pytest.mark.parametrize("action,button", [("approve", "Confirm details"), ("reject", "Change details in chat")])
def test_confirmation_buttons_resume_exact_fact_payload(monkeypatch, action, button):
    calls = []

    def fake_decision(api, thread_id, confirmation, selected_action, progress):
        calls.append((thread_id, confirmation["payload_hash"], selected_action))
        return thread_id, "Decision received.", {"status": "facts_rejected", "data": {}}

    monkeypatch.setattr(app_new, "_send_fact_decision", fake_decision)
    app = AppTest.from_function(confirmation_screen).run()
    assert not app.exception
    next(b for b in app.button if b.label == button).click().run()
    assert not app.exception
    assert calls == [("thread-1", "exact-hash", action)]
    assert app.session_state["chat_confirmation"] is None


def test_decision_posts_to_the_current_thread_with_the_exact_hash(monkeypatch):
    requests = []

    def request(url, **kwargs):
        requests.append((url, json.loads(kwargs["body"])))
        return {"thread_id": "t/1", "response": "Done", "next_step": "facts_rejected", "data": {}}

    monkeypatch.setattr(app_new, "_api_request", request)
    app_new._send_fact_decision("http://api", "t/1", {"payload_hash": "exact"}, "approve", None)
    assert requests == [
        ("http://api/api/chat/t%2F1/decision", {"action": "approve", "payload_hash": "exact"})
    ]


def test_chat_confirmation_leads_to_scheme_selection(monkeypatch):
    class HealthResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"status":"ok"}'

    monkeypatch.setattr(app_new, "_api_base_url", lambda: "http://api")
    monkeypatch.setattr(app_new, "urlopen", lambda *args, **kwargs: HealthResponse())
    monkeypatch.setattr(
        app_new, "_send_chat",
        lambda *args: (
            "thread-1", "Please confirm your details.",
            {"status": "awaiting_confirmation", "data": {
                "confirmation": {"facts": {"age": 35}, "payload_hash": "exact"}
            }},
        ),
    )
    monkeypatch.setattr(
        app_new, "_send_fact_decision",
        lambda *args: (
            "thread-1", "You may be eligible.",
            {"status": "eligibility_checked", "data": {},
             "profile": {"age": 35}, "verdicts": {"A": {"verdict": "eligible"}},
             "scheme_names": {"A": "Scheme A"}},
        ),
    )
    calls = []
    monkeypatch.setattr(app_new, "_start_application", lambda api, result, scheme: calls.append(scheme))
    app = AppTest.from_function(chat_screen).run()
    app.chat_input[0].set_value("Check my eligibility").run()
    assert not app.exception
    assert any(b.label == "Confirm details" for b in app.button)
    assert app.chat_input[0].disabled
    next(b for b in app.button if b.label == "Confirm details").click().run()
    assert not app.exception
    assert app.selectbox[0].options == ["Scheme A (A)"]
    app.selectbox[0].select("A").run()
    next(b for b in app.button if b.label == "Prepare selected application").click().run()
    assert calls == ["A"]


def test_sensitive_chat_is_not_rendered_stored_or_sent(monkeypatch):
    class HealthResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"status":"ok"}'

    calls = []
    monkeypatch.setattr(app_new, "_api_base_url", lambda: "http://api")
    monkeypatch.setattr(app_new, "urlopen", lambda *args, **kwargs: HealthResponse())
    monkeypatch.setattr(app_new, "_send_chat", lambda *args: calls.append(args))
    app = AppTest.from_function(chat_screen).run()
    secret = "1234 5678 9012"
    app.chat_input[0].set_value(f"My Aadhaar is {secret}").run()
    assert not app.exception
    assert not calls
    assert secret not in json.dumps(app.session_state["chat_messages"])
    assert not any(secret in item.value for item in app.markdown)
    assert any("Sensitive information detected" in item.value for item in app.warning)


def test_sensitive_chat_with_attachment_rejects_the_whole_submission(monkeypatch):
    calls = []
    monkeypatch.setattr(app_new, "_send_chat", lambda *args: calls.append(args))
    monkeypatch.setattr(app_new, "_upload_document", lambda *args: calls.append(args))
    app = AppTest.from_function(sensitive_attachment_screen).run()
    assert not app.exception
    assert not calls
    assert app.session_state["chat_messages"] == [{"role": "assistant", "content": "Previous question"}]
    assert any("attachments were not uploaded" in item.value for item in app.warning)


def test_partial_results_remain_available_without_allowing_application(monkeypatch):
    class HealthResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"status":"ok"}'

    monkeypatch.setattr(app_new, "_api_base_url", lambda: "http://api")
    monkeypatch.setattr(app_new, "urlopen", lambda *args, **kwargs: HealthResponse())
    monkeypatch.setattr(
        app_new, "_send_chat",
        lambda *args: (
            "thread-1", "More details are needed.",
            {"status": "intake_stopped", "data": {}, "profile": {"age": 35},
             "verdicts": {"A": {"verdict": "eligible"}}, "scheme_names": {"A": "Scheme A"}},
        ),
    )
    app = AppTest.from_function(chat_screen).run()
    app.chat_input[0].set_value("Check my eligibility").run()
    assert not app.exception
    next(b for b in app.button if b.label == "Review preliminary results").click().run()
    assert not app.exception
    assert not app.selectbox
    assert not any(b.label == "Prepare selected application" for b in app.button)
    next(b for b in app.button if b.label == "Back to chat").click().run()
    assert not app.chat_input[0].disabled
