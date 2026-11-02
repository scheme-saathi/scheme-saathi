"""A consent belongs to one household and cannot be used by another."""

from datetime import datetime, timedelta

import pytest

from agents.memory import MemoryConsent, MemoryFact, MemoryScope
from agents.memory_service import HouseholdAllowlist, InMemoryMemoryService


def _scope(household_id: str) -> MemoryScope:
    return MemoryScope(
        actor_id=f"actor_{household_id}", household_id=household_id, actor_role="citizen"
    )


def _consent(ref: str = "c1") -> MemoryConsent:
    now = datetime.now()
    return MemoryConsent(
        purpose="profile_facts",
        granted=True,
        notice_version="1.0",
        decided_at=now,
        expires_at=now + timedelta(days=30),
        consent_reference=ref,
    )


def _fact(ref: str = "c1") -> MemoryFact:
    now = datetime.now()
    return MemoryFact(
        field="state_code",
        value="KA",
        source="user",
        confirmed_at=now,
        reconfirm_by=now + timedelta(days=10),
        expires_at=now + timedelta(days=20),
        consent_reference=ref,
    )


@pytest.fixture
def service():
    return InMemoryMemoryService(
        HouseholdAllowlist(allowed_fields={"state_code": {"type": "string"}})
    )


def test_other_household_cannot_save_with_foreign_consent(service):
    service.record_consent(_scope("hh_a"), _consent())
    with pytest.raises(ValueError, match="not found or denied"):
        service.save_confirmed_fact(_scope("hh_b"), _fact())


def test_other_household_cannot_withdraw_foreign_consent(service):
    service.record_consent(_scope("hh_a"), _consent())
    with pytest.raises(ValueError, match="not found"):
        service.withdraw_consent(_scope("hh_b"), "c1")
    service.save_confirmed_fact(_scope("hh_a"), _fact())
    assert service.read_facts(_scope("hh_a"), ["state_code"]) == {"state_code": "KA"}


def test_consent_reference_cannot_be_rebound_to_another_household(service):
    service.record_consent(_scope("hh_a"), _consent())
    with pytest.raises(ValueError, match="another household"):
        service.record_consent(_scope("hh_b"), _consent())


def test_owner_can_still_use_own_consent(service):
    service.record_consent(_scope("hh_a"), _consent())
    service.save_confirmed_fact(_scope("hh_a"), _fact())
    assert service.read_facts(_scope("hh_a"), ["state_code"]) == {"state_code": "KA"}
