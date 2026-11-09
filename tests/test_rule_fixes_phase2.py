"""Phase 2 rule fixes (docs/rule-fix-plan.md): draft schemes that gave wrong verdicts.
All of them are draft, so every scheme is evaluated with include_draft."""
import pytest

from graph import tools


def verdict(profile, scheme_id):
    return tools.evaluate_scheme(profile, scheme_id, include_draft=True)["verdict"]


M08_OK = {"is_maharashtra_resident": True, "is_woman_or_girl": True, "is_charmakar_community": True, "age": 30,
          "has_knowledge_of_business_applied_for": True, "loan_is_for_agricultural_project": False,
          "household_below_bpl": False}


@pytest.mark.parametrize("changes, m08, m09", [
    ({"area_type": "urban", "annual_family_income": 120000}, "eligible", "not_eligible"),  # M09: "below"
    ({"area_type": "urban", "annual_family_income": 119999}, "eligible", "eligible"),
    ({"area_type": "urban", "annual_family_income": 120001}, "not_eligible", "not_eligible"),
    ({"area_type": "rural", "annual_family_income": 98000}, "eligible", "not_eligible"),
    ({"area_type": "rural", "annual_family_income": 98001}, "not_eligible", "not_eligible"),
    ({"area_type": "rural", "annual_family_income": 500000, "household_below_bpl": True}, "eligible", "eligible"),
    ({"annual_family_income": 90000}, "eligible", "eligible"),  # under both limits: no area question
    ({"annual_family_income": 110000}, "cant_tell", "cant_tell"),  # depends on the area
])
def test_m08_m09_income_limits(changes, m08, m09):
    assert verdict({**M08_OK, **changes}, "M08") == m08
    assert verdict({k: v for k, v in {**M08_OK, **changes}.items() if k != "loan_is_for_agricultural_project"},
                   "M09") == m09


@pytest.mark.parametrize("changes, expected", [
    ({"loan_is_for_agricultural_project": True, "has_7_12_extract_in_own_joint_or_husbands_name": True}, "eligible"),
    ({"loan_is_for_agricultural_project": True, "has_7_12_extract_in_own_joint_or_husbands_name": False},
     "not_eligible"),
])
def test_m08_land_record_only_for_agricultural_loans(changes, expected):
    assert verdict({**M08_OK, "annual_family_income": 50000, **changes}, "M08") == expected


M12_OK = {"years_resident_in_maharashtra": 20, "social_category": "Nav-Buddha", "family_member_already_got_ramai_awas": False,
          "owns_land_for_house": True, "receives_other_government_housing_benefit": False}


@pytest.mark.parametrize("changes, expected", [
    ({"residence_area_type": "rural", "annual_family_income": 100000}, "eligible"),
    ({"residence_area_type": "rural", "annual_family_income": 100001}, "not_eligible"),
    ({"residence_area_type": "municipal council", "annual_family_income": 150000}, "eligible"),
    ({"residence_area_type": "municipal council", "annual_family_income": 150001}, "not_eligible"),
    ({"residence_area_type": "municipal corporation", "annual_family_income": 200000}, "eligible"),
    ({"residence_area_type": "municipal corporation", "annual_family_income": 200001}, "not_eligible"),
    ({"annual_family_income": 90000}, "eligible"),          # within every limit
    ({"residence_area_type": "rural", "annual_family_income": 50000, "social_category": "OBC"}, "not_eligible"),
])
def test_m12_sc_nav_buddha_and_income_by_area(changes, expected):
    assert verdict({**M12_OK, **changes}, "M12") == expected


C24_OK = {"is_indian_citizen": True, "has_phd_md_or_ms_degree": False,
          "has_submitted_phd_md_or_ms_thesis_awaiting_award": True, "has_availed_npdf_before": False,
          "social_category": "General", "has_disability": False, "is_woman_or_girl": False}


@pytest.mark.parametrize("changes, expected", [
    ({"age": 35}, "eligible"),
    ({"age": 36}, "not_eligible"),
    ({"age": 40, "is_woman_or_girl": True}, "eligible"),   # five years' relaxation
    ({"age": 41, "is_woman_or_girl": True}, "not_eligible"),
    ({"age": 38, "social_category": "OBC"}, "eligible"),
    ({"age": 38, "social_category": "VJ-A"}, "not_eligible"),  # F2: not OBC unless the text says so
    ({"age": 30, "has_submitted_phd_md_or_ms_thesis_awaiting_award": False}, "not_eligible"),
])
def test_c24_age_relaxation_and_thesis(changes, expected):
    assert verdict({**C24_OK, **changes}, "C24") == expected


@pytest.mark.parametrize("changes, expected", [
    ({"age": 45}, "eligible"), ({"age": 46}, "not_eligible"),
    ({"age": 50, "has_disability": True}, "eligible"), ({"age": 51, "has_disability": True}, "not_eligible"),
    ({"age": 40, "resides_in_india": False}, "not_eligible"),
])
def test_c26_age_relaxation_and_residence(changes, expected):
    base = {"is_indian_citizen": True, "resides_in_india": True, "has_phd_in_science_engineering_or_ms_md": True,
            "holds_regular_position_in_state_university_college_or_private_institution": True,
            "has_ongoing_research_project_or_fellowship": False, "social_category": "General",
            "has_disability": False, "is_woman_or_girl": False}
    assert verdict({**base, **changes}, "C26") == expected


A = "permanent scientist at a government academic or research institution, retired or retiring within a year"
B = "temporary (non-permanent) researcher who has completed 2 independent research projects as principal investigator"


@pytest.mark.parametrize("changes, expected", [
    ({"widushi_employment_category": A, "age": 57, "research_publications_with_impact_factor": 20}, "eligible"),
    ({"widushi_employment_category": A, "age": 56, "research_publications_with_impact_factor": 20}, "not_eligible"),
    ({"widushi_employment_category": A, "age": 60, "research_publications_with_impact_factor": 19}, "not_eligible"),
    ({"widushi_employment_category": B, "age": 45, "research_publications_with_impact_factor": 10}, "eligible"),
    ({"widushi_employment_category": B, "age": 44, "research_publications_with_impact_factor": 10}, "not_eligible"),
    ({"widushi_employment_category": B, "age": 63, "research_publications_with_impact_factor": 30}, "not_eligible"),
])
def test_c25_categories_have_their_own_limits(changes, expected):
    base = {"is_woman_or_girl": True, "has_phd_or_equivalent_in_basic_or_applied_sciences": True,
            "was_pi_of_at_least_2_rd_projects": True}
    assert verdict({**base, **changes}, "C25") == expected


@pytest.mark.parametrize("changes, expected", [
    ({"religion": "Jain"}, "eligible"),
    ({"religion": "Hindu", "social_category": "EWS"}, "eligible"),
    ({"religion": "Hindu", "social_category": "General"}, "not_eligible"),
    ({"religion": "Sikh", "is_indian_citizen": False}, "not_eligible"),
])
def test_c27_notified_minorities_or_ews(changes, expected):
    assert verdict({"is_indian_citizen": True, "age": 20, **changes}, "C27") == expected


@pytest.mark.parametrize("changes, expected", [
    ({"state_artist_pension_per_month": 500}, "eligible"),
    ({"state_artist_pension_per_month": 0, "recommended_by_zonal_cultural_centre": True}, "eligible"),
    ({"state_artist_pension_per_month": 499, "recommended_by_zonal_cultural_centre": False}, "not_eligible"),
    ({"state_artist_pension_per_month": 500, "applicant_and_spouse_annual_income_excluding_artist_pension": 48001},
     "not_eligible"),
])
def test_c31_income_without_pension_and_split_pension_question(changes, expected):
    base = {"has_significant_contribution_to_art_or_letters": True, "age": 70,
            "applicant_and_spouse_annual_income_excluding_artist_pension": 48000,
            "gets_other_ministry_of_culture_assistance": False}
    assert verdict({**base, **changes}, "C31") == expected


C09_OK = {"is_indian_citizen": True, "has_innovative_idea_or_invention": True, "project_cost_rupees": 1000000,
          "proposal_is_working_model_testing_patenting_or_tech_transfer": True, "project_duration_months": 24,
          "proposal_is_only_software_development": False, "proposal_is_only_patenting_without_prototype": False,
          "proposal_is_basic_research_without_commercial_use": False}


@pytest.mark.parametrize("changes, expected", [
    ({}, "eligible"),
    ({"project_duration_months": 25}, "not_eligible"),
    ({"proposal_is_only_patenting_without_prototype": True}, "not_eligible"),
    ({"proposal_is_only_software_development": True}, "not_eligible"),
    ({"proposal_is_basic_research_without_commercial_use": True}, "not_eligible"),
])
def test_c09_duration_and_exclusions(changes, expected):
    assert verdict({**C09_OK, **changes}, "C09") == expected


@pytest.mark.parametrize("category, expected", [("OBC", "eligible"), ("EBC", "eligible"), ("SC", "not_eligible")])
def test_c16_obc_or_ebc(category, expected):
    profile = {"social_category": category, "admitted_abroad_masters_mphil_or_phd": True,
               "has_iba_education_loan_from_scheduled_bank": True, "annual_family_income": 800000}
    assert verdict(profile, "C16") == expected


C15_OK = {"is_indian_citizen": True, "is_woman_or_girl": True, "is_only_child": True, "age_at_pg_admission": 30,
          "admitted_full_time_first_year_masters": True, "course_is_non_professional": True,
          "studies_through_distance_education": False, "institution_is_deemed_university_without_government_funds": False}


@pytest.mark.parametrize("changes, expected", [
    ({}, "eligible"),
    ({"is_only_child": False}, "not_eligible"),  # a sister, a brother or a twin: not a single-child family (F7)
    ({"institution_is_deemed_university_without_government_funds": True}, "not_eligible"),
    ({"age_at_pg_admission": 31}, "not_eligible"),
])
def test_c15_single_child_family_and_deemed_universities(changes, expected):
    assert verdict({**C15_OK, **changes}, "C15") == expected


M14_OK = {"is_unemployed_or_starting_new_venture": True, "family_member_already_got_cmegp": False,
          "unit_already_got_government_subsidy": False, "social_category": "General", "is_woman_or_girl": False,
          "is_ex_serviceman": False, "has_disability": False, "religion": "Hindu", "cmegp_project_cost_rupees": 500000,
          "has_passed_class_7": False, "has_passed_class_10": False}


@pytest.mark.parametrize("changes, expected", [
    ({"age": 45}, "eligible"), ({"age": 46}, "not_eligible"),
    ({"age": 50, "is_ex_serviceman": True}, "eligible"), ({"age": 51, "is_ex_serviceman": True}, "not_eligible"),
    ({"age": 50, "social_category": "NT-C"}, "eligible"),   # VJNT, OBC and minorities too (benefits-11)
    ({"age": 50, "social_category": "OBC"}, "eligible"),
    ({"age": 50, "religion": "Parsi"}, "eligible"),
    ({"age": 50, "religion": "Jewish"}, "not_eligible"),     # six central minorities only
    ({"age": 30, "cmegp_project_cost_rupees": 1000000}, "eligible"),      # no class 7 needed up to 10 lakh
    ({"age": 30, "cmegp_project_cost_rupees": 1000001}, "not_eligible"),
    ({"age": 30, "cmegp_project_cost_rupees": 2000000, "has_passed_class_7": True}, "eligible"),
    ({"age": 30, "cmegp_project_cost_rupees": 2500001, "has_passed_class_7": True}, "not_eligible"),
    ({"age": 30, "cmegp_project_cost_rupees": 3000000, "has_passed_class_7": True, "has_passed_class_10": True},
     "eligible"),
])
def test_m14_age_relaxation_and_education_by_project_cost(changes, expected):
    assert verdict({**M14_OK, **changes}, "M14") == expected
