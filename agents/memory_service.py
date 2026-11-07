"""Memory Service implementation with allowlist enforcement and consent tracking."""

import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
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
    as_utc,
    utc_now,
)

DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[1] / "data" / "memory_policy.json"
MAX_TEXT_LENGTH = 100
PAN_NUMBER = re.compile(r"[A-Za-z]{5}\d{4}[A-Za-z]")


def looks_like_identifier(text: str) -> bool:
    """True for values shaped like an Aadhaar, bank-account, phone or PAN number."""
    compact = re.sub(r"[\s-]", "", text)
    return bool(re.search(r"\d{9,}", compact) or PAN_NUMBER.search(compact))


def _matches_type(kind: str, value: object) -> bool:
    if kind in {"bool", "boolean"}:
        return isinstance(value, bool)
    if kind in {"integer", "int"}:
        return isinstance(value, int) and not isinstance(value, bool)
    if kind in {"number", "float"}:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    if kind in {"str", "string"}:
        return isinstance(value, str)
    return False


class HouseholdAllowlist(BaseModel):
    """Configuration for which fields can be persisted."""

    allowed_fields: dict[str, dict] = Field(default_factory=dict)
    temporary_only: list[str] = Field(default_factory=list)
    # Example:
    # {
    #     "state_code": {
    #         "type": "string",
    #         "purpose": "Filter schemes by state",
    #         "retention": {"store": True, "reconfirm_days": 90, "expiry_days": 365},
    #         "known_values": [...],
    #     }
    # }

    @classmethod
    def from_policy_file(cls, path: Path | str | None = None) -> "HouseholdAllowlist":
        policy = json.loads(Path(path or DEFAULT_POLICY_PATH).read_text(encoding="utf-8"))
        allowlist = cls(
            allowed_fields=policy["fields"], temporary_only=policy.get("temporary_only", [])
        )
        overlap = set(allowlist.allowed_fields) & set(allowlist.temporary_only)
        if overlap:
            raise ValueError(f"Fields cannot be both stored and temporary only: {sorted(overlap)}")
        return allowlist

    def is_field_allowed(self, field: str) -> bool:
        """Check if a field is on the allowlist."""
        return field in self.allowed_fields

    def get_field_policy(self, field: str) -> Optional[dict]:
        """Get the retention policy for a field."""
        return self.allowed_fields.get(field)

    def validate_fact(self, field: str, value: object) -> None:
        """Raise ValueError unless the field may be stored and the value fits its policy."""
        if field in self.temporary_only:
            raise ValueError(f"Field {field} is not allowed for storage: it is used for one assessment only")
        policy = self.allowed_fields.get(field)
        if policy is None or policy.get("retention", {}).get("store", True) is False:
            raise ValueError(f"Field {field} is not allowed for storage")
        kind = policy.get("type")
        if kind is not None and not _matches_type(kind, value):
            raise ValueError(f"Field {field} must be of type {kind}")
        if not isinstance(value, (str, int, float, bool)):
            raise ValueError(f"Field {field} must be a single value")
        known_values = policy.get("known_values")
        if known_values and value not in known_values:
            raise ValueError(f"Field {field} must be one of {known_values}")
        if isinstance(value, str) and (len(value) > MAX_TEXT_LENGTH or looks_like_identifier(value)):
            raise ValueError(
                f"Field {field} is too long or looks like an identifier number and cannot be stored"
            )

    def retention_window(self, field: str, confirmed_at: datetime) -> tuple[datetime, datetime]:
        """The (reconfirm_by, expires_at) the policy gives a fact confirmed at `confirmed_at`."""
        retention = (self.allowed_fields.get(field) or {}).get("retention", {})
        if "reconfirm_days" not in retention or "expiry_days" not in retention:
            raise ValueError(f"Field {field} has no reconfirm_days and expiry_days in its policy")
        return (
            confirmed_at + timedelta(days=retention["reconfirm_days"]),
            confirmed_at + timedelta(days=retention["expiry_days"]),
        )


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
        self.consent_owner: dict[str, str] = {}  # consent_reference -> household_id

    def _bucket(self, owner: str) -> dict:
        if owner not in self.households:
            self.households[owner] = {
                "consents": [],
                "facts": [],
                "application_refs": [],
                "created_at": utc_now(),
            }
        return self.households[owner]

    def _consent_for(
        self, scope: MemoryScope, consent_reference: str
    ) -> Optional[MemoryConsent]:
        """Return the consent only if it belongs to the scope's owner for its purpose."""
        consent = self.consents.get(consent_reference)
        if consent is None:
            return None
        if self.consent_owner.get(consent_reference) != scope.owner_for(consent.purpose):
            return None
        return consent

    def record_consent(
        self, scope: MemoryScope, consent: MemoryConsent
    ) -> None:
        """Record user consent for memory operations."""
        self._validate_scope(scope)

        # Verify consent is not expired
        if as_utc(consent.expires_at) <= utc_now():
            raise ValueError("Cannot record consent that is already expired")

        # A consent reference belongs to exactly one owner
        new_owner = scope.owner_for(consent.purpose)
        owner = self.consent_owner.get(consent.consent_reference)
        if owner is not None and owner != new_owner:
            raise ValueError(
                f"Consent {consent.consent_reference} belongs to another household"
            )

        # Store consent
        self.consents[consent.consent_reference] = consent
        self.consent_owner[consent.consent_reference] = new_owner

        bucket = self._bucket(new_owner)
        if consent.consent_reference not in bucket["consents"]:
            bucket["consents"].append(consent.consent_reference)

    def withdraw_consent(
        self, scope: MemoryScope, consent_reference: str
    ) -> None:
        """Withdraw user consent and delete associated data."""
        self._validate_scope(scope)

        if self._consent_for(scope, consent_reference) is None:
            raise ValueError(f"Consent {consent_reference} not found")

        # Remove consent record
        del self.consents[consent_reference]
        del self.consent_owner[consent_reference]

        # Delete all facts and application references tied to this consent
        facts_to_delete = [
            fid
            for fid, fact in self.facts.items()
            if fact.consent_reference == consent_reference
        ]
        for fid in facts_to_delete:
            del self.facts[fid]
        refs_to_delete = [
            rid
            for rid, ref in self.application_refs.items()
            if ref.consent_reference == consent_reference
        ]
        for rid in refs_to_delete:
            del self.application_refs[rid]

        # Drop dangling ids from every household index
        for data in self.households.values():
            data["consents"] = [c for c in data["consents"] if c != consent_reference]
            data["facts"] = [f for f in data["facts"] if f in self.facts]
            data["application_refs"] = [
                r for r in data["application_refs"] if r in self.application_refs
            ]

    def read_facts(
        self, scope: MemoryScope, fields: list[str]
    ) -> FactMap:
        """Read consented household facts.
        
        Only returns non-expired facts that are:
        - On the allowlist
        - Consented
        - Not expired

        An empty `fields` list means every allowlisted field.
        """
        self._validate_scope(scope)

        if scope.household_id not in self.households:
            return {}

        result = {}
        now = utc_now()
        wanted = fields or list(self.allowlist.allowed_fields)

        for field in wanted:
            # Check allowlist
            if not self.allowlist.is_field_allowed(field):
                continue

            # Find facts for this field in this household
            # Newest valid fact wins
            newest = None
            for fact in self.households[scope.household_id].get("facts", []):
                fact_obj = self.facts.get(fact)
                if not fact_obj:
                    continue

                if (
                    fact_obj.field == field
                    and as_utc(fact_obj.expires_at) > now
                    and as_utc(fact_obj.reconfirm_by) > now
                ):
                    # Verify consent is still valid
                    consent = self._consent_for(scope, fact_obj.consent_reference)
                    if (
                        consent
                        and consent.granted
                        and consent.purpose == "profile_facts"
                        and as_utc(consent.expires_at) > now
                    ):
                        if newest is None or as_utc(fact_obj.confirmed_at) >= as_utc(newest.confirmed_at):
                            newest = fact_obj

            if newest is not None:
                result[field] = newest.value

        return result

    def save_confirmed_fact(
        self, scope: MemoryScope, fact: MemoryFact
    ) -> None:
        """Persist a confirmed household fact with consent check."""
        self._validate_scope(scope)

        # Check allowlist, type and value
        self.allowlist.validate_fact(fact.field, fact.value)

        # Verify consent exists and is valid
        consent = self._consent_for(scope, fact.consent_reference)
        if not consent or not consent.granted:
            raise ValueError(f"Consent {fact.consent_reference} not found or denied")

        if consent.purpose != "profile_facts":
            raise ValueError(
                f"Consent {fact.consent_reference} does not cover profile_facts"
            )

        now = utc_now()
        if as_utc(consent.expires_at) <= now:
            raise ValueError(f"Consent {fact.consent_reference} has expired")

        # Check field expiry
        if as_utc(fact.expires_at) <= now or as_utc(fact.reconfirm_by) <= now:
            raise ValueError("Fact retention window already expired")

        # Store fact
        fact_id = str(uuid4())
        self.facts[fact_id] = fact
        self._bucket(scope.household_id)["facts"].append(fact_id)

    def read_application_references(
        self, scope: MemoryScope
    ) -> list[ApplicationReference]:
        """Retrieve consented application references, newest first."""
        self._validate_scope(scope)

        owner = scope.owner_key
        if owner not in self.households:
            return []

        result = []
        now = utc_now()

        for ref_id in self.households[owner].get("application_refs", []):
            ref = self.application_refs.get(ref_id)
            if not ref:
                continue

            # Only return non-expired references
            if as_utc(ref.expires_at) > now:
                # Verify consent is still valid
                consent = self._consent_for(scope, ref.consent_reference)
                if (
                    consent
                    and consent.granted
                    and consent.purpose == "application_references"
                    and as_utc(consent.expires_at) > now
                ):
                    result.append(ref)

        return sorted(result, key=lambda r: as_utc(r.submitted_at), reverse=True)

    def save_application_reference(
        self, scope: MemoryScope, reference: ApplicationReference
    ) -> None:
        """Store application reference with consent check."""
        self._validate_scope(scope)

        # Verify consent exists and is valid
        consent = self._consent_for(scope, reference.consent_reference)
        if not consent or not consent.granted:
            raise ValueError(
                f"Consent {reference.consent_reference} not found or denied"
            )

        if consent.purpose != "application_references":
            raise ValueError(
                f"Consent {reference.consent_reference} does not cover "
                "application_references"
            )

        if as_utc(consent.expires_at) <= utc_now():
            raise ValueError(f"Consent {reference.consent_reference} has expired")

        # One record per application: saving it again replaces the earlier one
        bucket = self._bucket(scope.owner_key)
        for ref_id in list(bucket["application_refs"]):
            existing = self.application_refs.get(ref_id)
            if existing is not None and existing.application_id == reference.application_id:
                bucket["application_refs"].remove(ref_id)
                del self.application_refs[ref_id]

        ref_id = str(uuid4())
        self.application_refs[ref_id] = reference
        bucket["application_refs"].append(ref_id)

    def forget_household(self, scope: MemoryScope) -> None:
        """Delete all household data, facts, consents, and application references."""
        self._validate_scope(scope)

        if scope.actor_role == "operator":
            raise ValueError("Operators cannot delete a household's data")

        if scope.household_id not in self.households:
            return

        household_data = self.households[scope.household_id]

        # Delete all consents
        for consent_ref in household_data.get("consents", []):
            self.consents.pop(consent_ref, None)
            self.consent_owner.pop(consent_ref, None)

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

    def purge_expired(self) -> int:
        """Delete expired facts, references and consents, and what only an expired consent covered."""
        now = utc_now()
        expired_consents = {
            ref for ref, consent in self.consents.items() if as_utc(consent.expires_at) <= now
        }
        doomed_facts = [
            fid
            for fid, fact in self.facts.items()
            if as_utc(fact.expires_at) <= now or fact.consent_reference in expired_consents
        ]
        doomed_refs = [
            rid
            for rid, ref in self.application_refs.items()
            if as_utc(ref.expires_at) <= now or ref.consent_reference in expired_consents
        ]
        for fid in doomed_facts:
            del self.facts[fid]
        for rid in doomed_refs:
            del self.application_refs[rid]
        for ref in expired_consents:
            del self.consents[ref]
            self.consent_owner.pop(ref, None)

        for data in self.households.values():
            data["consents"] = [c for c in data["consents"] if c in self.consents]
            data["facts"] = [f for f in data["facts"] if f in self.facts]
            data["application_refs"] = [
                r for r in data["application_refs"] if r in self.application_refs
            ]
        return len(doomed_facts) + len(doomed_refs) + len(expired_consents)

    def _validate_scope(self, scope: MemoryScope) -> None:
        """Validate that scope is authorized and not expired."""
        if not scope.actor_id or not scope.household_id:
            raise ValueError("Scope must have actor_id and household_id")

        # In production, verify actor_id is authenticated and authorized
        # For MVP, accept any scope

        # Optional: check scope expiry
        # if scope.get("expires_at") and scope["expires_at"] < datetime.now():
        #     raise ValueError("Scope authorization has expired")
