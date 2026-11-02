"""Integration tests for agents/orchestrator.py - Workflow orchestration."""

import pytest
from datetime import datetime, timedelta
from agents.orchestrator import SchemeStathiOrchestrator
from agents.memory_service import HouseholdAllowlist, InMemoryMemoryService
from agents.memory import MemoryScope, MemoryConsent, MemoryFact
from graph.state import WorkflowState, HouseholdScope


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_model():
    """Create a mock LLM model for testing."""
    from unittest.mock import MagicMock
    from langchain_core.language_models.chat_models import BaseChatModel
    
    model = MagicMock(spec=BaseChatModel)
    model.invoke = MagicMock()
    return model


@pytest.fixture
def basic_allowlist():
    """Create a minimal household allowlist for testing."""
    return HouseholdAllowlist(
        allowed_fields={
            "state_code": {
                "type": "string",
                "purpose": "Filter schemes by state",
                "retention": {"store": True, "expiry_days": 365},
                "access": ["intake", "eligibility"],
            },
            "district_code": {
                "type": "string",
                "purpose": "Filter schemes by district",
                "retention": {"store": True, "expiry_days": 365},
                "access": ["intake", "eligibility"],
            },
            "household_size": {
                "type": "integer",
                "purpose": "Determine family-size based schemes",
                "retention": {"store": True, "expiry_days": 180},
                "access": ["intake", "eligibility", "documents"],
            },
        }
    )


@pytest.fixture
def memory_service(basic_allowlist):
    """Create an in-memory memory service."""
    return InMemoryMemoryService(allowlist=basic_allowlist)


@pytest.fixture
def orchestrator(mock_model, memory_service):
    """Create an orchestrator instance."""
    return SchemeStathiOrchestrator(
        supervisor_model=mock_model,
        specialist_model=mock_model,
        memory_service=memory_service,
    )


# ============================================================================
# Orchestrator Initialization Tests
# ============================================================================


class TestOrchestratorInitialization:
    """Test orchestrator setup."""

    def test_orchestrator_creates_successfully(self, mock_model, memory_service):
        """Orchestrator can be instantiated with models and memory service."""
        orchestrator = SchemeStathiOrchestrator(
            supervisor_model=mock_model,
            specialist_model=mock_model,
            memory_service=memory_service,
        )
        assert orchestrator.memory_service == memory_service


# ============================================================================
# Workflow State Tests
# ============================================================================


class TestWorkflowState:
    """Test WorkflowState structure."""

    def test_household_scope_creation(self):
        """HouseholdScope contains required authorization fields."""
        scope: HouseholdScope = {
            "actor_id": "user_123",
            "household_id": "household_456",
            "actor_role": "citizen",
        }

        assert scope["actor_id"] == "user_123"
        assert scope["household_id"] == "household_456"
        assert scope["actor_role"] == "citizen"

    def test_workflow_state_creation(self):
        """WorkflowState can be created."""
        scope: HouseholdScope = {
            "actor_id": "user_123",
            "household_id": "household_456",
            "actor_role": "citizen",
        }

        state: WorkflowState = {
            "household_scope": scope,
            "current_step": "intake",
            "user_request": "I need help with a scheme",
        }

        assert state["household_scope"]["actor_id"] == "user_123"
        assert state["current_step"] == "intake"


# ============================================================================
# Memory Integration Tests
# ============================================================================


class TestMemoryIntegration:
    """Test memory service integration with orchestrator."""

    def test_orchestrator_has_memory_service(self, orchestrator, memory_service):
        """Orchestrator can access memory service."""
        assert orchestrator.memory_service == memory_service

    def test_memory_service_can_store_facts(self, memory_service):
        """Memory service can persist facts."""
        now = datetime.utcnow()
        future = now + timedelta(days=365)

        scope = MemoryScope(
            actor_id="user_1",
            household_id="hh_1",
            actor_role="citizen",
        )

        # Record consent
        consent = MemoryConsent(
            purpose="profile_facts",
            granted=True,
            notice_version="1.0",
            decided_at=now,
            expires_at=future,
            consent_reference="consent_1",
        )
        memory_service.record_consent(scope, consent)

        # Save fact
        fact = MemoryFact(
            field="state_code",
            value="MH",
            source="intake_agent",
            confirmed_at=now,
            reconfirm_by=now + timedelta(days=90),
            expires_at=future,
            consent_reference="consent_1",
        )
        memory_service.save_confirmed_fact(scope, fact)

        # Verify stored
        facts = memory_service.read_facts(scope, fields=["state_code"])
        assert "state_code" in facts


# ============================================================================
# Scope Isolation Tests
# ============================================================================


class TestScopeIsolation:
    """Test household scope isolation."""

    def test_different_households_data_isolated(self, memory_service):
        """Different households don't share data."""
        now = datetime.utcnow()
        future = now + timedelta(days=365)

        scope_a = MemoryScope(
            actor_id="user_a",
            household_id="household_a",
            actor_role="citizen",
        )

        scope_b = MemoryScope(
            actor_id="user_b",
            household_id="household_b",
            actor_role="citizen",
        )

        # Household A saves data
        consent_a = MemoryConsent(
            purpose="profile_facts",
            granted=True,
            notice_version="1.0",
            decided_at=now,
            expires_at=future,
            consent_reference="consent_a",
        )
        memory_service.record_consent(scope_a, consent_a)

        fact_a = MemoryFact(
            field="state_code",
            value="MH",
            source="intake_agent",
            confirmed_at=now,
            reconfirm_by=now + timedelta(days=90),
            expires_at=future,
            consent_reference="consent_a",
        )
        memory_service.save_confirmed_fact(scope_a, fact_a)

        # Household B cannot see it
        facts_b = memory_service.read_facts(scope_b, fields=["state_code"])
        assert facts_b == {}


# ============================================================================
# Compliance Tests
# ============================================================================


class TestOrchestratorCompliance:
    """Test compliance with architecture requirements."""

    def test_orchestrator_has_memory_governance(self, orchestrator):
        """Orchestrator enforces memory governance."""
        # Memory service should enforce allowlist
        assert orchestrator.memory_service is not None
        assert orchestrator.memory_service.allowlist is not None

    def test_household_deletion_works(self, memory_service):
        """Household deletion removes all data."""
        now = datetime.utcnow()
        future = now + timedelta(days=365)

        scope = MemoryScope(
            actor_id="user_1",
            household_id="hh_1",
            actor_role="citizen",
        )

        # Save data
        consent = MemoryConsent(
            purpose="profile_facts",
            granted=True,
            notice_version="1.0",
            decided_at=now,
            expires_at=future,
            consent_reference="consent_1",
        )
        memory_service.record_consent(scope, consent)

        fact = MemoryFact(
            field="state_code",
            value="MH",
            source="intake_agent",
            confirmed_at=now,
            reconfirm_by=now + timedelta(days=90),
            expires_at=future,
            consent_reference="consent_1",
        )
        memory_service.save_confirmed_fact(scope, fact)

        # Delete
        memory_service.forget_household(scope)

        # Verify gone
        facts = memory_service.read_facts(scope, fields=["state_code"])
        assert facts == {}
