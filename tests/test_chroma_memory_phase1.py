"""ChromaDB memory: no embeddings of personal data, one current fact per field, owners, expiry."""

from datetime import datetime, timedelta, timezone

import pytest

from agents import chromadb_memory_service
from agents.chromadb_memory_service import PLACEHOLDER_VECTOR, ChromaDBMemoryService
from agents.memory import ApplicationReference, MemoryConsent, MemoryFact, MemoryScope


def _scope(household_id="hh_a", actor_id="u1", role="citizen") -> MemoryScope:
    return MemoryScope(actor_id=actor_id, household_id=household_id, actor_role=role)


def _consent(ref="c1", purpose="profile_facts", days=30, **changes) -> MemoryConsent:
    now = datetime.utcnow()
    return MemoryConsent(
        **{
            "purpose": purpose,
            "granted": True,
            "notice_version": "1",
            "decided_at": now,
            "expires_at": now + timedelta(days=days),
            "consent_reference": ref,
            **changes,
        }
    )


def _fact(field="age", value=34, ref="c1", confirmed_at=None, days=20) -> MemoryFact:
    confirmed_at = confirmed_at or datetime.utcnow()
    return MemoryFact(
        field=field,
        value=value,
        source="user",
        confirmed_at=confirmed_at,
        reconfirm_by=confirmed_at + timedelta(days=days // 2),
        expires_at=confirmed_at + timedelta(days=days),
        consent_reference=ref,
    )


def _reference(application_id="APP-1", ref="c1", days=90, **changes) -> ApplicationReference:
    now = datetime.utcnow()
    return ApplicationReference(
        **{
            "scheme_id": "C01",
            "application_id": application_id,
            "submitted_at": now,
            "expires_at": now + timedelta(days=days),
            "consent_reference": ref,
            **changes,
        }
    )


@pytest.fixture
def service(tmp_path):
    return ChromaDBMemoryService(persist_directory=str(tmp_path))


@pytest.fixture
def consented(service):
    service.record_consent(_scope(), _consent())
    return service


def test_records_carry_only_the_placeholder_vector(consented):
    consented.save_confirmed_fact(_scope(), _fact())
    consented.record_consent(_scope(), _consent("c2", "application_references"))
    consented.save_application_reference(_scope(), _reference(ref="c2"))
    for collection in (
        consented.facts_collection,
        consented.applications_collection,
        consented.consent_collection,
    ):
        vectors = collection.get(include=["embeddings"])["embeddings"]
        assert len(vectors) >= 1
        assert all(list(vector) == PLACEHOLDER_VECTOR for vector in vectors)


def test_default_policy_is_enforced(consented):
    with pytest.raises(ValueError, match="not allowed for storage"):
        consented.save_confirmed_fact(_scope(), _fact("household_size", 4))
    with pytest.raises(ValueError, match="not allowed for storage"):
        consented.save_confirmed_fact(_scope(), _fact("has_disability", True))
    with pytest.raises(ValueError, match="must be of type number"):
        consented.save_confirmed_fact(_scope(), _fact("age", "34"))
    with pytest.raises(ValueError, match="at most"):
        consented.save_confirmed_fact(_scope(), _fact("age", 34, days=3650))
    assert consented.get_household_fact_count("hh_a") == 0


def test_one_current_fact_per_field_and_newest_wins(consented):
    now = datetime.utcnow()
    consented.save_confirmed_fact(_scope(), _fact(value=30, confirmed_at=now - timedelta(days=2)))
    consented.save_confirmed_fact(_scope(), _fact(value=31, confirmed_at=now))
    consented.save_confirmed_fact(_scope(), _fact(value=29, confirmed_at=now - timedelta(days=1)))
    assert consented.get_household_fact_count("hh_a") == 1
    assert consented.read_facts(_scope(), ["age"]) == {"age": 31}


def test_reconsent_does_not_leave_a_duplicate_fact(consented):
    consented.save_confirmed_fact(_scope(), _fact(value=30))
    consented.record_consent(_scope(), _consent("c2"))
    consented.save_confirmed_fact(_scope(), _fact(value=31, ref="c2"))
    assert consented.get_household_fact_count("hh_a") == 1
    assert consented.read_facts(_scope(), ["age"]) == {"age": 31}


def test_an_empty_field_list_reads_every_allowlisted_field(consented):
    consented.save_confirmed_fact(_scope(), _fact("age", 34))
    consented.save_confirmed_fact(_scope(), _fact("is_indian_citizen", True))
    assert consented.read_facts(_scope(), []) == {"age": 34, "is_indian_citizen": True}
    assert consented.read_facts(_scope(), ["age", "social_category"]) == {"age": 34}


def test_fact_past_reconfirm_by_is_not_returned(consented, monkeypatch):
    consented.save_confirmed_fact(_scope(), _fact(days=20))
    later = datetime.utcnow() + timedelta(days=11)
    monkeypatch.setattr(chromadb_memory_service, "utc_now", lambda: later)
    assert consented.read_facts(_scope(), ["age"]) == {}


def test_application_reference_round_trips_subject_and_relation(service):
    scope = _scope()
    service.record_consent(scope, _consent("c2", "application_references"))
    service.save_application_reference(
        scope, _reference("APP-1", ref="c2", subject="other", relation="mother", submitted_by="u1")
    )
    [stored] = service.read_application_references(scope)
    assert (stored.subject, stored.relation, stored.submitted_by) == ("other", "mother", "u1")


def test_saving_the_same_application_again_replaces_it(service):
    scope = _scope()
    service.record_consent(scope, _consent("c2", "application_references"))
    service.save_application_reference(scope, _reference("APP-1", ref="c2"))
    service.save_application_reference(scope, _reference("APP-1", ref="c2", scheme_id="C02"))
    service.save_application_reference(scope, _reference("APP-2", ref="c2"))
    refs = service.read_application_references(scope)
    assert sorted(r.application_id for r in refs) == ["APP-1", "APP-2"]
    assert [r.scheme_id for r in refs if r.application_id == "APP-1"] == ["C02"]


def test_operator_list_is_separate_from_the_household(service):
    operator = _scope("hh_a", "op1", "operator")
    citizen = _scope("hh_a", "u1", "citizen")
    service.record_consent(
        operator,
        _consent("oc1", "application_references", obtained_via="in_person", recorded_by="op1"),
    )
    service.save_application_reference(operator, _reference("APP-9", ref="oc1", subject="other"))
    assert [r.application_id for r in service.read_application_references(operator)] == ["APP-9"]
    assert service.read_application_references(citizen) == []

    service.record_consent(citizen, _consent("c2", "application_references"))
    service.save_application_reference(citizen, _reference("APP-1", ref="c2"))
    assert [r.application_id for r in service.read_application_references(citizen)] == ["APP-1"]
    assert [r.application_id for r in service.read_application_references(operator)] == ["APP-9"]


def test_operator_consent_cannot_be_used_by_a_household(service):
    service.record_consent(_scope("hh_a", "op1", "operator"), _consent("oc1", "application_references"))
    with pytest.raises(ValueError, match="another household"):
        service.record_consent(_scope("hh_a"), _consent("oc1", "application_references"))
    with pytest.raises(ValueError, match="No active"):
        service.save_application_reference(_scope("hh_a"), _reference(ref="oc1"))


def test_operators_cannot_forget_a_household_and_forgetting_leaves_the_operator_list(consented):
    consented.save_confirmed_fact(_scope(), _fact())
    with pytest.raises(ValueError, match="Operators cannot"):
        consented.forget_household(_scope("hh_a", "op1", "operator"))
    assert consented.get_household_fact_count("hh_a") == 1

    operator = _scope("hh_a", "op1", "operator")
    consented.record_consent(operator, _consent("oc1", "application_references"))
    consented.save_application_reference(operator, _reference("APP-9", ref="oc1"))
    consented.forget_household(_scope())
    assert consented.get_household_fact_count("hh_a") == 0
    assert len(consented.read_application_references(operator)) == 1


def test_forget_removes_facts_references_and_consents(consented):
    scope = _scope()
    consented.save_confirmed_fact(scope, _fact())
    consented.record_consent(scope, _consent("c2", "application_references"))
    consented.save_application_reference(scope, _reference(ref="c2"))
    consented.forget_household(scope)
    for collection in (
        consented.facts_collection,
        consented.applications_collection,
        consented.consent_collection,
    ):
        assert collection.get()["ids"] == []


def test_a_withdrawn_consent_reference_cannot_be_recorded_again(consented):
    consented.withdraw_consent(_scope(), "c1")
    with pytest.raises(ValueError, match="was withdrawn"):
        consented.record_consent(_scope(), _consent("c1"))


def test_already_expired_consent_is_not_recorded(service):
    now = datetime.utcnow()
    consent = MemoryConsent(
        purpose="profile_facts",
        granted=True,
        notice_version="1",
        decided_at=now - timedelta(days=10),
        expires_at=now - timedelta(days=1),
        consent_reference="old",
    )
    with pytest.raises(ValueError, match="already expired"):
        service.record_consent(_scope(), consent)


def test_timezone_aware_times_are_compared_in_utc(service):
    scope = _scope()
    now = datetime.now(timezone.utc)
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
    service.save_confirmed_fact(
        scope,
        MemoryFact(
            field="age",
            value=34,
            source="user",
            confirmed_at=now,
            reconfirm_by=now + timedelta(days=10),
            expires_at=now + timedelta(days=20),
            consent_reference="c1",
        ),
    )
    assert service.read_facts(scope, ["age"]) == {"age": 34}


def test_purge_deletes_expired_records_and_keeps_current_ones(service, monkeypatch):
    scope = _scope()
    service.record_consent(scope, _consent("c1"))
    service.record_consent(scope, _consent("c2", "application_references"))
    service.save_confirmed_fact(scope, _fact("age", 34, days=10))
    service.save_confirmed_fact(scope, _fact("is_indian_citizen", True, days=40))
    service.save_application_reference(scope, _reference("APP-1", ref="c2", days=15))
    service.save_application_reference(scope, _reference("APP-2", ref="c2", days=28))

    assert service.purge_expired() == 0

    monkeypatch.setattr(
        chromadb_memory_service, "utc_now", lambda: datetime.utcnow() + timedelta(days=16)
    )
    assert service.purge_expired() == 2
    assert service.read_facts(scope, []) == {"is_indian_citizen": True}
    assert [r.application_id for r in service.read_application_references(scope)] == ["APP-2"]
    assert len(service.consent_collection.get()["ids"]) == 2


def test_purge_removes_what_an_expired_consent_covered_and_its_records(service, monkeypatch):
    scope = _scope()
    service.record_consent(scope, _consent("c1", days=5))
    service.save_confirmed_fact(scope, _fact("age", 34, days=20))
    service.record_consent(scope, _consent("c9", days=5))
    service.withdraw_consent(scope, "c9")

    monkeypatch.setattr(
        chromadb_memory_service, "utc_now", lambda: datetime.utcnow() + timedelta(days=6)
    )
    assert service.purge_expired() >= 3
    assert service.facts_collection.get()["ids"] == []
    assert service.consent_collection.get()["ids"] == []
