"""Fixes for Saurabh's review of PR #67 (scheme-saathi/scheme-saathi)."""
import pytest

from agents.intake import NONE_OF_THESE, direct_answer
from graph import tools

BOOL = {"type": "bool", "known_values": []}
CATEGORY = {"type": "str", "known_values": ["individual owner cultivator", "tenant farmer"]}


# 1. Only plain answers are read by code; doubt and mixed answers go to the model.

@pytest.mark.parametrize("reply, spec", [
    ("No, I am not sure", BOOL),
    ("No idea", BOOL),
    ("Yes, I think so", BOOL),
    ("No but my wife is", BOOL),
    ("नाही, माहित नाही", BOOL),
    ("नहीं, पता नहीं", BOOL),
    ("I am not a farmer but I am a tenant farmer", CATEGORY),
    ("Not an owner, I am a tenant farmer", CATEGORY),   # names a listed value
])
def test_doubtful_or_mixed_replies_are_left_to_the_model(reply, spec):
    assert direct_answer(reply, spec) is None


@pytest.mark.parametrize("reply, spec, value", [
    ("No.", BOOL, False),
    ("No, I am not a government employee.", BOOL, False),
    ("होय", BOOL, True),
    ("I am not a farmer.", CATEGORY, NONE_OF_THESE),
])
def test_plain_replies_are_still_read_by_code(reply, spec, value):
    assert direct_answer(reply, spec) == value


# 2. M08: the 7/12 land extract, for agricultural project loans only (elig-6).

M08 = {"is_maharashtra_resident": True, "is_woman_or_girl": True, "is_charmakar_community": True, "age": 35,
       "has_knowledge_of_business_applied_for": True, "household_below_bpl": True}


@pytest.mark.parametrize("facts, expected", [
    ({"is_agricultural_project_loan": False}, "eligible"),
    ({"is_agricultural_project_loan": True, "has_7_12_extract_in_own_joint_or_husbands_name": True}, "eligible"),
    ({"is_agricultural_project_loan": True, "has_7_12_extract_in_own_joint_or_husbands_name": False}, "not_eligible"),
    ({"is_agricultural_project_loan": True}, "cant_tell"),
    ({}, "cant_tell"),                                    # was "eligible" with no land facts at all
])
def test_m08_land_extract_for_agricultural_loans(facts, expected):
    assert tools.evaluate_scheme({**M08, **facts}, "M08")["verdict"] == expected


# 3. C24 and C26: the mentor's conditions (elig-5, elig-6).

def test_c24_needs_a_qualifying_mentor_with_room_for_a_fellow():
    ok = {"is_indian_citizen": True, "has_phd_md_ms_or_thesis_submitted": True, "age": 30,
          "has_availed_npdf_before": False,
          "has_mentor_with_regular_position_and_phd_in_science_or_engineering": True,
          "mentor_current_npdf_fellows": 1}
    verdict = lambda **c: tools.evaluate_scheme({**ok, **c}, "C24")["verdict"]
    assert verdict() == "eligible"
    assert verdict(mentor_current_npdf_fellows=2) == "not_eligible"  # a third fellow would be one too many
    assert verdict(has_mentor_with_regular_position_and_phd_in_science_or_engineering=False) == "not_eligible"
    no_mentor_facts = {k: v for k, v in ok.items() if "mentor" not in k}
    assert tools.evaluate_scheme(no_mentor_facts, "C24")["verdict"] == "cant_tell"  # was "eligible"


def test_c26_needs_a_senior_mentor_without_another_candidate():
    ok = {"is_indian_citizen": True, "has_phd_in_science_engineering_or_ms_md": True,
          "holds_regular_position_in_state_university_college_or_private_institution": True,
          "has_ongoing_research_project_or_fellowship": False, "age": 40,
          "has_mentor_at_associate_professor_or_scientist_e_level": True,
          "mentor_has_another_tare_candidate": False}
    verdict = lambda **c: tools.evaluate_scheme({**ok, **c}, "C26")["verdict"]
    assert verdict() == "eligible"
    assert verdict(has_mentor_at_associate_professor_or_scientist_e_level=False) == "not_eligible"
    assert verdict(mentor_has_another_tare_candidate=True) == "not_eligible"


# 4. M08 and M09: rural or urban, as the source says (any urban area, not two exact strings).

@pytest.mark.parametrize("scheme_id", ["M08", "M09"])
def test_any_urban_area_gets_the_urban_limit(scheme_id):
    facts = {**M08, "household_below_bpl": False, "annual_income": 110000, "is_agricultural_project_loan": False}
    verdict = lambda **c: tools.evaluate_scheme({**facts, **c}, scheme_id)["verdict"]
    assert verdict(lives_in_urban_area=True) == "eligible"    # was not_eligible for "urban"
    assert verdict(lives_in_urban_area=False) == "not_eligible"
    assert verdict() == "cant_tell"                            # area unknown
    assert "area_type" not in tools.field_specs([scheme_id])


# 5. A failed closed-scheme lookup is not cached as "open".

def test_a_failed_closed_lookup_is_not_cached():
    tools.scheme_is_closed.cache_clear()
    with tools.tool_call_budget(1):
        tools.search_schemes({})                         # uses up the budget
        assert tools.scheme_is_closed("C11") is False    # no note this time ...
    assert tools.scheme_is_closed("C11") is True         # ... but the next lookup succeeds
    assert tools.scheme_is_closed("NO-SUCH-SCHEME") is False


def test_closed_check_works_inside_eligibility_without_giving_it_the_kb():
    # The app runs this inside the eligibility step; the lookup was forbidden, so no note was added.
    tools.scheme_is_closed.cache_clear()
    with tools.acting_as("eligibility"):
        assert tools.scheme_is_closed("C11") is True
        with pytest.raises(tools.ToolCallError, match="may not use this read tool"):
            tools.call_tool(tools.SCHEMES_KB, "get_scheme_details", scheme_id="C11")  # RT-032
