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
    monkeypatch.setenv("AUTH0_ROLE_CLAIM", "")  # roles are off unless a test turns them on
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


ROLE_CLAIM = "https://scheme-saathi.example/role"


def operator_token(private_key, claim, role="operator", **overrides):
    """A token with no household claim of its own (null unless the test sets one)."""
    claims = {"sub": "auth0|operator-7", ROLE_CLAIM: role, claim: None, **overrides}
    return issue_token(private_key, claim, **claims)


def test_a_citizen_token_is_a_citizen_by_default(auth0_keys, monkeypatch):
    private_key, claim = auth0_keys
    monkeypatch.setenv("AUTH0_ROLE_CLAIM", "")
    principal = auth.verify_auth0_token(issue_token(private_key, claim))
    assert principal.role == "citizen"


def test_the_role_claim_is_ignored_unless_it_is_configured(auth0_keys, monkeypatch):
    private_key, claim = auth0_keys
    monkeypatch.setenv("AUTH0_ROLE_CLAIM", "")
    token = issue_token(private_key, claim, **{ROLE_CLAIM: "operator"})
    principal = auth.verify_auth0_token(token)
    assert (principal.role, principal.household_id) == ("citizen", "household-1")


def test_an_operator_signs_in_without_a_household_and_gets_their_own_namespace(auth0_keys, monkeypatch):
    private_key, claim = auth0_keys
    monkeypatch.setenv("AUTH0_ROLE_CLAIM", ROLE_CLAIM)

    principal = auth.verify_auth0_token(operator_token(private_key, claim))

    assert principal.role == "operator"
    assert principal.subject == "auth0|operator-7"
    assert principal.household_id == "operator:auth0|operator-7"


def test_an_operator_never_gets_a_citizens_household_even_if_the_token_names_one(auth0_keys, monkeypatch):
    private_key, claim = auth0_keys
    monkeypatch.setenv("AUTH0_ROLE_CLAIM", ROLE_CLAIM)
    token = operator_token(private_key, claim, **{claim: "household-1"})
    assert auth.verify_auth0_token(token).household_id == "operator:auth0|operator-7"


def test_a_role_list_with_operator_makes_an_operator(auth0_keys, monkeypatch):
    private_key, claim = auth0_keys
    monkeypatch.setenv("AUTH0_ROLE_CLAIM", ROLE_CLAIM)
    token = operator_token(private_key, claim, role=["staff", "operator", 5])
    assert auth.verify_auth0_token(token).role == "operator"


@pytest.mark.parametrize("role", ["citizen", "admin", "", ["staff"], 7, None])
def test_any_other_role_value_is_a_citizen_who_still_needs_a_household(auth0_keys, monkeypatch, role):
    private_key, claim = auth0_keys
    monkeypatch.setenv("AUTH0_ROLE_CLAIM", ROLE_CLAIM)
    assert auth.verify_auth0_token(issue_token(private_key, claim, **{ROLE_CLAIM: role})).role == "citizen"
    with pytest.raises(auth.Auth0TokenError):
        auth.verify_auth0_token(operator_token(private_key, claim, role=role))


def test_a_citizen_cannot_claim_a_household_in_the_operator_namespace(auth0_keys, monkeypatch):
    private_key, claim = auth0_keys
    monkeypatch.setenv("AUTH0_ROLE_CLAIM", ROLE_CLAIM)
    with pytest.raises(auth.Auth0TokenError):
        auth.verify_auth0_token(issue_token(private_key, claim, **{claim: "operator:auth0|operator-7"}))


def test_an_operator_token_still_needs_a_subject(auth0_keys, monkeypatch):
    private_key, claim = auth0_keys
    monkeypatch.setenv("AUTH0_ROLE_CLAIM", ROLE_CLAIM)
    with pytest.raises(auth.Auth0TokenError):
        auth.verify_auth0_token(operator_token(private_key, claim, sub=" "))
