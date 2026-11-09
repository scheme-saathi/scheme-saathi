"""The evaluation runner: configs load, scoring is correct, and the C0 baseline runs end to end."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("run_eval", ROOT / "tests" / "evaluation" / "run_eval.py")
run_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_eval)

CONFIG_DIR = ROOT / "tests" / "evaluation" / "configs"


@pytest.mark.parametrize("path", sorted(CONFIG_DIR.glob("*.json")), ids=lambda p: p.stem)
def test_every_config_loads_and_names_a_known_system(path):
    config = run_eval.load_config(path)
    assert config["system"] in run_eval.SYSTEMS
    assert config["name"] == path.stem


def test_scoring_uses_only_candidate_schemes():
    case = {"candidate_scheme_ids": ["C01", "C02"],
            "expected": {"C01": {"verdict": "eligible"}, "C02": {"verdict": "not_eligible"}}}
    score = run_eval.score_case(case, {"verdicts": {"C01": "eligible", "C02": "cant_tell", "M19": "eligible"}})
    assert score["per_scheme"]["C01"]["correct"] and not score["per_scheme"]["C02"]["correct"]
    assert not score["case_correct"]
    assert score["unscored_schemes"] == ["M19"]
    assert run_eval.score_case(case, {"verdicts": {}})["per_scheme"]["C01"]["got"] == "not_evaluated"


def test_a_failed_case_is_reported_not_dropped(monkeypatch):
    def boom(case, config):
        raise RuntimeError("model timed out")
    monkeypatch.setitem(run_eval.SYSTEMS, "fixed_workflow", boom)
    rows, summary = run_eval.run(run_eval.load_config(CONFIG_DIR / "c0_fixed_workflow.json"), "development", limit=2)
    assert summary["errors"] == 2 and len(rows) == 2
    assert rows[0]["error"] == "RuntimeError: model timed out"


def test_c0_fixed_workflow_matches_gold_on_development(tmp_path):
    config = run_eval.load_config(CONFIG_DIR / "c0_fixed_workflow.json")
    rows, summary = run_eval.run(config, "development")
    assert summary["errors"] == 0
    assert summary["verdict_accuracy"] == 1.0, summary["wrong"]
    assert summary["language_consistency"]["pairs"] == summary["language_consistency"]["same_verdicts"]
    assert all(r["result"]["tool_calls"] > 0 for r in rows)
    out = run_eval.write_run(config, "development", rows, summary, runs_dir=tmp_path)
    written = json.loads((out / "summary.json").read_text())
    assert written["config"]["name"] == "c0_fixed_workflow" and written["summary"]["cases"] == 21


def test_held_out_needs_the_final_flag(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["run_eval.py", "--config", str(CONFIG_DIR / "c0_fixed_workflow.json"),
                                     "--split", "held_out"])
    with pytest.raises(SystemExit):
        run_eval.main()
    assert "final evaluation only" in capsys.readouterr().err


def test_a_checked_scheme_without_a_final_answer_is_not_a_verdict():
    case = {"candidate_scheme_ids": ["C13", "M13"],
            "expected": {"C13": {"verdict": "not_eligible"}, "M13": {"verdict": "not_eligible"}}}
    # intake stopped: the graph had a working verdict for C13, but the person was never told it
    result = run_eval.final_answer({"C13": "eligible", "C04": "cant_tell"}, confirmations=0, stopped_at="intake_stopped")
    assert result["verdicts"] == {}
    score = run_eval.score_case(case, result)
    assert score["per_scheme"]["C13"]["got"] == "no_final_answer" and score["per_scheme"]["C13"]["evaluated"]
    assert score["per_scheme"]["M13"]["got"] == "not_evaluated" and not score["per_scheme"]["M13"]["evaluated"]
    told = run_eval.final_answer({"C13": "not_eligible"}, confirmations=1, stopped_at="eligibility_checked")
    assert told["verdicts"] == {"C13": "not_eligible"}


@pytest.mark.parametrize("text", [
    # from the first C2 development run (F02c, F02d, F13b)
    "Yes, your grandmother can get a pension under the Indira Gandhi National Widow Pension Scheme (IGNWPS).",
    "Yes, there is a pension for your grandmother. Additionally, she may also qualify for the Sanjay Gandhi scheme.",
    "Yes, as a tenant farmer, you can get a Kisan Credit Card.",
    "आप इस योजना के लिए पात्र हैं।",
    "तुम्हाला ही मदत मिळू शकते.",
])
def test_eligibility_claims_outside_the_rule_engine_are_flagged(text):
    assert run_eval.eligibility_claims([{"role": "agent", "text": text}]) == [text]


@pytest.mark.parametrize("text", [
    "C06: eligible: All required reviewed conditions are satisfied. Rule citations: ...",
    "C38: not_eligible: The reviewed rule expression is not satisfied.",
    "Are you eligible for any other pension?",
    "I couldn't find this in the reviewed scheme documents.",
    "I can't finish the eligibility check without these details: age.",
])
def test_rule_engine_answers_questions_and_refusals_are_not_claims(text):
    assert run_eval.eligibility_claims([{"role": "agent", "text": text}]) == []


def test_rescore_brings_an_old_run_up_to_the_current_rules(tmp_path):
    case = run_eval.load_cases("development")[0]
    scheme = case["candidate_scheme_ids"][0]
    old = {"case_id": case["case_id"], "family_id": case["family_id"], "language": case["language"],
           "variant_of": None, "error": None, "latency_ms": 1.0,
           "result": {"verdicts": {scheme: case["expected"][scheme]["verdict"]}, "questions_asked": 1,
                      "confirmations": 0, "stopped_at": "intake_stopped",
                      "transcript": [{"role": "agent", "text": "Yes, you can get this pension."}]}}
    (tmp_path / "cases.jsonl").write_text(json.dumps(old) + "\n")
    (tmp_path / "summary.json").write_text(json.dumps(
        {"config": {"name": "c2_agent_team", "system": "agent_team", "scheme_selection": "system"},
         "split": "development", "summary": {}}))
    rows, summary = run_eval.rescore(tmp_path)
    assert rows[0]["score"]["per_scheme"][scheme]["got"] == "no_final_answer"
    assert summary["cases_with_unbacked_eligibility_claims"] == 1 and summary["shortlist_recall"] == 1.0
    assert (tmp_path / "summary_rescored.json").exists()


def test_the_workflows_offer_to_check_eligibility_is_not_a_claim():
    from graph.agent_workflow import CHECK_ELIGIBILITY_INSTEAD
    for text in CHECK_ELIGIBILITY_INSTEAD.values():
        assert run_eval.eligibility_claims([{"role": "agent", "text": text}]) == []
