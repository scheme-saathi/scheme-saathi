"""One-level OR in the rule engine, and the Step 4 fixes to seven AI-drafted rule sets.

M01, M19, C29 and M20 were changed again in Phase 1 of docs/rule-fix-plan.md and are draft
until a person signs them off, so they are evaluated with include_draft."""
import pytest

from graph import tools
from servers.rule_engine.rules import evaluate
from servers.rule_engine.scheme import Rule, RuleSet

ANY_OF = Rule(field="household_below_bpl", op="eq", value=True, clause_id="c", status="reviewed",
              or_conditions=[{"field": "annual_family_income", "op": "lte", "value": 21000}])


@pytest.mark.parametrize("profile, verdict", [
    ({"household_below_bpl": True}, "eligible"),                                   # own condition holds
    ({"household_below_bpl": False, "annual_family_income": 18000}, "eligible"),   # alternative holds
    ({"household_below_bpl": False, "annual_family_income": 21001}, "not_eligible"),
    ({"household_below_bpl": False}, "cant_tell"),                                 # alternative unknown
    ({}, "cant_tell"),
])
def test_a_rule_with_alternatives_is_a_three_valued_or(profile, verdict):
    rules = RuleSet(rules=[ANY_OF], clauses=[{"clause_id": "c", "text": "x"}], ready=True)
    assert evaluate(profile, rules).verdict.value == verdict


def test_only_facts_that_can_still_settle_the_rule_are_asked():
    result = tools.evaluate_scheme({"is_indian_citizen": True, "is_maharashtra_resident": True,
                                    "household_below_bpl": False, "niradhar_category": "destitute widow"}, "M01", include_draft=True)
    assert result["verdict"] == "cant_tell"
    assert result["missing_fields"] == ["annual_family_income"]  # BPL is known to be false
    assert tools.next_question({"M01": result}) == "annual_family_income"


M01_WIDOW = {"is_indian_citizen": True, "is_maharashtra_resident": True, "household_below_bpl": True,
             "niradhar_category": "destitute widow", "age": 70}


@pytest.mark.parametrize("changes, verdict", [
    ({}, "eligible"),                                                    # a widow has no age limit
    ({"household_below_bpl": False, "annual_family_income": 21000}, "eligible"),
    ({"household_below_bpl": False, "annual_family_income": 21001}, "not_eligible"),
    ({"niradhar_category": "destitute man or woman below 65", "age": 64}, "eligible"),
    ({"niradhar_category": "destitute man or woman below 65", "age": 65}, "not_eligible"),
    ({"niradhar_category": "orphan child", "age": 17}, "eligible"),
    ({"niradhar_category": "orphan child", "age": 18}, "not_eligible"),
    ({"niradhar_category": "orphan child", "age": None}, "cant_tell"),
    ({"niradhar_category": "unmarried woman above 35", "age": 36}, "eligible"),
    ({"niradhar_category": "unmarried woman above 35", "age": 35}, "not_eligible"),
    ({"niradhar_category": "unable to sustain due to a serious disease (e.g. tb, cancer, aids, leprosy)"}, "eligible"),
])
def test_m01_or_income_and_the_below_65_limit(changes, verdict):
    assert tools.evaluate_scheme({**M01_WIDOW, **changes}, "M01", include_draft=True)["verdict"] == verdict


@pytest.mark.parametrize("changes, verdict", [
    ({}, "eligible"),
    ({"age": 64}, "not_eligible"),
    ({"household_below_bpl": False, "annual_family_income": 21000}, "eligible"),
    ({"household_below_bpl": False, "annual_family_income": 25000}, "not_eligible"),
])
def test_m02(changes, verdict):
    base = {"is_indian_citizen": True, "years_resident_in_maharashtra": 15, "is_destitute": True,
            "age": 65, "household_below_bpl": True}
    assert tools.evaluate_scheme({**base, **changes}, "M02")["verdict"] == verdict


@pytest.mark.parametrize("changes, verdict", [
    ({"disability_percent": 81}, "eligible"),
    ({"disability_percent": 80, "is_person_with_dwarfism": False}, "not_eligible"),
    ({"disability_percent": 80}, "cant_tell"),  # dwarfism, the alternative, is still unknown
    ({"disability_percent": 40, "is_person_with_dwarfism": True}, "eligible"),
    ({"disability_percent": 40, "is_person_with_dwarfism": False}, "not_eligible"),
    # a person with dwarfism who does not call it a disability still qualifies (elig-6)
    ({"has_disability": False, "disability_percent": 0, "is_person_with_dwarfism": True}, "eligible"),
    ({"has_disability": False, "disability_percent": 0, "is_person_with_dwarfism": False}, "not_eligible"),
])
def test_c29_more_than_80_percent_or_dwarfism(changes, verdict):
    base = {"age": 30, "resides_in_india": True, "has_disability": True, "household_below_bpl": True}
    assert tools.evaluate_scheme({**base, **changes}, "C29", include_draft=True)["verdict"] == verdict


M19_OK = {"is_woman_or_girl": True, "is_maharashtra_resident": True, "age": 30,
          "has_aadhaar_linked_bank_account": True, "annual_family_income": 200000,
          "family_has_income_tax_payer": False, "family_has_regular_government_employee_or_pensioner": False,
          "receives_1500_monthly_from_other_government_scheme": False, "family_has_present_or_former_mp_or_mla": False,
          "family_has_government_board_or_corporation_office_holder": False,
          "family_owns_four_wheeler_excluding_tractor": False}


@pytest.mark.parametrize("changes, verdict", [
    ({"marital_status": "married"}, "eligible"),  # the one-per-family limit is only for unmarried women
    ({"marital_status": "unmarried", "another_unmarried_woman_in_family_already_benefits": False}, "eligible"),
    ({"marital_status": "unmarried", "another_unmarried_woman_in_family_already_benefits": True}, "not_eligible"),
    ({"marital_status": "married", "family_has_regular_government_employee_or_pensioner": True}, "not_eligible"),
])
def test_m19_one_unmarried_woman_per_family(changes, verdict):
    assert tools.evaluate_scheme({**M19_OK, **changes}, "M19", include_draft=True)["verdict"] == verdict


NONE_M20 = {"ration_card_type": "none", "has_maharashtra_domicile_certificate": False,
            "is_student_in_government_ashram_school": False, "is_child_in_government_orphanage": False,
            "is_woman_in_government_womens_ashram": False, "is_senior_citizen_in_government_old_age_home": False,
            "is_journalist_or_dependent_meeting_dgipr_criteria": False,
            "is_out_of_state_construction_worker_registered_with_mbocww_board": False,
            "is_out_of_state_road_accident_victim_injured_in_maharashtra": False,
            "is_border_village_family_with_aay_phh_or_annapurna_card": False}


@pytest.mark.parametrize("changes, verdict", [
    ({}, "not_eligible"),
    ({"ration_card_type": "white"}, "eligible"),
    ({"ration_card_type": "phh"}, "eligible"),
    ({"is_child_in_government_orphanage": True}, "eligible"),
    ({"is_journalist_or_dependent_meeting_dgipr_criteria": True}, "eligible"),
    ({"is_border_village_family_with_aay_phh_or_annapurna_card": True}, "eligible"),
])
def test_m20_categories_a_to_e(changes, verdict):
    assert tools.evaluate_scheme({**NONE_M20, **changes}, "M20", include_draft=True)["verdict"] == verdict


def test_white_card_rule_cites_category_b():
    result = tools.evaluate_scheme({**NONE_M20, "ration_card_type": "white"}, "M20", include_draft=True)
    assert "elig-3" in {c["clause_id"] for c in result["citations"]}
