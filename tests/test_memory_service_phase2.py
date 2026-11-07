"""Memory service additions for the workflow, the run-config helpers and the intake agent's subject."""

from datetime import datetime, timedelta

import pytest
from langchain_core.runnables import RunnableLambda

from agents.intake import IntakeAgent
from agents.memory import MemoryConsent, MemoryFact, MemoryScope, clean_relation
from agents.memory_service import HouseholdAllowlist, InMemoryMemoryService
from graph.memory_nodes import memory_config, memory_context
from servers.rule_engine.server import get_field_specs

CITIZEN = MemoryScope(actor_id="u1", household_id="hh1", actor_role="citizen")
OPERATOR = MemoryScope(actor_id="op1", household_id="hh1", actor_role="operator")
ALLOWLIST = HouseholdAllowlist(
    allowed_fields={
        "age": {"type": "number", "retention": {"store": True, "reconfirm_days": 30, "expiry_days": 90}},
        "state_code": {"type": "string"},
    }
)


def _consent(reference="c1", purpose="profile_facts", days=30, decided_ago=0, **changes):
    now = datetime.utcnow()
    return MemoryConsent(
        **{
            "purpose": purpose,
            "granted": True,
            "notice_version": "1",
            "decided_at": now - timedelta(days=decided_ago),
            "expires_at": now + timedelta(days=days),
            "consent_reference": reference,
            **changes,
        }
    )


def _fact(field="age", value=34, confirmed_days_ago=0, reconfirm_days=30, expiry_days=90, reference="c1"):
    confirmed_at = datetime.utcnow() - timedelta(days=confirmed_days_ago)
    return MemoryFact(
        field=field,
        value=value,
        source="citizen_confirmed",
        confirmed_at=confirmed_at,
        reconfirm_by=confirmed_at + timedelta(days=reconfirm_days),
        expires_at=confirmed_at + timedelta(days=expiry_days),
        consent_reference=reference,
    )


@pytest.fixture(params=["memory", "chroma"])
def service(request, tmp_path):
    if request.param == "memory":
        return InMemoryMemoryService(ALLOWLIST)
    pytest.importorskip("chromadb")
    from agents.chromadb_memory_service import ChromaDBMemoryService

    return ChromaDBMemoryService(persist_directory=str(tmp_path), allowlist=ALLOWLIST)


def test_active_consent_is_the_newest_granted_unexpired_one(service):
    assert service.active_consent(CITIZEN, "profile_facts") is None
    service.record_consent(CITIZEN, _consent("old", decided_ago=5))
    service.record_consent(CITIZEN, _consent("new", decided_ago=1))
    service.record_consent(CITIZEN, _consent("refs", purpose="application_references"))
    assert service.active_consent(CITIZEN, "profile_facts").consent_reference == "new"
    assert service.active_consent(CITIZEN, "application_references").consent_reference == "refs"


def test_a_denied_or_withdrawn_consent_is_not_active(service):
    service.record_consent(CITIZEN, _consent("denied", granted=False))
    assert service.active_consent(CITIZEN, "profile_facts") is None
    service.record_consent(CITIZEN, _consent("c1"))
    assert service.active_consent(CITIZEN, "profile_facts").consent_reference == "c1"
    service.withdraw_consent(CITIZEN, "c1")
    assert service.active_consent(CITIZEN, "profile_facts") is None


def test_active_consent_belongs_to_the_owner(service):
    service.record_consent(CITIZEN, _consent("c1", purpose="application_references"))
    other = MemoryScope(actor_id="u2", household_id="hh2", actor_role="citizen")
    assert service.active_consent(other, "application_references") is None
    # an operator's reference consent is a separate list from the household's
    assert service.active_consent(OPERATOR, "application_references") is None
    service.record_consent(OPERATOR, _consent("op", purpose="application_references"))
    assert service.active_consent(OPERATOR, "application_references").consent_reference == "op"
    assert service.active_consent(CITIZEN, "application_references").consent_reference == "c1"


def held_fact(service):
    """The one fact stored, read straight from the backend."""
    if isinstance(service, InMemoryMemoryService):
        [held] = service.facts.values()
        return held
    import json

    [doc] = service.facts_collection.get()["documents"]
    return MemoryFact(**json.loads(doc))


def test_reconfirming_moves_the_reconfirm_date_and_keeps_the_expiry(service):
    service.record_consent(CITIZEN, _consent("c1", days=60))
    fact = _fact(confirmed_days_ago=20)
    service.save_confirmed_fact(CITIZEN, fact)

    assert service.reconfirm_facts(CITIZEN, ["age"]) == ["age"]

    assert service.read_facts(CITIZEN, ["age"]) == {"age": 34}
    held = held_fact(service)  # one record: reconfirming does not add a second fact
    assert held.expires_at == fact.expires_at
    assert held.reconfirm_by > fact.reconfirm_by
    assert held.reconfirm_by - held.confirmed_at == timedelta(days=30)


def test_reconfirm_never_goes_past_the_original_expiry(service):
    service.record_consent(CITIZEN, _consent("c1", days=60))
    fact = _fact(confirmed_days_ago=25, reconfirm_days=30, expiry_days=40)  # expires in 15 days
    service.save_confirmed_fact(CITIZEN, fact)

    assert service.reconfirm_facts(CITIZEN, ["age"]) == ["age"]

    held = held_fact(service)
    assert held.expires_at == fact.expires_at
    assert held.reconfirm_by == fact.expires_at  # a 30 day period would have run past it


def test_reconfirm_skips_missing_unconsented_and_unpolicied_facts(service):
    service.record_consent(CITIZEN, _consent("c1", days=60))
    service.save_confirmed_fact(CITIZEN, _fact("state_code", "KA"))  # the policy sets no reconfirm period
    service.save_confirmed_fact(CITIZEN, _fact("age"))
    assert service.reconfirm_facts(CITIZEN, ["state_code", "nothing"]) == []
    service.withdraw_consent(CITIZEN, "c1")
    assert service.reconfirm_facts(CITIZEN, ["age"]) == []


def test_reconfirm_does_not_reach_another_households_facts(service):
    service.record_consent(CITIZEN, _consent("c1", days=60))
    service.save_confirmed_fact(CITIZEN, _fact())
    other = MemoryScope(actor_id="u2", household_id="hh2", actor_role="citizen")
    assert service.reconfirm_facts(other, ["age"]) == []


def test_the_application_reference_period_comes_from_the_policy():
    assert HouseholdAllowlist().application_reference_expiry_days == 90
    assert HouseholdAllowlist.from_policy_file().application_reference_expiry_days == 90


def test_clean_relation_keeps_a_short_word_and_drops_anything_else():
    assert clean_relation(" Mother ") == "mother"
    assert clean_relation("माँ") == "माँ"
    for bad in ["Ramesh 9876543210", "12", "", None, 7, "x" * 41]:
        assert clean_relation(bad) is None


def test_the_run_config_carries_a_scope_and_only_a_valid_one(service):
    config = {"configurable": {"thread_id": "t", **memory_config(CITIZEN)}}
    ctx = memory_context(service, config)
    assert ctx.scope == CITIZEN and ctx.allowlist is service.allowlist
    assert memory_context(None, config) is None
    assert memory_context(service, {"configurable": {"thread_id": "t"}}) is None
    assert memory_context(service, None) is None
    bad_role = {"configurable": {**memory_config(CITIZEN), "memory_role": "admin"}}
    assert memory_context(service, bad_role) is None
    no_household = {"configurable": {**memory_config(CITIZEN), "memory_household_id": ""}}
    assert memory_context(service, no_household) is None


class FakeModel:
    def __init__(self, *replies):
        self.replies = list(replies)

    def with_structured_output(self, schema):
        return RunnableLambda(lambda _: self.replies.pop(0))


@pytest.fixture
def specs():
    return get_field_specs(["SYNTH-PENSION-001"])["data"]


def test_the_intake_agent_reports_whose_facts_these_are(specs):
    mine = IntakeAgent(FakeModel({"facts": {"age": 67}, "subject": "self", "relation": None}))
    result = mine.extract({"request": "I am 67"}, specs)
    assert (result.subject, result.relation) == ("self", None)

    hers = IntakeAgent(FakeModel({"facts": {"age": 67}, "subject": "other", "relation": "mother"}))
    result = hers.extract({"request": "My mother is 67"}, specs)
    assert (result.subject, result.relation) == ("other", "mother")


@pytest.mark.parametrize("reply", [{"facts": {"age": 67}}, {"facts": {"age": 67}, "subject": "maybe"}])
def test_a_missing_or_unrecognised_subject_counts_as_someone_else(specs, reply):
    result = IntakeAgent(FakeModel(reply)).extract({"request": "67"}, specs)
    assert result.subject == "other"


def test_the_subject_survives_the_narrow_second_read_of_a_pending_field(specs):
    model = FakeModel(
        {"facts": {"age": 67}, "reply_kind": "dont_know", "subject": "other", "relation": "mother"},
        {"facts": {"is_widow": False}, "reply_kind": "answer", "subject": "self", "relation": None},
    )
    result = IntakeAgent(model).extract({"request": "No", "pending_field": "is_widow"}, specs)
    assert result.facts == {"age": 67, "is_widow": False}
    assert (result.subject, result.relation) == ("other", "mother")
