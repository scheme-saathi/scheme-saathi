from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import threading
import time
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv

CAPABILITY_TTL_SECONDS = 60
_used_nonces: dict[str, float] = {}
_nonce_lock = threading.Lock()


class CapabilityError(ValueError):
    """Raised when a portal write capability is missing, invalid, or reused."""


def application_payload_hash(
    scheme_id: str,
    applicant: dict[str, Any],
    documents: dict[str, Any] | None = None,
) -> str:
    payload = {
        "scheme_id": scheme_id,
        "applicant": applicant,
        "documents": documents or {},
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def issue_write_capability(
    action: str,
    resource: str,
    payload_hash: str,
) -> str:
    load_dotenv()
    secret = os.getenv("MOCK_PORTAL_AUTH_SECRET", "")
    if not secret:
        raise CapabilityError("Mock portal write authorization is not configured.")

    now = time.time()
    payload = {
        "action": action,
        "resource": resource,
        "payload_hash": payload_hash,
        "expires_at": int(now + CAPABILITY_TTL_SECONDS),
        "nonce": uuid4().hex,
    }
    encoded = _encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
    return f"{encoded}.{_encode(signature)}"


def consume_write_capability(
    token: str,
    action: str,
    resource: str,
    payload_hash: str,
) -> None:
    if not isinstance(token, str) or not token:
        raise CapabilityError("Write capability is required.")
    load_dotenv()
    secret = os.getenv("MOCK_PORTAL_AUTH_SECRET", "")
    if not secret:
        raise CapabilityError("Mock portal write authorization is not configured.")
    try:
        encoded, provided_signature = token.split(".", 1)
        expected_signature = hmac.new(
            secret.encode(), encoded.encode(), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_decode(provided_signature), expected_signature):
            raise CapabilityError("Write capability is invalid.")
        payload = json.loads(_decode(encoded))
    except CapabilityError:
        raise
    except (ValueError, TypeError, json.JSONDecodeError):
        raise CapabilityError("Write capability is invalid.") from None

    if not isinstance(payload, dict):
        raise CapabilityError("Write capability is invalid.")
    if (
        payload.get("action") != action
        or payload.get("resource") != resource
        or payload.get("payload_hash") != payload_hash
        or not isinstance(payload.get("expires_at"), int)
        or payload["expires_at"] < time.time()
        or not isinstance(payload.get("nonce"), str)
    ):
        raise CapabilityError("Write capability does not authorize this action.")

    nonce = payload["nonce"]
    with _nonce_lock:
        expired = [key for key, expiry in _used_nonces.items() if expiry < time.time()]
        for key in expired:
            del _used_nonces[key]
        if nonce in _used_nonces:
            raise CapabilityError("Write capability has already been used.")
        _used_nonces[nonce] = float(payload["expires_at"])


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
