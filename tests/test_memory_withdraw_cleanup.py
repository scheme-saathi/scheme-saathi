"""Withdrawing consent removes every record that relied on it."""

from datetime import datetime, timedelta

import pytest

from agents.memory import ApplicationReference, MemoryConsent, MemoryScope
from agents.memory_service import HouseholdAllowlist, InMemoryMemoryService

SCOPE = MemoryScope(actor_id="a1", household_id="hh1", actor_role="citizen")


@pytest.fixture
def service():
    return InMemoryMemoryService(HouseholdAllowlist())


def test_withdraw_deletes_application_references(service):
    now = datetime.now()
    service.record_consent(
        SCOPE,
        MemoryConsent(
            purpose="application_references",
            granted=True,
            notice_version="1.0",
            decided_at=now,
            expires_at=now + timedelta(days=30),
            consent_reference="c1",
        ),
    )
    service.save_application_reference(
        SCOPE,
        ApplicationReference(
            scheme_id="S1",
            application_id="APP1",
            submitted_at=now,
            expires_at=now + timedelta(days=20),
            consent_reference="c1",
        ),
    )
    service.withdraw_consent(SCOPE, "c1")

    assert service.application_refs == {}
    assert service.households["hh1"]["application_refs"] == []
    assert service.households["hh1"]["consents"] == []
    assert service.read_application_references(SCOPE) == []
