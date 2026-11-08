"""Issue 2: questions about the person's own eligibility go to intake, never to scheme Q&A.

Examples come from the development split of the eligibility gold set and from general
scheme questions; held-out cases are not used here.
"""
import pytest

from agents.contracts import IntakeResult, SupervisorPlan
from agents.supervisor import asks_about_own_eligibility
from graph import tools
from graph.agent_workflow import build_agent_graph
from tests.test_agent_workflow import StubIntake, StubSupervisor, build_agents

PERSONAL = [
    # openings the supervisor sent to scheme Q&A in the first agent-team run (development split)
    "I lost my husband last year. I am 39 and we have a BPL card. Is there a widow pension for me?",
    "My grandmother is a widow aged 79. Our family is BPL. Can she get a pension?",
    "My grandmother is 80 and a widow, and we are a BPL household. Is there a pension for her?",
    "I am 40 and work in a shop. I want to save for a pension. Which schemes can I join?",
    "I just turned 41. I work in a shop and want a pension. What can I join?",
    "I am 32 and have a savings account, but I don't want money taken from it automatically. "
    "Can I still get insurance or a pension?",
    "I am a tenant farmer. I farm 3 acres on lease from a landlord. Can I get a Kisan Credit Card?",
    "मी 40 वर्षांचा आहे आणि दुकानात काम करतो. मी कोणत्या योजनांमध्ये सामील होऊ शकतो?",
    # other phrasings
    "Am I eligible for the Atal Pension Yojana?",
    "Will my father get the old age pension?",
    "क्या मेरी माँ को विधवा पेंशन मिल सकती है?",
    "मला शेतकरी योजनेचा लाभ मिळू शकतो का?",
]

FACTUAL = [
    "What is the age limit for Atal Pension Yojana?",
    "How do I apply for PMSBY?",
    "How can I join the Atal Pension Yojana?",
    "What documents are needed for the widow pension?",
    "How much pension does IGNWPS give each month?",
    "Where do I submit the Kisan Credit Card form?",
    "अटल पेंशन योजना की आयु सीमा क्या है?",
    "किसान क्रेडिट कार्डसाठी कोणती कागदपत्रे लागतात?",
]


@pytest.mark.parametrize("text", PERSONAL)
def test_personal_eligibility_questions_are_recognised(text):
    assert asks_about_own_eligibility(text)


@pytest.mark.parametrize("text", FACTUAL)
def test_factual_scheme_questions_are_not(text):
    assert not asks_about_own_eligibility(text)


class RecordingIntake(StubIntake):
    def __init__(self):
        super().__init__()
        self.answer_calls = []

    def answer(self, value):
        self.answer_calls.append(value)
        raise AssertionError("a personal question must not reach scheme Q&A")


def test_supervisor_sending_a_personal_question_to_scheme_qa_is_overridden(monkeypatch):
    monkeypatch.setattr(tools, "search_evidence", lambda q, scheme_id=None: [])
    plan = SupervisorPlan(next_agent="respond", reason="Scheme question.", scheme_question=True, language="en")
    intake = RecordingIntake()
    graph = build_agent_graph(build_agents(intake=intake, plan=StubSupervisor(plan)))
    result = graph.invoke({"request": "My grandmother is 80 and a widow. Is there a pension for her?"})
    assert result["plan"]["next_agent"] == "intake" and result["plan"]["scheme_question"] is False
    assert "Rerouted" in result["plan"]["reason"]
    assert result["status"] not in {"answered", "answer_not_found"}
    assert intake.answer_calls == []


def test_a_factual_question_still_goes_to_scheme_qa(monkeypatch):
    monkeypatch.setattr(tools, "search_evidence", lambda q, scheme_id=None: [])
    plan = SupervisorPlan(next_agent="respond", reason="Scheme question.", scheme_question=True, language="en")
    graph = build_agent_graph(build_agents(plan=StubSupervisor(plan)))
    result = graph.invoke({"request": "What is the age limit for Atal Pension Yojana?"})
    assert result["plan"]["next_agent"] == "respond"
    assert result["status"] == "answer_not_found"
