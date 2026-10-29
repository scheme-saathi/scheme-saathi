import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PERSONA_FILES = (
    ROOT / "data" / "personas" / "scheme_saathi_central_personas.json",
    ROOT / "data" / "personas" / "scheme_saathi_maharashtrastate_personas.json",
)
HOUSEHOLD_TEST_CASES = (
    ROOT / "data" / "household_profiles" / "scheme_saathi_50_household_profile_test_cases.json",
)
RULE_FIELD_ALIASES = {
    "respondent_age": "age",
    "approx_annual_household_income_inr": "income",
    "annual_household_income_inr": "income",
    "primary_occupation": "occupation",
}


def profile_facts_to_rule_fields(persona: Mapping[str, Any]) -> dict[str, Any]:
    """Prepare persona facts in the field format expected by the rule engine.

    Accepts either a household test case containing a ``profile_facts`` object or
    a persona whose facts are stored directly in the object. Renames known fields
    (for example, ``respondent_age`` to ``age``) and skips facts with ``None``
    values so unknown information is not treated as a confirmed answer.

    Args:
        persona: Persona or household test-case data to convert.

    Returns:
        A new dictionary containing the available facts with rule-engine field
        names.

    Raises:
        ValueError: If ``profile_facts`` is present but is not an object.
    """
    facts = persona.get("profile_facts", persona)
    if not isinstance(facts, Mapping):
        raise ValueError("Persona profile_facts must be an object")

    profile: dict[str, Any] = {}
    for field, value in facts.items():
        if value is not None:
            profile[RULE_FIELD_ALIASES.get(field, field)] = value
    return profile


def load_persona_profile(persona_id: str) -> dict[str, Any]:
    """Find a saved persona and return its facts for the rule engine.

    Searches household test cases first, then the Central and Maharashtra persona
    files. If the ID appears in both a test case and a persona file, the test
    case's ``profile_facts`` are used. The result is converted to rule-engine
    field names, and unknown (``None``) values are omitted.

    Args:
        persona_id: ID to find, such as ``SS001``.

    Returns:
        The persona's available facts in rule-engine profile format.

    Raises:
        ValueError: If no saved persona or household test case has this ID.
    """
    for path in HOUSEHOLD_TEST_CASES:
        cases = json.loads(path.read_text(encoding="utf-8"))
        for case in cases:
            if case.get("source_persona_id") == persona_id:
                return profile_facts_to_rule_fields(case)

    for path in PERSONA_FILES:
        personas = json.loads(path.read_text(encoding="utf-8"))
        for persona in personas:
            if persona.get("persona_id") == persona_id:
                return profile_facts_to_rule_fields(persona)

    raise ValueError(f"No persona found with ID '{persona_id}'.")
