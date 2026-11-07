"""Memory in the agent workflow: prefill after intake, remember after confirmation and submission."""

from datetime import datetime, timedelta

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from agents.contracts import (
    ApplicationDraft,
    DocumentCheckResult,
    EligibilityNarrative,
    IntakeExtraction,
    IntakeQuestion,
    SupervisorPlan,
)
from agents.eligibility import EligibilityAgent
from agents.memory import ApplicationReference, MemoryConsent, MemoryFact, MemoryScope
from agents.memory_service import HouseholdAllowlist, InMemoryMemoryService
from agents.supervisor import InputValidator, OutputValidator, UnifiedRouter
from graph import tools
from graph.agent_workflow import AgentSet, build_agent_graph
from graph.memory_nodes import memory_config
from graph.workflow import application_hash

PENSION = "SYNTH-PENSION-001"
WIDOW_67 = {"age": 67, "income": 100000, "is_widow": True}
CITIZEN = MemoryScope(actor_id="user-1", household_id="hh1", actor_role="citizen")
OPERATOR = MemoryScope(actor_id="op-1", household_id="hh1", actor_role="operator")

ALLOWLIST = HouseholdAllowlist(
    allowed_fields={
        "age": {"type": "number", "retention": {"store": True, "reconfirm_days": 30, "expiry_days": 90}},
        "is_widow": {"type": "bool", "retention": {"store": True, "reconfirm_days": 90, "expiry_days": 180}},
        "income": {"type": "number", "retention": {"store": True, "reconfirm_days": 30, "expiry_days": 30}},
    }
)


class StubAgent:
    def __init__(self, result):
        self.result = result

    def invoke(self, value):
        return self.result


class Supervisor:
    def __init__(self, plan):
        self.plan = plan
        router = UnifiedRouter()
        router.api_available = False
        self.input_validator = InputValidator(router=router)
        self.output_validator = OutputValidator()

    def validate_input(self, request, actor_id=None, is_reply=False):
        return self.input_validator.validate_request(request, actor_id, is_reply)

    def validate_output(self, response, agent_name, language):
        return self.output_validator.validate_specialist_output(response, agent_name, language)

    def handle_validation_error(self, result, language):
        return {"user_message": self.output_validator.get_user_friendly_error(result, language)}

    def invoke(self, value):
        return self.plan


class ScriptedIntake:
    def __init__(self, *extractions):
        self.extractions = list(extractions)
        self.ask_calls = []

    def extract(self, value, specs):
        return self.extractions.pop(0)

    def ask(self, value):
        self.ask_calls.append(value)
        return IntakeQuestion(field=value.field, question=f"Q:{value.field}")


class Conversation:
    def __init__(self, intake, memory=None, scope=CITIZEN, next_agent="eligibility", application=None):
        self.intake = intake
        agents = AgentSet(
            intake=intake,
            supervisor=Supervisor(SupervisorPlan(next_agent=next_agent, reason="Check.", language="en")),
            eligibility=EligibilityAgent(model=None),
            document_checker=StubAgent(DocumentCheckResult()),
            application=application
            or StubAgent(ApplicationDraft(scheme_id="s", fields={}, missing_fields=[], review_summary="-")),
        )
        self.graph = build_agent_graph(agents, checkpointer=MemorySaver(), memory=memory)
        self.config = {"configurable": {"thread_id": "t", **(memory_config(scope) if scope else {})}}

    def send(self, message="Can my family get the pension?"):
        return self.graph.invoke({"request": message, "selected_scheme_id": PENSION}, self.config)

    def resume(self, **decision):
        return self.graph.invoke(Command(resume=decision), self.config)

    def state(self):
        return self.graph.get_state(self.config).values

    def approve(self, pending):
        return self.resume(action="approve", payload_hash=pending["payload_hash"])


def memory_service(consent_facts=True, consent_references=False, scope=CITIZEN):
    service = InMemoryMemoryService(ALLOWLIST)
    now = datetime.utcnow()
    for granted, purpose, reference in (
        (consent_facts, "profile_facts", "c-facts"),
        (consent_references, "application_references", "c-refs"),
    ):
        if granted:
            service.record_consent(
                scope,
                MemoryConsent(
                    purpose=purpose,
                    granted=True,
                    notice_version="1",
                    decided_at=now,
                    expires_at=now + timedelta(days=60),
                    consent_reference=reference,
                ),
            )
    return service


def remember(service, facts, confirmed_days_ago=0, scope=CITIZEN):
    confirmed_at = datetime.utcnow() - timedelta(days=confirmed_days_ago)
    for field, value in facts.items():
        policy = ALLOWLIST.allowed_fields[field]["retention"]
        service.save_confirmed_fact(
            scope,
            MemoryFact(
                field=field,
                value=value,
                source="citizen_confirmed",
                confirmed_at=confirmed_at,
                reconfirm_by=confirmed_at + timedelta(days=policy["reconfirm_days"]),
                expires_at=confirmed_at + timedelta(days=policy["expiry_days"]),
                consent_reference="c-facts",
            ),
        )


def stored(service, field):
    """The newest fact held for the field; the in-memory service keeps older ones behind it."""
    return max((f for f in service.facts.values() if f.field == field), key=lambda f: f.confirmed_at)


def test_without_memory_every_fact_is_asked():
    conversation = Conversation(ScriptedIntake(IntakeExtraction()))
    result = conversation.send()
    assert result["pending_field"] == "age"
    assert "remembered_fields" not in conversation.state()


def test_without_a_scope_in_the_run_config_nothing_is_read_or_written():
    service = memory_service()
    remember(service, WIDOW_67)
    conversation = Conversation(ScriptedIntake(IntakeExtraction()), memory=service, scope=None)
    result = conversation.send()
    assert result["pending_field"] == "age"
    assert conversation.state().get("known_facts", {}) == {}


def test_a_returning_citizen_is_not_asked_what_memory_already_holds():
    service = memory_service()
    remember(service, WIDOW_67)
    conversation = Conversation(ScriptedIntake(IntakeExtraction()), memory=service)

    result = conversation.send()

    assert conversation.intake.ask_calls == []
    pending = result["__interrupt__"][0].value
    assert pending["kind"] == "confirm_facts"
    assert pending["facts"] == WIDOW_67
    assert pending["remembered_fields"] == ["age", "income", "is_widow"]
    assert (pending["subject"], pending["relation"]) == ("self", None)


def test_remembered_facts_are_unconfirmed_until_the_person_approves():
    service = memory_service()
    remember(service, WIDOW_67)
    conversation = Conversation(ScriptedIntake(IntakeExtraction()), memory=service)
    conversation.send()

    state = conversation.state()
    assert state.get("confirmed_facts", {}) == {}
    assert state["explanations"] == {}  # no final answer from unconfirmed facts


def test_the_same_conversation_without_memory_asks_a_question():
    service = memory_service()
    remember(service, WIDOW_67)
    with_memory = Conversation(ScriptedIntake(IntakeExtraction()), memory=service)
    without = Conversation(ScriptedIntake(IntakeExtraction()))
    with_memory.send()
    without.send()
    assert (len(with_memory.intake.ask_calls), len(without.intake.ask_calls)) == (0, 1)


def test_only_the_fields_the_schemes_need_are_read(monkeypatch):
    service = memory_service()
    remember(service, WIDOW_67)
    asked = []
    original = service.read_facts
    monkeypatch.setattr(
        service, "read_facts", lambda scope, fields: asked.append(sorted(fields)) or original(scope, fields)
    )
    Conversation(ScriptedIntake(IntakeExtraction()), memory=service).send()
    assert asked == [["age", "income", "is_widow"]]


def test_a_fact_in_the_message_wins_over_the_remembered_one():
    service = memory_service()
    remember(service, WIDOW_67)
    conversation = Conversation(ScriptedIntake(IntakeExtraction(facts={"age": 68})), memory=service)
    pending = conversation.send("I am 68, can I get the pension?")["__interrupt__"][0].value
    assert pending["facts"]["age"] == 68
    assert pending["remembered_fields"] == ["income", "is_widow"]


def test_facts_past_their_dates_are_asked_again(monkeypatch):
    service = memory_service()
    remember(service, WIDOW_67)
    later = datetime.utcnow() + timedelta(days=31)  # age and income are past reconfirm_by
    monkeypatch.setattr("agents.memory_service.utc_now", lambda: later)
    conversation = Conversation(ScriptedIntake(IntakeExtraction()), memory=service)
    result = conversation.send()
    assert result["pending_field"] == "age"
    assert conversation.state()["remembered_fields"] == ["is_widow"]


def test_without_consent_nothing_is_read_or_saved():
    service = memory_service(consent_facts=False)
    conversation = Conversation(ScriptedIntake(IntakeExtraction(facts=WIDOW_67)), memory=service)
    pending = conversation.send()["__interrupt__"][0].value
    assert pending["remembered_fields"] == []
    result = conversation.approve(pending)
    assert result["status"] == "eligibility_checked"
    assert service.facts == {}


def test_confirmed_facts_are_remembered_with_the_policy_windows():
    service = memory_service()
    conversation = Conversation(ScriptedIntake(IntakeExtraction(facts=WIDOW_67)), memory=service)
    pending = conversation.send()["__interrupt__"][0].value
    assert service.facts == {}  # nothing is remembered before the person confirms

    result = conversation.approve(pending)

    assert result["memory_saved"] == ["age", "income", "is_widow"]
    assert service.read_facts(CITIZEN, []) == WIDOW_67
    age = stored(service, "age")
    assert age.source == "citizen_confirmed"
    assert age.reconfirm_by - age.confirmed_at == timedelta(days=30)
    assert age.expires_at - age.confirmed_at == timedelta(days=90)


def test_an_unchanged_confirmed_fact_only_moves_its_reconfirm_date():
    service = memory_service()
    remember(service, WIDOW_67, confirmed_days_ago=20)
    before = {field: stored(service, field) for field in WIDOW_67}
    conversation = Conversation(ScriptedIntake(IntakeExtraction()), memory=service)
    pending = conversation.send()["__interrupt__"][0].value

    result = conversation.approve(pending)

    assert result["memory_saved"] == ["age", "income", "is_widow"]
    assert len(service.facts) == 3  # no duplicates
    for field in WIDOW_67:
        after = stored(service, field)
        assert after.expires_at == before[field].expires_at  # retention is not extended
        assert after.reconfirm_by >= before[field].reconfirm_by
    assert stored(service, "age").reconfirm_by > before["age"].reconfirm_by
    assert stored(service, "age").confirmed_at > before["age"].confirmed_at


def test_a_changed_fact_replaces_the_old_one_with_a_fresh_window():
    service = memory_service()
    remember(service, WIDOW_67, confirmed_days_ago=20)
    old_expiry = stored(service, "age").expires_at
    conversation = Conversation(ScriptedIntake(IntakeExtraction()), memory=service)
    conversation.send()

    result = conversation.resume(action="edit", changes={"age": 68})

    assert result["confirmed_facts"]["age"] == 68
    assert service.read_facts(CITIZEN, ["age"]) == {"age": 68}
    assert stored(service, "age").expires_at > old_expiry


def test_confirming_twice_in_one_thread_does_not_extend_retention():
    service = memory_service()
    conversation = Conversation(ScriptedIntake(IntakeExtraction(facts=WIDOW_67), IntakeExtraction(facts={"age": 68})), memory=service)
    pending = conversation.send()["__interrupt__"][0].value
    conversation.approve(pending)
    first = stored(service, "income").expires_at

    again = conversation.send("Sorry, my age is 68")["__interrupt__"][0].value
    conversation.approve(again)

    assert stored(service, "age").value == 68
    assert stored(service, "income").expires_at == first


def test_facts_the_policy_does_not_allow_are_not_remembered_and_do_not_fail_the_run():
    service = memory_service()
    facts = {**WIDOW_67, "caste": "x"}
    conversation = Conversation(ScriptedIntake(IntakeExtraction(facts=facts)), memory=service)
    pending = conversation.send()["__interrupt__"][0].value
    assert pending["facts"] == facts
    result = conversation.approve(pending)
    assert result["status"] == "eligibility_checked"
    assert result["memory_saved"] == ["age", "income", "is_widow"]
    assert service.read_facts(CITIZEN, []) == WIDOW_67


def test_facts_about_someone_else_are_neither_prefilled_nor_saved():
    service = memory_service()
    remember(service, {"age": 30})
    intake = ScriptedIntake(
        IntakeExtraction(facts={"is_widow": True, "income": 100000}, subject="other", relation="mother")
    )
    conversation = Conversation(intake, memory=service)

    result = conversation.send("My mother is a widow with income 1 lakh")

    assert result["pending_field"] == "age"  # the citizen's own age is not used for the mother
    assert conversation.state().get("remembered_fields", []) == []
    assert conversation.state()["known_facts"] == {"is_widow": True, "income": 100000}

    answered = Conversation(
        ScriptedIntake(IntakeExtraction(facts={**WIDOW_67}, subject="other", relation="mother")),
        memory=service,
    )
    pending = answered.send("My mother is 67, a widow, income 1 lakh")["__interrupt__"][0].value
    assert (pending["subject"], pending["relation"]) == ("other", "mother")
    answered.approve(pending)
    assert service.read_facts(CITIZEN, []) == {"age": 30}  # still only the citizen's own fact


def test_an_unclear_relation_label_is_dropped_but_the_subject_stays_other():
    service = memory_service()
    intake = ScriptedIntake(IntakeExtraction(facts=WIDOW_67, subject="other", relation="Ramesh 9876543210"))
    conversation = Conversation(intake, memory=service)
    pending = conversation.send()["__interrupt__"][0].value
    assert (pending["subject"], pending["relation"]) == ("other", None)
    conversation.approve(pending)
    assert service.facts == {}


def test_switching_to_another_person_clears_the_first_persons_facts():
    service = memory_service()
    remember(service, {"age": 70})
    intake = ScriptedIntake(
        IntakeExtraction(),
        IntakeExtraction(facts={"is_widow": True, "income": 50000}, subject="other", relation="neighbour"),
    )
    conversation = Conversation(intake, memory=service)
    first = conversation.send("Can I get the pension?")
    assert conversation.state()["known_facts"] == {"age": 70}
    assert first["pending_field"] == "income"

    # A new request rather than a reply to the pending question.
    conversation.graph.update_state(conversation.config, {"pending_field": None})
    conversation.send("My neighbour is a widow and earns 50000 a year")

    state = conversation.state()
    assert state["known_facts"] == {"is_widow": True, "income": 50000}  # nothing of the first person remains
    assert (state["subject"], state["relation"]) == ("other", "neighbour")
    assert state["remembered_fields"] == []


def test_a_reply_that_names_a_different_relation_with_facts_switches_person():
    service = memory_service()
    intake = ScriptedIntake(
        IntakeExtraction(facts={"age": 67}, subject="other", relation="mother"),
        IntakeExtraction(facts={"age": 40, "is_widow": True}, subject="other", relation="neighbour"),
    )
    conversation = Conversation(intake, memory=service)
    assert conversation.send("My mother is 67")["pending_field"] == "income"

    conversation.send("Actually my neighbour is 40 and a widow")

    state = conversation.state()
    assert state["known_facts"] == {"age": 40, "is_widow": True}
    assert state["relation"] == "neighbour"


def test_a_bare_reply_never_changes_the_person():
    service = memory_service()
    intake = ScriptedIntake(
        IntakeExtraction(facts={"age": 67}, subject="other", relation="mother"),
        IntakeExtraction(facts={"income": 100000}, subject="self"),
    )
    conversation = Conversation(intake, memory=service)
    conversation.send("My mother is 67")
    conversation.send("1 lakh a year")
    state = conversation.state()
    assert (state["subject"], state["relation"]) == ("other", "mother")
    assert state["known_facts"] == {"age": 67, "income": 100000}


def test_operators_neither_load_nor_save_profile_facts():
    service = memory_service(scope=OPERATOR)
    remember(service, {"age": 30}, scope=OPERATOR)
    conversation = Conversation(
        ScriptedIntake(IntakeExtraction(facts=WIDOW_67)), memory=service, scope=OPERATOR
    )
    pending = conversation.send()["__interrupt__"][0].value
    assert pending["remembered_fields"] == []
    conversation.approve(pending)
    assert service.read_facts(OPERATOR, []) == {"age": 30}  # unchanged by the run


def test_a_memory_failure_does_not_stop_the_run(monkeypatch):
    service = memory_service()
    monkeypatch.setattr(service, "read_facts", lambda scope, fields: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(service, "active_consent", lambda scope, purpose: (_ for _ in ()).throw(RuntimeError("down")))
    conversation = Conversation(ScriptedIntake(IntakeExtraction(facts=WIDOW_67)), memory=service)
    pending = conversation.send()["__interrupt__"][0].value
    result = conversation.approve(pending)
    assert result["status"] == "eligibility_checked"


def test_another_households_facts_are_never_loaded():
    service = memory_service()
    remember(service, WIDOW_67)
    other = MemoryScope(actor_id="user-2", household_id="hh2", actor_role="citizen")
    conversation = Conversation(ScriptedIntake(IntakeExtraction()), memory=service, scope=other)
    result = conversation.send()
    assert result["pending_field"] == "age"
    assert conversation.state().get("remembered_fields", []) == []


# Submission: the application reference


def application_conversation(service, scope=CITIZEN):
    facts = {"age": 30, "has_individual_bank_or_post_office_account": True}
    draft = ApplicationDraft(scheme_id="C01", fields=facts, missing_fields=[], review_summary="Ready.")
    conversation = Conversation(
        ScriptedIntake(IntakeExtraction()),
        memory=service,
        scope=scope,
        next_agent="application",
        application=StubAgent(draft),
    )
    return conversation, facts


def run_to_submission(monkeypatch, service, scope=CITIZEN, subject="self", relation=None):
    monkeypatch.setattr(
        "graph.agent_workflow.tools.submit_application",
        lambda form, application_id=None, write_capability=None, household_id=None: {
            "application_id": "APP-1",
            "status": "submitted (mock)",
        },
    )
    conversation, facts = application_conversation(service, scope)
    seeded = {
        "request": "Help me apply",
        "selected_scheme_id": "C01",
        "known_facts": facts,
        "confirmed_facts": facts,
        "subject": subject,
        "relation": relation,
        "deterministic_evaluation": {
            "verdict": "eligible",
            "reason": "All reviewed conditions are satisfied.",
            "missing_fields": [],
            "unresolved_fields": [],
            "conditions": [],
            "citations": [],
        },
    }
    paused = conversation.graph.invoke(seeded, conversation.config)
    pending = paused["__interrupt__"][0].value
    final = conversation.approve(pending)
    return pending, final


def test_the_approval_screen_says_who_the_application_is_for(monkeypatch):
    pending, _ = run_to_submission(monkeypatch, memory_service(), subject="other", relation="mother")
    assert (pending["subject"], pending["relation"]) == ("other", "mother")
    assert pending["payload_hash"] == application_hash(pending["form"])  # the hash still binds only the form


def test_a_submitted_application_is_remembered_for_the_citizen(monkeypatch):
    service = memory_service(consent_references=True)
    _, final = run_to_submission(monkeypatch, service)
    assert final["status"] == "submitted"
    assert final["reference_saved"] is True
    [reference] = service.read_application_references(CITIZEN)
    assert (reference.application_id, reference.scheme_id) == ("APP-1", "C01")
    assert (reference.subject, reference.relation, reference.submitted_by) == ("self", None, "user-1")
    assert reference.expires_at - reference.submitted_at == timedelta(days=90)


def test_an_application_for_someone_else_is_remembered_with_the_relation(monkeypatch):
    service = memory_service(consent_references=True)
    run_to_submission(monkeypatch, service, subject="other", relation="mother")
    [reference] = service.read_application_references(CITIZEN)
    assert (reference.subject, reference.relation) == ("other", "mother")


def test_without_reference_consent_nothing_is_remembered_but_the_application_goes_through(monkeypatch):
    service = memory_service(consent_references=False)
    _, final = run_to_submission(monkeypatch, service)
    assert final["status"] == "submitted"
    assert final["reference_saved"] is False
    assert service.read_application_references(CITIZEN) == []


def test_an_operators_submission_goes_to_the_operators_own_list(monkeypatch):
    service = InMemoryMemoryService(ALLOWLIST)
    now = datetime.utcnow()
    service.record_consent(
        OPERATOR,
        MemoryConsent(
            purpose="application_references",
            granted=True,
            notice_version="1",
            decided_at=now,
            expires_at=now + timedelta(days=60),
            consent_reference="op-refs",
            obtained_via="in_person",
            recorded_by="op-1",
        ),
    )
    run_to_submission(monkeypatch, service, scope=OPERATOR, subject="self")
    [reference] = service.read_application_references(OPERATOR)
    assert (reference.subject, reference.submitted_by) == ("other", "op-1")
    assert service.read_application_references(CITIZEN) == []


def test_a_failure_saving_the_reference_does_not_undo_the_submission(monkeypatch):
    service = memory_service(consent_references=True)
    monkeypatch.setattr(
        service, "save_application_reference", lambda scope, reference: (_ for _ in ()).throw(RuntimeError("down"))
    )
    _, final = run_to_submission(monkeypatch, service)
    assert final["status"] == "submitted"
    assert final["submission"]["application_id"] == "APP-1"
    assert final["reference_saved"] is False


def test_facts_edited_at_the_approval_step_are_remembered_like_confirm_edits(monkeypatch):
    service = memory_service()
    remember(service, {"age": 30})
    monkeypatch.setattr(
        "graph.agent_workflow.tools.submit_application",
        lambda *args, **kwargs: {"application_id": "APP-1", "status": "submitted (mock)"},
    )
    conversation, facts = application_conversation(service)
    seeded = {
        "request": "Help me apply",
        "selected_scheme_id": "C01",
        "known_facts": facts,
        "confirmed_facts": facts,
        "remembered_facts": {"age": 30},
        "deterministic_evaluation": {
            "verdict": "eligible",
            "reason": "All reviewed conditions are satisfied.",
            "missing_fields": [],
            "unresolved_fields": [],
            "conditions": [],
            "citations": [],
        },
    }
    conversation.graph.invoke(seeded, conversation.config)

    result = conversation.resume(action="edit", changes={"age": 31})

    assert result["status"] == "draft_edited"
    assert service.read_facts(CITIZEN, ["age"]) == {"age": 31}


# Tracking an application in chat

FOLLOW_UP = "Track the status of my case"


def saved_applications(service, scope=CITIZEN):
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
        ),
    )
    for application_id, subject, relation, scheme in (
        ("a1b2c3d4-0000-4000-8000-000000000001", "self", None, "C01"),
        ("e5f6a7b8-0000-4000-8000-000000000002", "other", "mother", "C02"),
    ):
        service.save_application_reference(
            scope,
            ApplicationReference(
                scheme_id=scheme,
                application_id=application_id,
                submitted_at=now,
                expires_at=now + timedelta(days=90),
                consent_reference=f"refs-{scope.household_id}",
                subject=subject,
                relation=relation,
                submitted_by=scope.actor_id,
            ),
        )


def test_a_follow_up_is_answered_from_the_persons_own_saved_applications(monkeypatch):
    service = memory_service(consent_facts=False)
    saved_applications(service)
    looked_up = []
    monkeypatch.setattr(
        "graph.agent_workflow.tools.application_status",
        lambda application_id, household_id: looked_up.append((application_id, household_id))
        or {"application_id": application_id, "status": "submitted"},
    )
    conversation = Conversation(ScriptedIntake(), memory=service)

    result = conversation.send(FOLLOW_UP)

    assert result["status"] == "applications_listed"
    assert "C01: submitted" in result["response"]
    assert "C02: submitted for your mother" in result["response"]
    assert sorted(looked_up) == [
        ("a1b2c3d4-0000-4000-8000-000000000001", "hh1"),  # the portal is asked on behalf of the household
        ("e5f6a7b8-0000-4000-8000-000000000002", "hh1"),
    ]
    assert "a1b2c3d4-0000" not in result["response"]  # only a short reference is shown
    assert "a1b2c3d4" in result["response"]


def test_a_follow_up_naming_a_family_member_tracks_only_that_member(monkeypatch):
    service = memory_service(consent_facts=False)
    saved_applications(service)
    looked_up = []
    monkeypatch.setattr(
        "graph.agent_workflow.tools.application_status",
        lambda application_id, household_id: looked_up.append(application_id) or {"status": "submitted"},
    )
    conversation = Conversation(ScriptedIntake(), memory=service)

    result = conversation.send("Track the status of my mother's case")

    assert result["status"] == "applications_listed"
    assert "C02: submitted for your mother" in result["response"]
    assert "C01" not in result["response"]
    assert looked_up == ["e5f6a7b8-0000-4000-8000-000000000002"]


def test_a_follow_up_for_a_family_member_with_nothing_saved_says_so_without_a_lookup(monkeypatch):
    service = memory_service(consent_facts=False)
    saved_applications(service)
    monkeypatch.setattr(
        "graph.agent_workflow.tools.application_status",
        lambda application_id, household_id: pytest.fail("no lookup"),
    )
    conversation = Conversation(ScriptedIntake(), memory=service)

    result = conversation.send("Track the status of my father's case")

    assert result["status"] == "no_applications"
    assert "your father" in result["response"]


def test_a_family_members_nickname_is_shown_in_the_follow_up(monkeypatch):
    from agents.family import rename_family_member

    service = memory_service(consent_facts=False)
    saved_applications(service)
    rename_family_member(service, CITIZEN, "mother", "Amma")
    monkeypatch.setattr(
        "graph.agent_workflow.tools.application_status",
        lambda application_id, household_id: {"status": "submitted"},
    )

    result = Conversation(ScriptedIntake(), memory=service).send(FOLLOW_UP)

    assert "for your mother (Amma)" in result["response"]


def test_an_application_id_in_the_message_is_never_looked_up(monkeypatch):
    service = memory_service(consent_facts=False)
    saved_applications(service)
    other = MemoryScope(actor_id="user-2", household_id="hh2", actor_role="citizen")
    service.record_consent(
        other,
        MemoryConsent(
            purpose="application_references",
            granted=True,
            notice_version="1",
            decided_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=60),
            consent_reference="refs-hh2",
        ),
    )
    looked_up = []
    monkeypatch.setattr(
        "graph.agent_workflow.tools.application_status",
        lambda application_id, household_id: looked_up.append(application_id) or {"status": "submitted"},
    )
    conversation = Conversation(ScriptedIntake(), memory=service, scope=other)

    result = conversation.send("Track the status of case OTHER-HOUSEHOLD-APP")

    assert result["status"] == "no_applications"
    assert looked_up == []


def test_a_follow_up_with_nothing_saved_says_so(monkeypatch):
    monkeypatch.setattr(
        "graph.agent_workflow.tools.application_status",
        lambda application_id, household_id: pytest.fail("no lookup"),
    )
    conversation = Conversation(ScriptedIntake(), memory=memory_service(consent_facts=False))
    result = conversation.send(FOLLOW_UP)
    assert result["status"] == "no_applications"
    assert "only if you allowed it" in result["response"]


def test_a_follow_up_without_a_scope_does_not_read_any_list():
    service = memory_service(consent_facts=False)
    saved_applications(service)
    conversation = Conversation(ScriptedIntake(), memory=service, scope=None)
    result = conversation.send(FOLLOW_UP)
    assert result["status"] == "responded"
    assert "not available" in result["response"]


def test_an_application_the_portal_lost_or_cannot_reach_is_reported_per_application(monkeypatch):
    service = memory_service(consent_facts=False)
    saved_applications(service)

    def status(application_id, household_id):
        code = "application_not_found" if application_id.startswith("a1b2") else "transport_error"
        raise tools.ToolCallError("mock-portal", "get_application_status", code, "x")

    monkeypatch.setattr("graph.agent_workflow.tools.application_status", status)
    result = Conversation(ScriptedIntake(), memory=service).send(FOLLOW_UP)

    assert "C01: not found at the portal" in result["response"]
    assert "C02: status unavailable right now" in result["response"]


def test_without_memory_a_follow_up_is_routed_as_before():
    conversation = Conversation(ScriptedIntake(IntakeExtraction()), next_agent="respond")
    result = conversation.send(FOLLOW_UP)
    assert result["status"] == "responded"
    assert result["response"] == "Check."


def test_the_tracking_wording_exists_in_every_language_with_the_same_keys():
    from graph.agent_workflow import TRACK_TEXT

    assert set(TRACK_TEXT["hi"]) == set(TRACK_TEXT["mr"]) == set(TRACK_TEXT["en"])
