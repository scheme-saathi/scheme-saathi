"""The rule extractor's inputs, the code scorer, and the runner (signature challenge A)."""
import importlib.util
import json
from pathlib import Path

import pytest

from agents.rule_extractor import INSTRUCTIONS, Extraction, RuleExtractor, instructions_with
from evaluation import rule_extraction as rx

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("run_rule_extraction", ROOT / "tests" / "evaluation" / "run_rule_extraction.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)
CONFIG = ROOT / "tests" / "evaluation" / "rule_extraction_configs" / "rx0_no_playbook.json"


def test_the_split_is_d1_and_uses_only_reviewed_rules():
    split = rx.load_split()
    assert len(split["development"]) == 34 and len(split["held_out"]) == 15
    assert not set(split["development"]) & set(split["held_out"])
    assert {"C01", "C02", "C04", "C06", "M13", "M18"} <= set(split["held_out"])  # the hand-coded gold
    for scheme_id in split["development"] + split["held_out"]:
        rx.load_gold(scheme_id)  # raises on any draft rule


@pytest.mark.parametrize("scheme_id", rx.load_split()["development"] + rx.load_split()["held_out"])
def test_the_gold_rules_written_as_a_draft_score_exactly(scheme_id):
    gold = rx.load_gold(scheme_id)
    clauses = rx.source_clauses(rx.load_scheme(scheme_id))
    result = rx.score(rx.gold_as_draft(gold, clauses), gold, clauses)
    assert result["scheme_exact"], result["errors"]


def test_the_extractor_sees_only_eligibility_and_exclusion_sentences():
    value = rx.extraction_input("M12")
    assert {c["clause_id"].split("-")[0] for c in value["clauses"]} == {"elig"}
    assert not any("Scheduled Caste" in c["text"] for c in value["clauses"])  # M12's det-1 is not shown
    assert {"field": "age", "type": "number", "known_values": []} in value["fields"]


GOLD = {"rule_logic": "all", "clauses": [{"clause_id": "elig-1", "text": "Age 18 to 40."},
                                         {"clause_id": "elig-2", "text": "BPL or income up to 21,000."},
                                         {"clause_id": "det-1", "text": "For SC families."}],
        "rules": [
            {"field": "age", "op": "gte", "value": 18, "clause_id": "elig-1", "status": "reviewed"},
            {"field": "age", "op": "lte", "value": 40, "clause_id": "elig-1", "status": "reviewed"},
            {"field": "household_below_bpl", "op": "eq", "value": True, "clause_id": "elig-2", "status": "reviewed",
             "or_conditions": [{"field": "annual_family_income", "op": "lte", "value": 21000}]},
            {"field": "social_category", "op": "eq", "value": "SC", "clause_id": "det-1", "status": "reviewed"},
        ]}
CLAUSES = [{"clause_id": "elig-1", "text": "Age 18 to 40."}, {"clause_id": "elig-2", "text": "BPL or income up to 21,000."}]
AGE_FROM = {"field": "age", "op": "gte", "value": 18, "clause_id": "elig-1"}
AGE_TO = {"field": "age", "op": "lte", "value": 40, "clause_id": "elig-1"}
BPL = {"field": "household_below_bpl", "op": "eq", "value": True, "clause_id": "elig-2",
       "or_conditions": [{"field": "annual_family_income", "op": "lte", "value": 21000, "clause_id": "elig-2"}]}


def errors(rules, logic="all"):
    return [e["type"] for e in rx.score({"rules": rules, "rule_logic": logic}, GOLD, CLAUSES)["errors"]]


@pytest.mark.parametrize("rules, logic, expected", [
    ([AGE_FROM, AGE_TO, BPL], "all", []),                                        # det-1 is out of section
    ([AGE_FROM, BPL], "all", ["missing_rule"]),
    ([AGE_FROM, AGE_TO, BPL, {"field": "is_widow", "op": "eq", "value": True, "clause_id": "elig-1"}], "all",
     ["extra_rule"]),
    ([AGE_FROM, {**AGE_TO, "op": "lt"}, BPL], "all", ["wrong_operator"]),
    ([AGE_FROM, {**AGE_TO, "value": 45}, BPL], "all", ["wrong_value"]),
    ([AGE_FROM, AGE_TO, {**BPL, "or_conditions": []}], "all", ["wrong_or"]),
    ([AGE_FROM, AGE_TO, {**BPL, "clause_id": "elig-1", "or_conditions": [{**BPL["or_conditions"][0], "clause_id": "elig-1"}]}],
     "all", ["wrong_clause"]),
    ([{**AGE_FROM, "field": "age_years"}, AGE_TO, BPL], "all", ["wrong_field"]),
    ([AGE_FROM, AGE_TO, BPL], "any", ["wrong_logic"]),
])
def test_each_error_is_named_by_type(rules, logic, expected):
    assert errors(rules, logic) == expected


def test_scores_count_conditions_and_out_of_section_rules():
    result = rx.score({"rules": [AGE_FROM, BPL]}, GOLD, CLAUSES)
    assert result["out_of_section_rules"] == 1 and result["gold_rules"] == 3
    assert result["condition_precision"] == 1.0 and result["condition_recall"] == 0.75
    assert result["exact_rules"] == 2 and not result["scheme_exact"]


def test_lessons_fill_their_slot_and_braces_are_escaped():
    assert "{lessons}" not in instructions_with([]) and "LESSONS" not in instructions_with([])
    filled = instructions_with(['"below" means lt {not a variable}'])
    assert "LESSONS FROM REVIEWED EXTRACTIONS" in filled and "{{not a variable}}" in filled
    assert INSTRUCTIONS.count("{lessons}") == 1


def test_the_extractor_returns_a_typed_draft():
    from langchain_core.runnables import RunnableLambda

    class FakeModel:
        def with_structured_output(self, schema):
            return RunnableLambda(lambda prompt: {"clauses": [
                {"clause_id": "elig-1", "rules": [AGE_FROM, AGE_TO], "note": ""},
                {"clause_id": "elig-2", "rules": [], "note": "a document, not a condition"}],
                "rule_logic": "all", "open_questions": []})

    result = RuleExtractor(FakeModel()).extract(rx.extraction_input("C11"))
    assert isinstance(result, Extraction) and [r.field for r in result.rules] == ["age", "age"]
    assert result.clause_notes == {"elig-2": "a document, not a condition"}


def test_the_extractor_caps_its_output_length():
    from langchain_openai import ChatOpenAI
    from agents.rule_extractor import MAX_OUTPUT_TOKENS

    model = ChatOpenAI(model="x", api_key="test-only", base_url="http://localhost:9")
    assert RuleExtractor(model)._model.max_tokens == MAX_OUTPUT_TOKENS


def test_the_runner_scores_drafts_and_never_writes_rules(tmp_path):
    before = {p.name: p.read_text() for p in (ROOT / "data" / "rules").glob("*.json")}

    def perfect(value, lessons):
        gold = rx.load_gold(value["scheme_id"])
        return rx.gold_as_draft(gold, value["clauses"])

    config = runner.load_config(CONFIG)
    rows, summary = runner.run(config, "development", limit=3, extract=perfect, quiet=True)
    assert summary["schemes"] == 3 and summary["scheme_exact_rate"] == 1.0 and summary["errors"] == 0
    out = runner.write_run(config, "development", rows, summary, runs_dir=tmp_path)
    assert json.loads((out / "summary.json").read_text())["summary"]["schemes"] == 3
    assert {p.name: p.read_text() for p in (ROOT / "data" / "rules").glob("*.json")} == before


def test_a_failed_extraction_is_reported_not_dropped():
    def boom(value, lessons):
        raise RuntimeError("model timed out")
    rows, summary = runner.run(runner.load_config(CONFIG), "development", limit=2, extract=boom, quiet=True)
    assert summary["errors"] == 2 and rows[0]["error"] == "RuntimeError: model timed out"
    assert rows[0]["score"]["errors"][0]["type"] == "missing_rule"


def test_held_out_needs_the_final_flag(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["run_rule_extraction.py", "--config", str(CONFIG), "--split", "held_out"])
    with pytest.raises(SystemExit):
        runner.main()
    assert "final evaluation only" in capsys.readouterr().err
