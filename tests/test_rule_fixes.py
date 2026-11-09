"""Phase 1 rule fixes (docs/rule-fix-plan.md). The changed rules are draft until a person
signs them off, so every scheme here is evaluated with include_draft."""
import pytest

from graph import tools


def verdict(profile, scheme_id):
    return tools.evaluate_scheme(profile, scheme_id, include_draft=True)["verdict"]


M13_OK = {"is_cultivable_landholding_farmer_family": True, "held_qualifying_land_on_2019_02_01": True,
          "is_pm_kisan_beneficiary": True, "is_institutional_landholder": False,
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
