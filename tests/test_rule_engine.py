"""Integration tests for loading and evaluating a scheme through mock tools."""

import pytest

from graph.tools import evaluate_scheme


@pytest.mark.parametrize(
    ("profile", "expected_verdict", "expected_missing"),
    [
        (
            {"age": 62, "is_widow": True, "income": 250000},
            "eligible",
            [],
        ),
        (
            {"age": 59, "is_widow": True, "income": 250000},
            "not_eligible",
            [],
        ),
        (
            {"age": 62, "is_widow": True},
            "cant_tell",
            ["income"],
        ),
    ],
    ids=["eligible-profile", "ineligible-profile", "missing-income"],
)
def test_evaluate_scheme_loads_fixture_and_returns_result(
    profile: dict[str, object],
    expected_verdict: str,
    expected_missing: list[str],
) -> None:
    result = evaluate_scheme(profile, "SYNTH-PENSION-001")

    assert result["verdict"] == expected_verdict
    assert result["missing_fields"] == expected_missing
    assert {clause["clause_id"] for clause in result["citations"]} == {"cl-1", "cl-2"}
