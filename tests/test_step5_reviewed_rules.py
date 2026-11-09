"""The Step 5 review (9 Nov 2026): fixes to the last 27 AI-drafted rule sets, checked at their boundaries."""
import pytest

from graph import tools

A = "permanent, retiring within a year or retired from a government institution"
B = "temporary, not a permanent employee"

BASE = {
    "C07": {"is_agricultural_scientist_in_icar_or_public_institution": True,
            "work_has_proven_impact_supported_by_head": True, "has_clean_service_record_last_5_years": True,
            "age": 50},
    "C09": {"is_indian_citizen": True, "has_innovative_idea_or_invention": True, "project_cost_rupees": 1000000,
            "proposal_is_working_model_testing_patenting_or_tech_transfer": True, "project_duration_months": 18,
            "proposal_is_only_software": False, "proposal_is_basic_research_without_commercial_use": False,
            "proposal_is_only_patenting_without_prototype": False},
    "C11": {"is_starting_greenfield_enterprise": True, "is_woman_or_girl": False, "social_category": "SC",
            "age": 30, "is_bank_loan_defaulter": False},
    "C15": {"is_indian_citizen": True, "is_woman_or_girl": True, "is_only_child_or_one_of_twin_daughters": True,
            "age": 23, "admitted_full_time_first_year_masters": True, "course_is_non_professional": True,
            "studies_through_distance_education": False, "institution_is_unfunded_deemed_university": False},
    "C16": {"social_category": "OBC", "admitted_abroad_masters_mphil_or_phd": True,
            "has_iba_education_loan_from_scheduled_bank": True, "annual_income": 600000},
    "C24": {"is_indian_citizen": True, "has_phd_md_ms_or_thesis_submitted": True, "age": 33,
            "has_availed_npdf_before": False},
    "C25": {"is_woman_or_girl": True, "widushi_employment": B, "has_phd_in_basic_or_applied_sciences": True,
            "was_pi_of_at_least_2_rd_projects": True, "research_publications_with_impact_factor": 12, "age": 50},
    "C26": {"is_indian_citizen": True, "has_phd_in_science_engineering_or_ms_md": True,
            "holds_regular_position_in_state_university_college_or_private_institution": True,
            "has_ongoing_research_project_or_fellowship": False, "age": 40},
    "C27": {"religion": "Jain", "age": 30},
    "C31": {"has_significant_contribution_to_art_or_letters": True,
            "applicant_and_spouse_annual_income_excluding_artist_pension": 40000, "age": 70,
            "state_artist_pension_per_month": 800, "gets_other_ministry_of_culture_assistance": False},
    "M05": {"is_indian_citizen": True, "is_maharashtra_resident": True, "institution_recognized_by_maharashtra_govt": True,
            "has_disability": True, "disability_percent": 60, "has_passed_class_10": True,
            "failed_last_qualifying_exam": False, "is_pursuing_post_matric_course": True},
    "M08": {"is_maharashtra_resident": True, "is_woman_or_girl": True, "is_charmakar_community": True, "age": 35,
            "has_knowledge_of_business_applied_for": True, "household_below_bpl": True},
    "M12": {"social_category": "Nav-Buddha", "years_resident_in_maharashtra": 20, "annual_income": 90000,
            "family_member_already_beneficiary": False, "owns_land_for_house": True,
            "receives_other_government_housing_benefit": False},
    "M14": {"age": 30, "is_unemployed_or_starting_new_venture": True, "has_passed_class_7": True,
            "has_passed_class_10": True, "family_member_already_beneficiary": False,
            "availed_other_scheme_same_purpose": False},
}
BASE["M09"] = {k: v for k, v in BASE["M08"].items()}


def verdict(scheme_id, **changes):
    return tools.evaluate_scheme({**BASE[scheme_id], **changes}, scheme_id)["verdict"]


@pytest.mark.parametrize("scheme_id", sorted(BASE))
def test_the_base_profile_is_eligible(scheme_id):
    assert verdict(scheme_id) == "eligible"


@pytest.mark.parametrize("scheme_id, changes", [
    ("C07", {"work_has_proven_impact_supported_by_head": False}),
    ("C09", {"project_duration_months": 25}),
    ("C09", {"proposal_is_only_software": True}),
    ("C09", {"proposal_is_basic_research_without_commercial_use": True}),
    ("C09", {"proposal_is_only_patenting_without_prototype": True}),
    ("C15", {"institution_is_unfunded_deemed_university": True}),
    ("C15", {"is_only_child_or_one_of_twin_daughters": False}),   # F2: the strict reading
    ("M05", {"institution_recognized_by_maharashtra_govt": False}),
])
def test_a_condition_the_draft_missed_now_refuses(scheme_id, changes):
    assert verdict(scheme_id, **changes) == "not_eligible"


@pytest.mark.parametrize("scheme_id, changes, expected", [
    # F1: the community named in the scheme's Details section
    ("C16", {"social_category": "SC"}, "not_eligible"),
    ("C16", {"social_category": "EBC"}, "eligible"),
    ("C27", {"religion": "Hindu"}, "not_eligible"),
    ("C27", {"religion": "Parsi"}, "eligible"),
    ("M12", {"social_category": "OBC"}, "not_eligible"),
    ("M12", {"social_category": "SC"}, "eligible"),
])
def test_the_target_community_is_checked(scheme_id, changes, expected):
    assert verdict(scheme_id, **changes) == expected


@pytest.mark.parametrize("changes, expected", [
    ({}, "eligible"),                                                         # B: 45-62, 10+ publications
    ({"age": 44}, "not_eligible"),
    ({"research_publications_with_impact_factor": 9}, "not_eligible"),
    ({"widushi_employment": A, "age": 58, "research_publications_with_impact_factor": 20}, "eligible"),
    ({"widushi_employment": A, "age": 56, "research_publications_with_impact_factor": 25}, "not_eligible"),
    ({"widushi_employment": A, "age": 60, "research_publications_with_impact_factor": 19}, "not_eligible"),
    ({"widushi_employment": "permanent, not retiring"}, "not_eligible"),     # fits neither category
    ({"age": 63}, "not_eligible"),
])
def test_c25_is_category_a_or_category_b(changes, expected):
    assert verdict("C25", **changes) == expected


@pytest.mark.parametrize("scheme_id, base, relaxed", [("C24", 35, 40), ("C26", 45, 50)])
def test_the_five_year_age_relaxation(scheme_id, base, relaxed):
    general = {"social_category": "General", "is_woman_or_girl": False, "has_disability": False}
    assert verdict(scheme_id, age=base, **general) == "eligible"
    assert verdict(scheme_id, age=base + 1, **general) == "not_eligible"
    for group in ({"social_category": "OBC"}, {"is_woman_or_girl": True}, {"has_disability": True}):
        assert verdict(scheme_id, age=relaxed, **{**general, **group}) == "eligible"
        assert verdict(scheme_id, age=relaxed + 1, **{**general, **group}) == "not_eligible"


def test_m14_age_relaxation_and_schooling_by_project_size():
    general = {"social_category": "General", "is_woman_or_girl": False, "is_ex_serviceman": False,
               "has_disability": False}
    assert verdict("M14", age=46, **general) == "not_eligible"
    assert verdict("M14", age=50, **{**general, "is_ex_serviceman": True}) == "eligible"
    assert verdict("M14", age=51, **{**general, "is_woman_or_girl": True}) == "not_eligible"
    no_school = {"has_passed_class_7": False, "has_passed_class_10": False}
    assert verdict("M14", **no_school, project_cost_rupees=1000000) == "eligible"     # up to 10 lakh: none needed
    assert verdict("M14", **no_school, project_cost_rupees=1000001) == "not_eligible"
    assert verdict("M14", has_passed_class_10=False, project_cost_rupees=2500000) == "eligible"
    assert verdict("M14", has_passed_class_10=False, project_cost_rupees=2500001) == "not_eligible"


@pytest.mark.parametrize("area, limit", [("rural", 100000), ("municipal council area", 150000),
                                          ("municipal corporation", 200000)])
def test_m12_income_limit_depends_on_the_area(area, limit):
    assert verdict("M12", area_type=area, annual_income=limit) == "eligible"
    assert verdict("M12", area_type=area, annual_income=limit + 1) == "not_eligible"


@pytest.mark.parametrize("scheme_id, rural_ok, rural_no, urban_ok, urban_no", [
    ("M08", 98000, 98001, 120000, 120001),   # "the income limit is"
    ("M09", 97999, 98000, 119999, 120000),   # "should be below"
])
def test_bpl_or_the_nsfdc_income_limit(scheme_id, rural_ok, rural_no, urban_ok, urban_no):
    not_bpl = {"household_below_bpl": False}
    assert verdict(scheme_id, **not_bpl, area_type="rural", annual_income=rural_ok) == "eligible"
    assert verdict(scheme_id, **not_bpl, area_type="rural", annual_income=rural_no) == "not_eligible"
    assert verdict(scheme_id, **not_bpl, area_type="municipal corporation", annual_income=urban_ok) == "eligible"
    assert verdict(scheme_id, **not_bpl, area_type="municipal corporation", annual_income=urban_no) == "not_eligible"
    assert verdict(scheme_id, household_below_bpl=True, annual_income=500000) == "eligible"


def test_or_questions_are_decided_by_code():
    assert verdict("C11", is_woman_or_girl=True, social_category="General") == "eligible"
    assert verdict("C11", is_woman_or_girl=False, social_category="OBC") == "not_eligible"
    assert verdict("C31", state_artist_pension_per_month=499, recommended_by_zonal_cultural_centre=False) == "not_eligible"
    assert verdict("C31", state_artist_pension_per_month=0, recommended_by_zonal_cultural_centre=True) == "eligible"


def test_closed_schemes_say_so_in_the_answer():
    """F6: C11 and M14 are closed on myScheme; the verdict stands, and the answer says so."""
    assert tools.with_closed_note("C11", "eligible: ...") == f"eligible: ... {tools.CLOSED_NOTE}"
    assert tools.with_closed_note("M14", "x").endswith(tools.CLOSED_NOTE)
    assert tools.with_closed_note("C01", "eligible: ...") == "eligible: ..."
    assert tools.with_closed_note("SYNTH-PENSION-001", "x") == "x"  # no scheme record
