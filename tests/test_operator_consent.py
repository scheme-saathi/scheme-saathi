"""An operator has no standing consent: the person helped agrees for each application, in person.

The agreement is recorded for that one application, names who recorded it, ends with the saved
entry, and is withdrawn when the entry is removed.
"""

from datetime import datetime, timedelta

import pytest

from agents.memory import (
    PER_APPLICATION_CONSENT_PREFIX,
    ApplicationReference,
    MemoryConsent,
    MemoryScope,
    remove_application,
)
from agents.memory_service import HouseholdAllowlist, InMemoryMemoryService
from app.memory_runtime import forget_memory
from graph.memory_nodes import MemoryContext, save_application_reference

ALLOWLIST = HouseholdAllowlist.from_policy_file()
OPERATOR = MemoryScope(actor_id="op-1", household_id="operator:op-1", actor_role="operator")
OTHER_OPERATOR = MemoryScope(actor_id="op-2", household_id="operator:op-2", actor_role="operator")
CITIZEN = MemoryScope(actor_id="user-1", household_id="hh1", actor_role="citizen")


@pytest.fixture(params=["memory", "chroma"])
def service(request, tmp_path):
    if request.param == "memory":
        return InMemoryMemoryService(ALLOWLIST)
    pytest.importorskip("chromadb")
    from agents.chromadb_memory_service import ChromaDBMemoryService

    return ChromaDBMemoryService(persist_directory=str(tmp_path), allowlist=ALLOWLIST)


def submit(service, application_id, scope=OPERATOR, agreed=True, relation="neighbour"):
    return save_application_reference(
        MemoryContext(service, scope), "C01", application_id, "other", relation, citizen_agreed=agreed
    )


def saved(service, scope=OPERATOR):
    return {r.application_id: r for r in service.read_application_references(scope)}


def blanket(service, scope=OPERATOR, reference="old-blanket"):
    now = datetime.utcnow()
    service.record_consent(
        scope,
        MemoryConsent(
            purpose="application_references",
            granted=True,
            notice_version="1",
            decided_at=now,
            expires_at=now + timedelta(days=60),
            consent_reference=reference,
            obtained_via="in_person",
            recorded_by=scope.actor_id,
        ),
    )


def test_without_the_persons_agreement_nothing_is_saved_and_no_agreement_is_recorded(service):
    assert submit(service, "A1", agreed=False) is False
    assert saved(service) == {}
    assert service.active_consent(OPERATOR, "application_references") is None


def test_with_the_agreement_the_application_is_saved_under_an_in_person_agreement_for_it_alone(service):
    assert submit(service, "A1") is True

    reference = saved(service)["A1"]
    consent = service.active_consent(OPERATOR, "application_references")
    assert reference.consent_reference == consent.consent_reference
    assert consent.consent_reference.startswith(PER_APPLICATION_CONSENT_PREFIX)
    assert (consent.obtained_via, consent.recorded_by) == ("in_person", "op-1")
    assert reference.subject == "other" and reference.submitted_by == "op-1"
    assert abs(consent.expires_at - reference.expires_at) < timedelta(seconds=1)
    assert reference.expires_at - reference.submitted_at == timedelta(days=ALLOWLIST.application_reference_expiry_days)


def test_every_agreed_application_has_its_own_agreement(service):
    submit(service, "A1")
    submit(service, "A2")
    refs = saved(service)
    assert refs["A1"].consent_reference != refs["A2"].consent_reference


def test_a_standing_consent_from_before_does_not_let_an_unagreed_application_be_saved(service):
    blanket(service)
    assert submit(service, "A1", agreed=False) is False
    assert saved(service) == {}


def test_removing_one_application_withdraws_only_its_own_agreement(service):
    submit(service, "A1")
    submit(service, "A2")

    assert remove_application(service, OPERATOR, "A1") is True

    assert set(saved(service)) == {"A2"}
    assert remove_application(service, OPERATOR, "A1") is False


def test_removing_an_application_under_a_standing_consent_leaves_the_others_alone(service):
    blanket(service)
    now = datetime.utcnow()

    for application_id in ("OLD-1", "OLD-2"):
        service.save_application_reference(
            OPERATOR,
            ApplicationReference(
                scheme_id="C01",
                application_id=application_id,
                submitted_at=now,
                expires_at=now + timedelta(days=90),
                consent_reference="old-blanket",
                subject="other",
                relation="neighbour",
            ),
        )

    assert remove_application(service, OPERATOR, "OLD-1") is True

    assert set(saved(service)) == {"OLD-2"}  # withdrawing the shared agreement would have deleted this too


def test_a_citizens_removal_never_withdraws_their_own_consent(service):
    now = datetime.utcnow()
    service.record_consent(
        CITIZEN,
        MemoryConsent(
            purpose="application_references",
            granted=True,
            notice_version="1",
            decided_at=now,
            expires_at=now + timedelta(days=60),
            consent_reference="citizen-refs",
        ),
    )
    save_application_reference(MemoryContext(service, CITIZEN), "C01", "C1", "self", None)
    save_application_reference(MemoryContext(service, CITIZEN), "C01", "C2", "self", None)

    assert remove_application(service, CITIZEN, "C1") is True

    assert set(saved(service, CITIZEN)) == {"C2"}
    assert service.active_consent(CITIZEN, "application_references").consent_reference == "citizen-refs"


def test_a_failure_saving_leaves_no_agreement_behind(service, monkeypatch):
    def broken(scope, reference):
        raise RuntimeError("down")

    monkeypatch.setattr(service, "save_application_reference", broken)
    with pytest.raises(RuntimeError):
        submit(service, "A1")
    assert service.active_consent(OPERATOR, "application_references") is None


def test_one_operators_agreements_and_applications_are_invisible_to_another(service):
    submit(service, "A1")
    assert saved(service, OTHER_OPERATOR) == {}
    assert service.active_consent(OTHER_OPERATOR, "application_references") is None
    assert remove_application(service, OTHER_OPERATOR, "A1") is False
    assert set(saved(service)) == {"A1"}


def test_forgetting_clears_every_agreement_and_application_of_the_operator_only(service):
    submit(service, "A1")
    submit(service, "A2")
    submit(service, "B1", scope=OTHER_OPERATOR)
    blanket(service)

    forget_memory(service, OPERATOR)

    assert saved(service) == {}
    assert service.active_consent(OPERATOR, "application_references") is None
    assert set(saved(service, OTHER_OPERATOR)) == {"B1"}
