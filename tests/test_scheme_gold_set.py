import json
from pathlib import Path

from graph import mock_tools

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_IDS = {
    "C01", "C02", "C04", "C05", "C06", "C10", "C13", "C17",
    "C19", "C23", "C30", "C38", "M13", "M16", "M18",
}


def test_fifteen_hand_coded_scheme_records_are_source_linked_drafts():
    paths = sorted((ROOT / "data/rules").glob("*.json"))
    records = {record["scheme_id"]: record for record in (json.loads(path.read_text()) for path in paths)}
    assert set(records) == EXPECTED_IDS
    for record in records.values():
        clause_ids = {clause["clause_id"] for clause in record["clauses"]}
        assert record["source"]["url"].startswith("https://")
        assert record["source"]["collected_on"]
        assert record["rules"]
        assert all(rule["status"] == "draft" for rule in record["rules"])
        assert all(rule["clause_id"] in clause_ids for rule in record["rules"])


def test_all_fifteen_load_but_are_not_live_by_default():
    assert set(mock_tools.search_schemes({}, sorted(EXPECTED_IDS))) == EXPECTED_IDS
    assert "C01" not in mock_tools.search_schemes({})
    assert "M13" not in mock_tools.search_schemes({})


def test_each_new_record_can_be_preview_evaluated_when_its_rules_are_satisfied():
    new_ids = EXPECTED_IDS - {"C02", "C04", "C10"}
    for scheme_id in sorted(new_ids):
        record = mock_tools._load(scheme_id)
        profile = {}
        for rule in record.rules:
            if rule.op == "in":
                profile[rule.field] = rule.value[0]
            elif rule.op == "not_in":
                profile[rule.field] = "__not_listed__"
            else:
                profile[rule.field] = rule.value
        result = mock_tools.evaluate_scheme(profile, scheme_id, include_draft=True)
        assert result["verdict"] == "eligible", scheme_id
