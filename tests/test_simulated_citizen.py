"""The simulated citizen and the agent-team driver, without any model or API key."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "tests" / "evaluation"
sys.path.insert(0, str(EVAL))
import simulated_citizen as sc  # noqa: E402

_spec = importlib.util.spec_from_file_location("run_eval", EVAL / "run_eval.py")
run_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_eval)

CASE = {
    "case_id": "T01a", "language": "hi", "opening_message": "Meri maa 62 saal ki vidhwa hain.",
    "candidate_scheme_ids": ["C06"],
    "hidden_profile": {"is_widow": True, "age": 62, "household_below_bpl": None, "is_remarried": False},
    "expected": {"C06": {"verdict": "cant_tell"}},
}


class RecordingModel:
    def __init__(self, reply="वह 62 साल की हैं।"):
        self.reply, self.calls = reply, []

    def invoke(self, messages):
        self.calls.append(messages)
        return SimpleNamespace(content=self.reply)


def test_card_shows_only_the_hidden_profile_and_unknowns():
    card = sc.profile_card(CASE["hidden_profile"])
    assert card.splitlines() == ["- is widow: yes", "- age: 62", "- household below bpl: doesn't know",
                                 "- is remarried: no"]


def test_citizen_prompt_has_card_language_and_opening_but_never_the_answers():
    model = RecordingModel()
    citizen = sc.SimulatedCitizen(CASE, model)
    assert citizen.answer("उनकी उम्र क्या है?") == "वह 62 साल की हैं।"
    system = model.calls[0][0][1]
    assert "Hindi" in system and "- age: 62" in system and CASE["opening_message"] in system
    assert "cant_tell" not in system and "C06" not in system  # gold answers never reach the citizen
    assert model.calls[0][-1] == ("human", "Helper: उनकी उम्र क्या है?")


@pytest.mark.parametrize("citizen, agent, same", [
    ("meta-llama/llama-3.3-70b-instruct", "openai/gpt-4o-mini", False),
    ("openai/gpt-4.1-mini", "openai/gpt-4o-mini", True),
    ("gpt-4.1-mini", "gpt-4o", True),
])
def test_model_family(citizen, agent, same):
    assert (sc.model_family(citizen) == sc.model_family(agent)) is same


def test_same_family_citizen_is_refused(monkeypatch):
    monkeypatch.setenv("CITIZEN_MODEL", "openai/gpt-4.1-mini")
    monkeypatch.setenv("SUPERVISOR_MODEL", "openai/gpt-4o-mini")
    monkeypatch.setenv("OPENROUTER_API_KEY", "dummy")
    with pytest.raises(RuntimeError, match="same family"):
        sc.SimulatedCitizen.from_environment(CASE)


class FakeGraph:
    """Follows the agent graph's protocol: a question, then the confirm step, then verdicts."""

    def __init__(self, confirmed_facts):
        self.confirmed_facts, self.step, self.requests = confirmed_facts, 0, []
        self.values = {"shortlist": ["C06"], "verdicts": {}}

    def invoke(self, value, config):
        self.requests.append(value)
        self.step += 1
        if self.step == 1:
            return {"status": "needs_information", "response": "Does she have a BPL card?"}
        if self.step == 2:
            self.interrupt = {"kind": "confirm_facts", "facts": self.confirmed_facts, "payload_hash": "h1"}
            return {"__interrupt__": [self.interrupt]}
        self.interrupt = None
        self.values["verdicts"] = {"C06": {"verdict": "cant_tell"}, "C02": {"verdict": "eligible"}}
        return {"status": "eligibility_checked", "response": "C06: can't tell"}

    def get_state(self, config):
        pending = getattr(self, "interrupt", None)
        tasks = [SimpleNamespace(interrupts=[SimpleNamespace(value=pending)])] if pending else []
        return SimpleNamespace(tasks=tasks, values=self.values)


def test_driver_answers_questions_confirms_facts_and_scores(monkeypatch):
    graph = FakeGraph({"is_widow": True, "age": 61, "household_below_bpl": None})
    citizen = sc.SimulatedCitizen(CASE, RecordingModel("पता नहीं"))
    config = {"name": "t", "system": "agent_team", "scheme_selection": "system"}
    result = run_eval.run_agent_team(CASE, config, graph=graph, citizen=citizen)
    assert result["verdicts"] == {"C06": "cant_tell", "C02": "eligible"}
    assert result["questions_asked"] == 1 and result["confirmations"] == 1
    assert result["fact_errors"] == ["age: confirmed 61, hidden profile 62"]  # intake misheard the age
    assert graph.requests[1]["request"] == "पता नहीं"  # the citizen's words went to the agents
    assert graph.requests[2].resume == {"action": "approve", "payload_hash": "h1"}
    assert result["stopped_at"] == "eligibility_checked"
    score = run_eval.score_case(CASE, result)
    assert score["case_correct"] and score["unscored_schemes"] == ["C02"]


def test_agent_team_must_pick_its_own_schemes(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"name": "bad", "system": "agent_team", "scheme_selection": "candidates"}')
    with pytest.raises(ValueError, match="picks its own schemes"):
        run_eval.load_config(bad)
