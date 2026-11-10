"""Step 6 (9 Nov 2026): Snehal Patel's findings from fix/rule-phase, added onto the reviewed rules."""
import pytest

from graph import tools

MINORITY_OK = {"religion": "Jain", "age": 30}
M11_OK = {"is_unemployed": True, "is_indian_citizen": True, "is_maharashtra_resident": True, "has_disability": True,
          "disability_percent": 50, "age": 30, "annual_income": 50000}
M14_OK = {"age": 30, "is_unemployed_or_starting_new_venture": True, "has_passed_class_7": True,
          "has_passed_class_10": True, "family_member_already_beneficiary": False,
          "availed_other_scheme_same_purpose": False}
GENERAL = {"social_category": "General", "religion": "Hindu", "is_woman_or_girl": False, "is_ex_serviceman": False,
           "has_disability": False}
M13_OK = {
    "is_cultivable_landholding_farmer_family": True, "held_qualifying_land_on_2019_02_01": True,
    "is_pm_kisan_beneficiary": True, "holds_farmland_in_maharashtra": True, "is_institutional_landholder": False,
    "family_has_former_or_present_constitutional_post_holder": False,
    "family_has_former_or_present_listed_political_office_holder": False,
    "family_has_government_or_local_body_employee": False,
    "family_has_retired_pensioner_with_monthly_pension_10000_or_more": False,
    "family_has_member_who_paid_income_tax_in_last_assessment_year": False,
    "family_has_practicing_registered_professional_in_listed_field": False, "family_has_non_resident_indian": False,
}


def verdict(profile, scheme_id):
    return tools.evaluate_scheme(profile, scheme_id)["verdict"]


@pytest.mark.parametrize("changes, expected", [
    ({}, "eligible"),
    ({"religion": "Hindu", "social_category": "EWS"}, "eligible"),      # details-20: non-minority EWS
    ({"religion": "Hindu", "social_category": "OBC"}, "not_eligible"),
])
def test_c27_minorities_or_ews(changes, expected):
    assert verdict({**MINORITY_OK, **changes}, "C27") == expected


def test_m11_needs_an_unemployed_applicant():
    assert verdict(M11_OK, "M11") == "eligible"
    assert verdict({**M11_OK, "is_unemployed": False}, "M11") == "not_eligible"


@pytest.mark.parametrize("group", [{"social_category": "OBC"}, {"social_category": "NT-C"},
                                   {"religion": "Muslim"}, {"is_ex_serviceman": True}])
def test_m14_special_category_from_benefits_11(group):
    assert verdict({**M14_OK, **GENERAL, "age": 46}, "M14") == "not_eligible"
    assert verdict({**M14_OK, **GENERAL, **group, "age": 50}, "M14") == "eligible"


def test_c02_keeps_70_nearer_birthday_after_the_sign_off():
    """Snehal's F7 answer (70 not included) was reverted at the Step 6 sign-off: 70 is still in."""
    ok = {"has_bank_account": True, "age": 60, "age_nearer_birthday": 70, "consents_to_auto_debit": True}
    profile = {f: ok.get(f, True) for f in tools.field_specs(["C02"])}
    profile.update(ok)
    assert verdict(profile, "C02") == "eligible"
    assert verdict({**profile, "age_nearer_birthday": 71}, "C02") == "not_eligible"


@pytest.mark.parametrize("changes, expected", [
    ({"school_class": 3}, "eligible"),
    ({"school_class": 0, "is_in_bal_vatika_or_pre_school_class": True}, "eligible"),   # benefits-7
    ({"school_class": 0, "is_in_bal_vatika_or_pre_school_class": False}, "not_eligible"),
    ({"school_class": 9, "is_in_bal_vatika_or_pre_school_class": False}, "not_eligible"),
    ({"school_class": 0, "is_in_bal_vatika_or_pre_school_class": True, "school_type": "private"}, "not_eligible"),
])
def test_c19_covers_bal_vatika(changes, expected):
    base = {"is_indian_citizen": True, "school_type": "government", "is_in_bal_vatika_or_pre_school_class": False}
    assert verdict({**base, **changes}, "C19") == expected


@pytest.mark.parametrize("state, expected", [("Assam", "eligible"), ("Andaman and Nicobar Islands", "eligible"),
                                             ("Maharashtra", "not_eligible"), (None, "cant_tell")])
def test_c23_runs_only_in_the_pilot_states(state, expected):
    profile = {"is_woman_or_girl": True}
    if state:
        profile["state_of_residence"] = state
    assert verdict(profile, "C23") == expected


@pytest.mark.parametrize("changes, expected", [
    ({}, "eligible"),
    ({"is_pm_kisan_beneficiary": False}, "not_eligible"),
    ({"holds_farmland_in_maharashtra": False}, "not_eligible"),
    ({"family_has_government_or_local_body_employee": True,
      "family_government_or_local_body_employees_are_all_mts_class_iv_or_group_d": False}, "not_eligible"),
    ({"family_has_government_or_local_body_employee": True,
      "family_government_or_local_body_employees_are_all_mts_class_iv_or_group_d": True}, "eligible"),
    ({"family_has_retired_pensioner_with_monthly_pension_10000_or_more": True,
      "family_pensioners_with_10000_or_more_are_all_former_mts_class_iv_or_group_d": True}, "eligible"),
])
def test_m13_pm_kisan_farmland_and_group_d(changes, expected):
    assert verdict({**M13_OK, **changes}, "M13") == expected


@pytest.mark.parametrize("category, expected", [("VJ-A", "eligible"), ("NT-D", "eligible"), ("SBC", "eligible"),
                                                ("SC", "not_eligible")])
def test_m18_vjnt_is_split_and_the_motor_vehicle_act_is_two_questions(category, expected):
    ok = {"social_category": category, "age": 18, "is_medically_fit_to_drive": True}
    assert verdict(ok, "M18") == expected
    assert verdict({**ok, "social_category": "VJ-A", "age": 17}, "M18") == "not_eligible"
