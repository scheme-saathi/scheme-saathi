import json
from pathlib import Path

from graph import tools
from servers.rule_engine.server import _load_scheme

ROOT = Path(__file__).resolve().parents[1]
# Hand-coded and checked rule by rule against the scheme text by a person (Step 1, 7 Nov 2026);
# the gold standard for rule extraction.
GOLD_IDS = {
    "C01", "C02", "C04", "C05", "C06", "C10", "C13", "C17",
    "C19", "C23", "C30", "C38", "M13", "M16", "M18",
}
# AI-drafted, then checked by a person and fixed where needed (Step 4, 8 Nov 2026; Step 5, 9 Nov 2026).
STEP4_IDS = {"C03", "C14", "C29", "M01", "M02", "M19", "M20"}
STEP5_IDS = {
    "C07", "C09", "C11", "C15", "C16", "C18", "C21", "C22", "C24", "C25", "C26", "C27",
    "C28", "C31", "C32", "C33", "C36", "M05", "M06", "M07", "M08", "M09", "M10",
    "M11", "M12", "M14", "M21",
}
AI_DRAFTED_REVIEWED_IDS = STEP4_IDS | STEP5_IDS
EXPECTED_IDS = GOLD_IDS | AI_DRAFTED_REVIEWED_IDS  # every live (reviewed) scheme
# AI-drafted and not yet checked by a person, kept as draft (no live verdicts); none left after
# Step 5. A new AI-drafted rule set goes here until a person reviews it (data/rules/REVIEW_STATUS.md).
AI_DRAFTED_IDS: set[str] = set()


def test_rule_records_are_source_linked_with_the_expected_status():
    paths = sorted((ROOT / "data/rules").glob("*.json"))
    records = {record["scheme_id"]: record for record in (json.loads(path.read_text()) for path in paths)}
    assert set(records) == EXPECTED_IDS | AI_DRAFTED_IDS
    for record in records.values():
        clause_ids = {clause["clause_id"] for clause in record["clauses"]}
        assert record["source"]["url"].startswith("https://")
        assert record["source"]["collected_on"]
        assert record["rules"]
        expected_status = "reviewed" if record["scheme_id"] in EXPECTED_IDS else "draft"
        assert all(rule["status"] == expected_status for rule in record["rules"]), record["scheme_id"]
        assert all(rule["clause_id"] in clause_ids for rule in record["rules"])


def test_ai_drafted_rules_are_not_live_until_reviewed():
    # Draft handling itself is tested with a draft copy of C02 (tests/test_draft_preview.py).
    assert not set(tools.search_schemes({})) & AI_DRAFTED_IDS
    if AI_DRAFTED_IDS:
        assert set(tools.search_schemes({}, sorted(AI_DRAFTED_IDS), include_draft=True)) == AI_DRAFTED_IDS


def test_every_reviewed_scheme_is_live_by_default():
    assert set(tools.search_schemes({}, sorted(EXPECTED_IDS))) == EXPECTED_IDS
    assert set(tools.search_schemes({})) == EXPECTED_IDS | {"SYNTH-PENSION-001"}


def test_each_reviewed_record_evaluates_live_when_its_rules_are_satisfied():
    for scheme_id in sorted(EXPECTED_IDS):
        record = _load_scheme(scheme_id)
        profile = {}
        for rule in record.rules:
            # Fill each condition's field with a passing value unless an earlier rule set it;
            # a rule with alternatives then passes through whichever condition holds.
            for c in rule.conditions():
                if c.field in profile:
                    continue
                if c.op == "in":
                    profile[c.field] = c.value[0]
                elif c.op == "not_in":
                    profile[c.field] = "__not_listed__"
                elif c.op in {"gt", "lt"}:  # strict bounds: step just inside
                    profile[c.field] = c.value + (1 if c.op == "gt" else -1)
                elif c.op == "ne":
                    profile[c.field] = (not c.value) if isinstance(c.value, bool) else (
                        f"{c.value}__other" if isinstance(c.value, str) else c.value + 1)
                else:
                    profile[c.field] = c.value
        result = tools.evaluate_scheme(profile, scheme_id)
        assert result["verdict"] == "eligible", scheme_id


def test_c05_exclusions_reject_members_and_tax_payers():
    ok = {"is_unorganized_worker": True, "age": 30, "monthly_income": 12000,
          "has_savings_or_jandhan_account_with_ifsc": True, "is_income_tax_payer": False,
          "is_organized_sector_worker": False, "is_epfo_member": False, "is_nps_member": False,
          "is_esic_member": False, "is_nps_traders_member": False}
    verdict = lambda **c: tools.evaluate_scheme({**ok, **c}, "C05", include_draft=True)["verdict"]
    assert verdict() == "eligible"
    assert verdict(is_nps_traders_member=True) == "not_eligible"
    assert verdict(is_epfo_member=True) == "not_eligible"
    assert verdict(monthly_income=15001) == "not_eligible"
    assert verdict(age=41) == "not_eligible"

