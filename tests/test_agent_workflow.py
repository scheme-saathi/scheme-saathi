import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agents.application import ApplicationAgent
from agents.contracts import (
    ApplicationDraft,
    ApplicationInput,
    ApplicationNarrative,
    DocumentCheckResult,
    EligibilityNarrative,
    IntakeInput,
    IntakeResult,
    SupervisorPlan,
)
from graph.agent_workflow import AgentSet, build_agent_graph
from graph.persona import HOUSEHOLD_TEST_CASES, profile_facts_to_rule_fields
from agents.memory import ApplicationReference, MemoryConsent, MemoryFact
from servers.rule_engine.scheme import SchemeRecord

ROOT = Path(__file__).resolve().parents[1]


class StubAgent:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def invoke(self, value):
        self.calls.append(value)
        return self.result


def build_agents(
    *,
    intake=None,
    plan=None,
    eligibility=None,
    documents=None,
    application=None,
):
    return AgentSet(
        intake=intake or StubAgent(IntakeResult(language="en", intent="eligibility")),
        supervisor=plan or StubAgent(SupervisorPlan(next_agent="eligibility", reason="Check eligibility.")),
        eligibility=eligibility or StubAgent(EligibilityNarrative(explanation="Reviewed result.")),
        document_checker=documents or StubAgent(DocumentCheckResult()),
        application=application or StubAgent(
            ApplicationDraft(
                scheme_id="C01",
                fields={},
                missing_fields=[],
                review_summary="Draft is ready for human review.",
            )
        ),
    )


def test_intake_questions_pause_before_supervisor_or_specialists():
    agents = build_agents(
        intake=StubAgent(
            IntakeResult(
                language="mr",
                intent="eligibility",
                clarifying_questions=["Which district do you live in?"],
            )
        )
    )

    result = build_agent_graph(agents).invoke({"request": "मला योजना शोधायची आहे"})

    assert result["status"] == "needs_clarification"
    assert "Which district" in result["response"]
    assert agents.supervisor.calls == []


def test_document_request_is_routed_to_checker_without_application_access():
    documents = StubAgent(
        DocumentCheckResult(
            missing_documents=["Income certificate"],
            authenticity_verified=False,
        )
    )
    application = StubAgent(
        ApplicationDraft(
            scheme_id="C01",
            fields={},
            missing_fields=[],
            review_summary="Should not run.",
        )
    )
    agents = build_agents(
        plan=StubAgent(
            SupervisorPlan(next_agent="document_checker", reason="Check documents.")
        ),
        documents=documents,
        application=application,
    )

    result = build_agent_graph(agents).invoke(
        {
            "request": "Which documents are missing?",
            "selected_scheme_id": "C01",
            "required_documents": ["Income certificate"],
            "available_documents": [],
        }
    )

    assert result["status"] == "documents_checked"
    assert "Income certificate" in result["response"]
    assert application.calls == []


def test_respond_route_does_not_invoke_specialists():
    agents = build_agents(
        plan=StubAgent(SupervisorPlan(next_agent="respond", reason="Please clarify your request."))
    )

    result = build_agent_graph(agents).invoke({"request": "Hello"})

    assert result["status"] == "responded"
    assert result["response"] == "Please clarify your request."
    assert agents.eligibility.calls == []


def test_missing_deterministic_evaluation_fails_closed():
    agents = build_agents(
        plan=StubAgent(SupervisorPlan(next_agent="eligibility", reason="Check eligibility."))
    )

    result = build_agent_graph(agents).invoke(
        {"request": "Am I eligible?", "selected_scheme_id": "C01"}
    )

    assert result["eligibility"]["verdict"] == "cant_tell"
    assert agents.eligibility.calls == []


def test_gpt_explanation_cannot_change_deterministic_verdict_or_citations():
    agents = build_agents()
    evaluation = {
        "verdict": "not_eligible",
        "reason": "A reviewed condition is not satisfied.",
        "missing_fields": ["landholding_hectares"],
        "unresolved_fields": ["landholding_hectares"],
        "conditions": [],
        "citations": [],
    }

    result = build_agent_graph(agents).invoke(
        {
            "request": "Am I eligible?",
            "selected_scheme_id": "C01",
            "deterministic_evaluation": evaluation,
        }
    )

    assert result["eligibility"]["verdict"] == "not_eligible"
    assert result["eligibility"]["missing_fields"] == ["landholding_hectares"]
    assert result["eligibility"]["explanation"] == "Reviewed result."


def test_application_route_stops_when_deterministic_result_is_not_eligible():
    documents = StubAgent(DocumentCheckResult())
    application = StubAgent(
        ApplicationDraft(
            scheme_id="C01",
            fields={},
            missing_fields=[],
            review_summary="Should not run.",
        )
    )
    agents = build_agents(
        plan=StubAgent(SupervisorPlan(next_agent="application", reason="Prepare draft.")),
        documents=documents,
        application=application,
    )

    result = build_agent_graph(agents).invoke(
        {
            "request": "Help me apply",
            "selected_scheme_id": "C01",
            "deterministic_evaluation": {
                "verdict": "cant_tell",
                "reason": "Rules are incomplete.",
                "missing_fields": [],
                "unresolved_fields": [],
                "conditions": [],
                "citations": [],
            },
        }
    )

    assert result["eligibility"]["verdict"] == "cant_tell"
    assert documents.calls == []
    assert application.calls == []


def test_application_route_requires_eligibility_and_returns_review_only_draft():
    agents = build_agents(
        plan=StubAgent(SupervisorPlan(next_agent="application", reason="Prepare draft.")),
        documents=StubAgent(DocumentCheckResult()),
    )

    result = build_agent_graph(agents).invoke(
        {
            "request": "Help me apply",
            "selected_scheme_id": "C01",
            "known_facts": {"age": 30},
            "deterministic_evaluation": {
                "verdict": "eligible",
                "reason": "All reviewed conditions are satisfied.",
                "missing_fields": [],
                "unresolved_fields": [],
                "conditions": [],
                "citations": [],
            },
        }
    )

    assert result["status"] == "draft_ready_for_review"
    assert result["application_draft"]["review_summary"] == "Draft is ready for human review."
    assert "submission" not in result
    assert agents.application.calls[0].confirmed_facts == {}


def test_existing_household_persona_fixtures_validate_as_agent_context():
    for path in HOUSEHOLD_TEST_CASES:
        cases = json.loads(path.read_text(encoding="utf-8"))
        for case in cases:
            facts = profile_facts_to_rule_fields(case)
            validated = IntakeInput(
                request=case["simulated_user_opening"],
                known_facts=facts,
            )
            assert validated.known_facts == facts


def test_existing_rule_schema_files_validate():
    for path in (ROOT / "data" / "rules").glob("*.json"):
        SchemeRecord.model_validate_json(path.read_text(encoding="utf-8"))


def test_application_fields_are_copied_only_from_confirmed_fact_mapping(monkeypatch):
    class NarrativeAgent:
        def __init__(self, *args):
            pass

        def invoke(self, value):
            return ApplicationNarrative(review_summary="Review the mapped draft.")

    monkeypatch.setattr("agents.application.StructuredGPTAgent", NarrativeAgent)
    agent = ApplicationAgent(model=None)
    draft = agent.invoke(
        ApplicationInput(
            scheme_id="C01",
            confirmed_facts={"age": 42, "unknown": "not mapped"},
            required_fields=["applicant_age", "household_size"],
            field_mapping={
                "applicant_age": "age",
                "household_size": "household_size",
            },
        )
    )

    assert draft.fields == {"applicant_age": 42}
    assert draft.missing_fields == ["household_size"]
    assert draft.review_summary == "Review the mapped draft."


def test_application_agent_rejects_unreviewed_form_fields_before_model_call(monkeypatch):
    class NarrativeAgent:
        def __init__(self, *args):
            pass

        def invoke(self, value):
            raise AssertionError("Narrative model must not run for an invalid schema.")

    monkeypatch.setattr("agents.application.StructuredGPTAgent", NarrativeAgent)
    agent = ApplicationAgent(model=None)

    with pytest.raises(ValueError, match="outside the reviewed application schema"):
        agent.invoke(
            ApplicationInput(
                scheme_id="C01",
                confirmed_facts={"age": 42},
                required_fields=["applicant_age"],
                field_mapping={"unreviewed_field": "age"},
            )
        )


def test_long_term_memory_contracts_require_separate_consent_and_valid_expiry():
    from datetime import datetime, timedelta, timezone

    confirmed_at = datetime.now(timezone.utc)
    reconfirm_by = confirmed_at + timedelta(days=30)
    expires_at = confirmed_at + timedelta(days=60)
    fact = MemoryFact(
        field="district_code",
        value="IN-MH-PN",
        source="citizen_confirmed",
        confirmed_at=confirmed_at,
        reconfirm_by=reconfirm_by,
        expires_at=expires_at,
        consent_reference="memory-consent-1",
    )
    reference = ApplicationReference(
        scheme_id="C01",
        application_id="MOCK-APP-001",
        submitted_at=confirmed_at,
        expires_at=expires_at,
        consent_reference="application-reference-consent-1",
    )
    profile_consent = MemoryConsent(
        purpose="profile_facts",
        granted=True,
        notice_version="v1",
        decided_at=confirmed_at,
        expires_at=expires_at,
        consent_reference=fact.consent_reference,
    )
    application_consent = MemoryConsent(
        purpose="application_references",
        granted=True,
        notice_version="v1",
        decided_at=confirmed_at,
        expires_at=expires_at,
        consent_reference=reference.consent_reference,
    )

    assert profile_consent.purpose != application_consent.purpose
    assert fact.consent_reference == profile_consent.consent_reference
    assert reference.consent_reference == application_consent.consent_reference
    with pytest.raises(ValidationError, match="deadlines must be ordered"):
        MemoryFact(
            field="district_code",
            value="IN-MH-PN",
            source="citizen_confirmed",
            confirmed_at=confirmed_at,
            reconfirm_by=expires_at,
            expires_at=reconfirm_by,
            consent_reference="memory-consent-2",
        )


def test_model_factory_requires_configuration_without_network_access(monkeypatch):
    from agents import model_factory

    monkeypatch.setattr(model_factory, "load_dotenv", lambda: None)
    monkeypatch.delenv("SUPERVISOR_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="SUPERVISOR_MODEL"):
        model_factory.create_chat_model("supervisor")


@pytest.mark.parametrize(
    ("variables", "expected_base_url"),
    [
        (
            {
                "OPENROUTER_API_KEY": "test-key",
                "OPENROUTER_BASE_URL": "https://openrouter.example/v1",
                "SUPERVISOR_MODEL": "openai/gpt-model",
            },
            "https://openrouter.example/v1",
        ),
        (
            {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_BASE_URL": "https://api.openai.example/v1",
                "SUPERVISOR_MODEL": "gpt-model",
            },
            "https://api.openai.example/v1",
        ),
    ],
)
def test_model_factory_uses_configured_gpt_provider_and_model(
    monkeypatch, variables, expected_base_url
):
    from agents import model_factory

    monkeypatch.setattr(model_factory, "load_dotenv", lambda: None)
    captured = {}
    monkeypatch.setattr(
        model_factory,
        "ChatOpenAI",
        lambda **kwargs: captured.update(kwargs) or kwargs,
    )
    for name in (
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_BASE_URL",
        "OPENROUTER_BASE_URL",
        "SUPERVISOR_MODEL",
        "SPECIALIST_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in variables.items():
        monkeypatch.setenv(name, value)

    model_factory.create_chat_model("supervisor")

    assert captured["model"] == variables["SUPERVISOR_MODEL"]
    assert captured["base_url"] == expected_base_url
    assert captured["temperature"] == 0
    assert captured["max_retries"] == 2
