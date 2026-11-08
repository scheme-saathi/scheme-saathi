import json
from pathlib import Path

from graph import tools
from servers.rule_engine.server import _load_scheme

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_IDS = {
    "C01", "C02", "C04", "C05", "C06", "C10", "C13", "C17",
    "C19", "C23", "C30", "C38", "M13", "M16", "M18",
    # AI-drafted from data/schemes and marked reviewed without a human check; see data/rules/REVIEW_NOTES.md
    "C03", "C07", "C09", "C11", "C14", "C15", "C16", "C18", "C21", "C22", "C24", "C25", "C26", "C27",
    "C28", "C29", "C31", "C32", "C33", "C36", "M01", "M02", "M05", "M06", "M07", "M08", "M09", "M10",
    "M11", "M12", "M14", "M19", "M20", "M21",
}


def test_fifteen_hand_coded_scheme_records_are_source_linked_and_reviewed():
    paths = sorted((ROOT / "data/rules").glob("*.json"))
    records = {record["scheme_id"]: record for record in (json.loads(path.read_text()) for path in paths)}
    assert set(records) == EXPECTED_IDS
    for record in records.values():
        clause_ids = {clause["clause_id"] for clause in record["clauses"]}
        assert record["source"]["url"].startswith("https://")
        assert record["source"]["collected_on"]
        assert record["rules"]
        assert all(rule["status"] == "reviewed" for rule in record["rules"])
        assert all(rule["clause_id"] in clause_ids for rule in record["rules"])


def test_all_fifteen_reviewed_schemes_are_live_by_default():
    assert set(tools.search_schemes({}, sorted(EXPECTED_IDS))) == EXPECTED_IDS
    assert set(tools.search_schemes({})) == EXPECTED_IDS | {"SYNTH-PENSION-001"}


def test_each_reviewed_record_evaluates_live_when_its_rules_are_satisfied():
    for scheme_id in sorted(EXPECTED_IDS):
        record = _load_scheme(scheme_id)
        profile = {}
        for rule in record.rules:
            if rule.op == "in":
                profile[rule.field] = rule.value[0]
            elif rule.op == "not_in":
                profile[rule.field] = "__not_listed__"
            elif rule.op in {"gt", "lt"}:  # strict bounds: step just inside
                profile[rule.field] = rule.value + (1 if rule.op == "gt" else -1)
            else:
                profile[rule.field] = rule.value
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

