"""The memory policy, its allowlist checks and the memory contract models."""

from datetime import datetime, timedelta, timezone

import pytest

from agents.memory import ApplicationReference, MemoryConsent, MemoryFact, MemoryScope
from agents.memory_service import HouseholdAllowlist, InMemoryMemoryService, looks_like_identifier
from servers.rule_engine.server import get_field_specs, list_rule_schemes

NOW = datetime(2026, 11, 8, 12, 0, 0)


@pytest.fixture(scope="module")
def policy():
    return HouseholdAllowlist.from_policy_file()


@pytest.fixture(scope="module")
def rule_specs():
    return get_field_specs(list_rule_schemes()["data"])["data"]


def test_every_policy_field_is_a_reviewed_rule_field_of_the_same_type(policy, rule_specs):
    for field, spec in policy.allowed_fields.items():
        assert field in rule_specs, f"{field} is not a field of any reviewed rule"
        assert spec["type"] == rule_specs[field]["type"], field
        if rule_specs[field]["known_values"]:
            assert sorted(spec["known_values"]) == sorted(rule_specs[field]["known_values"]), field


def test_temporary_only_fields_are_reviewed_rule_fields_and_never_stored(policy, rule_specs):
    assert "has_disability" in policy.temporary_only and "social_category" in policy.temporary_only
    for field in policy.temporary_only:
        assert field in rule_specs, field
        assert not policy.is_field_allowed(field)
        with pytest.raises(ValueError, match="not allowed for storage"):
            policy.validate_fact(field, True)


def test_every_stored_field_has_a_retention_window(policy):
    confirmed = NOW
    for field in policy.allowed_fields:
        reconfirm_by, expires_at = policy.retention_window(field, confirmed)
        assert confirmed < reconfirm_by <= expires_at


def test_retention_window_follows_the_policy(policy):
    assert policy.retention_window("age", NOW) == (NOW + timedelta(days=30), NOW + timedelta(days=90))


def test_valid_values_are_accepted(policy):
    policy.validate_fact("age", 34)
    policy.validate_fact("annual_income", 120000.5)
    policy.validate_fact("is_woman_or_girl", False)
    policy.validate_fact("marital_status", "married")


@pytest.mark.parametrize(
    "field, value, message",
    [
        ("aadhaar_number", "123456789012", "not allowed for storage"),
        ("age", "34", "must be of type number"),
        ("age", True, "must be of type number"),
        ("age", float("nan"), "must be of type number"),
        ("is_indian_citizen", "yes", "must be of type bool"),
        ("marital_status", "single", "must be one of"),
        ("ration_card_type", ["white"], "must be of type str"),
    ],
)
def test_unlisted_or_wrongly_typed_values_are_rejected(policy, field, value, message):
    with pytest.raises(ValueError, match=message):
        policy.validate_fact(field, value)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("1234 5678 9012", True),
        ("1234-5678-9012", True),
        ("ABCDE1234F", True),
        ("9876543210", True),
        ("married", False),
        ("ward 12 block 4", False),
    ],
)
def test_identifier_shaped_text_is_detected(text, expected):
    assert looks_like_identifier(text) is expected


def test_identifier_shaped_values_are_rejected_even_for_listed_text_fields():
    allowlist = HouseholdAllowlist(allowed_fields={"nickname": {"type": "string"}})
    allowlist.validate_fact("nickname", "Asha")
    with pytest.raises(ValueError, match="identifier"):
        allowlist.validate_fact("nickname", "1234 5678 9012")
    with pytest.raises(ValueError, match="too long"):
        allowlist.validate_fact("nickname", "x" * 101)


def test_a_field_cannot_be_both_stored_and_temporary_only(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text('{"fields": {"age": {"type": "number"}}, "temporary_only": ["age"]}')
    with pytest.raises(ValueError, match="both stored and temporary"):
        HouseholdAllowlist.from_policy_file(path)


def test_in_memory_service_enforces_the_policy_on_save(policy):
    service = InMemoryMemoryService(policy)
    scope = MemoryScope(actor_id="a", household_id="hh1", actor_role="citizen")
    now = datetime.utcnow()
    service.record_consent(
        scope,
        MemoryConsent(
            purpose="profile_facts",
            granted=True,
            notice_version="1",
            decided_at=now,
            expires_at=now + timedelta(days=30),
            consent_reference="c1",
        ),
    )

    def fact(field, value):
        return MemoryFact(
            field=field,
            value=value,
            source="user",
            confirmed_at=now,
            reconfirm_by=now + timedelta(days=10),
            expires_at=now + timedelta(days=20),
            consent_reference="c1",
        )

    with pytest.raises(ValueError, match="must be of type number"):
        service.save_confirmed_fact(scope, fact("age", "34"))
    with pytest.raises(ValueError, match="not allowed for storage"):
        service.save_confirmed_fact(scope, fact("social_category", "OBC"))

    service.save_confirmed_fact(scope, fact("age", 34))
    service.save_confirmed_fact(scope, fact("is_indian_citizen", True))
    assert service.read_facts(scope, []) == {"age": 34, "is_indian_citizen": True}
    assert service.read_facts(scope, ["age", "social_category"]) == {"age": 34}


def test_scope_owner_is_the_household_for_citizens_and_the_operator_for_operators():
    citizen = MemoryScope(actor_id="u1", household_id="hh1", actor_role="citizen")
    operator = MemoryScope(actor_id="op1", household_id="hh1", actor_role="operator")
    assert citizen.owner_key == "hh1"
    assert operator.owner_key == "operator:op1"
    assert operator.owner_for("profile_facts") == "hh1"
    assert operator.owner_for("application_references") == "operator:op1"


def _consent(**changes):
    values = dict(
        purpose="application_references",
        granted=True,
        notice_version="1",
        decided_at=NOW,
        expires_at=NOW + timedelta(days=30),
        consent_reference="c1",
    )
    return MemoryConsent(**{**values, **changes})


def test_consent_taken_in_person_names_who_recorded_it():
    with pytest.raises(ValueError, match="who recorded"):
        _consent(obtained_via="in_person")
    consent = _consent(obtained_via="in_person", recorded_by="operator-7")
    assert consent.recorded_by == "operator-7"
    assert _consent().obtained_via == "self_service"


def test_consent_comparison_accepts_timezone_aware_times():
    consent = _consent(
        decided_at=datetime(2026, 11, 8, 12, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))),
        expires_at=datetime(2026, 11, 8, 7, 0, tzinfo=timezone.utc),
    )
    assert consent.expires_at > consent.decided_at
    with pytest.raises(ValueError, match="must expire after"):
        _consent(
            decided_at=datetime(2026, 11, 8, 12, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))),
            expires_at=datetime(2026, 11, 8, 6, 0, tzinfo=timezone.utc),
        )


def _reference(**changes):
    values = dict(
        scheme_id="C01",
        application_id="APP-1",
        submitted_at=NOW,
        expires_at=NOW + timedelta(days=90),
        consent_reference="c1",
    )
    return ApplicationReference(**{**values, **changes})


def test_application_reference_defaults_to_the_account_holder():
    reference = _reference()
    assert reference.subject == "self"
    assert reference.relation is None and reference.submitted_by is None


def test_relation_label_is_only_for_other_people_and_is_a_short_word():
    assert _reference(subject="other", relation="mother", submitted_by="u1").relation == "mother"
    assert _reference(subject="other", relation="माँ").relation == "माँ"
    with pytest.raises(ValueError, match="only applies"):
        _reference(relation="mother")
    for bad in ["Ramesh 9876543210", "1234", "", "a" * 41, "<script>"]:
        with pytest.raises(ValueError, match="relation label"):
            _reference(subject="other", relation=bad)
