"""Structure of the eligibility gold set, and rule-engine agreement on its development split.

The held-out split is only structure-checked here: its verdicts are compared with the
system once, in the final evaluation, so they cannot steer rule or prompt changes.
"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_eligibility_gold", ROOT / "tests" / "evaluation" / "check_eligibility_gold.py")
gold = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gold)

RECORDS = gold.load_records()


@pytest.mark.parametrize("split", gold.SPLITS)
def test_cases_are_well_formed_and_consistent(split):
    cases = gold.load_cases(split)
    assert cases
    assert all(case["split"] == split for case in cases)
    assert [msg for case in cases for msg in gold.problems(case, RECORDS)] == []


def test_splits_are_disjoint_and_keep_families_together():
    dev, held = gold.load_cases("development"), gold.load_cases("held_out")
    assert len(dev) + len(held) >= 60
    assert {c["case_id"] for c in dev}.isdisjoint({c["case_id"] for c in held})
    assert {c["family_id"] for c in dev}.isdisjoint({c["family_id"] for c in held})


def test_language_versions_share_their_source_profile_and_labels():
    cases = {c["case_id"]: c for split in gold.SPLITS for c in gold.load_cases(split)}
    variants = [c for c in cases.values() if c.get("variant_of")]
    assert {c["language"] for c in variants} >= {"hi", "mr"}
    for case in variants:
        source = cases[case["variant_of"]]
        assert case["hidden_profile"] == source["hidden_profile"]
        assert case["expected"] == source["expected"]


def test_no_identifiers_in_cases():
    text = "".join((ROOT / "tests/evaluation/eligibility_gold_v1" / s / "cases.jsonl").read_text()
                   for s in gold.SPLITS)
    import re
    assert not re.search(r"\b\d{4}\s?\d{4}\s?\d{4}\b", text), "looks like an Aadhaar number"


def test_rule_engine_matches_gold_on_development_split():
    assert gold.compare(gold.load_cases("development"), RECORDS) == []
