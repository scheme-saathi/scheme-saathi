"""Withdrawing consent in ChromaDB deletes the data stored under it."""

from datetime import datetime, timedelta

import pytest

from agents.chromadb_memory_service import ChromaDBMemoryService
from agents.memory import ApplicationReference, MemoryConsent, MemoryFact, MemoryScope
from agents.memory_service import HouseholdAllowlist

ALLOWLIST = HouseholdAllowlist(allowed_fields={"state_code": {"type": "string"}})


def _scope(household_id: str) -> MemoryScope:
    return MemoryScope(actor_id="a", household_id=household_id, actor_role="citizen")


def _consent(ref: str, purpose: str = "profile_facts") -> MemoryConsent:
    now = datetime.utcnow()
    return MemoryConsent(
        purpose=purpose,
        granted=True,
        notice_version="1.0",
        decided_at=now,
        expires_at=now + timedelta(days=30),
        consent_reference=ref,
    )


def _fact(ref: str) -> MemoryFact:
    now = datetime.utcnow()
    return MemoryFact(
        field="state_code",
        value="KA",
        source="user",
        confirmed_at=now,
        reconfirm_by=now + timedelta(days=10),
        expires_at=now + timedelta(days=20),
        consent_reference=ref,
    )


def _reference(ref: str) -> ApplicationReference:
    now = datetime.utcnow()
    return ApplicationReference(
        scheme_id="S1",
        application_id="APP1",
        submitted_at=now,
        expires_at=now + timedelta(days=20),
        consent_reference=ref,
    )


@pytest.fixture
def service(tmp_path):
    return ChromaDBMemoryService(persist_directory=str(tmp_path), allowlist=ALLOWLIST)


def test_withdraw_deletes_facts_and_references_of_that_consent(service):
    scope = _scope("hh_a")
    service.record_consent(scope, _consent("c1"))
    service.record_consent(scope, _consent("c2", "application_references"))
    service.save_confirmed_fact(scope, _fact("c1"))
    service.save_application_reference(scope, _reference("c2"))

    service.withdraw_consent(scope, "c1")
    assert service.facts_collection.get()["ids"] == []
    assert len(service.applications_collection.get()["ids"]) == 1

    service.withdraw_consent(scope, "c2")
    assert service.applications_collection.get()["ids"] == []


def test_withdraw_keeps_other_consents_and_households(service):
    scope_a, scope_b = _scope("hh_a"), _scope("hh_b")
    service.record_consent(scope_a, _consent("c1"))
    service.record_consent(scope_b, _consent("c3"))
    service.save_confirmed_fact(scope_a, _fact("c1"))
    service.save_confirmed_fact(scope_b, _fact("c3"))

    service.withdraw_consent(scope_a, "c1")

    assert service.read_facts(scope_a, ["state_code"]) == {}
    assert service.read_facts(scope_b, ["state_code"]) == {"state_code": "KA"}
