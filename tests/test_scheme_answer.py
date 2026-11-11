from agents.contracts import IntakeAnswer, SupervisorPlan
from agents.intake import IntakeAgent
from agents.supervisor import OutputValidator
from graph import tools
from graph.agent_workflow import build_agent_graph
from servers.schemes_kb import search as kb_search
from servers.schemes_kb.server import search_scheme_evidence
from tests.test_agent_workflow import StubIntake, StubSupervisor, build_agents

PASSAGE = {
    "id": "C04:eligibility:1", "scheme_id": "C04", "source_type": "scheme_page", "section": "eligibility",
    "page": None, "text": "Any citizen aged 18 to 40 can join.",
    "citations": [{"source_url": "https://example.gov/apy", "source_path": "eligibility[0]"}],
}


class AnsweringIntake(StubIntake):
    def __init__(self, result):
        super().__init__()
        self.result = result
        self.answer_calls = []

    def answer(self, value):
        self.answer_calls.append(value)
        return self.result


def ask(monkeypatch, intake, passages, question="What is the age limit for Atal Pension Yojana?"):
    monkeypatch.setattr(tools, "search_evidence", lambda q, scheme_id=None: passages)
    plan = SupervisorPlan(next_agent="respond", reason="Scheme question.", scheme_question=True)
    return build_agent_graph(build_agents(intake=intake, plan=StubSupervisor(plan))).invoke({"request": question})


def test_scheme_question_gets_a_cited_answer(monkeypatch):
    intake = AnsweringIntake(IntakeAnswer(found=True, answer="Citizens aged 18 to 40 can join.",
                                          cited_passage_ids=["C04:eligibility:1"]))
    result = ask(monkeypatch, intake, [PASSAGE])
    assert result["status"] == "answered"
    assert result["response"] == "Citizens aged 18 to 40 can join.\n\nSources:\n- C04: https://example.gov/apy"


def test_no_evidence_says_not_found_without_calling_the_model(monkeypatch):
    intake = AnsweringIntake(None)
    result = ask(monkeypatch, intake, [])
    assert result["status"] == "answer_not_found"
    assert intake.answer_calls == []


def test_answer_deciding_the_users_eligibility_is_blocked(monkeypatch):
    intake = AnsweringIntake(IntakeAnswer(found=True, answer="You are eligible for this scheme.",
                                          cited_passage_ids=["C04:eligibility:1"]))
    assert ask(monkeypatch, intake, [PASSAGE])["status"] == "output_blocked"


def test_search_failure_falls_back_to_not_found(monkeypatch):
    def fail(q, scheme_id=None):
        raise tools.ToolCallError("schemes-kb", "search_scheme_evidence", "tool_error", "index missing")
    monkeypatch.setattr(tools, "search_evidence", fail)
    plan = SupervisorPlan(next_agent="respond", reason="Scheme question.", scheme_question=True)
    result = build_agent_graph(build_agents(plan=StubSupervisor(plan))).invoke({"request": "What is APY's age limit?"})
    assert result["status"] == "answer_not_found"


class FixedModel:
    def __init__(self, output):
        self.output = output

    def with_structured_output(self, _):
        return lambda _: self.output


def test_intake_answer_rejects_citations_outside_the_passages():
    passages = [{"id": "a", "scheme_id": "C04", "text": "x"}]
    invented = IntakeAgent(FixedModel(IntakeAnswer(found=True, answer="y", cited_passage_ids=["a", "zzz"])))
    uncited = IntakeAgent(FixedModel(IntakeAnswer(found=True, answer="y")))
    good = IntakeAgent(FixedModel(IntakeAnswer(found=True, answer="y", cited_passage_ids=["a"])))
    request = {"question": "q", "passages": passages}
    assert invented.answer(request).found is False
    assert uncited.answer(request).found is False
    assert good.answer(request).found is True


def test_quoting_criteria_is_allowed_but_personal_verdicts_are_not():
    check = OutputValidator().validate_specialist_output
    assert check("People aged 18 to 40 are eligible to join.", "scheme_info", "en").passed
    assert not check("You are not eligible for APY.", "scheme_info", "en").passed
    assert not check("आप पात्र हैं।", "scheme_info", "hi").passed


def test_intake_output_rule_now_runs():
    assert not OutputValidator().validate_specialist_output("You are eligible.", "intake", "en").passed


def test_intake_questions_may_name_approved_or_eligible():
    """A word match blocked these C36 questions and showed the user a generic error."""
    check = OutputValidator().validate_specialist_output
    assert check("Is your institution approved by AICTE?", "intake", "en").passed
    assert check("Are you currently an engineering student in an eligible year?", "intake", "en").passed
    assert not check("Your application has been approved.", "intake", "en").passed


def test_evidence_tool_drops_low_rerank_scores_and_strips_tables(monkeypatch):
    rows = [
        {**PASSAGE, "kind": "text", "rank_score": 9.0},
        {**PASSAGE, "id": "t", "kind": "table", "text": "<td>Limit</td><td>20%</td>", "rank_score": 6.0},
        {**PASSAGE, "id": "low", "kind": "text", "rank_score": 2.0},
        {**PASSAGE, "id": "unscored", "kind": "text", "rank_score": None},
    ]
    calls = []
    monkeypatch.setattr(kb_search, "search_schemes",
                        lambda *a, **k: calls.append(k) or {"ranking": "hybrid+rewrite+llm_rerank", "results": rows})
    data = search_scheme_evidence("q")["data"]
    assert calls[0]["rewrite"] is True and calls[0]["rerank"] is True
    assert [p["id"] for p in data] == ["C04:eligibility:1", "t"]
    assert data[1]["text"] == "Limit 20%"
