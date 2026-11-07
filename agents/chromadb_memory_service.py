"""
ChromaDB-backed persistent memory service for Scheme Saathi.

Personal records are read back by exact IDs and metadata filters, never by similarity,
so the collections hold no real embeddings: every record carries one constant placeholder
vector and automatic embedding is switched off. Timestamps used in filters are stored as
UTC epoch seconds because Chroma range filters only compare numbers.

Three collections:
1. memory_facts: one current fact per household and field
2. memory_application_references: one reference per owner and application
3. memory_consents: consent records and withdrawal markers
"""

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import chromadb

from agents.memory import (
    MemoryService,
    MemoryConsent,
    MemoryFact,
    MemoryScope,
    ApplicationReference,
    Purpose,
    as_utc,
    utc_now,
)
from agents.contracts import FactMap
from agents.memory_service import HouseholdAllowlist

FACTS_COLLECTION = "memory_facts"
REFERENCES_COLLECTION = "memory_application_references"
CONSENTS_COLLECTION = "memory_consents"
PLACEHOLDER_VECTOR = [0.0]


def _timestamp(value: datetime) -> float:
    return as_utc(value).replace(tzinfo=timezone.utc).timestamp()


def _record_id(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


class ChromaDBMemoryService:
    """
    Persistent memory service using ChromaDB.

    Implements the MemoryService protocol. Authorization, consent, the field allowlist and
    expiry are checked here on every call. Writes are serialised with a lock, because
    Chroma has no transactions.
    """

    def __init__(
        self,
        persist_directory: Optional[str] = None,
        allowlist: Optional[HouseholdAllowlist] = None,
    ):
        """
        Initialize ChromaDB memory service.

        Args:
            persist_directory: Path for persistent storage. Defaults to ./chroma_data
            allowlist: Fields that may be stored. Defaults to data/memory_policy.json.
        """
        if persist_directory is None:
            persist_directory = os.path.join(
                os.path.dirname(__file__), "..", "chroma_data"
            )

        self.allowlist = allowlist or HouseholdAllowlist.from_policy_file()
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

        self.client = chromadb.PersistentClient(path=str(self.persist_directory))
        self.facts_collection = self._collection(FACTS_COLLECTION, "Long-term household facts")
        self.applications_collection = self._collection(
            REFERENCES_COLLECTION, "Application submission tracking"
        )
        self.consent_collection = self._collection(
            CONSENTS_COLLECTION, "Consent decisions and withdrawals"
        )

    def _collection(self, name: str, description: str):
        return self.client.get_or_create_collection(
            name=name, embedding_function=None, metadata={"description": description}
        )

    def _put(self, collection, record_id: str, metadata: dict, document: str) -> None:
        collection.upsert(
            ids=[record_id],
            embeddings=[PLACEHOLDER_VECTOR],
            metadatas=[metadata],
            documents=[document],
        )

    def record_consent(
        self,
        scope: MemoryScope,
        consent: MemoryConsent,
    ) -> None:
        """
        Record a consent decision.

        Args:
            scope: Authorization context (actor, household, role)
            consent: Consent decision with purpose, duration, etc.
        """
        self._validate_scope(scope)

        if as_utc(consent.expires_at) <= utc_now():
            raise ValueError("Cannot record consent that is already expired")

        owner = scope.owner_for(consent.purpose)
        with self._lock:
            for meta in self._consent_rows(consent.consent_reference)["metadatas"]:
                if meta["owner_key"] != owner:
                    raise ValueError(
                        f"Consent {consent.consent_reference} belongs to another household"
                    )
                if meta["kind"] == "withdrawal":
                    raise ValueError(
                        f"Consent {consent.consent_reference} was withdrawn; use a new reference"
                    )
            self._put(
                self.consent_collection,
                _record_id(owner, consent.consent_reference),
                {
                    "kind": "consent",
                    "owner_key": owner,
                    "actor_id": scope.actor_id,
                    "actor_role": scope.actor_role,
                    "consent_reference": consent.consent_reference,
                    "purpose": consent.purpose,
                    "granted": consent.granted,
                    "obtained_via": consent.obtained_via,
                    "recorded_by": consent.recorded_by or "",
                    "decided_at_ts": _timestamp(consent.decided_at),
                    "expires_at_ts": _timestamp(consent.expires_at),
                },
                json.dumps(consent.model_dump(mode="json")),
            )

    def withdraw_consent(
        self,
        scope: MemoryScope,
        consent_reference: str,
    ) -> None:
        """
        Withdraw a consent and delete everything stored under it.

        Args:
            scope: Authorization context
            consent_reference: Consent ID to revoke
        """
        self._validate_scope(scope)

        with self._lock:
            rows = self._consent_rows(consent_reference)
            for meta in rows["metadatas"]:
                purpose = meta.get("purpose")
                if meta["kind"] != "consent" or meta["owner_key"] != scope.owner_for(purpose):
                    continue
                owner = meta["owner_key"]
                self._put(
                    self.consent_collection,
                    _record_id(owner, consent_reference, "withdrawn"),
                    {
                        "kind": "withdrawal",
                        "owner_key": owner,
                        "consent_reference": consent_reference,
                        "purpose": purpose,
                        "withdrawn_at_ts": _timestamp(utc_now()),
                        "expires_at_ts": meta["expires_at_ts"],
                    },
                    "{}",
                )
                self._delete_covered(owner, consent_reference, purpose)

    def _consent_rows(self, consent_reference: str) -> dict:
        return self.consent_collection.get(
            where={"consent_reference": {"$eq": consent_reference}}
        )

    def _delete_covered(self, owner: str, consent_reference: str, purpose: Purpose) -> int:
        """Delete the facts or references that only this consent allowed."""
        if purpose == "profile_facts":
            collection, owner_field = self.facts_collection, "household_id"
        else:
            collection, owner_field = self.applications_collection, "owner_key"
        stored = collection.get(
            where={
                "$and": [
                    {owner_field: {"$eq": owner}},
                    {"consent_reference": {"$eq": consent_reference}},
                ]
            }
        )
        if stored["ids"]:
            collection.delete(ids=stored["ids"])
        return len(stored["ids"])

    def _has_active_consent(self, owner: str, consent_reference: str, purpose: Purpose) -> bool:
        """True if the owner holds a granted, unexpired, unwithdrawn consent for the purpose."""
        rows = self.consent_collection.get(
            where={
                "$and": [
                    {"owner_key": {"$eq": owner}},
                    {"consent_reference": {"$eq": consent_reference}},
                ]
            }
        )
        metas = rows["metadatas"] or []
        if any(m["kind"] == "withdrawal" for m in metas):
            return False
        now = _timestamp(utc_now())
        return any(
            m["kind"] == "consent"
            and m["purpose"] == purpose
            and m["granted"] is True
            and m["expires_at_ts"] > now
            for m in metas
        )

    def read_facts(
        self,
        scope: MemoryScope,
        fields: list[str],
    ) -> FactMap:
        """
        Read the household's current facts, skipping expired, unreconfirmed and unconsented ones.

        Args:
            scope: Authorization context
            fields: Fields to read; an empty list means every allowlisted field

        Returns:
            Dictionary of field -> value (FactMap)
        """
        self._validate_scope(scope)

        wanted = [f for f in (fields or self.allowlist.allowed_fields) if self.allowlist.is_field_allowed(f)]
        if not wanted:
            return {}

        results = self.facts_collection.get(
            where={
                "$and": [
                    {"household_id": {"$eq": scope.household_id}},
                    {"field": {"$in": wanted}},
                ]
            },
        )

        facts: FactMap = {}
        now = _timestamp(utc_now())
        consent_ok: dict[str, bool] = {}

        for meta, doc in zip(results["metadatas"], results["documents"]):
            if meta["expires_at_ts"] <= now or meta["reconfirm_by_ts"] <= now:
                continue
            reference = meta["consent_reference"]
            if reference not in consent_ok:
                consent_ok[reference] = self._has_active_consent(
                    scope.household_id, reference, "profile_facts"
                )
            if not consent_ok[reference]:
                continue
            facts[meta["field"]] = MemoryFact(**json.loads(doc)).value

        return facts

    def save_confirmed_fact(
        self,
        scope: MemoryScope,
        fact: MemoryFact,
    ) -> None:
        """
        Save a confirmed fact, replacing the household's earlier value for that field.

        An older confirmation never replaces a newer one.

        Args:
            scope: Authorization context (actor, household, role)
            fact: MemoryFact to store
        """
        self._validate_scope(scope)
        self.allowlist.validate_fact(fact.field, fact.value)
        self.allowlist.validate_retention(fact)

        if not self._has_active_consent(scope.household_id, fact.consent_reference, "profile_facts"):
            raise ValueError(
                f"No active profile_facts consent {fact.consent_reference} "
                "for this household"
            )

        now = utc_now()
        if as_utc(fact.expires_at) <= now or as_utc(fact.reconfirm_by) <= now:
            raise ValueError("Fact retention window already expired")

        fact_id = _record_id(scope.household_id, fact.field)
        confirmed_ts = _timestamp(fact.confirmed_at)
        with self._lock:
            current = self.facts_collection.get(ids=[fact_id])
            if current["metadatas"] and current["metadatas"][0]["confirmed_at_ts"] > confirmed_ts:
                return
            self._put(
                self.facts_collection,
                fact_id,
                {
                    "household_id": scope.household_id,
                    "field": fact.field,
                    "source": fact.source,
                    "consent_reference": fact.consent_reference,
                    "confirmed_at_ts": confirmed_ts,
                    "reconfirm_by_ts": _timestamp(fact.reconfirm_by),
                    "expires_at_ts": _timestamp(fact.expires_at),
                },
                json.dumps(fact.model_dump(mode="json")),
            )

    def read_application_references(
        self,
        scope: MemoryScope,
    ) -> list[ApplicationReference]:
        """
        Read the owner's application references, newest first.

        Args:
            scope: Authorization context

        Returns:
            List of ApplicationReference objects
        """
        self._validate_scope(scope)

        results = self.applications_collection.get(
            where={"owner_key": {"$eq": scope.owner_key}}
        )

        apps: list[ApplicationReference] = []
        now = _timestamp(utc_now())
        consent_ok: dict[str, bool] = {}

        for meta, doc in zip(results["metadatas"], results["documents"]):
            if meta["expires_at_ts"] <= now:
                continue
            reference = meta["consent_reference"]
            if reference not in consent_ok:
                consent_ok[reference] = self._has_active_consent(
                    scope.owner_key, reference, "application_references"
                )
            if consent_ok[reference]:
                apps.append(ApplicationReference(**json.loads(doc)))

        return sorted(apps, key=lambda app: as_utc(app.submitted_at), reverse=True)

    def save_application_reference(
        self,
        scope: MemoryScope,
        reference: ApplicationReference,
    ) -> None:
        """
        Save an application submission reference, replacing an earlier one for the same application.

        Args:
            scope: Authorization context
            reference: ApplicationReference to store
        """
        self._validate_scope(scope)

        if not self._has_active_consent(
            scope.owner_key, reference.consent_reference, "application_references"
        ):
            raise ValueError(
                f"No active application_references consent "
                f"{reference.consent_reference} for this household"
            )

        if as_utc(reference.expires_at) <= utc_now():
            raise ValueError("Application reference retention window already expired")

        with self._lock:
            self._put(
                self.applications_collection,
                _record_id(scope.owner_key, reference.application_id),
                {
                    "owner_key": scope.owner_key,
                    "application_id": reference.application_id,
                    "scheme_id": reference.scheme_id,
                    "consent_reference": reference.consent_reference,
                    "submitted_at_ts": _timestamp(reference.submitted_at),
                    "expires_at_ts": _timestamp(reference.expires_at),
                },
                json.dumps(reference.model_dump(mode="json")),
            )

    def forget_household(self, scope: MemoryScope) -> None:
        """
        Delete everything stored for a household: facts, references and consents.

        Args:
            scope: Authorization context
        """
        self._validate_scope(scope)

        if scope.actor_role == "operator":
            raise ValueError("Operators cannot delete a household's data")

        household_id = scope.household_id
        with self._lock:
            for collection, owner_field in (
                (self.facts_collection, "household_id"),
                (self.applications_collection, "owner_key"),
                (self.consent_collection, "owner_key"),
            ):
                stored = collection.get(where={owner_field: {"$eq": household_id}})
                if stored["ids"]:
                    collection.delete(ids=stored["ids"])

    def purge_expired(self) -> int:
        """
        Delete expired facts, references and consents, and what only an expired consent covered.

        Returns:
            Number of records deleted
        """
        now = _timestamp(utc_now())
        expired = {"expires_at_ts": {"$lt": now}}
        deleted = 0
        with self._lock:
            lapsed = self.consent_collection.get(
                where={"$and": [{"kind": {"$eq": "consent"}}, expired]}
            )
            for meta in lapsed["metadatas"]:
                deleted += self._delete_covered(
                    meta["owner_key"], meta["consent_reference"], meta["purpose"]
                )
            for collection in (
                self.facts_collection,
                self.applications_collection,
                self.consent_collection,
            ):
                stored = collection.get(where=expired)
                if stored["ids"]:
                    collection.delete(ids=stored["ids"])
                    deleted += len(stored["ids"])
        return deleted

    def get_household_fact_count(self, household_id: str) -> int:
        """Get count of stored facts for a household."""
        facts = self.facts_collection.get(
            where={"household_id": {"$eq": household_id}}
        )
        return len(facts["ids"])

    def _validate_scope(self, scope: MemoryScope) -> None:
        """Validate scope structure."""
        if not scope.actor_id or not scope.household_id:
            raise ValueError(
                "Invalid scope: missing actor_id or household_id"
            )
