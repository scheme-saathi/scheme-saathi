import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from servers.rule_engine.rules import Verdict, evaluate
from servers.rule_engine.scheme import SchemeRecord, live_conditions

EXAMPLE = Path(__file__).resolve().parents[1] / "data" / "schemes" / "SYNTH-PENSION-001.json"
PROFILE = {"age": 62, "is_widow": True, "income": 250000}


def load():
    return json.loads(EXAMPLE.read_text())


def test_example_validates():
    SchemeRecord.model_validate(load())


def test_rule_citing_unknown_clause_is_rejected():
    data = load()
    data["rules"][0]["clause_id"] = "cl-99"
    with pytest.raises(ValidationError):
        SchemeRecord.model_validate(data)


def test_draft_rules_do_not_decide():
    data = load()
    for r in data["rules"]:
        r["status"] = "draft"
    scheme = SchemeRecord.model_validate(data)
    assert evaluate(PROFILE, live_conditions(scheme)).verdict == Verdict.CANT_TELL


def test_no_reviewed_rules_gives_cant_tell():
    scheme = SchemeRecord.model_validate(load())
    scheme.rules = []
    assert evaluate(PROFILE, live_conditions(scheme)).verdict == Verdict.CANT_TELL


def test_reviewed_rules_return_cited_eligible_result():
    scheme = SchemeRecord.model_validate(load())
    result = evaluate(PROFILE, live_conditions(scheme))

    assert result.verdict == Verdict.ELIGIBLE
    assert result.missing_fields == []
    assert {clause.clause_id for clause in result.citations} == {"cl-1", "cl-2"}


def test_failed_condition_decides_not_eligible_even_if_another_fact_is_missing():
    scheme = SchemeRecord.model_validate(load())
    result = evaluate({"age": 59}, live_conditions(scheme))

    assert result.verdict == Verdict.NOT_ELIGIBLE
    assert result.missing_fields == ["income", "is_widow"]


def test_missing_fact_gives_cant_tell_and_names_field():
    scheme = SchemeRecord.model_validate(load())
    result = evaluate({"age": 62, "is_widow": True}, live_conditions(scheme))

    assert result.verdict == Verdict.CANT_TELL
    assert result.missing_fields == ["income"]
    assert result.unresolved_fields == ["income"]


def test_mixed_review_status_fails_closed():
    data = load()
    data["rules"][0]["status"] = "draft"
    scheme = SchemeRecord.model_validate(data)

    assert evaluate(PROFILE, live_conditions(scheme)).verdict == Verdict.CANT_TELL


def test_invalid_profile_type_is_unknown_not_coerced():
    scheme = SchemeRecord.model_validate(load())
    result = evaluate({**PROFILE, "age": "62"}, live_conditions(scheme))

    assert result.verdict == Verdict.CANT_TELL
    assert result.missing_fields == []
    assert result.unresolved_fields == ["age"]


def test_any_logic_accepts_one_satisfied_alternative():
    data = load()
    data["rule_logic"] = "any"
    scheme = SchemeRecord.model_validate(data)
    result = evaluate({"age": 62, "is_widow": False, "income": 400000}, live_conditions(scheme))

    assert result.verdict == Verdict.ELIGIBLE


@pytest.mark.parametrize(
    ("operator", "value", "actual", "expected"),
    [
        ("eq", 4, 4, Verdict.ELIGIBLE),
        ("ne", 4, 5, Verdict.ELIGIBLE),
        ("gt", 4, 5, Verdict.ELIGIBLE),
        ("gte", 4, 4, Verdict.ELIGIBLE),
        ("lt", 4, 3, Verdict.ELIGIBLE),
        ("lte", 4, 4, Verdict.ELIGIBLE),
        ("in", ["A", "B"], "A", Verdict.ELIGIBLE),
        ("not_in", ["A", "B"], "C", Verdict.ELIGIBLE),
    ],
)
def test_supported_operators(operator, value, actual, expected):
    data = load()
    data["rules"] = [
        {"field": "fact", "op": operator, "value": value, "clause_id": "cl-1", "status": "reviewed"}
    ]
    scheme = SchemeRecord.model_validate(data)

    assert evaluate({"fact": actual}, live_conditions(scheme)).verdict == expected
