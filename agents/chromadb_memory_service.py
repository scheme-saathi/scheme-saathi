"""
ChromaDB-backed persistent memory service for Scheme Saathi.

This implements the MemoryService protocol with durable storage using ChromaDB.
Replaces the MVP InMemoryMemoryService for Phase 2+ use.

Features:
- Persistent storage across workflow runs
- Cross-process state sharing
- Concurrent access safety
- Searchable household facts
- Consent audit trail
"""

import json
import os
from datetime import datetime
from typing import Optional
from pathlib import Path

import chromadb

from agents.memory import (
    MemoryService,
    MemoryConsent,
    MemoryFact,
    MemoryScope,
    ApplicationReference,
)
from agents.contracts import FactMap


class ChromaDBMemoryService:
    """
    Production memory service using ChromaDB for persistent storage.

    Implements MemoryService protocol with three collections:
    1. household_facts: Long-term household data
    2. application_refs: Application submission tracking and status
    3. consent_log: Audit trail for consent decisions
    """

    def __init__(self, persist_directory: Optional[str] = None):
        """
        Initialize ChromaDB memory service.

        Args:
            persist_directory: Path for persistent storage. Defaults to ./chroma_data
        """
        if persist_directory is None:
            persist_directory = os.path.join(
                os.path.dirname(__file__), "..", "chroma_data"
            )

        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)

        # Initialize ChromaDB client with new API
        self.client = chromadb.PersistentClient(
            path=str(self.persist_directory)
        )

        # Get or create collections
        self.facts_collection = self.client.get_or_create_collection(
            name="household_facts",
            metadata={"description": "Long-term household facts"},
        )

        self.applications_collection = self.client.get_or_create_collection(
            name="application_references",
            metadata={"description": "Application submission tracking"},
        )

        self.consent_collection = self.client.get_or_create_collection(
            name="consent_log",
            metadata={"description": "Audit trail for consent decisions"},
        )

    def record_consent(
        self,
        scope: MemoryScope,
        consent: MemoryConsent,
    ) -> None:
        """
        Record consent grant/withdrawal.

        Args:
            scope: Authorization context (actor, household, role)
            consent: Consent decision with purpose, duration, etc.
        """
        # Store in audit trail
        consent_id = f"{scope.household_id}:{scope.actor_id}:{consent.consent_reference}"
        
        self.consent_collection.upsert(
            ids=[consent_id],
            metadatas={
                "household_id": scope.household_id,
                "actor_id": scope.actor_id,
                "actor_role": scope.actor_role,
                "purpose": consent.purpose,
                "granted": str(consent.granted),
                "decided_at": consent.decided_at.isoformat(),
                "expires_at": consent.expires_at.isoformat(),
                "timestamp": datetime.utcnow().isoformat(),
            },
            documents=[json.dumps(consent.model_dump(mode="json"))],
        )

    def withdraw_consent(
        self,
        scope: MemoryScope,
        consent_reference: str,
    ) -> None:
        """
        Withdraw previously granted consent.

        Args:
            scope: Authorization context
            consent_reference: Consent ID to revoke
        """
        consent_id = f"{scope.household_id}:{scope.actor_id}:{consent_reference}"
        
        # Create withdrawal record
        self.consent_collection.upsert(
            ids=[f"{consent_id}:withdrawn"],
            metadatas={
                "household_id": scope.household_id,
                "actor_id": scope.actor_id,
                "consent_reference": consent_reference,
                "withdrawn_at": datetime.utcnow().isoformat(),
            },
            documents=["{}"],
        )

    def read_facts(
        self,
        scope: MemoryScope,
        fields: list[str],
    ) -> FactMap:
        """
        Read facts for a household with expiry validation.

        Args:
            scope: Authorization context
            fields: Specific fields to read

        Returns:
            Dictionary of field -> value (FactMap)
        """
        self._validate_scope(scope)

        # Query facts for this household
        results = self.facts_collection.get(
            where={
                "$and": [
                    {"household_id": {"$eq": scope.household_id}},
                    {"field": {"$in": fields}},
                ]
            },
        )

        facts: FactMap = {}
        now = datetime.utcnow()

        for doc in results.get("documents", []):
            try:
                fact_dict = json.loads(doc)
                fact = MemoryFact(**fact_dict)

                # Check expiry
                if fact.expires_at < now:
                    continue

                # Check reconfirm deadline
                if fact.reconfirm_by < now:
                    continue

                facts[fact.field] = fact.value

            except (json.JSONDecodeError, ValueError):
                continue

        return facts

    def save_confirmed_fact(
        self,
        scope: MemoryScope,
        fact: MemoryFact,
    ) -> None:
        """
        Save a confirmed fact with scope and expiry validation.

        Args:
            scope: Authorization context (actor, household, role)
            fact: MemoryFact to store
        """
        self._validate_scope(scope)

        # Store in facts collection
        fact_id = f"{scope.household_id}:{fact.field}:{fact.consent_reference}"
        
        self.facts_collection.upsert(
            ids=[fact_id],
            metadatas={
                "household_id": scope.household_id,
                "field": fact.field,
                "confirmed_at": fact.confirmed_at.isoformat(),
                "expires_at": fact.expires_at.isoformat(),
                "reconfirm_by": fact.reconfirm_by.isoformat(),
                "source": fact.source,
                "consent_reference": fact.consent_reference,
            },
            documents=[json.dumps(fact.model_dump(mode="json"))],
        )

    def read_application_references(
        self,
        scope: MemoryScope,
    ) -> list[ApplicationReference]:
        """
        Read application references for a household.

        Args:
            scope: Authorization context

        Returns:
            List of ApplicationReference objects
        """
        self._validate_scope(scope)

        results = self.applications_collection.get(
            where={"household_id": {"$eq": scope.household_id}}
        )

        apps: list[ApplicationReference] = []
        now = datetime.utcnow()

        for doc in results.get("documents", []):
            try:
                app_dict = json.loads(doc)
                app = ApplicationReference(**app_dict)

                # Check expiry
                if app.expires_at >= now:
                    apps.append(app)

            except (json.JSONDecodeError, ValueError):
                continue

        return apps

    def save_application_reference(
        self,
        scope: MemoryScope,
        reference: ApplicationReference,
    ) -> None:
        """
        Save an application submission reference.

        Args:
            scope: Authorization context
            reference: ApplicationReference to store
        """
        self._validate_scope(scope)

        app_id = f"{scope.household_id}:{reference.application_id}:{reference.consent_reference}"
        
        self.applications_collection.upsert(
            ids=[app_id],
            metadatas={
                "household_id": scope.household_id,
                "application_id": reference.application_id,
                "scheme_id": reference.scheme_id,
                "submitted_at": reference.submitted_at.isoformat(),
                "expires_at": reference.expires_at.isoformat(),
            },
            documents=[json.dumps(reference.model_dump(mode="json"))],
        )

    def forget_household(self, scope: MemoryScope) -> None:
        """
        Delete all data for a household (GDPR right to be forgotten).

        Args:
            scope: Authorization context
        """
        household_id = scope.household_id

        # Delete from facts
        facts = self.facts_collection.get(
            where={"household_id": {"$eq": household_id}}
        )
        if facts["ids"]:
            self.facts_collection.delete(ids=facts["ids"])

        # Delete from applications
        apps = self.applications_collection.get(
            where={"household_id": {"$eq": household_id}}
        )
        if apps["ids"]:
            self.applications_collection.delete(ids=apps["ids"])

        # Delete from consent log
        consent_logs = self.consent_collection.get(
            where={"household_id": {"$eq": household_id}}
        )
        if consent_logs["ids"]:
            self.consent_collection.delete(ids=consent_logs["ids"])

    def cleanup_expired_facts(self) -> int:
        """
        Clean up expired facts from storage.

        Returns:
            Number of facts deleted
        """
        now = datetime.utcnow().isoformat()
        expired = self.facts_collection.get(
            where={"expires_at": {"$lt": now}}
        )

        if expired["ids"]:
            self.facts_collection.delete(ids=expired["ids"])
            return len(expired["ids"])

        return 0

    def get_household_fact_count(self, household_id: str) -> int:
        """Get count of active facts for a household."""
        facts = self.facts_collection.get(
            where={"household_id": {"$eq": household_id}}
        )
        return len(facts["ids"])

    # Private helper methods
    def _validate_scope(self, scope: MemoryScope) -> None:
        """Validate scope structure."""
        if not scope.actor_id or not scope.household_id:
            raise ValueError(
                "Invalid scope: missing actor_id or household_id"
            )
