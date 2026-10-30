import json

from servers.schemes_kb.check_retrieval import approved_schemes, check, rule_record_ids

SCHEMES = {"A1": "Alpha Yojana", "B2": "Beta Yojana"}


def test_check_passes_and_fails_by_rank():
    search = lambda q, k, m: ["A1"] if q == "Alpha Yojana" else ["A1", "X9"]
    rows = check(search, SCHEMES, [], 5, "hybrid")
    assert [(r["check"], r["ok"]) for r in rows] == [("find A1 by name", True), ("find B2 by name", False)]
    assert "rank 1" in rows[0]["detail"] and "not in top 5" in rows[1]["detail"]


def test_rule_records_need_an_indexed_scheme():
    rows = check(lambda q, k, m: list(SCHEMES), SCHEMES, ["A1", "ZZ"], 5, "vector")
    assert [r["ok"] for r in rows if r["check"].startswith("rule record")] == [True, False]


def test_approved_schemes_skips_drafts_and_rule_fixtures(tmp_path):
    (tmp_path / "ok.json").write_text(json.dumps({"scheme_id": "A", "name": "N", "sections": {}, "review_status": "approved"}))
    (tmp_path / "draft.json").write_text(json.dumps({"scheme_id": "B", "name": "N", "sections": {}, "review_status": "draft"}))
    (tmp_path / "rules.json").write_text(json.dumps({"scheme_id": "C", "name": "N", "rules": []}))
    assert approved_schemes(tmp_path) == {"A": "N"}


def test_real_rule_records_are_listed():
    assert {"C02", "C10"} <= set(rule_record_ids())
