"""A consent only covers the purpose it was granted for."""

from datetime import datetime, timedelta

import pytest

from agents.memory import ApplicationReference, MemoryConsent, MemoryFact, MemoryScope
from agents.memory_service import HouseholdAllowlist, InMemoryMemoryService

SCOPE = MemoryScope(actor_id="a1", household_id="hh1", actor_role="citizen")


def _consent(purpose: str) -> MemoryConsent:
    now = datetime.utcnow()
    return MemoryConsent(
        purpose=purpose,
        granted=True,
        notice_version="1.0",
        decided_at=now,
        expires_at=now + timedelta(days=30),
        consent_reference="c1",
    )


@pytest.fixture
def service():
    return InMemoryMemoryService(
        HouseholdAllowlist(allowed_fields={"state_code": {"type": "string"}})
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


def _reference() -> ApplicationReference:
    now = datetime.utcnow()
    return ApplicationReference(
        scheme_id="S1",
        application_id="APP1",
        submitted_at=now,
        expires_at=now + timedelta(days=20),
        consent_reference="c1",
    )


def test_application_consent_cannot_store_profile_facts(service):
    service.record_consent(SCOPE, _consent("application_references"))
    with pytest.raises(ValueError, match="does not cover profile_facts"):
        service.save_confirmed_fact(SCOPE, _fact())


def test_profile_consent_cannot_store_application_references(service):
    service.record_consent(SCOPE, _consent("profile_facts"))
    with pytest.raises(ValueError, match="does not cover application_references"):
        service.save_application_reference(SCOPE, _reference())


def test_matching_purpose_is_accepted(service):
    service.record_consent(SCOPE, _consent("profile_facts"))
    service.save_confirmed_fact(SCOPE, _fact())
    assert service.read_facts(SCOPE, ["state_code"]) == {"state_code": "KA"}
