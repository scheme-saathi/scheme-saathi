import pytest

from graph.persona import load_persona_profile, profile_facts_to_rule_fields


def test_profile_facts_are_mapped_and_unknown_values_are_omitted():
    """Map household fact names to rule-engine names and omit unknown (None) facts."""
    profile = profile_facts_to_rule_fields(
        {
            "profile_facts": {
                "respondent_age": 46,
                "approx_annual_household_income_inr": 120000,
                "primary_occupation": "Small farmer",
                "household_size": None,
            }
        }
    )

    assert profile == {"age": 46, "income": 120000, "occupation": "Small farmer"}


def test_flat_persona_facts_are_supported():
    """Map rule-relevant facts when they are stored directly on a persona."""
    assert profile_facts_to_rule_fields(
        {"age": 46, "annual_household_income_inr": 120000}
    ) == {"age": 46, "income": 120000}


def test_load_persona_prefers_household_test_case_facts():
    """Return converted household-case facts when the ID exists in both data files."""
    assert load_persona_profile("SS001") == {
        "age": 46,
        "occupation": "Small farmer",
        "income": 120000,
        "household_situation": (
            "Cultivates a small landholding and wants to understand available farmer support."
        ),
        "documents_available": ["Aadhaar", "bank account", "land records"],
    }


def test_unknown_persona_id_is_reported():
    """Raise ValueError with the requested ID when no matching persona is found."""
    with pytest.raises(ValueError, match="No persona found with ID 'unknown'"):
        load_persona_profile("unknown")
