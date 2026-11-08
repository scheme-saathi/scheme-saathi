"""read_facts returns the most recently confirmed value for a field."""

from datetime import datetime, timedelta

import pytest

from agents.memory import MemoryConsent, MemoryFact, MemoryScope
from agents.memory_service import HouseholdAllowlist, InMemoryMemoryService

SCOPE = MemoryScope(actor_id="a1", household_id="hh1", actor_role="citizen")


@pytest.fixture
def service():
    svc = InMemoryMemoryService(
        HouseholdAllowlist(allowed_fields={"state_code": {"type": "string"}})
    )
    now = datetime.utcnow()
    svc.record_consent(
        SCOPE,
        MemoryConsent(
            purpose="profile_facts",
            granted=True,
            notice_version="1.0",
            decided_at=now,
            expires_at=now + timedelta(days=30),
            consent_reference="c1",
        ),
    )
    return svc


def _fact(value: str, confirmed_at: datetime) -> MemoryFact:
    return MemoryFact(
        field="state_code",
        value=value,
        source="user",
        confirmed_at=confirmed_at,
        reconfirm_by=datetime.utcnow() + timedelta(days=10),
        expires_at=datetime.utcnow() + timedelta(days=20),
        consent_reference="c1",
    )


def test_updated_value_replaces_old_one(service):
    now = datetime.utcnow()
    service.save_confirmed_fact(SCOPE, _fact("KA", now - timedelta(days=1)))
    service.save_confirmed_fact(SCOPE, _fact("TN", now))
    assert service.read_facts(SCOPE, ["state_code"]) == {"state_code": "TN"}


def test_newest_wins_regardless_of_save_order(service):
    now = datetime.utcnow()
    service.save_confirmed_fact(SCOPE, _fact("TN", now))
    service.save_confirmed_fact(SCOPE, _fact("KA", now - timedelta(days=1)))
    assert service.read_facts(SCOPE, ["state_code"]) == {"state_code": "TN"}
