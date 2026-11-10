"""The red-team suite (tests/redteam): its size, its categories, and what the defences stop.

Attacks that still get through are listed in tests/redteam/known_gaps.json with the reason.
A new gap fails this test, and so does a fixed one that stays on the list, so the list stays honest.
"""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("run_redteam", ROOT / "tests" / "redteam" / "run_redteam.py")
redteam = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(redteam)

KNOWN_GAPS = json.loads((ROOT / "tests" / "redteam" / "known_gaps.json").read_text(encoding="utf-8"))
ATTACKS = redteam.load("attacks.jsonl")
LEGITIMATE = redteam.load("benign.jsonl")
SLOW = {"approval_hash"}  # each case runs the whole graph


def test_the_suite_meets_the_brief():
    assert len(ATTACKS) >= 30
    assert len(LEGITIMATE) >= 20
    assert len({c["id"] for c in ATTACKS + LEGITIMATE}) == len(ATTACKS) + len(LEGITIMATE)
    assert len({a["category"] for a in ATTACKS}) >= 8


def test_every_case_names_a_runner_and_a_goal():
    for case in ATTACKS + LEGITIMATE:
        assert case["runner"] in redteam.RUNNERS, case["id"]
        assert case["goal"] and isinstance(case["params"], dict), case["id"]


def test_every_known_gap_is_a_real_attack():
    assert set(KNOWN_GAPS) <= {a["id"] for a in ATTACKS}
    assert all(KNOWN_GAPS.values())


@pytest.fixture(scope="module")
def results():
    rows = {}
    with redteam.environment():
        for kind, cases in (("attack", ATTACKS), ("legitimate", LEGITIMATE)):
            for case in cases:
                for on in (False, True):
                    if case["runner"] in SLOW and not on and case["id"] != "RT-057":
                        continue
                    rows[(case["id"], on)] = redteam.run_case(case, on)
    return rows


def test_no_runner_crashes(results):
    assert [k for k, r in results.items() if r["error"]] == []


def test_attacks_that_get_through_with_defences_on_are_exactly_the_known_gaps(results):
    through = {a["id"] for a in ATTACKS if results[(a["id"], True)]["went_through"]}
    assert through == set(KNOWN_GAPS)


def test_the_defences_do_not_block_legitimate_work(results):
    blocked = [c["id"] for c in LEGITIMATE if not results[(c["id"], True)]["went_through"]]
    assert blocked == []


def test_turning_a_defence_off_lets_its_attacks_through(results):
    for category in ("tool_permission", "write_capability", "agent_output", "data_path_injection",
                     "tool_budget", "rate_limit", "input_limits", "approval_edit", "rule_engine",
                     "household_isolation"):
        cases = [a for a in ATTACKS if a["category"] == category]
        off = sum(results[(a["id"], False)]["went_through"] for a in cases)
        on = sum(results[(a["id"], True)]["went_through"] for a in cases)
        assert off > on, category


def test_the_summary_reports_both_rates(results):
    rows = [{**r, "kind": "attack" if r["id"].startswith("RT") else "legitimate",
             "defences": "on" if on else "off"} for (_, on), r in results.items()]
    summary = redteam.summarise(rows, [a for a in ATTACKS], LEGITIMATE)
    assert summary["attack_success_defences_off"] > summary["attack_success_defences_on"]
    assert summary["legitimate_blocked_defences_on"] == 0.0
