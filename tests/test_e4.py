"""E4, the signature ablation: LLM-direct eligibility vs the rule engine, and question order."""
import importlib.util
import json
from pathlib import Path

import pytest

from evaluation import e4

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tests" / "evaluation" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner, run_eval = _load("run_e4"), _load("run_eval")
CONFIG = ROOT / "tests" / "evaluation" / "e4_configs" / "e4_llm_direct_gpt41mini.json"


def test_boundary_verdicts_are_facts_at_or_next_to_a_limit():
    case = {"hidden_profile": {"age": 40, "monthly_income": 15001, "is_widow": True}}
    assert e4.boundary_conditions(case, "C06") == ["age 40 vs gte 40"]
    assert e4.boundary_conditions({"hidden_profile": {"monthly_income": 15001}}, "C05") == [
        "monthly_income 15001 vs lte 15000"]
    assert e4.boundary_conditions({"hidden_profile": {"age": 60}}, "C06") == []
    work = runner.items("development")
    assert sum(1 for w in work if w["boundary"]) == 10 and len(work) == 39


def test_the_llm_sees_the_scheme_text_and_the_same_facts_as_the_rule_engine():
    case = runner.load_cases("development")[0]
    value = e4.direct_input(case, case["candidate_scheme_ids"][0])
    assert value["facts"] == case["hidden_profile"]
    assert {c["clause_id"].split("-")[0] for c in value["clauses"]} <= {"elig", "excl"}


def test_the_rule_engine_matches_every_label_and_a_wrong_llm_is_counted(monkeypatch):
    def always_eligible(value):
        return {"verdict": "eligible", "reason": "", "clauses": []}
    config = e4.load_config(CONFIG)
    rows, summary = runner.run(config, "development", repeat=2, decide=always_eligible, workers=2, quiet=True)
    assert summary["rule_engine"]["accuracy"] == 1.0 and summary["rule_engine"]["boundary_errors"] == 0
    wrong = sum(1 for w in runner.items("development") if w["gold"] != "eligible")
    assert summary["llm_runs"][0]["errors"] == wrong and summary["llm"]["errors"]["mean"] == wrong
    assert summary["llm_runs"][0]["boundary_errors"] > 0
    assert len(rows) == 2 * 39 and {r["run"] for r in rows} == {1, 2}
    assert "# E4" in runner.markdown({"config": config, "split": "development"}, summary)


def test_a_failed_llm_call_is_reported_not_dropped():
    def boom(value):
        raise RuntimeError("timeout")
    rows, summary = runner.run(e4.load_config(CONFIG), "development", limit=1, decide=boom, workers=1, quiet=True)
    assert summary["llm_runs"][0]["failed_calls"] == len(rows) and rows[0]["llm"] == "error"


def test_held_out_needs_the_final_flag(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["run_e4.py", "--config", str(CONFIG), "--split", "held_out"])
    with pytest.raises(SystemExit):
        runner.main()
    assert "final evaluation only" in capsys.readouterr().err


def test_the_llm_prompt_builds(monkeypatch):
    from langchain_core.runnables import RunnableLambda

    class FakeModel:
        def with_structured_output(self, schema):
            return RunnableLambda(lambda prompt: {"verdict": "cant_tell", "reason": "age unknown", "clauses": ["elig-1"]})

    case = runner.load_cases("development")[0]
    result = e4.LLMDirectChecker(FakeModel()).decide(e4.direct_input(case, case["candidate_scheme_ids"][0]))
    assert result.verdict == "cant_tell"


def test_a_fixed_questionnaire_reaches_the_same_verdicts():
    planned = run_eval.load_config(ROOT / "tests" / "evaluation" / "configs" / "c0_fixed_workflow.json")
    fixed = run_eval.load_config(ROOT / "tests" / "evaluation" / "configs" / "c0_fixed_questionnaire.json")
    _, a = run_eval.run(planned, "development", limit=6, quiet=True)
    _, b = run_eval.run(fixed, "development", limit=6, quiet=True)
    assert a["verdict_accuracy"] == b["verdict_accuracy"] == 1.0
