import json
import subprocess
import sys
from pathlib import Path

from graph import mock_tools
from graph.workflow import build_graph

ROOT = Path(__file__).resolve().parents[1]
PMSBY_OK = {"has_bank_account": True, "age": 40, "consents_to_auto_debit": True}


def run(citizen, scheme_ids, include_draft):
    payload = {"simulated_citizen": citizen, "scheme_ids": scheme_ids, **({"include_draft": True} if include_draft else {})}
    return build_graph().invoke(payload, {"configurable": {"thread_id": "t"}})


def test_second_scheme_rules_are_valid_cited_drafts():
    record = json.loads((ROOT / "data/rules/C02.json").read_text())
    assert {r["status"] for r in record["rules"]} == {"draft"}
    assert {r["clause_id"] for r in record["rules"]} <= {c["clause_id"] for c in record["clauses"]}
    assert mock_tools.search_schemes({}, ["C02"]) == ["C02"]
    assert "C02" not in mock_tools.search_schemes({})


def test_without_the_flag_draft_rules_fail_closed():
    state = run(PMSBY_OK, ["C02"], False)
    assert state["verdicts"]["C02"]["verdict"] == "cant_tell"


def test_preview_evaluates_draft_rules_but_never_drafts_or_submits():
    state = run(PMSBY_OK, ["C02"], True)
    assert state["verdicts"]["C02"]["verdict"] == "eligible"
    assert "__interrupt__" not in state and not state.get("application") and not state.get("submission")


def test_preview_rules_for_c02_at_the_age_limits():
    verdict = lambda age: run({**PMSBY_OK, "age": age}, ["C02"], True)["verdicts"]["C02"]["verdict"]
    assert [verdict(17), verdict(18), verdict(70), verdict(71)] == [
        "not_eligible", "eligible", "eligible", "not_eligible"]


def test_preview_does_not_change_the_stored_rules():
    run(PMSBY_OK, ["C02"], True)
    assert {r["status"] for r in json.loads((ROOT / "data/rules/C02.json").read_text())["rules"]} == {"draft"}


def test_preview_intake_asks_only_for_the_rule_fields():
    state = run(PMSBY_OK, ["C02"], True)
    assert set(state["profile"]) == {"has_bank_account", "age", "consents_to_auto_debit"}


def test_cli_preview_prints_banner_and_verdict():
    result = subprocess.run(
        [sys.executable, "-m", "graph.run", "--include-draft", "--scheme-id", "C02", "--citizen", json.dumps(PMSBY_OK)],
        cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "DRAFT PREVIEW" in result.stdout and "Eligible" in result.stdout
    assert "Preview only; no application drafted." in result.stdout and "Mock submission" not in result.stdout
