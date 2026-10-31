"""Memory Service implementation with allowlist enforcement and consent tracking."""

from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from agents.contracts import FactMap
from agents.memory import (
    MemoryScope,
    MemoryConsent,
    MemoryFact,
    ApplicationReference,
    MemoryService,
)


class HouseholdAllowlist(BaseModel):
    """Configuration for which fields can be persisted."""

    allowed_fields: dict[str, dict] = Field(default_factory=dict)
    # Example:
    # {
    #     "state_code": {
    #         "type": "string",
    #         "purpose": "Filter schemes by state",
    #         "retention": {"store": True, "expiry_days": 365},
    #         "access": ["intake", "eligibility"]
    #     }
    # }

    def is_field_allowed(self, field: str) -> bool:
        """Check if a field is on the allowlist."""
        return field in self.allowed_fields

    def get_field_policy(self, field: str) -> Optional[dict]:
        """Get the retention policy for a field."""
        return self.allowed_fields.get(field)


class InMemoryMemoryService(MemoryService):
    """In-memory implementation of MemoryService for testing/MVP.
    
    In production, replace with ChromaDB-backed implementation.
    """

    def __init__(self, allowlist: HouseholdAllowlist):
        self.allowlist = allowlist
        self.households: dict[str, dict] = {}  # household_id -> data
        self.consents: dict[str, MemoryConsent] = {}  # consent_reference -> consent
        self.facts: dict[str, MemoryFact] = {}  # fact_id -> fact
        self.application_refs: dict[str, ApplicationReference] = (
            {}
        )  # ref_id -> reference

    def record_consent(
        self, scope: MemoryScope, consent: MemoryConsent
    ) -> None:
        """Record user consent for memory operations."""
        self._validate_scope(scope)

        # Verify consent is not expired
        if consent.expires_at <= datetime.now():
            raise ValueError("Cannot record consent that is already expired")

        # Store consent
        self.consents[consent.consent_reference] = consent

        # Ensure household entry exists
        if scope.household_id not in self.households:
            self.households[scope.household_id] = {
                "consents": [],
                "facts": [],
                "application_refs": [],
                "created_at": datetime.now(),
            }

        self.households[scope.household_id]["consents"].append(
            consent.consent_reference
        )

    def withdraw_consent(
        self, scope: MemoryScope, consent_reference: str
    ) -> None:
        """Withdraw user consent and delete associated data."""
        self._validate_scope(scope)

        if consent_reference not in self.consents:
            raise ValueError(f"Consent {consent_reference} not found")

        # Remove consent record
        del self.consents[consent_reference]

        # Delete all facts tied to this consent
        facts_to_delete = [
            fid
            for fid, fact in self.facts.items()
            if fact.consent_reference == consent_reference
        ]
        for fid in facts_to_delete:
            del self.facts[fid]

    def read_facts(
        self, scope: MemoryScope, fields: list[str]
    ) -> FactMap:
        """Read consented household facts.
        
        Only returns non-expired facts that are:
        - On the allowlist
        - Consented
        - Not expired
        """
        self._validate_scope(scope)

        if scope.household_id not in self.households:
            return {}

        result = {}
        now = datetime.now()

        for field in fields:
            # Check allowlist
            if not self.allowlist.is_field_allowed(field):
                continue

            # Find facts for this field in this household
            for fact in self.households[scope.household_id].get("facts", []):
                fact_obj = self.facts.get(fact)
                if not fact_obj:
                    continue

                if fact_obj.field == field and fact_obj.expires_at > now:
                    # Verify consent is still valid
                    consent = self.consents.get(fact_obj.consent_reference)
                    if consent and consent.granted and consent.expires_at > now:
                        result[field] = fact_obj.value
                        break

        return result

    def save_confirmed_fact(
        self, scope: MemoryScope, fact: MemoryFact
    ) -> None:
        """Persist a confirmed household fact with consent check."""
        self._validate_scope(scope)

        # Check allowlist
        if not self.allowlist.is_field_allowed(fact.field):
            raise ValueError(f"Field {fact.field} is not allowed for storage")

        # Verify consent exists and is valid
        consent = self.consents.get(fact.consent_reference)
        if not consent or not consent.granted:
            raise ValueError(f"Consent {fact.consent_reference} not found or denied")

        if consent.expires_at <= datetime.now():
            raise ValueError(f"Consent {fact.consent_reference} has expired")

        # Check field expiry
        now = datetime.now()
        if fact.expires_at <= now or fact.reconfirm_by <= now:
            raise ValueError("Fact retention window already expired")

        # Ensure household entry exists
        if scope.household_id not in self.households:
            self.households[scope.household_id] = {
                "consents": [],
                "facts": [],
                "application_refs": [],
                "created_at": datetime.now(),
            }

        # Store fact
        fact_id = str(uuid4())
        self.facts[fact_id] = fact
        self.households[scope.household_id]["facts"].append(fact_id)

    def read_application_references(
        self, scope: MemoryScope
    ) -> list[ApplicationReference]:
        """Retrieve consented application references."""
        self._validate_scope(scope)

        if scope.household_id not in self.households:
            return []

        result = []
        now = datetime.now()

        for ref_id in self.households[scope.household_id].get("application_refs", []):
            ref = self.application_refs.get(ref_id)
            if not ref:
                continue

            # Only return non-expired references
            if ref.expires_at > now:
                # Verify consent is still valid
                consent = self.consents.get(ref.consent_reference)
                if consent and consent.granted and consent.expires_at > now:
                    result.append(ref)

        return result

    def save_application_reference(
        self, scope: MemoryScope, reference: ApplicationReference
    ) -> None:
        """Store application reference with consent check."""
        self._validate_scope(scope)

        # Verify consent exists and is valid
        consent = self.consents.get(reference.consent_reference)
        if not consent or not consent.granted:
            raise ValueError(
                f"Consent {reference.consent_reference} not found or denied"
            )

        if consent.expires_at <= datetime.now():
            raise ValueError(f"Consent {reference.consent_reference} has expired")

        # Ensure household entry exists
        if scope.household_id not in self.households:
            self.households[scope.household_id] = {
                "consents": [],
                "facts": [],
                "application_refs": [],
                "created_at": datetime.now(),
            }

        # Store reference
        ref_id = str(uuid4())
        self.application_refs[ref_id] = reference
        self.households[scope.household_id]["application_refs"].append(ref_id)

    def forget_household(self, scope: MemoryScope) -> None:
        """Delete all household data, facts, consents, and application references."""
        self._validate_scope(scope)

        if scope.household_id not in self.households:
            return

        household_data = self.households[scope.household_id]

        # Delete all consents
        for consent_ref in household_data.get("consents", []):
            if consent_ref in self.consents:
                del self.consents[consent_ref]

        # Delete all facts
        for fact_id in household_data.get("facts", []):
            if fact_id in self.facts:
                del self.facts[fact_id]

        # Delete all application references
        for ref_id in household_data.get("application_refs", []):
            if ref_id in self.application_refs:
                del self.application_refs[ref_id]

        # Delete household record
        del self.households[scope.household_id]

    def _validate_scope(self, scope: MemoryScope) -> None:
        """Validate that scope is authorized and not expired."""
        if not scope.actor_id or not scope.household_id:
            raise ValueError("Scope must have actor_id and household_id")

        # In production, verify actor_id is authenticated and authorized
        # For MVP, accept any scope

        # Optional: check scope expiry
        # if scope.get("expires_at") and scope["expires_at"] < datetime.now():
        #     raise ValueError("Scope authorization has expired")
