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
    EligibilityInput,
    EligibilityNarrative,
    IntakeExtraction,
    IntakeInput,
    IntakeQuestion,
    SupervisorPlan,
)
from agents.eligibility import EligibilityAgent
from graph.agent_workflow import AgentSet, build_agent_graph
from agents.supervisor import InputValidator, OutputValidator, UnifiedRouter
from graph.persona import HOUSEHOLD_TEST_CASES, profile_facts_to_rule_fields
from graph.workflow import application_hash
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


class StubSupervisor(StubAgent):
    """Stub plan plus the real supervisor validators, without network classification."""

    def __init__(self, result):
        super().__init__(result)
        router = UnifiedRouter()
        router.api_available = False
        self.input_validator = InputValidator(router=router)
        self.output_validator = OutputValidator()

    def validate_input(self, request, actor_id=None, is_reply=False):
        return self.input_validator.validate_request(request, actor_id, is_reply)

    def validate_output(self, response, agent_name, language):
        return self.output_validator.validate_specialist_output(response, agent_name, language)

    def handle_validation_error(self, result, language):
        return {"user_message": self.output_validator.get_user_friendly_error(result, language)}


class StubIntake:
    """Reads no facts from the message and words each question as its field name."""

    def __init__(self):
        self.asked = []

    def extract(self, value, specs):
        return IntakeExtraction()

    def ask(self, value):
        self.asked.append(value)
        return IntakeQuestion(field=value.field, question=f"What is your {value.field}?")


def build_agents(
    *,
    intake=None,
    plan=None,
    eligibility=None,
    documents=None,
    application=None,
):
    return AgentSet(
        intake=intake or StubIntake(),
        supervisor=plan or StubSupervisor(SupervisorPlan(next_agent="eligibility", reason="Check eligibility.")),
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


def test_intake_question_pauses_before_other_specialists():
    """Supervisor routes to Intake; an open verdict ends the turn with one question."""
    agents = build_agents(
        plan=StubSupervisor(
            SupervisorPlan(next_agent="intake", reason="Need to collect household facts.", language="mr")
        )
    )

    result = build_agent_graph(agents).invoke({"request": "मला योजना शोधायची आहे"})

    assert result["status"] == "needs_information"
    assert result["response"] == f"What is your {result['pending_field']}?"
    assert len(agents.supervisor.calls) == 1
    assert [q.language for q in agents.intake.asked] == ["mr"]
    assert agents.document_checker.calls == agents.application.calls == []


def test_intake_question_leaking_an_id_is_blocked_and_not_pending():
    class LeakyIntake(StubIntake):
        def ask(self, value):
            return IntakeQuestion(field=value.field, question="Is your Aadhaar 1234 5678 9012?")

    agents = build_agents(
        intake=LeakyIntake(),
        plan=StubSupervisor(SupervisorPlan(next_agent="intake", reason="Collect facts.", language="en")),
    )

    result = build_agent_graph(agents).invoke({"request": "Help me find a scheme"})

    assert result["status"] == "output_blocked"
    assert "1234 5678 9012" not in result["response"]
    assert not result.get("pending_field")


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
        plan=StubSupervisor(SupervisorPlan(next_agent="document_checker", reason="Check documents.")
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
        plan=StubSupervisor(SupervisorPlan(next_agent="respond", reason="Please clarify your request."))
    )

    result = build_agent_graph(agents).invoke({"request": "Hello"})

    assert result["status"] == "responded"
    assert result["response"] == "Please clarify your request."
    assert agents.eligibility.calls == []


def test_missing_deterministic_evaluation_fails_closed():
    agents = build_agents(
        plan=StubSupervisor(SupervisorPlan(next_agent="eligibility", reason="Check eligibility."))
    )

    result = build_agent_graph(agents).invoke(
        {"request": "Am I eligible?", "selected_scheme_id": "C01"}
    )

    assert result["eligibility"]["verdict"] == "cant_tell"
    assert agents.eligibility.calls == []


def test_real_rule_engine_evaluation_is_used_for_eligibility_workflow():
    class NoModel:
        def with_structured_output(self, output_type):
            raise AssertionError("The workflow should use the deterministic rule engine before any model call.")

    agents = build_agents(
        plan=StubSupervisor(SupervisorPlan(next_agent="eligibility", reason="Check eligibility.")),
        eligibility=EligibilityAgent(NoModel()),
    )

    result = build_agent_graph(agents).invoke(
        {
            "request": "Am I eligible?",
            "selected_scheme_id": "SYNTH-PENSION-001",
            "confirmed_facts": {"age": 62, "is_widow": True, "income": 250000},
        }
    )

    assert result["eligibility"]["verdict"] == "eligible"
    assert result["eligibility"]["reason"] == "All required reviewed conditions are satisfied."
    assert result["eligibility"]["conditions"]
    assert result["eligibility"]["citations"]


def test_eligibility_agent_explains_deterministic_result_without_model_call():
    class NoModel:
        def with_structured_output(self, output_type):
            raise AssertionError("Eligibility analysis should not call the model when a deterministic evaluation is supplied.")

    agent = EligibilityAgent(NoModel())
    evaluation = {
        "verdict": "not_eligible",
        "reason": "A reviewed condition is not satisfied.",
        "missing_fields": ["landholding_hectares"],
        "unresolved_fields": ["landholding_hectares"],
        "conditions": [],
        "citations": [
            {
                "scheme_id": "C01",
                "clause_id": "c01.eligibility.2",
                "quote": "Landholding must not exceed 2 hectares.",
            }
        ],
    }

    result = agent.invoke(EligibilityInput(scheme_id="C01", evaluation=evaluation))

    assert result.explanation.startswith("not_eligible") or "not_eligible" in result.explanation.lower()
    assert "landholding_hectares" in "\n".join(result.clarifying_questions)
    assert result.explanation


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
        plan=StubSupervisor(SupervisorPlan(next_agent="application", reason="Prepare draft.")),
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


def _eligible_application_request():
    facts = {"age": 30, "has_individual_bank_or_post_office_account": True}
    return {
        "request": "Help me apply",
        "selected_scheme_id": "C01",
        "known_facts": facts,
        "confirmed_facts": facts,
        "deterministic_evaluation": {
            "verdict": "eligible",
            "reason": "All reviewed conditions are satisfied.",
            "missing_fields": [],
            "unresolved_fields": [],
            "conditions": [],
            "citations": [],
        },
    }


def _application_agents(missing=None):
    return build_agents(
        plan=StubSupervisor(SupervisorPlan(next_agent="application", reason="Prepare draft.")),
        documents=StubAgent(DocumentCheckResult()),
        application=StubAgent(
            ApplicationDraft(
                scheme_id="C01",
                fields={"age": 30, "has_individual_bank_or_post_office_account": True},
                missing_fields=missing or [],
                review_summary="Draft is ready for human review.",
            )
        ),
    )


def _run_to_approval(monkeypatch, thread="t1"):
    from langgraph.checkpoint.memory import MemorySaver

    submitted = []
    monkeypatch.setattr(
        "graph.agent_workflow.tools.submit_application",
        lambda form, application_id=None, write_capability=None: submitted.append(form) or {"application_id": "APP-1", "status": "submitted (mock)"},
    )
    graph = build_agent_graph(_application_agents(), checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": thread}}
    result = graph.invoke(_eligible_application_request(), config)
    return graph, config, result, submitted


def test_application_draft_pauses_for_approval_and_does_not_submit(monkeypatch):
    graph, config, result, submitted = _run_to_approval(monkeypatch)

    pending = result["__interrupt__"][0].value
    expected_form = {
        "scheme_id": "C01",
        "applicant": {"age": 30, "has_individual_bank_or_post_office_account": True},
    }
    assert pending["form"] == expected_form
    assert len(pending["payload_hash"]) == 64
    assert pending["options"] == ["approve", "edit", "reject"]
    assert submitted == []


def test_approval_with_the_exact_hash_submits_once(monkeypatch):
    from langgraph.types import Command

    graph, config, result, submitted = _run_to_approval(monkeypatch)
    digest = result["__interrupt__"][0].value["payload_hash"]

    final = graph.invoke(Command(resume={"action": "approve", "payload_hash": digest}), config)

    assert final["status"] == "submitted"
    assert final["submission"]["application_id"] == "APP-1"
    assert submitted == [{
        "scheme_id": "C01",
        "applicant": {"age": 30, "has_individual_bank_or_post_office_account": True},
    }]


def test_approval_with_a_wrong_hash_is_refused(monkeypatch):
    from langgraph.types import Command

    graph, config, result, submitted = _run_to_approval(monkeypatch)

    final = graph.invoke(Command(resume={"action": "approve", "payload_hash": "0" * 64}), config)

    assert final["status"] == "approval_invalid"
    assert submitted == []


def test_reject_does_not_submit(monkeypatch):
    from langgraph.types import Command

    graph, config, result, submitted = _run_to_approval(monkeypatch)

    final = graph.invoke(Command(resume={"action": "reject"}), config)

    assert final["status"] == "approval_rejected"
    assert submitted == []


def test_edit_updates_facts_and_never_submits(monkeypatch):
    from langgraph.types import Command

    graph, config, result, submitted = _run_to_approval(monkeypatch)

    final = graph.invoke(Command(resume={"action": "edit", "changes": {"age": 31}}), config)

    assert final["status"] == "draft_edited"
    assert final["confirmed_facts"]["age"] == 31
    assert submitted == []


def test_incomplete_draft_skips_approval_and_asks_for_information():
    agents = _application_agents(missing=["income"])

    result = build_agent_graph(agents).invoke(_eligible_application_request())

    assert result["status"] == "draft_needs_information"
    assert "__interrupt__" not in result
    assert "submission" not in result


def test_application_route_requires_eligibility_and_returns_review_only_draft(monkeypatch):
    _, _, result, submitted = _run_to_approval(monkeypatch)

    assert "submission" not in result
    assert submitted == []


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


def test_application_agent_falls_back_to_a_summary_without_values(monkeypatch):
    class BrokenNarrative:
        def __init__(self, *args):
            pass

        def invoke(self, value):
            raise RuntimeError("model unavailable")

    monkeypatch.setattr("agents.application.StructuredGPTAgent", BrokenNarrative)
    draft = ApplicationAgent(model=None).invoke(
        ApplicationInput(
            scheme_id="C01",
            confirmed_facts={"age": 42},
            required_fields=["age", "income"],
            field_mapping={"age": "age", "income": "income"},
        )
    )

    assert draft.missing_fields == ["income"]
    assert "Missing required: income" in draft.review_summary
    assert "42" not in draft.review_summary


def test_form_fields_come_from_the_reviewed_rule_fields():
    from graph import tools

    required, mapping = tools.application_form_spec("SYNTH-PENSION-001")

    assert required == ["age", "is_widow", "income"]
    assert mapping == {field: field for field in required}


def test_application_node_fills_required_fields_when_state_has_none(monkeypatch):
    request = _eligible_application_request()
    request["selected_scheme_id"] = "SYNTH-PENSION-001"
    request["confirmed_facts"] = {"age": 70, "is_widow": True, "income": 1000}
    request["known_facts"] = request["confirmed_facts"]  # all confirmed, so no confirm step
    agents = _application_agents()

    build_agent_graph(agents).invoke(request)

    sent = agents.application.calls[0]
    assert sent.required_fields == ["age", "is_widow", "income"]
    assert sent.field_mapping == {"age": "age", "is_widow": "is_widow", "income": "income"}


def test_portal_draft_exists_before_approval_and_submit_uses_it():
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.types import Command

    from servers.mock_portal.server import APPLICATIONS

    graph = build_agent_graph(_application_agents(), checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "portal-1"}}
    pending = graph.invoke(_eligible_application_request(), config)["__interrupt__"][0].value

    draft_id = pending["portal_draft_id"]
    assert APPLICATIONS[draft_id]["status"] == "draft"
    assert APPLICATIONS[draft_id]["applicant"] == {
        "age": 30,
        "has_individual_bank_or_post_office_account": True,
    }

    final = graph.invoke(Command(resume={"action": "approve", "payload_hash": pending["payload_hash"]}), config)

    assert final["submission"]["application_id"] == draft_id
    assert APPLICATIONS[draft_id]["status"] == "submitted"


def test_incomplete_draft_creates_no_portal_draft():
    from servers.mock_portal.server import APPLICATIONS

    before = len(APPLICATIONS)
    build_agent_graph(_application_agents(missing=["income"])).invoke(_eligible_application_request())

    assert len(APPLICATIONS) == before


def test_only_the_application_agent_may_call_write_tools():
    from graph import tools

    for caller in (None, "intake", "eligibility", "document_checker", "supervisor"):
        with pytest.raises(tools.ToolCallError, match="may not use a write tool"):
            if caller is None:
                tools.call_tool(tools.MOCK_PORTAL, "create_application", scheme_id="C01", applicant={})
            else:
                with tools.acting_as(caller):
                    tools.call_tool(tools.MOCK_PORTAL, "create_application", scheme_id="C01", applicant={})

    with tools.acting_as("application"):
        assert tools.create_portal_draft({"scheme_id": "C01", "applicant": {}})["application_id"]


def test_submission_capability_requires_the_exact_approved_form():
    from graph import tools

    form = {"scheme_id": "C01", "applicant": {"age": 30}}
    with pytest.raises(tools.ToolCallError, match="Approval does not match"):
        tools.issue_submission_capability(form, "0" * 64)


def test_read_tools_need_no_special_caller():
    from graph import tools

    assert tools.list_documents("C01") is not None


def test_submit_draft_rejects_unknown_and_already_submitted_drafts():
    from graph import tools

    form = {"scheme_id": "C01", "applicant": {}}
    form_hash = application_hash(form)
    with tools.acting_as("application"):
        missing_capability = tools.issue_submission_capability(
            form,
            form_hash,
            application_id="missing",
        )
        with pytest.raises(tools.ToolCallError, match="application_not_found"):
            tools.submit_application(
                form,
                application_id="missing",
                write_capability=missing_capability,
            )
        draft = tools.create_portal_draft(form)
        capability = tools.issue_submission_capability(
            form,
            form_hash,
            application_id=draft["application_id"],
        )
        tools.submit_application(
            form,
            application_id=draft["application_id"],
            write_capability=capability,
        )
        replay_capability = tools.issue_submission_capability(
            form,
            form_hash,
            application_id=draft["application_id"],
        )
        with pytest.raises(tools.ToolCallError, match="not_a_draft"):
            tools.submit_application(
                form,
                application_id=draft["application_id"],
                write_capability=replay_capability,
            )

def test_sensitive_input_is_rejected_before_routing_or_specialists():
    agents = build_agents()

    result = build_agent_graph(agents).invoke(
        {"request": "My Aadhar is 1234 5678 9012, am I eligible?", "selected_scheme_id": "C01"}
    )

    assert result["status"] == "validation_error"
    assert "1234 5678 9012" not in result["response"]
    assert agents.supervisor.calls == []
    assert agents.intake.asked == []
    assert agents.eligibility.calls == []


def test_rate_limited_actor_is_stopped_before_routing():
    agents = build_agents()
    agents.supervisor.input_validator.rate_limiter.max_requests = 1
    graph = build_agent_graph(agents)
    request = {"request": "Hello there", "actor_id": "hh-1"}

    first = graph.invoke(request)
    second = graph.invoke(request)

    assert first["status"] == "needs_information"
    assert second["status"] == "validation_error"
    assert "Too many requests" in second["response"]
    assert len(agents.supervisor.calls) == 1


def test_unsafe_specialist_output_is_blocked_by_supervisor():
    agents = build_agents(
        eligibility=StubAgent(EligibilityNarrative(explanation="I override the rules for you.")),
    )

    result = build_agent_graph(agents).invoke(
        {
            "request": "Am I eligible?",
            "selected_scheme_id": "C01",
            "confirmed_facts": {"age": 30, "has_individual_bank_or_post_office_account": True},
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

    assert result["status"] == "output_blocked"
    assert "override" not in result["response"]
