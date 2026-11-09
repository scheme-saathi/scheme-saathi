from agents.base import StructuredGPTAgent
from agents.contracts import DocumentCheckInput, DocumentCheckResult
from agents.document_checker import (
    DocumentCheckerAgent,
    _persona_mismatches,
)


def _checker(monkeypatch, model_result=None):
    observed_inputs = []
    model_result = model_result or DocumentCheckResult()

    def invoke(_agent, value):
        observed_inputs.append(value)
        return model_result

    monkeypatch.setattr(StructuredGPTAgent, "invoke", invoke)
    return DocumentCheckerAgent(None), observed_inputs


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
    agent, observed_inputs = _checker(monkeypatch)

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


def test_missing_documents_uses_normalized_names_and_clear_aliases(monkeypatch):
    agent, _ = _checker(monkeypatch)

    result = agent.invoke(
        DocumentCheckInput(
            scheme_id="C01",
            required_documents=[
                "Aadhaar card",
                "Bank passbook",
                "Income Certificate",
            ],
            available_documents=[
                "Aadhar Card: Name: Applicant",
                "Bank Account Passbook",
            ],
        )
    )

    assert result.missing_documents == ["Income Certificate"]
    assert result.authenticity_verified is False


def test_empty_checklist_requests_requirements_without_claiming_complete(monkeypatch):
    agent, _ = _checker(monkeypatch)

    result = agent.invoke(
        DocumentCheckInput(
            scheme_id="C01",
            available_documents=["Aadhaar card"],
        )
    )

    assert result.missing_documents == []
    assert any("required-document checklist" in q for q in result.clarifying_questions)


def test_empty_available_documents_reports_required_items_and_asks_clarification(
    monkeypatch,
):
    agent, _ = _checker(monkeypatch)
    required = ["Income certificate", "Age proof"]

    result = agent.invoke(
        DocumentCheckInput(scheme_id="C01", required_documents=required)
    )

    assert result.missing_documents == required
    assert any("no documents to report" in q for q in result.clarifying_questions)


def test_aadhaar_and_passbook_name_mismatch_is_reported_without_echoing_names(
    monkeypatch,
):
    agent, _ = _checker(monkeypatch)

    result = agent.invoke(
        DocumentCheckInput(
            scheme_id="C01",
            available_documents=[
                "Aadhaar card: Name: Asha Patil",
                "Bank passbook: Full name: Asha Patel",
            ],
        )
    )

    assert any(
        "Aadhaar card and bank passbook show different names" in message
        for message in result.possible_inconsistencies
    )
    assert any("Which name reflects" in q for q in result.clarifying_questions)
    assert all(
        "Asha Patil" not in message and "Asha Patel" not in message
        for message in result.possible_inconsistencies + result.clarifying_questions
    )


def test_document_titles_alone_do_not_create_persona_or_name_mismatches(monkeypatch):
    agent, _ = _checker(monkeypatch)

    result = agent.invoke(
        DocumentCheckInput(
            scheme_id="C01",
            required_documents=["Aadhaar card", "Bank passbook"],
            available_documents=["Aadhaar card", "Bank passbook"],
            household_persona={"age": 62},
        )
    )

    assert result.possible_inconsistencies == []
    assert result.clarifying_questions == []


def test_model_questions_are_preserved_and_duplicate_questions_removed(monkeypatch):
    agent, _ = _checker(
        monkeypatch,
        DocumentCheckResult(
            clarifying_questions=["Please share document list.", "Please share document list."]
        ),
    )

    result = agent.invoke(
        DocumentCheckInput(
            scheme_id="C01",
            required_documents=["Income certificate"],
        )
    )

    assert result.clarifying_questions == [
        "Please share document list.",
        "Does the family have no documents to report yet, or has the document list not been provided?",
    ]
