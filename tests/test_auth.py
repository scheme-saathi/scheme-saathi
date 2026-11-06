from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app import auth


@pytest.fixture
def auth0_keys(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    claim = "https://scheme-saathi.example/household_id"
    monkeypatch.setenv("AUTH0_DOMAIN", "tenant.example.auth0.com")
    monkeypatch.setenv("AUTH0_AUDIENCE", "https://api.scheme-saathi.example")
    monkeypatch.setenv("AUTH0_HOUSEHOLD_CLAIM", claim)
    monkeypatch.setattr(
        auth,
        "_jwks_client",
        lambda issuer: SimpleNamespace(
            get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=public_key)
        ),
    )
    return private_key, claim


def issue_token(private_key, claim, **overrides):
    now = datetime.now(timezone.utc)
    claims = {
        "sub": "auth0|citizen-1",
        claim: "household-1",
        "iss": "https://tenant.example.auth0.com/",
        "aud": "https://api.scheme-saathi.example",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        **overrides,
    }
    return jwt.encode(claims, private_key, algorithm="RS256")


def test_auth0_verification_returns_only_the_verified_household(auth0_keys):
    private_key, claim = auth0_keys
    principal = auth.verify_auth0_token(issue_token(private_key, claim))

    assert principal.household_id == "household-1"
    assert principal.subject == "auth0|citizen-1"


def test_auth0_verification_loads_dotenv_settings(auth0_keys, monkeypatch):
    private_key, claim = auth0_keys
    loaded = []
    monkeypatch.setattr(auth, "load_dotenv", lambda: loaded.append(True))

    auth.verify_auth0_token(issue_token(private_key, claim))

    assert loaded == [True]


def test_auth0_verification_rejects_wrong_audience(auth0_keys):
    private_key, claim = auth0_keys
    token = issue_token(private_key, claim, aud="another-api")

    with pytest.raises(auth.Auth0TokenError):
        auth.verify_auth0_token(token)


def test_auth0_verification_requires_expiration(auth0_keys):
    private_key, claim = auth0_keys
    token = jwt.decode(
        issue_token(private_key, claim),
        options={"verify_signature": False},
    )
    token.pop("exp")
    token = jwt.encode(token, private_key, algorithm="RS256")

    with pytest.raises(auth.Auth0TokenError):
        auth.verify_auth0_token(token)


def test_auth0_verification_rejects_expired_token(auth0_keys):
    private_key, claim = auth0_keys
    token = issue_token(
        private_key,
        claim,
        exp=datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    with pytest.raises(auth.Auth0TokenError):
        auth.verify_auth0_token(token)


def test_auth0_verification_requires_household_claim(auth0_keys):
    private_key, claim = auth0_keys
    token = issue_token(private_key, claim, **{claim: ""})

    with pytest.raises(auth.Auth0TokenError):
        auth.verify_auth0_token(token)


def test_auth0_verification_fails_closed_when_configuration_is_missing(monkeypatch):
    for name in ("AUTH0_DOMAIN", "AUTH0_AUDIENCE", "AUTH0_HOUSEHOLD_CLAIM"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(auth.Auth0ConfigurationError):
        auth.verify_auth0_token("token")
