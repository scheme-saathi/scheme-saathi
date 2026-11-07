"""Memory screens: the consent choices, the saved-details panel and the subject lines."""

import re

import pytest
from streamlit.testing.v1 import AppTest

from app import app_new, memory_text


def consent_screen():
    from app import app_new

    app_new._initialize_portal_state()
    app_new._render_consent_page()


def test_the_consent_page_offers_both_memory_choices_unticked_with_the_real_periods():
    app = AppTest.from_function(consent_screen).run()
    assert not app.exception
    boxes = {box.label: box.value for box in app.checkbox}
    assert boxes["Remember these household details"] is False
    assert boxes["Save application references so I can track them later"] is False
    assert any("Age: asked again after 30 days, deleted after 90 days" in c.value for c in app.caption)
    assert any("Leave both boxes unticked" in c.value for c in app.caption)


def test_the_session_consent_box_is_still_required_and_comes_first():
    app = AppTest.from_function(consent_screen).run()
    assert app.checkbox[0].label.startswith("I have read this notice")


def choices_screen():
    import streamlit as st
    from app import app_new

    app_new._initialize_portal_state()
    st.session_state["memory-consent-facts"] = True
    st.session_state["memory-consent-refs"] = False
    app_new._save_memory_choices()


def test_only_the_ticked_memory_choices_are_sent(monkeypatch):
    calls = []
    monkeypatch.setattr(app_new, "_api_base_url", lambda: "http://api")
    monkeypatch.setattr(
        app_new,
        "_memory_request",
        lambda api_base, path, method="GET", payload=None: calls.append((api_base, path, method, payload)),
    )
    app = AppTest.from_function(choices_screen).run()
    assert not app.exception
    assert calls == [("http://api", "/api/memory/consent", "PUT", {"purpose": "profile_facts", "granted": True})]
    assert app.session_state["memory_choice_error"] is None


def test_a_failed_memory_choice_is_reported_and_does_not_block_the_chat(monkeypatch):
    def down(*args, **kwargs):
        raise RuntimeError("the store is down")

    monkeypatch.setattr(app_new, "_api_base_url", lambda: "http://api")
    monkeypatch.setattr(app_new, "_memory_request", down)
    app = AppTest.from_function(choices_screen).run()
    assert not app.exception
    assert "the store is down" in app.session_state["memory_choice_error"]


def nothing_ticked_screen():
    import streamlit as st
    from app import app_new

    app_new._initialize_portal_state()
    st.session_state["memory-consent-facts"] = False
    st.session_state["memory-consent-refs"] = False
    app_new._save_memory_choices()


def test_nothing_is_sent_when_nothing_is_ticked(monkeypatch):
    monkeypatch.setattr(
        app_new, "_memory_request", lambda *args, **kwargs: pytest.fail("no request without a choice")
    )
    app = AppTest.from_function(nothing_ticked_screen).run()
    assert not app.exception


# The saved-details panel


def panel_screen():
    from app import app_new

    app_new._initialize_portal_state()
    app_new._render_memory_panel("http://api")


class PanelApi:
    def __init__(self, granted=True, available=True, role="citizen"):
        self.calls = []
        self.granted = granted
        self.available = available
        self.role = role

    def __call__(self, api_base, path, method="GET", payload=None):
        self.calls.append((method, path, payload))
        if not self.available:
            raise RuntimeError("Remembering details is not available.")
        if path == "/api/memory/consent":
            if self.role == "operator":
                return {"role": "operator", "purposes": {"application_references": {"granted": True}}}
            return {
                "purposes": {
                    "profile_facts": {"granted": self.granted},
                    "application_references": {"granted": False},
                }
            }
        if path == "/api/memory":
            return {
                "facts": [
                    {"field": "age", "value": 34, "reconfirm_due": True, "expires_at": "2027-01-01T00:00:00"},
                    {"field": "is_indian_citizen", "value": True, "reconfirm_due": False, "expires_at": "2027-01-01T00:00:00"},
                ]
            }
        if path == "/api/applications":
            return {
                "for_me": [{"application_id": "APP-1", "scheme_id": "C01", "submitted_at": "2026-11-01T10:00:00", "relation": None}],
                "family": [
                    {
                        "relation": "mother",
                        "nickname": "Amma",
                        "applications": [
                            {"application_id": "APP-3", "scheme_id": "C01", "submitted_at": "2026-11-03T10:00:00", "relation": "mother"}
                        ],
                    }
                ],
                "for_others": [{"application_id": "APP-2", "scheme_id": "C02", "submitted_at": "2026-11-02T10:00:00", "relation": "neighbour"}],
            }
        if path.endswith("/status"):
            return {"found_at_portal": True, "status": "submitted"}
        return {"status": "success"}


@pytest.fixture
def panel(monkeypatch):
    api = PanelApi()
    monkeypatch.setattr(app_new, "_memory_request", api)
    monkeypatch.setattr(app_new, "_scheme_names", lambda api_base: {"C01": "Pension scheme"})
    return api


def test_the_panel_shows_what_is_remembered_and_the_saved_applications(panel):
    app = AppTest.from_function(panel_screen).run()
    assert not app.exception
    text = " ".join(m.value for m in app.markdown)
    assert "**Age:** 34" in text
    assert "**Indian citizen:** Yes" in text
    assert "Pension scheme" in text and "C02 (neighbour)" in text
    captions = " ".join(c.value for c in app.caption)
    assert "Will be asked again at your next check" in captions
    assert "APP-1" in captions and "APP-2" in captions and "APP-3" in captions
    assert "Remembering household details: on" in " ".join(w.value for w in app.markdown)


def test_each_remembered_fact_can_be_forgotten_on_its_own(panel):
    app = AppTest.from_function(panel_screen).run()
    next(b for b in app.button if b.key == "forget-fact-age").click().run()
    assert ("DELETE", "/api/memory/facts/age", None) in panel.calls


def test_status_is_fetched_only_when_asked_for(panel):
    app = AppTest.from_function(panel_screen).run()
    assert not any(path.endswith("/status") for _, path, _ in panel.calls)
    next(b for b in app.button if b.key == "status-APP-1").click().run()
    assert ("GET", "/api/applications/APP-1/status", None) in panel.calls
    assert any("Status at the portal: submitted" in i.value for i in app.info)


def test_a_saved_application_can_be_removed_from_the_list(panel):
    app = AppTest.from_function(panel_screen).run()
    next(b for b in app.button if b.key == "remove-APP-2").click().run()
    assert ("DELETE", "/api/applications/APP-2", None) in panel.calls


def test_the_consent_buttons_turn_remembering_on_and_off(panel):
    app = AppTest.from_function(panel_screen).run()
    next(b for b in app.button if b.key == "memory-consent-profile_facts").click().run()
    next(b for b in app.button if b.key == "memory-consent-application_references").click().run()
    assert ("PUT", "/api/memory/consent", {"purpose": "profile_facts", "granted": False}) in panel.calls
    assert ("PUT", "/api/memory/consent", {"purpose": "application_references", "granted": True}) in panel.calls


def test_forgetting_everything_needs_a_ticked_confirmation(panel):
    app = AppTest.from_function(panel_screen).run()
    forget = next(b for b in app.button if b.key == "memory-forget-all")
    assert forget.disabled
    assert any("already submitted" in c.value for c in app.caption)

    app.checkbox(key="memory-forget-confirm").check().run()
    next(b for b in app.button if b.key == "memory-forget-all").click().run()

    assert ("DELETE", "/api/memory", None) in panel.calls
    assert app.session_state["memory_notice"] == memory_text.text("en", "forget_done")


def test_a_family_member_is_listed_with_their_nickname_and_applications(panel):
    app = AppTest.from_function(panel_screen).run()
    assert not app.exception
    assert any("**Mother (Amma)**" in m.value for m in app.markdown)
    assert any("My family" in c.value for c in app.caption)
    assert app.text_input(key="nickname-mother").value == "Amma"
    assert any(b.key == "status-APP-3" for b in app.button)


def test_a_family_member_can_be_renamed(panel):
    app = AppTest.from_function(panel_screen).run()
    app.text_input(key="nickname-mother").set_value("Aai").run()
    next(b for b in app.button if b.key == "nickname-save-mother").click().run()
    assert ("PATCH", "/api/family/mother", {"nickname": "Aai"}) in panel.calls


def test_a_family_member_can_be_removed_with_their_saved_applications(panel):
    app = AppTest.from_function(panel_screen).run()
    next(b for b in app.button if b.key == "family-remove-mother").click().run()
    assert ("DELETE", "/api/family/mother", None) in panel.calls


def test_a_family_application_can_still_be_checked_and_removed_on_its_own(panel):
    app = AppTest.from_function(panel_screen).run()
    next(b for b in app.button if b.key == "status-APP-3").click().run()
    next(b for b in app.button if b.key == "remove-APP-3").click().run()
    assert ("GET", "/api/applications/APP-3/status", None) in panel.calls
    assert ("DELETE", "/api/applications/APP-3", None) in panel.calls


def test_a_response_without_a_family_group_still_renders(monkeypatch):
    class OldApi(PanelApi):
        def __call__(self, api_base, path, method="GET", payload=None):
            result = super().__call__(api_base, path, method, payload)
            if path == "/api/applications":
                result = {key: value for key, value in result.items() if key != "family"}
            return result

    monkeypatch.setattr(app_new, "_memory_request", OldApi())
    monkeypatch.setattr(app_new, "_scheme_names", lambda api_base: {})
    assert not AppTest.from_function(panel_screen).run().exception


def test_an_operator_sees_only_the_applications_list_choice(monkeypatch):
    api = PanelApi(role="operator")
    monkeypatch.setattr(app_new, "_memory_request", api)
    monkeypatch.setattr(app_new, "_scheme_names", lambda api_base: {})

    app = AppTest.from_function(panel_screen).run()

    assert not app.exception
    keys = {b.key for b in app.button}
    assert "memory-consent-application_references" in keys
    assert "memory-consent-profile_facts" not in keys


def test_the_panel_says_so_when_remembering_is_unavailable(monkeypatch):
    monkeypatch.setattr(app_new, "_memory_request", PanelApi(available=False))
    app = AppTest.from_function(panel_screen).run()
    assert not app.exception
    assert any("not available" in i.value for i in app.info)
    assert not app.button


# Who a check or application is for


def confirmation_screen():
    import streamlit as st
    from app import app_new

    app_new._initialize_portal_state()
    st.session_state["chat_session_id"] = "thread-1"
    st.session_state["chat_confirmation"] = {
        "facts": {"age": 67, "is_widow": True},
        "payload_hash": "exact",
        "subject": "other",
        "relation": "mother",
        "remembered_fields": ["age"],
    }
    app_new._render_fact_confirmation("http://api")


def test_the_confirmation_names_who_it_is_for_and_what_came_from_memory():
    app = AppTest.from_function(confirmation_screen).run()
    assert not app.exception
    assert any("Checking for: your mother" in m.value for m in app.markdown)
    assert any("Filled in from your last visit: Age." in i.value for i in app.info)


def own_confirmation_screen():
    import streamlit as st
    from app import app_new

    app_new._initialize_portal_state()
    st.session_state["chat_confirmation"] = {"facts": {"age": 30}, "payload_hash": "exact"}
    app_new._render_fact_confirmation("http://api")


def test_a_confirmation_without_a_subject_is_for_the_person_themselves():
    app = AppTest.from_function(own_confirmation_screen).run()
    assert any("Checking for: you" in m.value for m in app.markdown)


def start_screen():
    from app import app_new

    app_new._initialize_portal_state()
    result = {
        "status": "eligibility_checked",
        "profile": {"age": 30},
        "verdicts": {"A": {"verdict": "eligible"}},
        "data": {"subject": "other", "relation": "mother"},
    }
    app_new._start_application("http://api", result, "A")


def own_start_screen():
    from app import app_new

    app_new._initialize_portal_state()
    result = {
        "status": "eligibility_checked",
        "profile": {"age": 30},
        "verdicts": {"A": {"verdict": "eligible"}},
        "data": {"subject": "self"},
    }
    app_new._start_application("http://api", result, "A")


def test_an_application_for_someone_else_carries_the_relation(monkeypatch):
    sent = []
    monkeypatch.setattr(
        app_new, "_send_workflow", lambda api, path, payload, progress: sent.append((path, payload)) or {"thread_id": "t"}
    )
    app = AppTest.from_function(start_screen).run()
    assert not app.exception
    assert sent == [
        (
            "/api/analyze",
            {"citizen": {"age": 30}, "scheme_ids": ["A"], "subject": "other", "relation": "mother"},
        )
    ]
    assert app.session_state["application_subject"] == {"subject": "other", "relation": "mother"}


def test_an_application_for_the_person_themselves_sends_nothing_extra(monkeypatch):
    sent = []
    monkeypatch.setattr(
        app_new, "_send_workflow", lambda api, path, payload, progress: sent.append((path, payload)) or {"thread_id": "t"}
    )
    app = AppTest.from_function(own_start_screen).run()
    assert not app.exception
    assert sent == [("/api/analyze", {"citizen": {"age": 30}, "scheme_ids": ["A"]})]
    assert app.session_state["application_subject"] == {"subject": "self", "relation": None}


# Wording


def blanks(template):
    return sorted(re.findall(r"\{(\w+)\}", template))


def test_every_language_has_the_same_wording_with_the_same_blanks():
    english = memory_text.TEXT["en"]
    for language in ("hi", "mr"):
        table = memory_text.TEXT[language]
        assert set(table) == set(english), language
        for key, template in table.items():
            assert blanks(template) == blanks(english[key]), (language, key)


def test_every_field_the_policy_may_remember_has_a_name_in_every_language():
    from agents.memory_service import HouseholdAllowlist

    fields = HouseholdAllowlist.from_policy_file().allowed_fields
    for language in memory_text.LANGUAGES:
        for field in fields:
            assert field in memory_text.FIELD_NAMES[language], (language, field)


def test_every_family_relation_has_a_name_in_every_language():
    from agents.family import FAMILY_RELATIONS

    for language in memory_text.LANGUAGES:
        for relation in FAMILY_RELATIONS:
            assert relation in memory_text.RELATION_NAMES[language], (language, relation)


def test_unknown_languages_and_fields_fall_back_to_english():
    assert memory_text.text("xx", "yes") == "Yes"
    assert memory_text.field_name("hi", "some_new_field") == "Some new field"
    assert memory_text.text("en", "until", date="01 Jan 2027") == "kept until 01 Jan 2027"
