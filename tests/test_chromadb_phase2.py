"""
Phase 2 tests for ChromaDB-backed memory service and checkpointer.

Tests persistent storage, concurrent access safety, scope isolation with multiple users,
and cleanup operations.
"""

import pytest
import tempfile
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from agents.chromadb_memory_service import ChromaDBMemoryService
from agents.memory import MemoryFact, MemoryScope, MemoryConsent, ApplicationReference
from graph.chromadb_checkpointer import ChromaDBCheckpointer


class TestChromaDBMemoryServiceBasics:
    """Test ChromaDB memory service basic operations."""

    @pytest.fixture
    def temp_db_dir(self):
        """Create temporary directory for test database."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def service(self, temp_db_dir):
        """Create memory service with temporary storage."""
        return ChromaDBMemoryService(persist_directory=temp_db_dir)

    @pytest.fixture
    def scope_1(self):
        """Test scope for household 1."""
        return MemoryScope(
            actor_id="actor_001",
            household_id="hh_001",
            actor_role="operator",
        )

    def test_initialization(self, service, temp_db_dir):
        """Test service initializes with ChromaDB collections."""
        assert service is not None
        assert service.facts_collection is not None
        assert service.applications_collection is not None
        assert service.consent_collection is not None
        assert Path(temp_db_dir).exists()

    def test_record_consent(self, service, scope_1):
        """Test consent recording."""
        decided_at = datetime.utcnow()
        expires_at = decided_at + timedelta(days=30)

        consent = MemoryConsent(
            purpose="profile_facts",
            granted=True,
            notice_version="v1.0",
            decided_at=decided_at,
            expires_at=expires_at,
            consent_reference="consent_001",
        )

        # Should not raise
        service.record_consent(scope=scope_1, consent=consent)

    def test_save_confirmed_fact(self, service, scope_1):
        """Test saving a confirmed fact."""
        confirmed_at = datetime.utcnow()
        reconfirm_by = confirmed_at + timedelta(days=90)
        expires_at = confirmed_at + timedelta(days=365)

        fact = MemoryFact(
            field="state_code",
            value="AP",
            confirmed_at=confirmed_at,
            reconfirm_by=reconfirm_by,
            expires_at=expires_at,
            source="household_intake",
            consent_reference="consent_001",
        )

        service.save_confirmed_fact(scope=scope_1, fact=fact)

        # Read back
        facts = service.read_facts(
            scope=scope_1,
            fields=["state_code"],
        )

        assert facts.get("state_code") == "AP"

    def test_read_facts_empty(self, service, scope_1):
        """Test reading from empty household."""
        facts = service.read_facts(
            scope=scope_1,
            fields=["state_code"],
        )

        assert facts == {}

    def test_read_facts_with_expiry_check(self, service, scope_1):
        """Test that expired facts are not returned."""
        # Save expired fact
        confirmed_at = datetime.utcnow() - timedelta(days=400)
        reconfirm_by = confirmed_at + timedelta(days=90)
        expires_at = confirmed_at + timedelta(days=365)  # Expired

        fact = MemoryFact(
            field="state_code",
            value="AP",
            confirmed_at=confirmed_at,
            reconfirm_by=reconfirm_by,
            expires_at=expires_at,
            source="household_intake",
            consent_reference="consent_001",
        )

        service.save_confirmed_fact(scope=scope_1, fact=fact)

        # Read should not return expired fact
        facts = service.read_facts(
            scope=scope_1,
            fields=["state_code"],
        )

        assert "state_code" not in facts

    def test_forget_household(self, service, scope_1):
        """Test household deletion (GDPR)."""
        # Save some facts
        confirmed_at = datetime.utcnow()
        reconfirm_by = confirmed_at + timedelta(days=90)
        expires_at = confirmed_at + timedelta(days=365)

        for field in ["state_code", "district_code"]:
            fact = MemoryFact(
                field=field,
                value=f"value_{field}",
                confirmed_at=confirmed_at,
                reconfirm_by=reconfirm_by,
                expires_at=expires_at,
                source="household_intake",
                consent_reference="consent_001",
            )
            service.save_confirmed_fact(scope=scope_1, fact=fact)

        # Verify facts saved
        count_before = service.get_household_fact_count("hh_001")
        assert count_before == 2

        # Forget household
        service.forget_household(scope_1)

        # Verify facts deleted
        count_after = service.get_household_fact_count("hh_001")
        assert count_after == 0

    def test_save_application_reference(self, service, scope_1):
        """Test recording application submissions."""
        submitted_at = datetime.utcnow()
        expires_at = submitted_at + timedelta(days=365)

        app_ref = ApplicationReference(
            scheme_id="scheme_001",
            application_id="app_001",
            submitted_at=submitted_at,
            expires_at=expires_at,
            consent_reference="consent_001",
        )

        service.save_application_reference(scope=scope_1, reference=app_ref)

        # Verify stored
        apps = service.read_application_references(scope=scope_1)
        assert len(apps) > 0


class TestConcurrentAccess:
    """Test concurrent access safety with multiple users."""

    @pytest.fixture
    def temp_db_dir(self):
        """Create temporary directory for test database."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def service(self, temp_db_dir):
        """Create memory service with temporary storage."""
        return ChromaDBMemoryService(persist_directory=temp_db_dir)

    def test_concurrent_household_isolation(self, service):
        """Test that concurrent users for different households are isolated."""
        households = ["hh_001", "hh_002", "hh_003"]
        confirmed_at = datetime.utcnow()
        reconfirm_by = confirmed_at + timedelta(days=90)
        expires_at = confirmed_at + timedelta(days=365)

        def save_household_facts(hh_id):
            scope = MemoryScope(
                actor_id=f"actor_{hh_id}",
                household_id=hh_id,
                actor_role="operator",
            )

            for i in range(5):
                fact = MemoryFact(
                    field="state_code",
                    value=f"value_{hh_id}_{i}",
                    confirmed_at=confirmed_at,
                    reconfirm_by=reconfirm_by,
                    expires_at=expires_at,
                    source="household_intake",
                    consent_reference="consent_001",
                )
                service.save_confirmed_fact(scope=scope, fact=fact)

        # Save facts from multiple threads
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(save_household_facts, hh_id)
                for hh_id in households
            ]
            for future in as_completed(futures):
                future.result()

        # Verify isolation
        for hh_id in households:
            scope = MemoryScope(
                actor_id=f"actor_{hh_id}",
                household_id=hh_id,
                actor_role="operator",
            )

            facts = service.read_facts(
                scope=scope,
                fields=["state_code"],
            )

            # Should have exactly one fact (most recent write)
            assert len(facts) == 1
            # Verify it's the correct household's data
            assert f"value_{hh_id}" in str(facts.get("state_code", ""))

    def test_concurrent_saves_same_field(self, service):
        """Test concurrent saves to same field in household."""
        scope = MemoryScope(
            actor_id="actor_001",
            household_id="hh_001",
            actor_role="operator",
        )

        confirmed_at = datetime.utcnow()
        reconfirm_by = confirmed_at + timedelta(days=90)
        expires_at = confirmed_at + timedelta(days=365)

        def save_fact(value):
            fact = MemoryFact(
                field="state_code",
                value=value,
                confirmed_at=confirmed_at,
                reconfirm_by=reconfirm_by,
                expires_at=expires_at,
                source="household_intake",
                consent_reference="consent_001",
            )
            service.save_confirmed_fact(scope=scope, fact=fact)

        # Save from multiple threads
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(save_fact, f"state_{i}")
                for i in range(5)
            ]
            for future in as_completed(futures):
                future.result()

        # Read back - should have one value (last write wins)
        facts = service.read_facts(
            scope=scope,
            fields=["state_code"],
        )

        assert len(facts) == 1


class TestScopeIsolation:
    """Test scope isolation between actors and households."""

    @pytest.fixture
    def temp_db_dir(self):
        """Create temporary directory for test database."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def service(self, temp_db_dir):
        """Create memory service with temporary storage."""
        return ChromaDBMemoryService(persist_directory=temp_db_dir)

    def test_different_actors_same_household(self, service):
        """Test that different actors can read same household data."""
        household_id = "hh_001"

        # Actor 1 saves data
        scope_1 = MemoryScope(
            actor_id="actor_001",
            household_id=household_id,
            actor_role="operator",
        )

        confirmed_at = datetime.utcnow()
        reconfirm_by = confirmed_at + timedelta(days=90)
        expires_at = confirmed_at + timedelta(days=365)

        fact = MemoryFact(
            field="state_code",
            value="AP",
            confirmed_at=confirmed_at,
            reconfirm_by=reconfirm_by,
            expires_at=expires_at,
            source="household_intake",
            consent_reference="consent_001",
        )

        service.save_confirmed_fact(scope=scope_1, fact=fact)

        # Actor 2 (different role) reads same household data
        scope_2 = MemoryScope(
            actor_id="actor_002",
            household_id=household_id,
            actor_role="citizen",
        )

        facts = service.read_facts(
            scope=scope_2,
            fields=["state_code"],
        )

        assert facts.get("state_code") == "AP"

    def test_cross_household_access_prevented(self, service):
        """Test that actors cannot read other households' data."""
        # Actor 1 saves data for household 1
        scope_1 = MemoryScope(
            actor_id="actor_001",
            household_id="hh_001",
            actor_role="operator",
        )

        confirmed_at = datetime.utcnow()
        reconfirm_by = confirmed_at + timedelta(days=90)
        expires_at = confirmed_at + timedelta(days=365)

        fact = MemoryFact(
            field="state_code",
            value="AP",
            confirmed_at=confirmed_at,
            reconfirm_by=reconfirm_by,
            expires_at=expires_at,
            source="household_intake",
            consent_reference="consent_001",
        )

        service.save_confirmed_fact(scope=scope_1, fact=fact)

        # Actor tries to read different household
        scope_2 = MemoryScope(
            actor_id="actor_002",
            household_id="hh_002",  # Different household
            actor_role="operator",
        )

        facts = service.read_facts(
            scope=scope_2,
            fields=["state_code"],
        )

        # Should not return household 1 data
        assert facts == {}

    def test_invalid_scope_rejected(self, service):
        """Test that incomplete scopes raise errors."""
        incomplete_scope = MemoryScope(
            actor_id="actor_001",
            household_id="",  # Empty household_id
            actor_role="operator",
        )

        with pytest.raises((ValueError, AttributeError)):
            service.read_facts(
                scope=incomplete_scope,
                fields=["state_code"],
            )


class TestChromaDBCheckpointer:
    """Test LangGraph checkpointer with ChromaDB backend."""

    @pytest.fixture
    def temp_db_dir(self):
        """Create temporary directory for test database."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def checkpointer(self, temp_db_dir):
        """Create checkpointer with temporary storage."""
        return ChromaDBCheckpointer(persist_directory=temp_db_dir)

    def test_checkpointer_initialization(self, checkpointer):
        """Test checkpointer initializes correctly."""
        assert checkpointer is not None
        assert checkpointer.namespace == "default"
        assert checkpointer.checkpoints is not None

    def test_put_and_get_checkpoint(self, checkpointer):
        """Test saving and retrieving a checkpoint."""
        config = {
            "checkpoint_ns": "test_workflow",
            "checkpoint_id": "run_001",
        }

        checkpoint_data = {
            "state": {
                "household_id": "hh_001",
                "phase": "intake",
            },
            "step": 5,
        }

        metadata = {
            "user_input": "some_context",
        }

        # Put checkpoint
        version = checkpointer.put_checkpoint(
            config=config,
            checkpoint=checkpoint_data,
            metadata=metadata,
        )

        assert version is not None

        # Get checkpoint
        retrieved = checkpointer.get_checkpoint(config=config)

        assert retrieved is not None
        assert retrieved.checkpoint == checkpoint_data
        assert retrieved.metadata == metadata

    def test_list_checkpoints(self, checkpointer):
        """Test listing multiple checkpoints."""
        config = {
            "checkpoint_ns": "test_workflow",
            "checkpoint_id": "run_001",
        }

        # Save multiple checkpoints
        for i in range(3):
            checkpoint_data = {"step": i, "state": f"state_{i}"}
            checkpointer.put_checkpoint(
                config=config,
                checkpoint=checkpoint_data,
                metadata={"step_num": i},
            )

        # List checkpoints
        checkpoints = checkpointer.list_checkpoints(config=config)

        assert len(checkpoints) >= 3

    def test_cleanup_old_checkpoints(self, checkpointer):
        """Test cleanup keeps only recent checkpoints."""
        config = {
            "checkpoint_ns": "test_workflow",
            "checkpoint_id": "run_001",
        }

        # Save many checkpoints
        for i in range(15):
            checkpoint_data = {"step": i}
            checkpointer.put_checkpoint(
                config=config,
                checkpoint=checkpoint_data,
                metadata={"step": i},
            )

        # Cleanup keeping only 5
        deleted = checkpointer.cleanup_old_checkpoints(
            config=config,
            max_checkpoints=5,
        )

        assert deleted == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
