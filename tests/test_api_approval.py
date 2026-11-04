import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from agents.contracts import (
    ApplicationDraft,
    DocumentCheckResult,
    EligibilityNarrative,
    IntakeResult,
    SupervisorPlan,
)
from app import api
from graph.agent_workflow import AgentSet, build_agent_graph
from agents.supervisor import InputValidator, OutputValidator, UnifiedRouter
from servers.mock_portal.server import APPLICATIONS


class StubAgent:
    def __init__(self, result):
        self.result = result

    def invoke(self, value):
        return self.result


class StubSupervisor(StubAgent):
    def __init__(self, result):
        super().__init__(result)
        router = UnifiedRouter()
        router.api_available = False
        self.input_validator = InputValidator(router=router)
        self.output_validator = OutputValidator()

    def validate_input(self, request, actor_id=None):
        return self.input_validator.validate_request(request, actor_id)

    def validate_output(self, response, agent_name, language):
        return self.output_validator.validate_specialist_output(response, agent_name, language)

    def handle_validation_error(self, result, language):
        return {"user_message": self.output_validator.get_user_friendly_error(result, language)}


def make_agents(missing=None):
    return AgentSet(
        intake=StubAgent(IntakeResult(language="en", intent="application")),
        supervisor=StubSupervisor(SupervisorPlan(next_agent="application", reason="Prepare draft.")),
        eligibility=StubAgent(EligibilityNarrative(explanation="Reviewed result.")),
        document_checker=StubAgent(DocumentCheckResult()),
        application=StubAgent(
            ApplicationDraft(
                scheme_id="C01",
                fields={"age": 30},
                missing_fields=missing or [],
                review_summary="Draft is ready for human review.",
            )
        ),
    )


ELIGIBLE = {
    "verdict": "eligible",
    "reason": "All reviewed conditions are satisfied.",
    "missing_fields": [],
    "unresolved_fields": [],
    "conditions": [],
    "citations": [],
}


class WithEvaluation:
    """Stands in for the rule-engine step that supplies the deterministic result."""

    def __init__(self, graph):
        self._graph = graph

    def invoke(self, state, config):
        if isinstance(state, dict):
            state = {**state, "deterministic_evaluation": ELIGIBLE, "confirmed_facts": {"age": 30}}
        return self._graph.invoke(state, config)

    def get_state(self, config):
        return self._graph.get_state(config)


@pytest.fixture
def client(monkeypatch):
    service = api.AgentWorkflowService()
    service._agent_graph = WithEvaluation(build_agent_graph(make_agents(), checkpointer=MemorySaver()))
    monkeypatch.setattr(api, "get_workflow_service", lambda: service)
    return TestClient(api.create_api(service=object()))


def send(client, actor="household-1", thread_id=None, message="Help me apply"):
    body = {
        "message": message,
        "actor_id": actor,
        "known_facts": {"age": 30},
        "selected_scheme_id": "C01",
    }
    if thread_id:
        body["thread_id"] = thread_id
    return client.post("/api/chat", json=body, headers={"x-actor-id": actor})


def decide(client, thread_id, actor="household-1", **body):
    return client.post(f"/api/chat/{thread_id}/decision", json=body, headers={"x-actor-id": actor})


def start_paused(client):
    first = send(client)
    assert first.status_code == 200, first.text
    return first.json()


def test_chat_reports_detected_language_and_intent_not_the_client_hint(client):
    body = {
        "message": "I want to apply for this scheme",
        "actor_id": "household-1",
        "language": "hi",
        "known_facts": {"age": 30},
        "selected_scheme_id": "C01",
    }

    response = client.post("/api/chat", json=body, headers={"x-actor-id": "household-1"}).json()

    assert response["intent"] == "application"
    assert response["language"] == "en"


def test_chat_pauses_with_the_exact_form_and_does_not_submit(client):
    paused = start_paused(client)

    assert paused["next_step"] == "awaiting_approval"
    approval = paused["data"]["approval"]
    assert approval["form"] == {"scheme_id": "C01", "applicant": {"age": 30}}
    assert len(approval["payload_hash"]) == 64
    assert APPLICATIONS[approval["portal_draft_id"]]["status"] == "draft"


def test_approving_with_the_exact_hash_submits(client):
    paused = start_paused(client)
    approval = paused["data"]["approval"]

    done = decide(client, paused["thread_id"], action="approve", payload_hash=approval["payload_hash"])

    assert done.status_code == 200, done.text
    assert done.json()["next_step"] == "submitted"
    assert APPLICATIONS[approval["portal_draft_id"]]["status"] == "submitted"


def test_wrong_hash_is_refused_and_nothing_is_submitted(client):
    paused = start_paused(client)
    approval = paused["data"]["approval"]

    refused = decide(client, paused["thread_id"], action="approve", payload_hash="0" * 64)

    assert refused.json()["next_step"] == "approval_invalid"
    assert APPLICATIONS[approval["portal_draft_id"]]["status"] == "draft"


def test_reject_does_not_submit(client):
    paused = start_paused(client)

    rejected = decide(client, paused["thread_id"], action="reject")

    assert rejected.json()["next_step"] == "approval_rejected"
    assert APPLICATIONS[paused["data"]["approval"]["portal_draft_id"]]["status"] == "draft"


def test_decision_without_a_pending_draft_is_a_conflict(client):
    paused = start_paused(client)
    decide(client, paused["thread_id"], action="reject")

    again = decide(client, paused["thread_id"], action="approve", payload_hash="x")

    assert again.status_code == 409


def test_decision_for_an_unknown_thread_is_not_found(client):
    assert decide(client, "missing", action="reject").status_code == 404


def test_another_household_cannot_decide_or_chat_on_the_thread(client):
    paused = start_paused(client)

    other_decision = decide(client, paused["thread_id"], actor="household-2", action="reject")
    other_chat = send(client, actor="household-2", thread_id=paused["thread_id"])

    assert other_decision.status_code == 403
    assert other_chat.status_code == 403


def test_new_message_is_refused_while_a_draft_waits_for_approval(client):
    paused = start_paused(client)

    blocked = send(client, thread_id=paused["thread_id"], message="Something else")

    assert blocked.status_code == 409


def test_errors_do_not_leak_internal_details(client, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("secret internal path /etc/passwd")

    monkeypatch.setattr(api.AgentWorkflowService, "execute_workflow", boom)

    response = send(client)

    assert response.status_code == 500
    assert "secret" not in response.text


def test_confirmed_facts_sent_to_the_api_reach_the_draft(client, monkeypatch):
    seen = {}
    original = api.AgentWorkflowService.execute_workflow

    def spy(self, **kwargs):
        seen.update(kwargs)
        return original(self, **kwargs)

    monkeypatch.setattr(api.AgentWorkflowService, "execute_workflow", spy)
    body = {
        "message": "Help me apply",
        "actor_id": "household-1",
        "confirmed_facts": {"age": 30},
        "selected_scheme_id": "C01",
    }

    assert client.post("/api/chat", json=body, headers={"x-actor-id": "household-1"}).status_code == 200
    assert seen["confirmed_facts"] == {"age": 30}
