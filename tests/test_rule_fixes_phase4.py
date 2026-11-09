"""Phase 4 rule fixes (docs/rule-fix-plan.md). The schemes are draft, so they are evaluated with
include_draft. C01, C04, C05 and C10 were left live and untouched."""
import pytest

from graph import tools
from tests.test_scheme_gold_set import EXPECTED_IDS


def verdict(profile, scheme_id):
    return tools.evaluate_scheme(profile, scheme_id, include_draft=True)["verdict"]


def test_the_schemes_kept_live_are_still_live():
    assert {"C01", "C04", "C05", "C06", "C10", "C17", "C38"} <= set(tools.search_schemes({}))
    assert {"C01", "C04", "C05", "C10"} <= EXPECTED_IDS


@pytest.mark.parametrize("changes, expected", [
    ({"is_woman_or_girl": True}, "eligible"),
    ({"is_woman_or_girl": False, "social_category": "ST"}, "eligible"),
    ({"is_woman_or_girl": False, "social_category": "OBC"}, "not_eligible"),
])
def test_c11_woman_or_sc_st(changes, expected):
    base = {"is_starting_greenfield_enterprise": True, "age": 30, "is_bank_loan_defaulter": False}
    assert verdict({**base, **changes}, "C11") == expected


@pytest.mark.parametrize("weeks, expected", [(12, "not_eligible"), (13, "eligible"), (40, "eligible"), (41, "not_eligible")])
def test_c18_weeks_of_pregnancy(weeks, expected):
    profile = {"is_pregnant": True, "weeks_of_pregnancy": weeks, "is_indian_citizen": True, "resides_in_india": True}
    assert verdict(profile, "C18") == expected


@pytest.mark.parametrize("changes, expected", [
    ({"is_indigent": True}, "eligible"),
    ({"is_indigent": False, "has_dementia_or_needs_continuous_nursing_care": True}, "eligible"),
    ({"is_indigent": False, "has_dementia_or_needs_continuous_nursing_care": False}, "not_eligible"),
])
def test_c21_indigent_or_needs_care(changes, expected):
    assert verdict({"age": 65, **changes}, "C21") == expected


@pytest.mark.parametrize("years, expected", [(10, "not_eligible"), (11, "eligible")])
def test_c22_more_than_ten_years(years, expected):
    profile = {"years_case_pending_in_subordinate_courts": years, "lacks_legal_aid_due_to_social_or_economic_barriers": True,
               "suffering_delay_in_investigation_or_trial": True}
    assert verdict(profile, "C22") == expected


@pytest.mark.parametrize("born, expected", [("2009-05-09", "eligible"), ("2009-05-10", "not_eligible")])
def test_c28_seventeen_and_a_half_from_the_date_of_birth(born, expected, monkeypatch):
    from datetime import date

    from servers.rule_engine import ages
    real = ages.derive_age_fields
    monkeypatch.setattr("servers.rule_engine.server.derive_age_fields", lambda p: real(p, date(2026, 11, 9)))
    profile = {"is_indian_citizen": True, "date_of_birth": born, "meets_armed_forces_education_qualification": True,
               "meets_armed_forces_physical_and_medical_standards": True}
    assert verdict(profile, "C28") == expected


@pytest.mark.parametrize("changes, expected", [
    ({"is_national_games_medalist": False, "participated_in_recognised_international_sporting_event": True}, "eligible"),
    ({"is_national_games_medalist": False, "participated_in_recognised_international_sporting_event": False},
     "not_eligible"),
    ({"is_national_games_medalist": True, "institution_type": "private unaided college"}, "not_eligible"),
])
def test_c32_medal_or_participation_and_institution(changes, expected):
    base = {"is_national_games_medalist": True, "institution_type": "institute of national importance"}
    assert verdict({**base, **changes}, "C32") == expected


def test_c32_cites_the_matching_institution_clause():
    result = tools.evaluate_scheme({"is_national_games_medalist": True, "institution_type": "institute of national importance"},
                                   "C32", include_draft=True)
    assert {c["clause_id"] for c in result["citations"]} == {"elig-1", "elig-6"}


@pytest.mark.parametrize("changes, expected", [
    ({"previous_year_cgpa": 7}, "eligible"),
    ({"previous_year_cgpa": 6.9, "previous_year_percentage": 65}, "eligible"),
    ({"previous_year_cgpa": 6.9, "previous_year_percentage": 64.9}, "not_eligible"),
    ({"previous_year_cgpa": 8, "engineering_course_and_year": "second year of B.E./B.Tech"}, "not_eligible"),
])
def test_c36_course_and_score(changes, expected):
    base = {"engineering_course_and_year": "pre-final or final year of B.E./B.Tech", "institution_is_aicte_approved": True,
            "has_letter_of_acceptance_for_paper_at_event_abroad": True, "has_availed_aicte_inae_travel_grant_before": False}
    assert verdict({**base, **changes}, "C36") == expected


def test_m06_child_disability_and_care_are_separate():
    base = {"is_indian_citizen": True, "is_orphan": True, "is_maharashtra_resident": True, "age": 12,
            "has_intellectual_disability": True, "needs_care_and_protection": True, "disability_percent": 40}
    assert verdict(base, "M06") == "eligible"
    assert verdict({**base, "age": 18}, "M06") == "not_eligible"


@pytest.mark.parametrize("income, clause", [(17999, "elig-5"), (24000, "elig-6")])
def test_m10_family_income_limits_cite_their_clause(income, clause):
    profile = {"is_indian_citizen": True, "is_maharashtra_resident": True, "has_disability": True,
               "disability_percent": 40, "annual_family_income": income}
    result = tools.evaluate_scheme(profile, "M10", include_draft=True)
    assert result["verdict"] == "eligible" and clause in {c["clause_id"] for c in result["citations"]}
    assert verdict({**profile, "annual_family_income": 24001}, "M10") == "not_eligible"


def test_m11_needs_unemployment_and_family_income():
    base = {"is_indian_citizen": True, "is_maharashtra_resident": True, "has_disability": True, "disability_percent": 40,
            "age": 30, "is_unemployed": True, "annual_family_income": 99999}
    assert verdict(base, "M11") == "eligible"
    assert verdict({**base, "is_unemployed": False}, "M11") == "not_eligible"
    assert verdict({**base, "annual_family_income": 100000}, "M11") == "not_eligible"


@pytest.mark.parametrize("changes, expected", [
    ({"has_bank_or_post_office_savings_account": True}, "eligible"),
    ({"has_bank_or_post_office_savings_account": False, "has_pm_kisan_account": True}, "eligible"),
    ({"has_bank_or_post_office_savings_account": False, "has_pm_kisan_account": False}, "not_eligible"),
])
def test_c03_shared_bank_field_or_pm_kisan_account(changes, expected):
    from tests.test_rule_fixes import C03_OK
    base = {k: v for k, v in C03_OK.items() if k != "has_bank_or_post_office_savings_account"}
    assert verdict({**base, **changes}, "C03") == expected
