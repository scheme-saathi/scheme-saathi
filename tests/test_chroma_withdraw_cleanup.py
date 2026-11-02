"""Withdrawing consent in ChromaDB deletes the data stored under it."""

from datetime import datetime, timedelta

import pytest

from agents.chromadb_memory_service import ChromaDBMemoryService
from agents.memory import ApplicationReference, MemoryFact, MemoryScope


def _scope(household_id: str) -> MemoryScope:
    return MemoryScope(actor_id="a", household_id=household_id, actor_role="citizen")


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
    return ChromaDBMemoryService(persist_directory=str(tmp_path))


def test_withdraw_deletes_facts_and_references_of_that_consent(service):
    scope = _scope("hh_a")
    service.facts_collection.upsert(
        ids=["f1"],
        metadatas={"household_id": "hh_a", "consent_reference": "c1"},
        documents=[_fact("c1").model_dump_json()],
    )
    service.applications_collection.upsert(
        ids=["r1"],
        metadatas={"household_id": "hh_a", "consent_reference": "c1"},
        documents=[_reference("c1").model_dump_json()],
    )

    service.withdraw_consent(scope, "c1")

    assert service.facts_collection.get()["ids"] == []
    assert service.applications_collection.get()["ids"] == []


def test_withdraw_keeps_other_consents_and_households(service):
    for fid, hh, ref in [("f1", "hh_a", "c1"), ("f2", "hh_a", "c2"), ("f3", "hh_b", "c1")]:
        service.facts_collection.upsert(
            ids=[fid],
            metadatas={"household_id": hh, "consent_reference": ref},
            documents=[_fact(ref).model_dump_json()],
        )

    service.withdraw_consent(_scope("hh_a"), "c1")

    assert sorted(service.facts_collection.get()["ids"]) == ["f2", "f3"]
