"""ChromaDB memory only stores and returns data covered by an active consent."""

from datetime import datetime, timedelta

import pytest

from agents.chromadb_memory_service import ChromaDBMemoryService
from agents.memory import ApplicationReference, MemoryConsent, MemoryFact, MemoryScope
from agents.memory_service import HouseholdAllowlist

ALLOWLIST = HouseholdAllowlist(allowed_fields={"state_code": {"type": "string"}})


def _scope(household_id: str = "hh_a") -> MemoryScope:
    return MemoryScope(
        actor_id="actor", household_id=household_id, actor_role="citizen"
    )


def _consent(purpose="profile_facts", granted=True, days=30, reference="c1") -> MemoryConsent:
    now = datetime.utcnow()
    return MemoryConsent(
        purpose=purpose,
        granted=granted,
        notice_version="1.0",
        decided_at=now - timedelta(days=max(0, -days) + 1),
        expires_at=now + timedelta(days=days),
        consent_reference=reference,
    )


def _fact() -> MemoryFact:
    now = datetime.utcnow()
    return MemoryFact(
        field="state_code",
        value="KA",
        source="user",
        confirmed_at=now,
        reconfirm_by=now + timedelta(days=10),
        expires_at=now + timedelta(days=20),
        consent_reference="c1",
    )


def _reference(reference="c1") -> ApplicationReference:
    now = datetime.utcnow()
    return ApplicationReference(
        scheme_id="S1",
        application_id="APP1",
        submitted_at=now,
        expires_at=now + timedelta(days=20),
        consent_reference=reference,
    )


@pytest.fixture
def service(tmp_path):
    return ChromaDBMemoryService(persist_directory=str(tmp_path), allowlist=ALLOWLIST)


def test_save_without_consent_is_rejected(service):
    with pytest.raises(ValueError, match="No active"):
        service.save_confirmed_fact(_scope(), _fact())


def test_denied_consent_is_rejected(service):
    service.record_consent(_scope(), _consent(granted=False))
    with pytest.raises(ValueError, match="No active"):
        service.save_confirmed_fact(_scope(), _fact())


def test_wrong_purpose_is_rejected(service):
    service.record_consent(_scope(), _consent(purpose="application_references"))
    with pytest.raises(ValueError, match="No active"):
        service.save_confirmed_fact(_scope(), _fact())
    service.record_consent(_scope("hh_b"), _consent(purpose="profile_facts", reference="c2"))
    with pytest.raises(ValueError, match="No active"):
        service.save_application_reference(_scope("hh_b"), _reference("c2"))


def test_other_household_cannot_use_consent(service):
    service.record_consent(_scope("hh_a"), _consent())
    with pytest.raises(ValueError, match="No active"):
        service.save_confirmed_fact(_scope("hh_b"), _fact())


def test_withdrawn_consent_hides_facts_on_read(service):
    service.record_consent(_scope(), _consent())
    service.save_confirmed_fact(_scope(), _fact())
    assert service.read_facts(_scope(), ["state_code"]) == {"state_code": "KA"}
    service.withdraw_consent(_scope(), "c1")
    assert service.read_facts(_scope(), ["state_code"]) == {}


def test_withdrawn_consent_hides_references_on_read(service):
    service.record_consent(_scope(), _consent(purpose="application_references"))
    service.save_application_reference(_scope(), _reference())
    assert len(service.read_application_references(_scope())) == 1
    service.withdraw_consent(_scope(), "c1")
    assert service.read_application_references(_scope()) == []


def test_withdrawn_consent_cannot_be_used_to_save(service):
    service.record_consent(_scope(), _consent())
    service.withdraw_consent(_scope(), "c1")
    with pytest.raises(ValueError, match="No active"):
        service.save_confirmed_fact(_scope(), _fact())
