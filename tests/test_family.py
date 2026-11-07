"""Family members: which relations count, grouping saved applications, renaming and deleting."""

from datetime import datetime, timedelta

import pytest

from agents.family import (
    FAMILY_RELATIONS,
    clean_nickname,
    delete_family_member,
    family_members,
    family_relation,
    relation_in_text,
    rename_family_member,
)
from agents.memory import ApplicationReference, MemoryConsent, MemoryScope
from agents.memory_service import HouseholdAllowlist, InMemoryMemoryService
from graph.memory_nodes import MemoryContext, save_application_reference

ALLOWLIST = HouseholdAllowlist.from_policy_file()
CITIZEN = MemoryScope(actor_id="user-1", household_id="hh1", actor_role="citizen")
OTHER_HOUSEHOLD = MemoryScope(actor_id="user-2", household_id="hh2", actor_role="citizen")
OPERATOR = MemoryScope(actor_id="op-1", household_id="operator:op-1", actor_role="operator")


@pytest.fixture(params=["memory", "chroma"])
def service(request, tmp_path):
    if request.param == "memory":
        return InMemoryMemoryService(ALLOWLIST)
    pytest.importorskip("chromadb")
    from agents.chromadb_memory_service import ChromaDBMemoryService

    return ChromaDBMemoryService(persist_directory=str(tmp_path), allowlist=ALLOWLIST)


def consent(service, scope=CITIZEN):
    now = datetime.utcnow()
    service.record_consent(
        scope,
        MemoryConsent(
            purpose="application_references",
            granted=True,
            notice_version="1",
            decided_at=now,
            expires_at=now + timedelta(days=60),
            consent_reference=f"refs-{scope.household_id}",
            obtained_via="in_person" if scope.actor_role == "operator" else "self_service",
            recorded_by=scope.actor_id if scope.actor_role == "operator" else None,
        ),
    )


def save(service, application_id, relation=None, subject="other", scope=CITIZEN, nickname=None, days_ago=0):
    submitted = datetime.utcnow() - timedelta(days=days_ago)
    service.save_application_reference(
        scope,
        ApplicationReference(
            scheme_id="C01",
            application_id=application_id,
            submitted_at=submitted,
            expires_at=submitted + timedelta(days=90),
            consent_reference=f"refs-{scope.household_id}",
            subject=subject,
            relation=relation,
            nickname=nickname,
            submitted_by=scope.actor_id,
        ),
    )


def ids(service, scope=CITIZEN):
    return {r.application_id for r in service.read_application_references(scope)}


# Which relations are family


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("mother", "mother"),
        ("Mother", "mother"),
        (" mom ", "mother"),
        ("mother's", "mother"),
        ("माँ", "mother"),
        ("आई", "mother"),
        ("वडील", "father"),
        ("दादी", "grandmother"),
        ("आजोबा", "grandfather"),
        ("बेटी", "daughter"),
        ("मुलगा", "son"),
        ("बायको", "wife"),
        ("पति", "husband"),
    ],
)
def test_family_relations_are_recognised_in_english_hindi_and_marathi(word, expected):
    assert family_relation(word) == expected


@pytest.mark.parametrize("word", ["neighbour", "friend", "uncle", "", "   ", None, 7, "mothers"])
def test_anyone_else_is_not_family(word):
    assert family_relation(word) is None


def test_the_family_is_exactly_the_agreed_relations():
    assert set(FAMILY_RELATIONS) == {
        "mother", "father", "grandmother", "grandfather", "son", "daughter", "wife", "husband"
    }


def test_a_relation_is_found_in_a_message():
    assert relation_in_text("Where is my mother's application?") == "mother"
    assert relation_in_text("status for dad, please.") == "father"
    assert relation_in_text("मेरी माँ के आवेदन की स्थिति") == "mother"
    assert relation_in_text("Track the status of my case") is None
    assert relation_in_text("the reason is unclear") is None  # "son" inside a word is not a relation


# Nicknames


def test_a_nickname_is_letters_only_and_blank_means_none():
    assert clean_nickname("Amma") == "Amma"
    assert clean_nickname("  ") is None and clean_nickname(None) is None
    for bad in ("Amma 9876543210", "1234", "a@b", "x" * 41):
        with pytest.raises(ValueError):
            clean_nickname(bad)
    with pytest.raises(ValueError):
        clean_nickname(5)


def test_a_reference_cannot_hold_a_nickname_without_a_relation_or_with_digits():
    now = datetime.utcnow()
    common = dict(
        scheme_id="C01", application_id="A", submitted_at=now, expires_at=now + timedelta(days=1), consent_reference="c"
    )
    with pytest.raises(ValueError):
        ApplicationReference(**common, subject="other", nickname="Amma")
    with pytest.raises(ValueError):
        ApplicationReference(**common, subject="other", relation="mother", nickname="Amma9")


# Grouping, renaming and deleting


def test_family_applications_are_grouped_by_member_newest_first(service):
    consent(service)
    save(service, "A1", "mother", days_ago=5)
    save(service, "A2", "mother", days_ago=1)
    save(service, "A3", "son", days_ago=0)
    save(service, "A4", "neighbour")
    save(service, "A5", subject="self")

    members = family_members(service.read_application_references(CITIZEN))

    assert [m.relation for m in members] == ["son", "mother"]
    assert [a.application_id for a in members[1].applications] == ["A2", "A1"]


def test_a_member_is_renamed_for_every_one_of_their_applications(service):
    consent(service)
    save(service, "A1", "mother")
    save(service, "A2", "mother")
    save(service, "A3", "son")

    assert rename_family_member(service, CITIZEN, "mother", "Amma") == 2

    by_relation = {m.relation: m.nickname for m in family_members(service.read_application_references(CITIZEN))}
    assert by_relation == {"mother": "Amma", "son": None}
    assert rename_family_member(service, CITIZEN, "mother", "") == 2
    assert {m.relation: m.nickname for m in family_members(service.read_application_references(CITIZEN))}["mother"] is None


def test_renaming_with_an_invalid_nickname_changes_nothing(service):
    consent(service)
    save(service, "A1", "mother", nickname="Amma")
    with pytest.raises(ValueError):
        rename_family_member(service, CITIZEN, "mother", "Amma 12345")
    assert family_members(service.read_application_references(CITIZEN))[0].nickname == "Amma"


def test_renaming_a_member_who_is_not_saved_changes_nothing(service):
    consent(service)
    save(service, "A1", "mother")
    assert rename_family_member(service, CITIZEN, "father", "Papa") == 0


def test_deleting_a_member_removes_only_their_applications(service):
    consent(service)
    save(service, "A1", "mother")
    save(service, "A2", "mother")
    save(service, "A3", "son")
    save(service, "A4", "neighbour")
    save(service, "A5", subject="self")

    assert delete_family_member(service, CITIZEN, "mother") == 2

    assert ids(service) == {"A3", "A4", "A5"}
    assert delete_family_member(service, CITIZEN, "mother") == 0


def test_one_households_family_is_invisible_to_another(service):
    consent(service)
    consent(service, OTHER_HOUSEHOLD)
    save(service, "A1", "mother")

    assert family_members(service.read_application_references(OTHER_HOUSEHOLD)) == []
    assert delete_family_member(service, OTHER_HOUSEHOLD, "mother") == 0
    assert rename_family_member(service, OTHER_HOUSEHOLD, "mother", "Amma") == 0
    assert ids(service) == {"A1"}


def test_an_operator_has_family_members_under_their_own_account(service):
    consent(service)
    consent(service, OPERATOR)
    save(service, "A1", "mother")
    save(service, "OP1", "mother", scope=OPERATOR)

    assert delete_family_member(service, OPERATOR, "mother") == 1
    assert ids(service) == {"A1"} and ids(service, OPERATOR) == set()


def test_a_member_goes_when_their_last_application_is_removed(service):
    consent(service)
    save(service, "A1", "mother")
    save(service, "A2", "mother")
    save(service, "A3", "son")

    service.delete_application_reference(CITIZEN, "A1")
    assert {m.relation for m in family_members(service.read_application_references(CITIZEN))} == {"mother", "son"}

    service.delete_application_reference(CITIZEN, "A2")
    assert {m.relation for m in family_members(service.read_application_references(CITIZEN))} == {"son"}


# Saving through the workflow helper


def context(service, scope=CITIZEN):
    return MemoryContext(service, scope)


def test_a_new_application_is_saved_under_the_english_relation(service):
    consent(service)
    save_application_reference(context(service), "C01", "A1", "other", "माँ")
    [reference] = service.read_application_references(CITIZEN)
    assert (reference.subject, reference.relation) == ("other", "mother")


def test_a_returning_family_member_keeps_their_nickname(service):
    consent(service)
    save_application_reference(context(service), "C01", "A1", "other", "mother")
    rename_family_member(service, CITIZEN, "mother", "Amma")

    save_application_reference(context(service), "C02", "A2", "other", "mom")

    assert {r.application_id: r.nickname for r in service.read_application_references(CITIZEN)} == {
        "A1": "Amma",
        "A2": "Amma",
    }


def test_a_person_who_is_not_family_gets_no_nickname_and_stays_in_others(service):
    consent(service)
    save_application_reference(context(service), "C01", "A1", "other", "neighbour")
    [reference] = service.read_application_references(CITIZEN)
    assert (reference.relation, reference.nickname) == ("neighbour", None)
    assert family_members([reference]) == []


def test_an_operator_helping_a_family_relation_gets_a_member_under_their_own_account(service):
    consent(service, OPERATOR)
    save_application_reference(context(service, OPERATOR), "C01", "OP1", "self", "mother")
    [member] = family_members(service.read_application_references(OPERATOR))
    assert member.relation == "mother"


def test_without_consent_nothing_is_saved_and_no_member_exists(service):
    assert save_application_reference(context(service), "C01", "A1", "other", "mother") is False
    assert family_members(service.read_application_references(CITIZEN)) == []
