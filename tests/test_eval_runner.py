"""The evaluation runner: configs load, scoring is correct, and the C0 baseline runs end to end."""
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("run_eval", ROOT / "tests" / "evaluation" / "run_eval.py")
run_eval = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = run_eval
_spec.loader.exec_module(run_eval)

CONFIG_DIR = ROOT / "tests" / "evaluation" / "configs"
_e1_report_spec = importlib.util.spec_from_file_location(
    "e1_report", ROOT / "tests" / "evaluation" / "e1_report.py"
)
e1_report = importlib.util.module_from_spec(_e1_report_spec)
sys.modules[_e1_report_spec.name] = e1_report
_e1_report_spec.loader.exec_module(e1_report)


@pytest.mark.parametrize("path", sorted(CONFIG_DIR.glob("*.json")), ids=lambda p: p.stem)
def test_every_config_loads_and_names_a_known_system(path):
    config = run_eval.load_config(path)
    assert config["system"] in run_eval.SYSTEMS
    assert config["name"] == path.stem


def test_e1_c1_is_a_real_system_and_shares_the_configured_budget():
    assert run_eval.SYSTEMS["single_agent"] is run_eval.run_single_agent
    for path in (CONFIG_DIR / "c0_fixed_workflow.json",
                 CONFIG_DIR / "c1_single_agent.json",
                 CONFIG_DIR / "c2_agent_team.json"):
        assert run_eval.load_config(path)["tool_call_limit"] == 150


def test_shared_model_environment_sets_both_agent_roles_and_restores(monkeypatch):
    monkeypatch.setenv("SUPERVISOR_MODEL", "old-supervisor")
    monkeypatch.delenv("SPECIALIST_MODEL", raising=False)
    with run_eval.shared_model_environment({"model": "same-model"}):
        assert os.environ["SUPERVISOR_MODEL"] == os.environ["SPECIALIST_MODEL"] == "same-model"
    assert os.environ["SUPERVISOR_MODEL"] == "old-supervisor"
    assert "SPECIALIST_MODEL" not in os.environ


def test_single_agent_runner_scores_the_rule_engine_tool_result(monkeypatch):
    from langchain_core.messages import AIMessage, ToolMessage
    import langgraph.prebuilt
    import agents.model_factory
    import graph.baseline

    class FakeAgent:
        def invoke(self, *_args, **_kwargs):
            return {"messages": [
                AIMessage(content="", tool_calls=[{
                    "id": "call-1", "name": "check_eligibility", "args": {"scheme_id": "C01"}
                }]),
                ToolMessage(
                    content='{"verdict":"eligible"}',
                    tool_call_id="call-1",
                    name="check_eligibility",
                ),
                AIMessage(content="C01: eligible, according to the rule engine."),
            ]}

    def create_model(_role):
        assert os.environ["SUPERVISOR_MODEL"] == os.environ["SPECIALIST_MODEL"] == "fake/model"
        return object()

    monkeypatch.setattr(agents.model_factory, "create_chat_model", create_model)
    monkeypatch.setattr(
        graph.baseline, "build_tools",
        lambda _profile: [object(), object(), object(), object()],
    )

    def create_agent(_model, tools, **_kwargs):
        assert len(tools) == 4
        return FakeAgent()

    monkeypatch.setattr(langgraph.prebuilt, "create_react_agent", create_agent)
    case = {
        "case_id": "fake",
        "opening_message": "Check the pension rules.",
        "candidate_scheme_ids": ["C01"],
        "hidden_profile": {"age": 62},
    }

    result = run_eval.run_single_agent(case, {"model": "fake/model", "tool_call_limit": 150})

    assert result["verdicts"] == {"C01": "eligible"}
    assert result["unbacked_eligibility_claims"] == []
    assert result["estimated_cost_usd"] is None


def _e1_run(system, model="openai/same-model", budget=150, split="held_out", tokens=None, accuracy=1.0,
            name="run"):
    summary = {
        "verdict_accuracy": accuracy, "case_success_rate": accuracy, "answered_rate": 1.0,
        "accuracy_when_answered": 1.0, "shortlist_recall": 1.0, "cases_with_unbacked_eligibility_claims": 0,
        "cases_with_fact_errors": 0, "questions_per_case": {"mean": 5.0}, "tool_calls_per_case": {"mean": 10.0},
        "latency_ms": {"median": 1000.0, "p95": 2000.0}, "estimated_cost_usd_per_case": 0.001, "errors": 0,
        "tokens_by_model": tokens or {},
    }
    return {"name": name, "rows": [{"case_id": "F02a"}], "summary": summary,
            "meta": {"config": {"system": system, "model": model, "tool_call_limit": budget},
                     "split": split, "git_commit": "abc1234"}}


def _e1_runs(**c2):
    agent = {"openai/same-model": {"total_tokens": 10}}
    return {
        "c0": [_e1_run("fixed_workflow")],
        "c1": [_e1_run("single_agent", tokens=agent) for _ in range(3)],
        "c2": [_e1_run("agent_team", tokens={**agent, "anthropic/citizen": {"total_tokens": 5}}, **c2)
               for _ in range(3)],
    }


def test_e1_report_rejects_different_budgets_and_models():
    runs = _e1_runs()
    runs["c2"][1] = _e1_run("agent_team", budget=400)
    with pytest.raises(ValueError, match="same explicit MCP"):
        e1_report.validate(runs)
    runs["c2"][1] = _e1_run("agent_team", model="different/model")
    with pytest.raises(ValueError, match="same explicit model"):
        e1_report.validate(runs)
    runs = _e1_runs()
    runs["c1"][0] = _e1_run("single_agent", split="development")
    with pytest.raises(ValueError, match="same gold-set split"):
        e1_report.validate(runs)


def test_e1_report_checks_the_models_that_actually_used_tokens():
    runs = _e1_runs()
    # a router or supervisor quietly on another model (e.g. ROUTER_MODEL set in .env)
    runs["c1"][2] = _e1_run("single_agent", tokens={"openai/same-model-2024-07-18": {}, "openai/other": {}})
    with pytest.raises(ValueError, match="C1 run .* used other models: openai/other"):
        e1_report.validate(runs)
    runs = _e1_runs()
    runs["c2"][0] = _e1_run("agent_team", tokens={"openai/same-model": {}, "anthropic/citizen": {},
                                                  "openai/router": {}})
    with pytest.raises(ValueError, match="more than one model besides"):
        e1_report.validate(runs)
    runs = _e1_runs()
    runs["c2"][2] = _e1_run("agent_team", tokens={"openai/same-model": {}, "meta-llama/other-citizen": {}})
    with pytest.raises(ValueError, match="same simulated citizen"):
        e1_report.validate(runs)


def test_e1_report_gives_the_spread_over_repeated_runs():
    runs = _e1_runs()
    for run, accuracy in zip(runs["c2"], (0.5, 0.6, 0.7)):
        run["summary"]["verdict_accuracy"] = accuracy
    data = e1_report.report(runs)
    c2 = data["measures"]["Verdict accuracy"]["c2"]
    assert (c2["mean"], c2["min"], c2["max"], c2["runs"]) == (0.6, 0.5, 0.7, 3)
    assert data["citizen_model"] == "anthropic/citizen"
    assert data["notes"] == []
    text = e1_report.markdown(data)
    assert "| Verdict accuracy | 1 | 1 (all runs) | 0.6 (0.5–0.7) |" in text

    runs["c2"] = runs["c2"][:2]
    assert any("C2 has 2 run(s)" in note for note in e1_report.report(runs)["notes"])


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
    assert summary["estimated_cost_usd_per_case"] == 0.0
    assert summary["unpriced_model_cases"] == 0


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


def test_the_c2_config_raises_the_rate_limit_for_the_simulated_citizen():
    """Four development cases stopped at validation_error: the citizen replies faster than 10 a minute."""
    from types import SimpleNamespace
    from agents.supervisor import InputValidator
    config = run_eval.load_config(CONFIG_DIR / "c2_agent_team.json")
    agents = SimpleNamespace(supervisor=SimpleNamespace(input_validator=InputValidator()))
    run_eval.apply_rate_limit(agents, config)
    limiter = agents.supervisor.input_validator.rate_limiter
    assert all(limiter.is_allowed("eval-runner") for _ in range(50))
    untouched = SimpleNamespace(supervisor=SimpleNamespace(input_validator=InputValidator()))
    run_eval.apply_rate_limit(untouched, {})
    assert untouched.supervisor.input_validator.rate_limiter.max_requests == 10


def test_the_heartbeat_reports_progress_while_a_case_runs():
    lines = []
    beat = run_eval.Heartbeat(total=4, every=60, emit=lines.append)
    assert beat.line().startswith("... still running: 0/4 cases done")
    beat.case("F04a")
    beat.finished()
    beat.case("F04b")
    line = beat.line()
    assert "1/4 cases done" in line and "F04b running for" in line and "left" in line


def test_a_slow_case_gets_heartbeat_lines(monkeypatch, capsys):
    import time as _time
    def slow(case, config):
        _time.sleep(0.35)
        return {"verdicts": {}, "questions_asked": 0}
    monkeypatch.setitem(run_eval.SYSTEMS, "fixed_workflow", slow)
    run_eval.run(run_eval.load_config(CONFIG_DIR / "c0_fixed_workflow.json"), "development", limit=1,
                 heartbeat_seconds=0.1)
    err = capsys.readouterr().err
    assert "still running: 0/1 cases done" in err and "[1/1]" in err
