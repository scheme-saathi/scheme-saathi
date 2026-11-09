"""Issue 1: no answer outside the rule engine may tell a person (or their relative) whether they qualify."""
import pytest

from agents.contracts import IntakeAnswer, SupervisorPlan
from agents.supervisor import OutputValidator, _decides_eligibility
from graph import tools
from graph.agent_workflow import CHECK_ELIGIBILITY_INSTEAD, build_agent_graph
from tests.test_agent_workflow import StubIntake, StubSupervisor, build_agents

CLAIMS = [
    # the three replies from the first agent-team evaluation run (cases F02c, F02d, F13b)
    "Yes, your grandmother can get a pension under the Indira Gandhi National Widow Pension Scheme (IGNWPS) "
    "as she is a widow aged 79 and belongs to a BPL family.",
    "Yes, there is a pension for your grandmother. Under the Indira Gandhi National Widow Pension Scheme, "
    "widows aged 80 years and above receive a pension of Rs.500/- per month.",
    "Yes, as a tenant farmer, you can get a Kisan Credit Card.",
    # other personal verdicts
    "You are eligible for this scheme.",
    "She is eligible for IGNWPS.",
    "Your father does not qualify because he is over 40.",
    "Your mother will receive Rs 300 every month.",
    "He may also qualify for the Sanjay Gandhi scheme.",
    "No, your father cannot join APY.",
    "आप इस योजना के लिए पात्र हैं।",
    "आपकी माँ को हर महीने पेंशन मिल सकती है।",
    "तुम्ही या योजनेसाठी पात्र आहात.",
    "तुम्हाला या योजनेतून मदत मिळू शकते.",
]

ALLOWED = [
    "Citizens aged 18 to 40 can join.",
    "Widows aged 40 to 79 from BPL households can get a pension of Rs 300 a month.",
    "The applicant must be a widow in the age group of 40-79 years.",
    "The scheme is for widows aged 40 to 79. Scheme Saathi can check your eligibility step by step.",
    "You can get the application form at the tehsil office.",
    "You can apply online on the MahaDBT portal.",
    "Can she get a pension?",
    "Applicants who are eligible receive Rs 300 a month.",
    "पात्र व्यक्तियों को हर महीने 300 रुपये मिलते हैं।",
    "आपको आवेदन पत्र तहसील कार्यालय में मिल सकता है।",
    "अर्ज तहसील कार्यालयात मिळेल.",
]


@pytest.mark.parametrize("text", CLAIMS)
def test_personal_eligibility_claims_are_detected(text):
    assert _decides_eligibility(text)


@pytest.mark.parametrize("text", ALLOWED)
def test_criteria_procedures_and_questions_are_allowed(text):
    assert not _decides_eligibility(text)


@pytest.mark.parametrize("text", CLAIMS[:3])
def test_scheme_answer_with_a_claim_fails_output_validation(text):
    result = OutputValidator().validate_specialist_output(text, "scheme_info", "en")
    assert not result.passed and "must not decide" in result.errors[0]


PASSAGE = {
    "id": "C06:eligibility:1", "scheme_id": "C06", "source_type": "scheme_page", "section": "eligibility",
    "page": None, "text": "The applicant must be a widow in the age group of 40-79 years.",
    "citations": [{"source_url": "https://www.myscheme.gov.in/schemes/ignwps", "source_path": "eligibility[0]"}],
}


class AnsweringIntake(StubIntake):
    def __init__(self, answer):
        super().__init__()
        self.result = IntakeAnswer(found=True, answer=answer, cited_passage_ids=[PASSAGE["id"]])

    def answer(self, value):
        return self.result


@pytest.mark.parametrize("language", ["en", "hi", "mr"])
def test_blocked_scheme_answer_offers_a_proper_eligibility_check(monkeypatch, language):
    monkeypatch.setattr(tools, "search_evidence", lambda q, scheme_id=None: [PASSAGE])
    plan = SupervisorPlan(next_agent="respond", reason="Scheme question.", scheme_question=True, language=language)
    intake = AnsweringIntake("Yes, your grandmother can get a pension under IGNWPS.")
    graph = build_agent_graph(build_agents(intake=intake, plan=StubSupervisor(plan)))
    # A factual question (so it stays on scheme Q&A), answered with a verdict about a relative:
    # the guard must still block it. Personal questions are rerouted to intake earlier (issue 2).
    result = graph.invoke({"request": "How much pension does the widow pension scheme pay?"})
    assert result["status"] == "output_blocked"
    assert result["response"] == CHECK_ELIGIBILITY_INSTEAD[language]
    assert "grandmother can get" not in result["response"]
