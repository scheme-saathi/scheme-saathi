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
    assert run_eval.score_case(case, {"verdicts": {}})["per_scheme"]["C01"]["got"] == "missing"


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
