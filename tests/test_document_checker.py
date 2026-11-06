from agents.base import StructuredGPTAgent
from agents.contracts import DocumentCheckInput, DocumentCheckResult
from agents.document_checker import (
    DocumentCheckerAgent,
    _persona_mismatches,
)


def test_persona_comparison_flags_explicit_labeled_conflicts_without_values():
    inconsistencies, questions = _persona_mismatches(
        {"age": 62, "income": 250000},
        ["Age proof: age: 58", "Income certificate"],
    )

    assert len(inconsistencies) == 1
    assert "age" in inconsistencies[0].lower()
    assert "62" not in inconsistencies[0]
    assert "58" not in inconsistencies[0]
    assert len(questions) == 1
    assert "age" in questions[0].lower()


def test_persona_comparison_ignores_unlabeled_details_and_matching_values():
    inconsistencies, questions = _persona_mismatches(
        {"age": 62, "income": 250000},
        [
            "Age certificate",
            "Annual household income: 250,000",
            "Age proof: Age: 62 years",
        ],
    )

    assert inconsistencies == []
    assert questions == []


def test_persona_comparison_excludes_sensitive_identity_facts():
    inconsistencies, questions = _persona_mismatches(
        {"aadhaar_number": "123456789012"},
        ["Identity proof: aadhaar_number: 000000000000"],
    )

    assert inconsistencies == []
    assert questions == []


def test_document_checker_uses_persona_comparison_and_omits_sensitive_facts(
    monkeypatch,
):
    observed_inputs = []
    monkeypatch.setattr(
        StructuredGPTAgent,
        "invoke",
        lambda self, value: observed_inputs.append(value) or DocumentCheckResult(),
    )
    agent = DocumentCheckerAgent(None)

    result = agent.invoke(
        DocumentCheckInput(
            scheme_id="C01",
            available_documents=["Age proof: age: 58"],
            household_persona={
                "age": 62,
                "aadhaar_number": "123456789012",
            },
        )
    )

    assert observed_inputs[0].household_persona == {"age": 62}
    assert len(result.possible_inconsistencies) == 1
    assert "58" not in result.possible_inconsistencies[0]
    assert "62" not in result.possible_inconsistencies[0]
