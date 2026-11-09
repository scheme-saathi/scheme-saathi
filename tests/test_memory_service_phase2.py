"""Memory service additions for the workflow, the run-config helpers and the intake agent's subject."""

from datetime import datetime, timedelta

import pytest
from langchain_core.runnables import RunnableLambda

from agents.intake import IntakeAgent
from agents.memory import ApplicationReference, MemoryConsent, MemoryFact, MemoryScope, clean_relation
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


def _reference(application_id="APP-1", reference="r1", **changes):
    now = datetime.utcnow()
    return ApplicationReference(
        **{
            "scheme_id": "C01",
            "application_id": application_id,
            "submitted_at": now,
            "expires_at": now + timedelta(days=90),
            "consent_reference": reference,
            **changes,
        }
    )


def test_listing_facts_shows_stored_consented_facts_including_those_due_again(service, monkeypatch):
    service.record_consent(CITIZEN, _consent("c1", days=60))
    service.save_confirmed_fact(CITIZEN, _fact("age", 34))
    service.save_confirmed_fact(CITIZEN, _fact("state_code", "KA"))
    assert [f.field for f in service.list_facts(CITIZEN)] == ["age", "state_code"]

    later = datetime.utcnow() + timedelta(days=40)  # age is past reconfirm_by but not expired
    from agents import memory_service as module

    monkeypatch.setattr(module, "utc_now", lambda: later)
    if hasattr(service, "facts_collection"):
        from agents import chromadb_memory_service

        monkeypatch.setattr(chromadb_memory_service, "utc_now", lambda: later)
    assert [f.field for f in service.list_facts(CITIZEN)] == ["age", "state_code"]
    assert service.read_facts(CITIZEN, ["age"]) == {}  # no longer used for eligibility


def test_listing_facts_hides_expired_unconsented_and_other_households_facts(service):
    service.record_consent(CITIZEN, _consent("c1", days=60))
    service.save_confirmed_fact(CITIZEN, _fact("age", 34))
    other = MemoryScope(actor_id="u2", household_id="hh2", actor_role="citizen")
    assert service.list_facts(other) == []
    service.withdraw_consent(CITIZEN, "c1")
    assert service.list_facts(CITIZEN) == []


def test_one_fact_can_be_deleted_and_only_that_one(service):
    service.record_consent(CITIZEN, _consent("c1", days=60))
    service.save_confirmed_fact(CITIZEN, _fact("age", 34))
    service.save_confirmed_fact(CITIZEN, _fact("state_code", "KA"))
    other = MemoryScope(actor_id="u2", household_id="hh2", actor_role="citizen")

    assert service.delete_fact(other, "age") is False
    assert service.delete_fact(CITIZEN, "age") is True
    assert service.delete_fact(CITIZEN, "age") is False
    assert [f.field for f in service.list_facts(CITIZEN)] == ["state_code"]


def test_every_older_value_of_a_deleted_fact_goes_with_it(service):
    service.record_consent(CITIZEN, _consent("c1", days=60))
    service.save_confirmed_fact(CITIZEN, _fact("age", 33, confirmed_days_ago=2))
    service.save_confirmed_fact(CITIZEN, _fact("age", 34))
    service.delete_fact(CITIZEN, "age")
    assert service.read_facts(CITIZEN, ["age"]) == {}
    if isinstance(service, InMemoryMemoryService):
        assert service.facts == {}


def test_operators_cannot_delete_a_households_facts(service):
    service.record_consent(CITIZEN, _consent("c1", days=60))
    service.save_confirmed_fact(CITIZEN, _fact("age", 34))
    with pytest.raises(ValueError, match="Operators cannot"):
        service.delete_fact(OPERATOR, "age")
    assert [f.field for f in service.list_facts(CITIZEN)] == ["age"]


def test_one_application_can_be_removed_from_the_owners_list_only(service):
    service.record_consent(CITIZEN, _consent("r1", purpose="application_references", days=60))
    service.record_consent(OPERATOR, _consent("op", purpose="application_references", days=60))
    service.save_application_reference(CITIZEN, _reference("APP-1", "r1"))
    service.save_application_reference(CITIZEN, _reference("APP-2", "r1"))
    service.save_application_reference(OPERATOR, _reference("APP-1", "op", subject="other"))

    assert service.delete_application_reference(CITIZEN, "APP-1") is True
    assert service.delete_application_reference(CITIZEN, "APP-1") is False
    assert [r.application_id for r in service.read_application_references(CITIZEN)] == ["APP-2"]
    # the operator's entry for the same application number is a separate record
    assert [r.application_id for r in service.read_application_references(OPERATOR)] == ["APP-1"]
    other = MemoryScope(actor_id="u2", household_id="hh2", actor_role="citizen")
    assert service.delete_application_reference(other, "APP-2") is False


def test_cleanup_runs_now_and_then_on_every_interval():
    import threading

    from app.memory_runtime import MemoryCleanup

    done = threading.Event()
    calls = []

    class Service:
        def purge_expired(self):
            calls.append(1)
            if len(calls) >= 3:
                done.set()
            return 0

    cleanup = MemoryCleanup(Service(), interval=0.01)
    assert done.wait(5)
    cleanup.stop()
    assert len(calls) >= 3


def test_cleanup_keeps_running_after_a_failure():
    import threading

    from app.memory_runtime import MemoryCleanup

    recovered = threading.Event()
    calls = []

    class Service:
        def purge_expired(self):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("storage hiccup")
            recovered.set()
            return 2

    cleanup = MemoryCleanup(Service(), interval=0.01)
    assert recovered.wait(5)
    cleanup.stop()


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
    result = IntakeAgent(model).extract({"request": "No, she is not", "pending_field": "is_widow"}, specs)
    assert result.facts == {"age": 67, "is_widow": False}
    assert (result.subject, result.relation) == ("other", "mother")
