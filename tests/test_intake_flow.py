import json
from pathlib import Path

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
from agents.eligibility import EligibilityAgent
from agents.intake import IntakeAgent, profile_model
from agents.supervisor import InputValidator, OutputValidator, UnifiedRouter
from langgraph.types import Command

from app import api
from graph import tools
from graph.agent_workflow import AgentSet, build_agent_graph
from servers.rule_engine import server as rule_server
from servers.rule_engine.server import get_field_specs

PENSION = "SYNTH-PENSION-001"
ROOT = Path(__file__).resolve().parents[1]


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
            supervisor=CountingSupervisor(SupervisorPlan(next_agent="respond", reason="Hello.")),
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
    thread = service.execute_workflow("hello there", "a1", known_facts={"age": 67})["thread_id"]
    service.execute_workflow("more facts", "a1", thread_id=thread, known_facts={"income": 100000})
    service.execute_workflow("no facts this turn", "a1", thread_id=thread)

    state = service.agent_graph.get_state(service._config(thread)).values
    assert state["known_facts"] == {"age": 67, "income": 100000}


def test_newer_value_wins_and_confirmed_facts_merge():
    graph = responding_graph()
    config = {"configurable": {"thread_id": "t"}}
    graph.invoke({"request": "first turn", "confirmed_facts": {"age": 60, "is_widow": True}}, config)
    graph.invoke({"request": "second turn", "confirmed_facts": {"age": 61}}, config)
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


def test_draft_fields_are_hidden_outside_preview(tmp_path, monkeypatch):
    record = json.loads((ROOT / "data/rules/C06.json").read_text())
    for rule in record["rules"]:
        rule["status"] = "draft"
    (tmp_path / "C06.json").write_text(json.dumps(record))
    monkeypatch.setattr(rule_server, "RULE_DIRS", [ROOT / "data/schemes", ROOT / "tests/fixtures", tmp_path])
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
    def run(reply, pending):  # a missed pending field is asked again on its own, so script both calls
        return IntakeAgent(FakeModel(reply, reply)).extract({"request": "pata nahi", "pending_field": pending}, pension_specs)

    assert run({"facts": {}, "reply_kind": "dont_know"}, "income").dont_know
    assert not run({"facts": {}, "reply_kind": "other"}, "income").dont_know
    assert not run({"facts": {}, "reply_kind": "dont_know"}, None).dont_know
    answered = {"facts": {"income": {"amount": 100000, "period": "year"}}, "reply_kind": "dont_know"}
    assert not run(answered, "income").dont_know


def test_a_missed_pending_answer_is_read_again_against_that_field_alone(pension_specs):
    """gpt-4o-mini read "No" as dont_know against a wide schema, which stopped intake."""
    model = FakeModel(
        {"facts": {"age": 67}, "reply_kind": "dont_know"},
        {"facts": {"is_widow": False}, "reply_kind": "answer"},
    )
    result = IntakeAgent(model).extract({"request": "No", "pending_field": "is_widow"}, pension_specs)

    assert result.facts == {"age": 67, "is_widow": False}
    assert not result.dont_know
    assert set(model.schemas[1]["$defs"]["HouseholdProfile"]["properties"]) == {"is_widow"}


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
    """Returns its plans in order, repeating the last one."""

    def __init__(self, *plans):
        self.plans = plans
        self.calls = 0
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
        self.calls += 1
        return self.plans[min(self.calls, len(self.plans)) - 1]


def intake_graph(intake, language="en", next_agent="eligibility", later_plan=None):
    plans = [SupervisorPlan(next_agent=next_agent, reason="Check.", language=language)]
    supervisor = CountingSupervisor(*plans, *([later_plan] if later_plan else []))
    agents = AgentSet(
        intake=intake,
        supervisor=supervisor,
        eligibility=EligibilityAgent(model=None),  # explains rule-engine results without a model
        document_checker=StubAgent(DocumentCheckResult()),
        application=StubAgent(ApplicationDraft(scheme_id="s", fields={}, missing_fields=[], review_summary="-")),
    )
    graph = build_agent_graph(agents, checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t"}}
    return graph, supervisor, lambda message: graph.invoke(
        {"request": message, "selected_scheme_id": PENSION}, config
    )


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
    assert third["__interrupt__"][0].value["kind"] == "confirm_facts"  # settled: confirm next
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


# T8: when intake stops asking


def test_dont_know_stops_intake():
    intake = ScriptedIntake(IntakeExtraction(facts={"age": 67}), IntakeExtraction(dont_know=True))
    _, _, send = intake_graph(intake)

    send("My mother is 67")
    result = send("I don't know")
    assert result["status"] == "intake_stopped"
    assert result["intake_stopped"] == "dont_know"
    assert result["declined_fields"] == ["income"]
    assert "income" in result["response"] and "is widow" in result["response"]
    assert result["pending_field"] is None
    assert len(intake.ask_calls) == 1  # is_widow is not asked after "don't know"


def test_two_unusable_replies_to_one_question_stop_intake():
    intake = ScriptedIntake(
        IntakeExtraction(facts={"age": 67}), IntakeExtraction(), IntakeExtraction()
    )
    _, supervisor, send = intake_graph(intake)

    send("My mother is 67")
    again = send("hmm")
    assert again["response"] == "Q:income"  # asked a second time
    stopped = send("hmm")
    assert (stopped["status"], stopped["intake_stopped"]) == ("intake_stopped", "no_answer")
    assert stopped["declined_fields"] == ["income"]
    assert [q.field for q in intake.ask_calls] == ["income", "income"]
    assert supervisor.calls == 3  # each empty reply was re-routed by the Supervisor


def test_question_cap(monkeypatch):
    monkeypatch.setattr("graph.agent_workflow.MAX_QUESTIONS", 1)
    intake = ScriptedIntake(IntakeExtraction(facts={"age": 67}), IntakeExtraction(facts={"income": 100000}))
    _, _, send = intake_graph(intake)

    send("My mother is 67")
    result = send("1 lakh a year")
    assert result["intake_stopped"] == "question_cap"
    assert result["response"].startswith("You have reached your limit of questions.")
    assert [q.field for q in intake.ask_calls] == ["income"]


def test_new_request_while_a_question_is_pending_reaches_the_supervisor():
    intake = ScriptedIntake(IntakeExtraction(facts={"age": 67}), IntakeExtraction())
    later = SupervisorPlan(next_agent="respond", reason="Here is what I can help with.")
    _, supervisor, send = intake_graph(intake, later_plan=later)

    send("My mother is 67")
    result = send("What can you do?")
    assert (result["status"], result["response"]) == ("responded", "Here is what I can help with.")
    assert supervisor.calls == 2
    assert len(intake.ask_calls) == 1


def test_a_fresh_intake_resets_the_stop():
    intake = ScriptedIntake(
        IntakeExtraction(facts={"age": 67}),
        IntakeExtraction(dont_know=True),
        IntakeExtraction(facts={"income": 100000}),
    )
    _, _, send = intake_graph(intake)

    send("My mother is 67")
    assert send("I don't know")["status"] == "intake_stopped"
    result = send("I found out: her income is 1 lakh a year")
    assert result["intake_stopped"] is None and result["declined_fields"] == []
    assert result["response"] == "Q:is_widow"


def test_a_dont_know_that_no_longer_matters_does_not_block_the_verdict():
    intake = ScriptedIntake(
        IntakeExtraction(facts={"age": 67}),
        # "I don't know her income, and she isn't a widow": the second fact settles it.
        IntakeExtraction(facts={"is_widow": False}, dont_know=True),
    )
    _, _, send = intake_graph(intake)

    send("My mother is 67")
    result = send("I don't know her income, and she isn't a widow")
    assert result["verdicts"][PENSION]["verdict"] == "not_eligible"
    assert result["__interrupt__"][0].value["kind"] == "confirm_facts"


# T9: confirm the facts, then a final, cited verdict from confirmed facts only

WIDOW_67 = {"age": 67, "income": 100000, "is_widow": True}


def settled(facts=WIDOW_67):
    """A conversation paused at the confirm step after one message with every fact in it."""
    intake = ScriptedIntake(IntakeExtraction(facts=facts))
    graph, _, send = intake_graph(intake)
    first = send("My mother is a 67 year old widow, income 1 lakh a year")
    config = {"configurable": {"thread_id": "t"}}
    return graph, config, first["__interrupt__"][0].value


def resume(graph, config, **decision):
    return graph.invoke(Command(resume=decision), config)


def test_settled_verdict_waits_for_confirmation_before_any_answer():
    graph, config, pending = settled()
    assert pending["kind"] == "confirm_facts"
    assert pending["facts"] == WIDOW_67
    state = graph.get_state(config).values
    assert state.get("confirmed_facts", {}) == {}
    assert state["explanations"] == {}  # no final answer from unconfirmed facts


def test_approving_the_exact_facts_gives_a_cited_final_verdict():
    graph, config, pending = settled()
    result = resume(graph, config, action="approve", payload_hash=pending["payload_hash"])
    assert result["confirmed_facts"] == WIDOW_67
    assert result["status"] == "eligibility_checked"
    assert result["response"].startswith("eligible:")
    assert "Widow aged 60 or above" in result["response"]  # the clause text is cited


def test_approval_with_another_hash_confirms_nothing():
    graph, config, _ = settled()
    result = resume(graph, config, action="approve", payload_hash="0" * 64)
    assert result["status"] == "confirmation_invalid"
    assert result.get("confirmed_facts", {}) == {}


def test_an_edit_is_confirmed_and_can_change_the_verdict():
    graph, config, _ = settled()
    result = resume(graph, config, action="edit", changes={"is_widow": False})
    assert result["confirmed_facts"] == {**WIDOW_67, "is_widow": False}
    assert result["verdicts"][PENSION]["verdict"] == "not_eligible"
    assert result["response"].startswith("not_eligible:")


def test_a_wrongly_typed_edit_is_shown_again_not_used():
    graph, config, _ = settled()
    result = resume(graph, config, action="edit", changes={"age": "67", "caste": "x"})
    again = result["__interrupt__"][0].value
    assert again["rejected_edits"] == ["age", "caste"]
    assert again["facts"] == WIDOW_67
    assert graph.get_state(config).values.get("confirmed_facts", {}) == {}


def test_reject_confirms_nothing():
    graph, config, _ = settled()
    result = resume(graph, config, action="reject")
    assert result["status"] == "facts_rejected"
    assert result.get("confirmed_facts", {}) == {}


def test_a_later_correction_needs_confirming_again():
    intake = ScriptedIntake(IntakeExtraction(facts=WIDOW_67), IntakeExtraction(facts={"age": 68}))
    graph, _, send = intake_graph(intake)
    config = {"configurable": {"thread_id": "t"}}
    pending = send("My mother is a 67 year old widow, income 1 lakh a year")["__interrupt__"][0].value
    resume(graph, config, action="approve", payload_hash=pending["payload_hash"])

    again = send("Sorry, she is 68")["__interrupt__"][0].value
    assert again["facts"] == {**WIDOW_67, "age": 68}


def test_api_reports_the_confirm_step_and_accepts_the_decision():
    service = api.AgentWorkflowService()
    intake = ScriptedIntake(IntakeExtraction(facts=WIDOW_67))
    service._agent_graph = intake_graph(intake)[0]
    paused = service.execute_workflow(
        "My mother is a 67 year old widow, income 1 lakh",
        "a1",
        thread_id="t",
        selected_scheme_id=PENSION,
    )
    assert paused["status"] == "awaiting_confirmation"
    confirmation = paused["data"]["confirmation"]
    assert confirmation["facts"] == WIDOW_67

    done = service.submit_decision("t", "a1", "approve", confirmation["payload_hash"], {})
    assert done["status"] == "eligibility_checked"


def ui_confirmation_journey():
    from app import app_new

    app_new._initialize_portal_state()
    app_new._render_chat_page()


@pytest.mark.parametrize("correct_first", [False, True])
def test_ui_confirm_details_resumes_real_api_and_graph(monkeypatch, correct_first):
    from fastapi.testclient import TestClient
    from streamlit.testing.v1 import AppTest

    from app import app_new
    from app.auth import AuthenticatedHousehold, authenticated_household

    service = api.AgentWorkflowService()
    service._agent_graph = intake_graph(ScriptedIntake(
        IntakeExtraction(facts=WIDOW_67), IntakeExtraction(facts={"age": 68})
    ))[0]
    monkeypatch.setattr(api, "get_workflow_service", lambda: service)
    monkeypatch.setattr("graph.agent_workflow._shortlist_schemes", lambda agents, request, facts=None: [PENSION])
    application = api.create_api()
    application.dependency_overrides[authenticated_household] = lambda: AuthenticatedHousehold(
        household_id="test-household", subject="test-subject"
    )
    client = TestClient(application)

    class HealthResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"status":"ok"}'

    def request(url, method="GET", body=None, headers=None):
        response = client.request(method, url, content=body, headers=headers)
        if response.status_code >= 400:
            raise RuntimeError(response.json()["detail"])
        return response.json()

    monkeypatch.setattr(app_new, "_api_base_url", lambda: "http://testserver")
    monkeypatch.setattr(app_new, "urlopen", lambda *args, **kwargs: HealthResponse())
    monkeypatch.setattr(app_new, "_api_request", request)
    monkeypatch.setattr(app_new, "_scheme_names", lambda base: {PENSION: "Synthetic pension"})

    ui = AppTest.from_function(ui_confirmation_journey).run()
    ui.chat_input[0].set_value("My mother is 67, a widow, and earns 1 lakh a year").run()
    assert not ui.exception
    assert ui.session_state["chat_confirmation"]["facts"] == WIDOW_67
    expected = WIDOW_67
    if correct_first:
        next(button for button in ui.button if button.label == "Change details in chat").click().run()
        assert not ui.exception
        assert ui.session_state["chat_confirmation"] is None
        assert not ui.chat_input[0].disabled
        ui.chat_input[0].set_value("Sorry, she is 68").run()
        expected = {**WIDOW_67, "age": 68}
        assert ui.session_state["chat_confirmation"]["facts"] == expected
    next(button for button in ui.button if button.label == "Confirm details").click().run()
    assert not ui.exception
    assert ui.session_state["chat_confirmation"] is None
    assert ui.session_state["chat_eligibility_result"]["status"] == "eligibility_checked"
    assert ui.session_state["chat_eligibility_result"]["verdicts"][PENSION]["verdict"] == "eligible"
    assert ui.session_state["chat_eligibility_result"]["profile"] == expected
    assert ui.selectbox[0].options == [f"Synthetic pension ({PENSION})"]
