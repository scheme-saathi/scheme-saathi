from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

import jwt
from dotenv import load_dotenv
from fastapi import Header, HTTPException
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError, PyJWTError


class Auth0ConfigurationError(RuntimeError):
    """Auth0 is not configured for this application."""


class Auth0TokenError(ValueError):
    """An Auth0 access token is invalid or lacks a household identity."""


@dataclass(frozen=True)
class AuthenticatedHousehold:
    household_id: str
    subject: str


def _auth0_settings() -> tuple[str, str, str]:
    load_dotenv()
    domain = os.getenv("AUTH0_DOMAIN", "").strip().removeprefix("https://").rstrip("/")
    audience = os.getenv("AUTH0_AUDIENCE", "").strip()
    household_claim = os.getenv("AUTH0_HOUSEHOLD_CLAIM", "").strip()
    if not domain or not audience or not household_claim:
        raise Auth0ConfigurationError("Auth0 domain, audience and household claim are required.")
    if "/" in domain:
        raise Auth0ConfigurationError("AUTH0_DOMAIN must be a host name without a path.")
    return f"https://{domain}/", audience, household_claim


@lru_cache(maxsize=8)
def _jwks_client(issuer: str) -> PyJWKClient:
    return PyJWKClient(f"{issuer}.well-known/jwks.json")


def verify_auth0_token(token: str) -> AuthenticatedHousehold:
    issuer, audience, household_claim = _auth0_settings()
    try:
        signing_key = _jwks_client(issuer).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
            options={"require": ["exp", "sub"]},
        )
    except (PyJWKClientError, PyJWTError, ValueError) as error:
        raise Auth0TokenError("The access token is invalid.") from error

    subject = claims.get("sub")
    household_id = claims.get(household_claim)
    if (
        not isinstance(subject, str)
        or not subject.strip()
        or not isinstance(household_id, str)
        or not household_id.strip()
    ):
        raise Auth0TokenError("The access token has no household identity.")
    return AuthenticatedHousehold(household_id=household_id, subject=subject)


def authenticated_household(
    authorization: str | None = Header(default=None),
) -> AuthenticatedHousehold:
    """Validate an Auth0 bearer token and return its trusted household identity."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="A valid bearer token is required.")
    try:
        return verify_auth0_token(authorization.removeprefix("Bearer ").strip())
    except Auth0ConfigurationError as error:
        raise HTTPException(status_code=503, detail="Authentication is not configured.") from error
    except Auth0TokenError as error:
        raise HTTPException(status_code=401, detail="The bearer token is invalid.") from error
