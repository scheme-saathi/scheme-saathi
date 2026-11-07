"""Auth0 sign-in for the Streamlit UI using the Authorization Code flow with PKCE."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv

_PENDING_TTL_SECONDS = 600
_pending: dict[str, tuple[str, float]] = {}
_pending_lock = Lock()


class SignInError(RuntimeError):
    """Sign-in could not be completed; the message is safe to show to the user."""


@dataclass(frozen=True)
class Auth0UiSettings:
    domain: str
    client_id: str
    audience: str
    redirect_uri: str


@dataclass(frozen=True)
class AccessToken:
    value: str
    expires_at: float

    def is_valid(self) -> bool:
        return time.time() < self.expires_at - 30


def ui_settings() -> Auth0UiSettings | None:
    """Return the Auth0 settings, or None when the UI is not configured for sign-in."""
    load_dotenv()
    domain = os.getenv("AUTH0_DOMAIN", "").strip().removeprefix("https://").rstrip("/")
    client_id = os.getenv("AUTH0_CLIENT_ID", "").strip()
    audience = os.getenv("AUTH0_AUDIENCE", "").strip()
    redirect_uri = os.getenv("AUTH0_REDIRECT_URI", "http://localhost:8501").strip()
    if not domain or not client_id or not audience or "/" in domain:
        return None
    return Auth0UiSettings(domain, client_id, audience, redirect_uri)


def missing_settings() -> list[str]:
    load_dotenv()
    required = ("AUTH0_DOMAIN", "AUTH0_CLIENT_ID", "AUTH0_AUDIENCE", "AUTH0_HOUSEHOLD_CLAIM")
    return [name for name in required if not os.getenv(name, "").strip()]


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _forget_expired(now: float) -> None:
    for state in [key for key, (_, expires) in _pending.items() if expires < now]:
        del _pending[state]


def authorize_url(settings: Auth0UiSettings) -> str:
    """Start a sign-in. The PKCE verifier stays on the server, keyed by a one-time state."""
    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(32)
    now = time.time()
    with _pending_lock:
        _forget_expired(now)
        _pending[state] = (verifier, now + _PENDING_TTL_SECONDS)
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.client_id,
            "redirect_uri": settings.redirect_uri,
            "scope": "openid profile",
            "audience": settings.audience,
            "code_challenge": _challenge(verifier),
            "code_challenge_method": "S256",
            "state": state,
        }
    )
    return f"https://{settings.domain}/authorize?{query}"


def complete_sign_in(settings: Auth0UiSettings, code: str, state: str) -> AccessToken:
    """Exchange the one-time code for an access token for this application's API."""
    with _pending_lock:
        _forget_expired(time.time())
        pending = _pending.pop(state, None)
    if pending is None:
        raise SignInError("The sign-in attempt expired or was not started here. Please try again.")

    body = json.dumps(
        {
            "grant_type": "authorization_code",
            "client_id": settings.client_id,
            "code": code,
            "code_verifier": pending[0],
            "redirect_uri": settings.redirect_uri,
        }
    ).encode("utf-8")
    request = Request(
        f"https://{settings.domain}/oauth/token",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, ValueError) as error:
        raise SignInError("Sign-in could not be completed. Please try again.") from error

    token = payload.get("access_token") if isinstance(payload, dict) else None
    lifetime = payload.get("expires_in") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token or not isinstance(lifetime, (int, float)):
        raise SignInError("Sign-in could not be completed. Please try again.")
    return AccessToken(token, time.time() + float(lifetime))
