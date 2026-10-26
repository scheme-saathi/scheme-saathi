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
