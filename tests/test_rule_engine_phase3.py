"""Phase 3 of docs/rule-fix-plan.md: engine and intake changes that several schemes need."""
from datetime import date

import pytest
from pydantic import ValidationError

from agents.intake import profile_model
from graph import tools
from graph.agent_workflow import _intake_question_node
from servers.rule_engine.ages import derive_age_fields
from servers.rule_engine.rules import evaluate
from servers.rule_engine.scheme import SHARED_VALUES, Rule, RuleSet, SchemeRecord
from servers.rule_engine.server import get_field_specs
from tests.test_agent_workflow import build_agents


# 3.1 applicant_type (decision F1)
def test_schemes_for_organisations_are_left_out_of_the_citizen_list():
    assert "C30" not in tools.search_schemes({})
    assert tools.search_schemes({}, ["C30"]) == ["C30"]  # an operator can still ask for it by id
    assert "C10" in tools.search_schemes({})  # mixed schemes stay


# 3.2 shared values (decision F2)
def _record(value):
    return {"scheme_id": "X", "name": "x", "level": "state", "source": {"url": "https://x", "collected_on": "d"},
            "clauses": [{"clause_id": "c", "text": "t"}],
            "rules": [{"field": "social_category", "op": "in", "value": value, "clause_id": "c"}]}


def test_rule_values_must_use_the_shared_spelling():
    SchemeRecord.model_validate(_record(["VJ-A", "OBC"]))
    with pytest.raises(ValidationError, match="field_values.json"):
        SchemeRecord.model_validate(_record(["VJNT"]))


def test_intake_offers_the_whole_shared_list():
    spec = get_field_specs(["M18"], include_draft=True)["data"]["social_category"]
    assert spec == {"type": "str", "known_values": SHARED_VALUES["social_category"]}


# 3.3 citations
def test_a_passing_or_rule_cites_the_first_condition_that_held():
    rule = Rule(field="a", op="eq", value=True, clause_id="c1", status="reviewed",
                or_conditions=[{"field": "b", "op": "eq", "value": True, "clause_id": "c2"}])
    rules = RuleSet(rules=[rule], clauses=[{"clause_id": "c1", "text": "x"}, {"clause_id": "c2", "text": "y"}],
                    ready=True)
    cited = lambda profile: [c.clause_id for c in evaluate(profile, rules).citations]
    assert cited({"a": False, "b": True}) == ["c2"]
    assert cited({"a": True, "b": True}) == ["c1"]  # one reason is enough: the rule's own condition
    assert cited({"a": False, "b": False}) == ["c1", "c2"]  # a failing rule cites everything it tried


# 3.4 income period
def test_a_yes_no_tax_question_is_not_asked_per_year():
    agents = build_agents()
    state = {"request": "x", "shortlist": ["C04"],
             "verdicts": {"C04": {"verdict": "cant_tell", "unresolved_fields": ["is_or_was_income_tax_payer"]}}}
    _intake_question_node(agents, state)
    assert agents.intake.asked[-1].field == "is_or_was_income_tax_payer"
    assert agents.intake.asked[-1].period is None


# 3.5 ages from one date of birth
TODAY = date(2026, 11, 9)


@pytest.mark.parametrize("born, age, months, nearer", [
    ("1956-11-09", 70, 840, 70),   # birthday today
    ("1956-11-10", 69, 839, 70),   # 11 months past 69: nearer 70
    ("1957-05-09", 69, 834, 70),   # exactly six months past: nearer the next birthday
    ("1957-05-10", 69, 833, 69),
    ("2009-05-09", 17, 210, 18),   # 17.5 years
])
def test_ages_are_worked_out_from_the_date_of_birth(born, age, months, nearer):
    out = derive_age_fields({"date_of_birth": born}, TODAY)
    assert (out["age"], out["age_in_months"], out["age_nearer_birthday"]) == (age, months, nearer)


@pytest.mark.parametrize("profile", [{}, {"date_of_birth": "5 March 1962"}, {"date_of_birth": "2027-01-01"},
                                     {"date_of_birth": 1962}])
def test_a_missing_or_bad_date_adds_nothing(profile):
    assert derive_age_fields(profile, TODAY) == profile


def test_a_stated_age_wins_over_the_derived_one():
    assert derive_age_fields({"date_of_birth": "1956-11-09", "age": 69}, TODAY)["age"] == 69


def test_c02_is_decided_from_the_date_of_birth_alone():
    profile = {"has_bank_account": True, "consents_to_auto_debit": True, "date_of_birth": "1990-01-01"}
    assert tools.evaluate_scheme(profile, "C02")["verdict"] == "eligible"


def test_intake_asks_for_the_date_of_birth_not_age_nearer_birthday():
    verdicts = {"C02": {"verdict": "cant_tell", "unresolved_fields": ["age_nearer_birthday"]}}
    assert tools.next_question(verdicts) == "date_of_birth"
    assert tools.next_question(verdicts, declined=["date_of_birth"]) == "age_nearer_birthday"  # fallback
    assert tools.field_specs(["C02"])["date_of_birth"] == {"type": "date", "known_values": []}


def test_a_date_of_birth_must_be_iso():
    model = profile_model({"date_of_birth": {"type": "date", "known_values": []}})
    assert model.model_validate({"date_of_birth": "1962-03-05"}).date_of_birth == "1962-03-05"
    with pytest.raises(ValidationError):
        model.model_validate({"date_of_birth": "5 March 1962"})
