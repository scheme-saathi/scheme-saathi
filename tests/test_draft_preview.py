import json
import subprocess
import sys
from pathlib import Path

import pytest

from graph import tools
from graph.workflow import build_graph
from servers.rule_engine import server as rule_server

ROOT = Path(__file__).resolve().parents[1]
PMSBY_OK = {"has_bank_account": True, "age": 40, "age_nearer_birthday": 40, "consents_to_auto_debit": True}
APY_OK = {"has_savings_account": True, "age": 30, "is_or_was_income_tax_payer": False,
          "consents_to_auto_debit": True}


@pytest.fixture
def draft_rule_records(tmp_path, monkeypatch):
    for scheme_id in ("C02", "C04"):
        record = json.loads((ROOT / f"data/rules/{scheme_id}.json").read_text())
        for rule in record["rules"]:
            rule["status"] = "draft"
        (tmp_path / f"{scheme_id}.json").write_text(json.dumps(record))
    monkeypatch.setattr(rule_server, "RULE_DIRS", [ROOT / "data/schemes", ROOT / "tests/fixtures", tmp_path])
    return tmp_path


def run(citizen, scheme_ids, include_draft):
    payload = {"simulated_citizen": citizen, "scheme_ids": scheme_ids, **({"include_draft": True} if include_draft else {})}
    return build_graph().invoke(payload, {"configurable": {"thread_id": "t"}})


def test_second_scheme_rules_are_valid_cited_drafts(draft_rule_records):
    record = json.loads((draft_rule_records / "C02.json").read_text())
    assert {r["status"] for r in record["rules"]} == {"draft"}
    assert {r["clause_id"] for r in record["rules"]} <= {c["clause_id"] for c in record["clauses"]}
    assert tools.search_schemes({}, ["C02"]) == ["C02"]
    assert "C02" not in tools.search_schemes({})


def test_without_the_flag_draft_rules_fail_closed(draft_rule_records):
    state = run(PMSBY_OK, ["C02"], False)
    assert state["verdicts"]["C02"]["verdict"] == "cant_tell"


def test_preview_evaluates_draft_rules_but_never_drafts_or_submits(draft_rule_records):
    state = run(PMSBY_OK, ["C02"], True)
    assert state["verdicts"]["C02"]["verdict"] == "eligible"
    assert "__interrupt__" not in state and not state.get("application") and not state.get("submission")


def test_preview_rules_for_c02_at_the_age_limits(draft_rule_records):
    # The lower limit uses completed years; the upper limit uses age nearer birthday.
    verdict = lambda age, nearer: run({**PMSBY_OK, "age": age, "age_nearer_birthday": nearer},
                                      ["C02"], True)["verdicts"]["C02"]["verdict"]
    assert [verdict(17, 17), verdict(18, 18), verdict(70, 70), verdict(70, 71)] == [
        "not_eligible", "eligible", "eligible", "not_eligible"]


def test_preview_does_not_change_the_stored_rules(draft_rule_records):
    run(PMSBY_OK, ["C02"], True)
    assert {r["status"] for r in json.loads((draft_rule_records / "C02.json").read_text())["rules"]} == {"draft"}


def test_preview_intake_asks_only_for_the_rule_fields(draft_rule_records):
    state = run(PMSBY_OK, ["C02"], True)
    # date_of_birth is asked first; this citizen has none, so age nearer birthday is asked next.
    assert set(state["profile"]) == {"has_bank_account", "age", "date_of_birth", "age_nearer_birthday",
                                     "consents_to_auto_debit"}


def test_cli_preview_prints_banner_and_verdict():
    result = subprocess.run(
        [sys.executable, "-m", "graph.run", "--include-draft", "--scheme-id", "C02", "--citizen", json.dumps(PMSBY_OK)],
        cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "DRAFT PREVIEW" in result.stdout and "Eligible" in result.stdout
    assert "Preview only; no application drafted." in result.stdout and "Mock submission" not in result.stdout


def test_apy_rules_are_valid_cited_drafts(draft_rule_records):
    record = json.loads((draft_rule_records / "C04.json").read_text())
    assert {rule["status"] for rule in record["rules"]} == {"draft"}
    assert {rule["clause_id"] for rule in record["rules"]} <= {
        clause["clause_id"] for clause in record["clauses"]
    }
    assert tools.search_schemes({}, ["C04"]) == ["C04"]
    assert "C04" not in tools.search_schemes({})


def test_apy_draft_preview_observes_age_and_tax_payer_rules(draft_rule_records):
    verdict = lambda **changes: run({**APY_OK, **changes}, ["C04"], True)["verdicts"]["C04"]["verdict"]
    assert [verdict(age=17), verdict(age=18), verdict(age=40), verdict(age=41)] == [
        "not_eligible", "eligible", "eligible", "not_eligible"
    ]
    assert verdict(is_or_was_income_tax_payer=True) == "not_eligible"
    assert verdict(consents_to_auto_debit=False) == "not_eligible"


def test_apy_drafts_fail_closed_without_preview_and_do_not_mutate(draft_rule_records):
    state = run(APY_OK, ["C04"], False)
    assert state["verdicts"]["C04"]["verdict"] == "cant_tell"
    run(APY_OK, ["C04"], True)
    record = json.loads((draft_rule_records / "C04.json").read_text())
    assert {rule["status"] for rule in record["rules"]} == {"draft"}
