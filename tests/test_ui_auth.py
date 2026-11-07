import base64
import hashlib
import io
import json
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest
from streamlit.testing.v1 import AppTest

from app import app_new, ui_auth


@pytest.fixture(autouse=True)
def auth0_env(monkeypatch):
    monkeypatch.setattr(ui_auth, "load_dotenv", lambda: None)
    monkeypatch.setenv("AUTH0_DOMAIN", "https://tenant.example.auth0.com/")
    monkeypatch.setenv("AUTH0_CLIENT_ID", "client-1")
    monkeypatch.setenv("AUTH0_AUDIENCE", "https://api.scheme-saathi.example")
    monkeypatch.setenv("AUTH0_HOUSEHOLD_CLAIM", "https://scheme-saathi.example/household_id")
    monkeypatch.setenv("AUTH0_REDIRECT_URI", "http://localhost:8501")
    ui_auth._pending.clear()


class FakeResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


def access_screen():
    import streamlit as st
    from app import app_new

    st.session_state.setdefault("access_error", None)
    app_new._render_access_page()


def test_access_page_uses_clear_label_and_auth0_authorization(monkeypatch):
    links = []
    monkeypatch.setattr(
        app_new.st, "link_button",
        lambda label, url, **kwargs: links.append((label, url)),
    )
    app = AppTest.from_function(access_screen).run()
    assert not app.exception
    assert len(links) == 1
    label, url = links[0]
    assert label == "Sign in / Create account"
    parsed = urlparse(url)
    assert (parsed.scheme, parsed.netloc, parsed.path) == (
        "https", "tenant.example.auth0.com", "/authorize"
    )
    assert parse_qs(parsed.query)["code_challenge_method"] == ["S256"]


def test_settings_are_none_until_the_ui_client_id_is_configured(monkeypatch):
    assert ui_auth.ui_settings().domain == "tenant.example.auth0.com"
    monkeypatch.delenv("AUTH0_CLIENT_ID")
    assert ui_auth.ui_settings() is None
    assert ui_auth.missing_settings() == ["AUTH0_CLIENT_ID"]


def test_authorize_url_uses_pkce_and_requests_the_api_audience():
    url = ui_auth.authorize_url(ui_auth.ui_settings())
    parsed = urlparse(url)
    query = {key: values[0] for key, values in parse_qs(parsed.query).items()}

    assert (parsed.scheme, parsed.netloc, parsed.path) == (
        "https", "tenant.example.auth0.com", "/authorize"
    )
    assert query["response_type"] == "code"
    assert query["audience"] == "https://api.scheme-saathi.example"
    assert set(query["scope"].split()) == {"openid", "profile", "email"}
    assert query["code_challenge_method"] == "S256"
    verifier, _ = ui_auth._pending[query["state"]]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    assert query["code_challenge"] == base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    assert "code_verifier" not in query and verifier not in url


def test_user_email_reads_auth0_userinfo_with_access_token(monkeypatch):
    sent = []

    def fake_urlopen(request, timeout):
        sent.append(request)
        return FakeResponse({"sub": "synthetic-user", "email": "citizen@example.test"})

    monkeypatch.setattr(ui_auth, "urlopen", fake_urlopen)
    token = ui_auth.AccessToken("token-1", time.time() + 3600)
    assert ui_auth.user_email(ui_auth.ui_settings(), token) == "citizen@example.test"
    assert sent[0].full_url == "https://tenant.example.auth0.com/userinfo"
    assert sent[0].get_header("Authorization") == "Bearer token-1"


@pytest.mark.parametrize("profile", [{}, {"email": None}])
def test_user_email_can_be_absent(monkeypatch, profile):
    monkeypatch.setattr(ui_auth, "urlopen", lambda *args, **kwargs: FakeResponse(profile))
    assert ui_auth.user_email(
        ui_auth.ui_settings(), ui_auth.AccessToken("token", time.time() + 3600)
    ) is None


@pytest.mark.parametrize("profile", [[], {"email": 1}, {"email": "a\nb"}])
def test_invalid_userinfo_is_reported(monkeypatch, profile):
    monkeypatch.setattr(ui_auth, "urlopen", lambda *args, **kwargs: FakeResponse(profile))
    with pytest.raises(ui_auth.SignInError):
        ui_auth.user_email(
            ui_auth.ui_settings(), ui_auth.AccessToken("token", time.time() + 3600)
        )


def test_userinfo_error_does_not_expose_response(monkeypatch):
    def reject(request, timeout):
        raise HTTPError(request.full_url, 403, "private detail", {}, io.BytesIO(b"private detail"))

    monkeypatch.setattr(ui_auth, "urlopen", reject)
    with pytest.raises(ui_auth.SignInError) as error:
        ui_auth.user_email(ui_auth.ui_settings(), ui_auth.AccessToken("token", time.time() + 3600))
    assert "private detail" not in str(error.value)


def consent_screen():
    import streamlit as st
    from app import app_new

    app_new._initialize_portal_state()
    st.session_state["account_email"] = "citizen@example.test"
    app_new._render_consent_page()


def test_email_is_visible_on_consent_page():
    app = AppTest.from_function(consent_screen).run()
    assert not app.exception
    assert any(item.value == "Signed in as: citizen@example.test" for item in app.text)


def signed_in_chat_screen():
    import streamlit as st
    from app import app_new

    app_new._initialize_portal_state()
    st.session_state["account_email"] = "citizen@example.test"
    app_new._render_chat_page()


def test_email_is_visible_on_workflow_screens(monkeypatch):
    monkeypatch.setattr(app_new, "_api_base_url", lambda: "http://api")
    monkeypatch.setattr(
        app_new, "urlopen", lambda *args, **kwargs: FakeResponse({"status": "ok"})
    )
    app = AppTest.from_function(signed_in_chat_screen).run()
    assert not app.exception
    assert any(item.value == "Signed in as: citizen@example.test" for item in app.text)


def test_signout_clears_account_email(monkeypatch):
    session = {"account_email": "citizen@example.test", "account_email_error": "old"}
    monkeypatch.setattr(app_new.st, "session_state", session)
    app_new._sign_out()
    assert session["account_email"] is None
    assert session["account_email_error"] is None
    assert session["access_token"] is None


@pytest.mark.parametrize("outcome", ["email", "missing", "failure"])
def test_callback_keeps_signin_when_account_email_unavailable(monkeypatch, outcome):
    session = {"account_email": "old@example.test", "account_email_error": "old"}
    token = ui_auth.AccessToken("token-1", time.time() + 3600)
    monkeypatch.setattr(app_new.st, "session_state", session)
    monkeypatch.setattr(app_new.st, "query_params", {"code": "code", "state": "state"})
    monkeypatch.setattr(app_new.st, "rerun", lambda: None)
    monkeypatch.setattr(ui_auth, "complete_sign_in", lambda *args: token)

    def get_email(*args):
        if outcome == "failure":
            raise ui_auth.SignInError("Your account email could not be retrieved.")
        return "citizen@example.test" if outcome == "email" else None

    monkeypatch.setattr(ui_auth, "user_email", get_email)
    app_new._handle_sign_in_callback(ui_auth.ui_settings())
    assert session["access_token"] == token
    assert session["portal_stage"] == "consent"
    assert session["account_email"] == ("citizen@example.test" if outcome == "email" else None)
    assert bool(session["account_email_error"]) == (outcome != "email")


def test_expired_session_clears_account_email(monkeypatch):
    session = {
        "portal_stage": "chat",
        "account_email": "citizen@example.test",
        "access_error": None,
    }
    monkeypatch.setattr(app_new.st, "session_state", session)
    monkeypatch.setattr(app_new, "_access_token", lambda: None)
    monkeypatch.setattr(app_new, "_render_access_page", lambda: None)
    app_new._render_citizen_portal()
    assert session["account_email"] is None
    assert session["portal_stage"] == "access"


def test_code_exchange_sends_the_verifier_and_state_is_single_use(monkeypatch):
    settings = ui_auth.ui_settings()
    state = parse_qs(urlparse(ui_auth.authorize_url(settings)).query)["state"][0]
    verifier = ui_auth._pending[state][0]
    sent = []

    def fake_urlopen(request, timeout):
        sent.append((request.full_url, json.loads(request.data)))
        return FakeResponse({"access_token": "token-1", "expires_in": 3600})

    monkeypatch.setattr(ui_auth, "urlopen", fake_urlopen)
    token = ui_auth.complete_sign_in(settings, "code-1", state)

    assert token.value == "token-1" and token.is_valid()
    assert sent[0][0] == "https://tenant.example.auth0.com/oauth/token"
    assert sent[0][1]["code_verifier"] == verifier
    assert sent[0][1]["grant_type"] == "authorization_code"
    with pytest.raises(ui_auth.SignInError):
        ui_auth.complete_sign_in(settings, "code-1", state)


def test_unknown_state_is_rejected_without_calling_auth0(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("Auth0 must not be called for an unknown state.")

    monkeypatch.setattr(ui_auth, "urlopen", fail)
    with pytest.raises(ui_auth.SignInError):
        ui_auth.complete_sign_in(ui_auth.ui_settings(), "code", "forged-state")


def test_failed_exchange_does_not_leak_auth0_details(monkeypatch):
    settings = ui_auth.ui_settings()
    state = parse_qs(urlparse(ui_auth.authorize_url(settings)).query)["state"][0]

    def reject(request, timeout):
        raise HTTPError(request.full_url, 403, "secret detail", {}, io.BytesIO(b"secret detail"))

    monkeypatch.setattr(ui_auth, "urlopen", reject)
    with pytest.raises(ui_auth.SignInError) as error:
        ui_auth.complete_sign_in(settings, "code", state)
    assert "secret" not in str(error.value)


def test_expired_tokens_are_not_sent():
    assert not ui_auth.AccessToken("old", time.time() - 1).is_valid()
    assert not ui_auth.AccessToken("soon", time.time() + 10).is_valid()


def test_api_requests_carry_the_signed_in_users_bearer_token(monkeypatch):
    sent = []
    monkeypatch.setattr(app_new, "_access_token", lambda: "token-1")

    def fake_urlopen(request, timeout):
        sent.append(request)
        return FakeResponse({"ok": True})

    monkeypatch.setattr(app_new, "urlopen", fake_urlopen)
    app_new._api_request("http://api/x", headers={"Content-Type": "application/json"})

    assert sent[0].get_header("Authorization") == "Bearer token-1"
    assert sent[0].get_header("Content-type") == "application/json"


def test_requests_without_a_session_send_no_authorization_header(monkeypatch):
    monkeypatch.setattr(app_new, "_access_token", lambda: None)
    assert "Authorization" not in app_new._auth_headers({"Accept": "x"})


def test_unauthorized_response_ends_the_session(monkeypatch):
    signed_out = []
    monkeypatch.setattr(app_new, "_sign_out", lambda: signed_out.append(True))

    def unauthorized(request, timeout):
        raise HTTPError(request.full_url, 401, "x", {}, io.BytesIO(b'{"detail": "bad"}'))

    monkeypatch.setattr(app_new, "urlopen", unauthorized)
    with pytest.raises(RuntimeError, match="sign in again"):
        app_new._api_request("http://api/x")
    assert signed_out == [True]


def test_chat_result_exposes_rule_verdicts_for_the_ui(monkeypatch):
    verdicts = {"S1": {"verdict": "eligible", "conditions": [], "citations": []}}
    responses = iter(
        [
            {
                "thread_id": "t1",
                "next_step": "eligibility_checked",
                "response": "You may be eligible.",
                "data": {"verdicts": verdicts, "known_facts": {"age": 62}},
            },
            {"schemes": [{"scheme_id": "S1", "name": "Scheme One"}]},
        ]
    )
    monkeypatch.setattr(
        app_new, "urlopen", lambda request, timeout: FakeResponse(next(responses))
    )
    progress = type("Progress", (), {"write": lambda self, message: None})()

    _, _, result = app_new._send_chat("http://api", "I am 62", None, "a", progress)

    assert result["status"] == "eligibility_checked"
    assert result["verdicts"] == verdicts
    assert result["profile"] == {"age": 62}
    assert result["scheme_names"] == {"S1": "Scheme One"}
