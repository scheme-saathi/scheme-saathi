"""read_facts must not return facts past their reconfirm_by deadline."""

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
    now = datetime.now()
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


def _fact(reconfirm_by: datetime) -> MemoryFact:
    now = datetime.now()
    return MemoryFact(
        field="state_code",
        value="KA",
        source="user",
        confirmed_at=now - timedelta(days=5),
        reconfirm_by=reconfirm_by,
        expires_at=now + timedelta(days=20),
        consent_reference="c1",
    )


def test_fact_past_reconfirm_deadline_is_not_returned(service):
    service.save_confirmed_fact(SCOPE, _fact(datetime.now() + timedelta(seconds=1)))
    service.facts[next(iter(service.facts))] = _fact(datetime.now() - timedelta(seconds=1))
    assert service.read_facts(SCOPE, ["state_code"]) == {}


def test_fact_before_reconfirm_deadline_is_returned(service):
    service.save_confirmed_fact(SCOPE, _fact(datetime.now() + timedelta(days=5)))
    assert service.read_facts(SCOPE, ["state_code"]) == {"state_code": "KA"}
