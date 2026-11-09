"""Phase 1 rule fixes (docs/rule-fix-plan.md). The changed rules are draft until a person
signs them off, so every scheme here is evaluated with include_draft."""
import pytest

from graph import tools


def verdict(profile, scheme_id):
    return tools.evaluate_scheme(profile, scheme_id, include_draft=True)["verdict"]


M13_OK = {"is_cultivable_landholding_farmer_family": True, "held_qualifying_land_on_2019_02_01": True,
          "is_pm_kisan_beneficiary": True, "holds_farmland_in_maharashtra": True, "is_institutional_landholder": False,
          "family_has_former_or_present_constitutional_post_holder": False,
          "family_has_former_or_present_listed_political_office_holder": False,
          "family_has_government_or_local_body_employee": False,
          "family_has_retired_pensioner_with_monthly_pension_10000_or_more": False,
          "family_has_member_who_paid_income_tax_in_last_assessment_year": False,
          "family_has_practicing_registered_professional_in_listed_field": False,
          "family_has_non_resident_indian": False}


@pytest.mark.parametrize("changes, expected", [
    ({}, "eligible"),
    ({"is_pm_kisan_beneficiary": False}, "not_eligible"),
    ({"holds_farmland_in_maharashtra": False}, "not_eligible"),
    ({"family_has_non_resident_indian": True}, "not_eligible"),  # the husband, not the applicant
    ({"family_has_government_or_local_body_employee": True}, "cant_tell"),
    ({"family_has_government_or_local_body_employee": True,
      "family_government_or_local_body_employees_are_all_mts_class_iv_or_group_d": True}, "eligible"),
    ({"family_has_government_or_local_body_employee": True,
      "family_government_or_local_body_employees_are_all_mts_class_iv_or_group_d": False}, "not_eligible"),
    ({"family_has_retired_pensioner_with_monthly_pension_10000_or_more": True,
      "family_pensioners_with_10000_or_more_are_all_former_mts_class_iv_or_group_d": True}, "eligible"),
    ({"family_has_retired_pensioner_with_monthly_pension_10000_or_more": True,
      "family_pensioners_with_10000_or_more_are_all_former_mts_class_iv_or_group_d": False}, "not_eligible"),
])
def test_m13_family_exclusions_and_group_d_carve_outs(changes, expected):
    assert verdict({**M13_OK, **changes}, "M13") == expected


C03_OK = {"is_small_or_marginal_farmer": True, "cultivable_landholding_hectares": 2, "age": 30,
          "name_in_land_records_on_2019_08_01": True, "has_aadhaar": True, "has_savings_or_pm_kisan_account": True,
          "is_nps_member": False, "is_esic_member": False, "is_epfo_member": False,
          "covered_by_other_statutory_social_security_scheme": False,
          "opted_for_pm_sym_or_pm_vyapari_maandhan": False, "is_institutional_landholder": False,
          "family_has_former_or_present_constitutional_post_holder": False,
          "family_has_former_or_present_listed_political_office_holder": False,
          "family_has_government_or_local_body_employee": True,
          "family_government_or_local_body_employees_are_all_mts_class_iv_or_group_d": True,
          "family_has_member_who_paid_income_tax_in_last_assessment_year": False,
          "family_has_practicing_registered_professional_in_listed_field": False}


@pytest.mark.parametrize("changes, expected", [
    ({}, "eligible"),
    ({"covered_by_other_statutory_social_security_scheme": True}, "not_eligible"),
    ({"family_government_or_local_body_employees_are_all_mts_class_iv_or_group_d": False}, "not_eligible"),
])
def test_c03_shares_m13_carve_out_and_other_social_security(changes, expected):
    assert verdict({**C03_OK, **changes}, "C03") == expected


@pytest.mark.parametrize("category, expected", [
    ("sharecropper", "eligible"), ("farmer self-help group", "eligible"), ("not a farmer", "not_eligible"),
])
def test_c13_categories_are_one_rule(category, expected):
    assert verdict({"farmer_applicant_category": category}, "C13") == expected


C14_OK = {"grows_notified_crop": True, "farm_is_in_notified_area": True,
          "farmer_applicant_category": "tenant farmer", "has_land_record_or_tenancy_agreement": True,
          "received_compensation_for_same_crop_loss_elsewhere": False}


@pytest.mark.parametrize("changes, expected", [
    ({}, "eligible"),
    ({"farm_is_in_notified_area": False}, "not_eligible"),
    ({"farmer_applicant_category": "not a farmer"}, "not_eligible"),  # must cultivate the insured land
])
def test_c14_cultivator_and_split_notified_questions(changes, expected):
    assert verdict({**C14_OK, **changes}, "C14") == expected


@pytest.mark.parametrize("state, expected", [
    ("Assam", "eligible"), ("Maharashtra", "not_eligible"), (None, "cant_tell"),
])
def test_c23_only_in_pilot_states(state, expected):
    assert verdict({"is_woman_or_girl": True, "state_of_residence": state}, "C23") == expected


@pytest.mark.parametrize("changes, expected", [
    ({}, "eligible"),
    ({"age": 17}, "not_eligible"),
    ({"is_medically_fit_to_drive": False}, "not_eligible"),
])
def test_m18_licence_conditions_are_answerable(changes, expected):
    base = {"social_category": "OBC", "age": 18, "is_medically_fit_to_drive": True}
    assert verdict({**base, **changes}, "M18") == expected


def test_m16_board_field_matches_m20():
    profile = {"is_building_or_construction_worker": True, "registered_with_mbocww_board": True,
               "worker_or_family_member_undergoing_critical_treatment": True}
    assert verdict(profile, "M16") == "eligible"


M01_BASE = {"is_indian_citizen": True, "is_maharashtra_resident": True, "household_below_bpl": True}


@pytest.mark.parametrize("category, age, clause", [
    ("orphan child", 10, "elig-6"), ("destitute widow", 70, "elig-9"),
    ("destitute man or woman below 65", 60, "elig-5"), ("unmarried woman above 35", 40, "elig-14"),
    ("sickle cell disease", 30, "elig-16"),
])
def test_m01_cites_the_matching_category_only(category, age, clause):
    result = tools.evaluate_scheme({**M01_BASE, "niradhar_category": category, "age": age}, "M01", include_draft=True)
    cited = {c["clause_id"] for c in result["citations"]}
    assert result["verdict"] == "eligible"
    assert cited == {"elig-1", "elig-2", "elig-3", "elig-4", clause}


C19_BASE = {"is_indian_citizen": True, "school_type": "government"}


@pytest.mark.parametrize("changes, expected", [
    ({"is_in_bal_vatika_or_pre_school_class": True}, "eligible"),           # no class needed
    ({"school_class": 5, "is_in_bal_vatika_or_pre_school_class": False}, "eligible"),
    ({"school_class": 9, "is_in_bal_vatika_or_pre_school_class": False}, "not_eligible"),
    ({"is_in_bal_vatika_or_pre_school_class": True, "school_type": "private"}, "not_eligible"),
    ({"is_in_bal_vatika_or_pre_school_class": False}, "cant_tell"),         # class still unknown
])
def test_c19_feeds_bal_vatika_children_in_government_schools(changes, expected):
    assert verdict({**C19_BASE, **changes}, "C19") == expected


def test_c19_class_answer_settles_it_without_the_bal_vatika_question():
    result = tools.evaluate_scheme({**C19_BASE, "school_class": 5}, "C19", include_draft=True)
    assert result["verdict"] == "eligible" and "benefits-7" not in {c["clause_id"] for c in result["citations"]}
