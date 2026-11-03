import pytest
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.runnables import RunnableLambda
from pydantic import ValidationError

from agents.contracts import (
    ApplicationDraft,
    DocumentCheckResult,
    EligibilityNarrative,
    IntakeAskInput,
    IntakeExtraction,
    IntakeQuestion,
    IntakeResult,
    SupervisorPlan,
)
from agents.intake import IntakeAgent, profile_model
from app import api
from graph import tools
from graph.agent_workflow import AgentSet, build_agent_graph
from servers.rule_engine.server import get_field_specs

PENSION = "SYNTH-PENSION-001"


class StubAgent:
    def __init__(self, result):
        self.result = result

    def invoke(self, value):
        return self.result


def responding_graph():
    """A graph whose supervisor answers directly, so a turn only touches state."""
    return build_agent_graph(
        AgentSet(
            intake=StubAgent(IntakeResult(language="en", intent="other")),
            supervisor=StubAgent(SupervisorPlan(next_agent="respond", reason="Hello.")),
            eligibility=StubAgent(EligibilityNarrative(explanation="-")),
            document_checker=StubAgent(DocumentCheckResult()),
            application=StubAgent(ApplicationDraft(scheme_id="s", fields={}, missing_fields=[], review_summary="-")),
        ),
        checkpointer=MemorySaver(),
    )


# T1 + T2: facts survive and accumulate across turns


def test_api_keeps_and_merges_facts_across_turns():
    service = api.AgentWorkflowService()
    service._agent_graph = responding_graph()
    thread = service.execute_workflow("hi", "a1", known_facts={"age": 67})["thread_id"]
    service.execute_workflow("more", "a1", thread_id=thread, known_facts={"income": 100000})
    service.execute_workflow("no facts this turn", "a1", thread_id=thread)

    state = service.agent_graph.get_state(service._config(thread)).values
    assert state["known_facts"] == {"age": 67, "income": 100000}


def test_newer_value_wins_and_confirmed_facts_merge():
    graph = responding_graph()
    config = {"configurable": {"thread_id": "t"}}
    graph.invoke({"request": "a", "confirmed_facts": {"age": 60, "is_widow": True}}, config)
    graph.invoke({"request": "b", "confirmed_facts": {"age": 61}}, config)
    assert graph.get_state(config).values["confirmed_facts"] == {"age": 61, "is_widow": True}


# T3: field types come from the rules


def test_field_specs_for_live_scheme():
    specs = get_field_specs([PENSION])
    assert specs["ok"]
    assert {f: s["type"] for f, s in specs["data"].items()} == {"age": "number", "is_widow": "bool", "income": "number"}


def test_field_specs_list_known_string_values():
    spec = get_field_specs(["M18"], include_draft=True)["data"]["social_category"]
    assert spec == {"type": "str", "known_values": ["VJNT", "OBC", "SBC"]}


def test_field_specs_unknown_scheme_is_an_error():
    assert get_field_specs(["NOPE"])["error"]["code"] == "scheme_not_found"


def test_draft_fields_are_hidden_outside_preview():
    assert get_field_specs(["C06"])["data"] == {}


# T4: ask only what can still change a verdict


def verdicts(facts, schemes=(PENSION,), include_draft=False):
    return {s: tools.evaluate_scheme(facts, s, include_draft) for s in schemes}


def test_empty_profile_asks_a_rule_field():
    assert tools.next_question(verdicts({})) == "age"  # three-way tie, alphabetical


def test_settled_verdicts_ask_nothing():
    assert tools.next_question(verdicts({"age": 67, "is_widow": True, "income": 100000})) is None
    # age 40 already fails "age >= 60", so widowhood and income can't change the verdict.
    assert tools.next_question(verdicts({"age": 40})) is None


def test_wrongly_typed_fact_is_asked_again():
    assert tools.next_question(verdicts({"age": "67", "is_widow": True, "income": 1})) == "age"


def test_field_shared_by_more_open_verdicts_wins():
    # is_widow is open in both schemes; every other field in only one.
    open_verdicts = verdicts({"age": 65}, [PENSION, "C06"], include_draft=True)
    assert tools.next_question(open_verdicts) == "is_widow"


def test_declined_fields_are_skipped():
    assert tools.next_question(verdicts({}), declined=["age"]) == "income"
    assert tools.next_question(verdicts({}), declined=["age", "income", "is_widow"]) is None


# T5: typed household profile


@pytest.fixture
def profile():
    return profile_model(get_field_specs([PENSION])["data"])


def test_profile_accepts_typed_values(profile):
    assert profile.model_validate({"age": 67, "is_widow": True}).model_dump(exclude_none=True) == {
        "age": 67,
        "is_widow": True,
    }


@pytest.mark.parametrize("bad", [{"age": "sixty"}, {"age": "67"}, {"is_widow": "yes"}, {"caste": "x"}])
def test_profile_rejects_untyped_or_unknown_fields(profile, bad):
    with pytest.raises(ValidationError):
        profile.model_validate(bad)


def test_profile_schema_carries_known_values():
    model = profile_model(get_field_specs(["M18"], include_draft=True)["data"])
    assert "OBC" in model.model_json_schema()["properties"]["social_category"]["description"]


# T6: the intake agent reads typed facts and words one question


class FakeModel:
    """Returns scripted structured replies and records the schema each call was given."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.schemas = []

    def with_structured_output(self, schema):
        self.schemas.append(schema)
        return RunnableLambda(lambda _: self.replies.pop(0))


@pytest.fixture
def pension_specs():
    return get_field_specs([PENSION])["data"]


def test_extract_keeps_typed_facts_and_drops_the_rest(pension_specs):
    model = FakeModel({"facts": {"age": 67, "income": "1 lakh", "caste": "x", "is_widow": None}})
    result = IntakeAgent(model).extract({"request": "My mother is 67"}, pension_specs)

    assert result.facts == {"age": 67}
    assert sorted(result.rejected_fields) == ["caste", "income"]
    assert not result.dont_know


def test_extract_gives_the_model_the_typed_rule_fields(pension_specs):
    model = FakeModel({"facts": {}})
    IntakeAgent(model).extract({"request": "hi"}, pension_specs)

    profile = model.schemas[0]["$defs"]["HouseholdProfile"]
    assert set(profile["properties"]) == {"age", "income", "is_widow"}
    assert profile["additionalProperties"] is False


def test_extract_never_sees_earlier_facts(pension_specs):
    """Earlier facts made the model restate them and apply monthly x12 a second time."""
    seen = []
    model = FakeModel()
    model.with_structured_output = lambda schema: RunnableLambda(lambda prompt: seen.append(prompt.to_string()) or {"facts": {}})
    IntakeAgent(model).extract({"request": "yes", "pending_field": "is_widow"}, pension_specs)
    assert "known_facts" not in seen[0] and "is_widow" in seen[0]


def test_dont_know_counts_only_for_an_unanswered_pending_field(pension_specs):
    def run(reply, pending):
        return IntakeAgent(FakeModel(reply)).extract({"request": "pata nahi", "pending_field": pending}, pension_specs)

    assert run({"facts": {}, "dont_know": True}, "income").dont_know
    assert not run({"facts": {}, "dont_know": True}, None).dont_know
    answered = {"facts": {"income": {"amount": 100000, "period": "year"}}, "dont_know": True}
    assert not run(answered, "income").dont_know


@pytest.mark.parametrize(
    "said, pending, stored",
    [
        ({"amount": 8000, "period": "month"}, None, 96000),  # stated monthly: x12 in code
        ({"amount": 300000, "period": "year"}, None, 300000),
        ({"amount": 300000, "period": "unstated"}, "income", 300000),  # our question asked per year
        ({"amount": 8000, "period": "unstated"}, None, None),  # no period anywhere: not guessed
        ({"amount": -5, "period": "year"}, None, None),
    ],
)
def test_income_is_converted_in_code_never_guessed(pension_specs, said, pending, stored):
    model = FakeModel({"facts": {"income": said}})
    result = IntakeAgent(model).extract({"request": "...", "pending_field": pending}, pension_specs)
    assert result.facts.get("income") == stored
    assert ("income" in result.rejected_fields) == (stored is None)


def test_monthly_field_divides_a_yearly_amount():
    from agents.intake import Amount, to_field_period

    assert to_field_period("monthly_income", Amount(amount=120000, period="year"), None) == 10000


def test_ask_keeps_the_field_the_caller_chose():
    model = FakeModel({"question": "Does she already receive any pension?"})
    question = IntakeAgent(model).ask(
        IntakeAskInput(field="is_widow", field_type="bool", language="en", request="My mother is 67")
    )
    assert question == IntakeQuestion(field="is_widow", question="Does she already receive any pension?")


# T7: Supervisor → intake → eligibility → one question, across turns


class ScriptedIntake:
    def __init__(self, *extractions):
        self.extractions = list(extractions)
        self.extract_calls = []
        self.ask_calls = []

    def extract(self, value, specs):
        self.extract_calls.append(value)
        return self.extractions.pop(0)

    def ask(self, value):
        self.ask_calls.append(value)
        return IntakeQuestion(field=value.field, question=f"Q:{value.field}")


class CountingSupervisor:
    def __init__(self, plan):
        self.plan = plan
        self.calls = 0

    def invoke(self, value):
        self.calls += 1
        return self.plan


def intake_graph(intake, language="en", next_agent="eligibility"):
    supervisor = CountingSupervisor(SupervisorPlan(next_agent=next_agent, reason="Check.", language=language))
    agents = AgentSet(
        intake=intake,
        supervisor=supervisor,
        eligibility=StubAgent(EligibilityNarrative(explanation="-")),
        document_checker=StubAgent(DocumentCheckResult()),
        application=StubAgent(ApplicationDraft(scheme_id="s", fields={}, missing_fields=[], review_summary="-")),
    )
    graph = build_agent_graph(agents, checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t"}}
    return graph, supervisor, lambda message: graph.invoke({"request": message}, config)


def test_one_question_per_turn_until_the_verdict_is_settled():
    intake = ScriptedIntake(
        IntakeExtraction(facts={"age": 67}),
        IntakeExtraction(facts={"income": 100000}),
        IntakeExtraction(facts={"is_widow": True}),
    )
    _, supervisor, send = intake_graph(intake)

    first = send("My mother is 67, can she get a pension?")
    assert (first["status"], first["response"], first["pending_field"]) == ("needs_information", "Q:income", "income")

    second = send("1 lakh a year")
    assert second["response"] == "Q:is_widow"
    assert intake.extract_calls[1].pending_field == "income"
    assert intake.extract_calls[1].pending_question == "Q:income"  # "1 lakh" is read against it

    third = send("yes")
    assert third["verdicts"][PENSION]["verdict"] == "eligible"
    assert third["known_facts"] == {"age": 67, "income": 100000, "is_widow": True}
    assert third["pending_field"] is None
    assert third["status"] != "needs_information"
    assert [q.field for q in intake.ask_calls] == ["income", "is_widow"]
    # Later questions are worded from the first message, so "she" stays the mother.
    assert {q.request for q in intake.ask_calls} == {"My mother is 67, can she get a pension?"}
    assert supervisor.calls == 1  # replies to a question are not re-routed by the model


def test_facts_in_the_first_message_mean_no_questions():
    intake = ScriptedIntake(IntakeExtraction(facts={"age": 67, "income": 100000, "is_widow": True}))
    _, _, send = intake_graph(intake)

    result = send("My mother is a 67 year old widow, income 1 lakh")
    assert result["verdicts"][PENSION]["verdict"] == "eligible"
    assert intake.ask_calls == []


def test_a_settled_no_asks_nothing_more():
    intake = ScriptedIntake(IntakeExtraction(facts={"age": 40}))
    _, _, send = intake_graph(intake)

    assert send("I am 40")["verdicts"][PENSION]["verdict"] == "not_eligible"
    assert intake.ask_calls == []


def test_dont_know_is_never_asked_again():
    intake = ScriptedIntake(IntakeExtraction(facts={"age": 67}), IntakeExtraction(dont_know=True))
    _, _, send = intake_graph(intake)

    send("My mother is 67")
    result = send("I don't know")
    assert result["declined_fields"] == ["income"]
    assert "income" not in [q.field for q in intake.ask_calls[1:]]


def test_question_uses_the_language_the_supervisor_detected():
    intake = ScriptedIntake(IntakeExtraction(facts={"age": 67}))
    _, _, send = intake_graph(intake, language="hi")

    send("मेरी माँ 67 साल की हैं")
    assert intake.ask_calls[0].language == "hi"
    assert intake.ask_calls[0].period == "year"  # income is annual, so the question asks per year


def test_scheme_without_reviewed_fields_skips_extraction():
    intake = ScriptedIntake()
    graph = intake_graph(intake)[0]

    graph.invoke({"request": "Am I eligible?", "selected_scheme_id": "C01"}, {"configurable": {"thread_id": "c01"}})
    assert intake.extract_calls == []
