"""Check the eligibility gold set and compare the rule engine with its human labels.

    python tests/evaluation/check_eligibility_gold.py --split development
    python tests/evaluation/check_eligibility_gold.py --split held_out   # final evaluation only

The gold labels were written by a person from the scheme source sentences, before
and independently of the engine. A mismatch is either a labelling error or a rule
bug; it is never fixed by copying the engine's verdict into the gold file.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from servers.rule_engine.rules import evaluate  # noqa: E402
from servers.rule_engine.scheme import SHARED_VALUES, SchemeRecord, live_conditions  # noqa: E402

GOLD_DIR = ROOT / "tests" / "evaluation" / "eligibility_gold_v1"
SPLITS = ("development", "held_out")
VERDICTS = {"eligible", "not_eligible", "cant_tell"}
ALLOWED_VALUES = {
    **{field: set(values) for field, values in SHARED_VALUES.items()},
    "farmer_applicant_category": {
        "individual owner cultivator", "joint borrower owner cultivator", "tenant farmer",
        "oral lessee", "sharecropper", "farmer self-help group",
        "farmer joint-liability group", "not a farmer",
    },
    "school_type": {"government", "government-aided", "private"},
    "state_of_residence": {"Maharashtra", "Assam", "Jammu and Kashmir", "Bihar", "Karnataka",
                           "Andaman and Nicobar Islands"},
}
BANK_FIELDS = (
    "has_individual_bank_or_post_office_account", "has_bank_account",
    "has_savings_account", "has_savings_or_jandhan_account_with_ifsc",
)


def load_records() -> dict[str, SchemeRecord]:
    records = {}
    for path in sorted((ROOT / "data" / "rules").glob("*.json")):
        record = SchemeRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))
        records[record.scheme_id] = record
    return records


def load_cases(split: str) -> list[dict]:
    path = GOLD_DIR / split / "cases.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def scheme_fields(record: SchemeRecord) -> list[str]:
    return list(dict.fromkeys(c.field for rule in record.rules for c in rule.conditions()))


def _type_ok(field: str, value: object, expected: object) -> bool:
    if value is None:
        return True
    if field in ALLOWED_VALUES:
        return value in ALLOWED_VALUES[field]
    if isinstance(expected, bool):
        return isinstance(value, bool)
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def problems(case: dict, records: dict[str, SchemeRecord]) -> list[str]:
    """Structural and consistency problems in one case (Step 2 rules 1-11)."""
    cid, p, out = case["case_id"], case["hidden_profile"], []
    needed = []
    for scheme_id in case["candidate_scheme_ids"]:
        if scheme_id not in records:
            out.append(f"{cid}: unknown scheme {scheme_id}")
            continue
        needed += scheme_fields(records[scheme_id])
    needed = list(dict.fromkeys(needed))
    if set(p) != set(needed):
        out.append(f"{cid}: profile fields differ from candidate-scheme fields: "
                   f"missing {sorted(set(needed) - set(p))}, extra {sorted(set(p) - set(needed))}")
    expected_values = {c.field: c.value for rec in records.values() for r in rec.rules for c in r.conditions()}
    for field, value in p.items():
        if field in expected_values and not _type_ok(field, value, expected_values[field]):
            out.append(f"{cid}: bad value {field}={value!r}")
    if set(case["expected"]) != set(case["candidate_scheme_ids"]):
        out.append(f"{cid}: expected verdicts must cover exactly the candidate schemes")
    for scheme_id, label in case["expected"].items():
        if label.get("verdict") not in VERDICTS:
            out.append(f"{cid}: bad verdict for {scheme_id}: {label.get('verdict')!r}")
    g = p.get
    if g("has_savings_or_jandhan_account_with_ifsc") is True and False in {g(b) for b in BANK_FIELDS if b in p}:
        out.append(f"{cid}: rule 1, bank-account fields disagree")
    if g("is_income_tax_payer") is True and g("is_or_was_income_tax_payer") is False:
        out.append(f"{cid}: rule 2, taxpayer now but never a taxpayer")
    if g("is_unorganized_worker") is True and g("is_organized_sector_worker") is True:
        out.append(f"{cid}: rule 3, both organised and unorganised")
    if g("is_widow") is False and g("is_remarried") is not None:
        out.append(f"{cid}: rule 5, remarriage answer for a non-widow")
    if g("is_widow") is True and g("is_woman_or_girl") is False:
        out.append(f"{cid}: rule 5, widow who is not a woman")
    if g("farmer_applicant_category") in {"not a farmer", "tenant farmer", "oral lessee", "sharecropper"} \
            and g("is_cultivable_landholding_farmer_family") is True:
        out.append(f"{cid}: rule 6, landholding for a non-owner")
    if g("has_tuberculosis") is False and (g("government_notification_on_or_after_2018_04_01") is not None
                                           or g("registered_or_notified_on_nikshay") is not None):
        out.append(f"{cid}: rule 8, TB details without TB")
    if g("is_building_or_construction_worker") is False and g("registered_with_mbocww_board") is True:
        out.append(f"{cid}: rule 9, board registration for a non-worker")
    if g("age_nearer_birthday") is not None and g("age") is not None \
            and g("age_nearer_birthday") not in (g("age"), g("age") + 1):
        out.append(f"{cid}: rule 11, age nearer birthday must be age or age + 1")
    return out


def compare(cases: list[dict], records: dict[str, SchemeRecord]) -> list[tuple]:
    """Return (case_id, scheme_id, gold, engine) for every disagreement."""
    mismatches = []
    for case in cases:
        for scheme_id in case["candidate_scheme_ids"]:
            engine = evaluate(case["hidden_profile"], live_conditions(records[scheme_id])).verdict.value
            gold = case["expected"][scheme_id]["verdict"]
            if engine != gold:
                mismatches.append((case["case_id"], scheme_id, gold, engine))
    return mismatches


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", choices=SPLITS, default="development")
    args = parser.parse_args()
    records, cases = load_records(), load_cases(args.split)
    found = [msg for case in cases for msg in problems(case, records)]
    mismatches = compare(cases, records)
    labels = sum(len(c["candidate_scheme_ids"]) for c in cases)
    print(f"{args.split}: {len(cases)} cases, {labels} verdicts, "
          f"{Counter(v['verdict'] for c in cases for v in c['expected'].values())}")
    for msg in found:
        print("PROBLEM", msg)
    print(f"rule engine agrees on {labels - len(mismatches)} of {labels}")
    for case_id, scheme_id, gold, engine in mismatches:
        print(f"MISMATCH {case_id} {scheme_id}: gold {gold}, engine {engine}")
    return 1 if found or mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
