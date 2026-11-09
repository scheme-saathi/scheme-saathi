"""Service boundary for consented long-term memory; no storage backend is implied.

Naive datetimes are read as UTC. Timezone-aware values are converted to naive UTC
with `as_utc` before any comparison, so every implementation uses one clock.
"""

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import Field, JsonValue, model_validator

from agents.contracts import Contract, FactMap

if TYPE_CHECKING:
    from agents.memory_service import HouseholdAllowlist

Purpose = Literal["profile_facts", "application_references"]

# A relation label such as "mother": letters (Latin or Devanagari) only, so it cannot carry a name with digits or an ID.
RELATION_LABEL = re.compile(r"^[A-Za-z\u0900-\u097F][A-Za-z\u0900-\u097F '\-]{0,39}$")


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def clean_relation(value: object) -> str | None:
    """A relation label that passes the same check as ApplicationReference, or None."""
    if not isinstance(value, str):
        return None
    label = value.strip().lower()
    return label if RELATION_LABEL.fullmatch(label) else None


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


class MemoryScope(Contract):
    """Trusted authorization context created by the application backend."""

    actor_id: str = Field(min_length=1)
    household_id: str = Field(min_length=1)
    actor_role: Literal["citizen", "operator"]
    grant_id: str | None = None

    @property
    def owner_key(self) -> str:
        """Who owns application references: the household, or the operator's own list."""
        if self.actor_role == "operator":
            return f"operator:{self.actor_id}"
        return self.household_id

    def owner_for(self, purpose: Purpose) -> str:
        """Profile facts and their consent belong to the household; references to `owner_key`."""
        return self.owner_key if purpose == "application_references" else self.household_id


class MemoryConsent(Contract):
    purpose: Purpose
    granted: bool
    notice_version: str = Field(min_length=1)
    decided_at: datetime
    expires_at: datetime
    consent_reference: str = Field(min_length=1)
    obtained_via: Literal["self_service", "in_person"] = "self_service"
    recorded_by: str | None = None

    @model_validator(mode="after")
    def validate_expiry(self) -> "MemoryConsent":
        if as_utc(self.expires_at) <= as_utc(self.decided_at):
            raise ValueError("Memory consent must expire after it is recorded.")
        if self.obtained_via == "in_person" and not self.recorded_by:
            raise ValueError("Consent obtained in person must say who recorded it.")
        return self


class MemoryFact(Contract):
    field: str = Field(min_length=1)
    value: JsonValue
    source: str = Field(min_length=1)
    confirmed_at: datetime
    reconfirm_by: datetime
    expires_at: datetime
    consent_reference: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_retention_window(self) -> "MemoryFact":
        if not as_utc(self.confirmed_at) <= as_utc(self.reconfirm_by) <= as_utc(self.expires_at):
            raise ValueError(
                "Memory fact deadlines must be ordered: confirmed_at <= "
                "reconfirm_by <= expires_at."
            )
        return self


class ApplicationReference(Contract):
    scheme_id: str = Field(min_length=1)
    application_id: str = Field(min_length=1)
    submitted_at: datetime
    expires_at: datetime
    consent_reference: str = Field(min_length=1)
    subject: Literal["self", "other"] = "self"
    relation: str | None = None
    submitted_by: str | None = None
    nickname: str | None = None

    @model_validator(mode="after")
    def validate_expiry(self) -> "ApplicationReference":
        if as_utc(self.expires_at) <= as_utc(self.submitted_at):
            raise ValueError("Application references must expire after submission.")
        if self.relation is not None:
            if self.subject != "other":
                raise ValueError("A relation label only applies to applications for someone else.")
            if not RELATION_LABEL.fullmatch(self.relation):
                raise ValueError("A relation label is a short word such as 'mother', never a name or number.")
        if self.nickname is not None:
            if self.relation is None:
                raise ValueError("A nickname needs a relation.")
            if not RELATION_LABEL.fullmatch(self.nickname):
                raise ValueError("A nickname is a short word made of letters, never a number or ID.")
        return self


class MemoryService(Protocol):
    """Implementations must enforce authorization, consent, allowlists, and expiry."""

    allowlist: "HouseholdAllowlist"

    def record_consent(
        self, scope: MemoryScope, consent: MemoryConsent
    ) -> None: ...

    def withdraw_consent(
        self, scope: MemoryScope, consent_reference: str
    ) -> None: ...

    def active_consent(
        self, scope: MemoryScope, purpose: Purpose
    ) -> MemoryConsent | None:
        """The newest granted, unexpired, unwithdrawn consent the scope's owner holds for the purpose."""
        ...

    def read_facts(
        self, scope: MemoryScope, fields: list[str]
    ) -> FactMap: ...

    def save_confirmed_fact(
        self, scope: MemoryScope, fact: MemoryFact
    ) -> None: ...

    def reconfirm_facts(
        self, scope: MemoryScope, fields: list[str], confirmed_at: datetime | None = None
    ) -> list[str]:
        """Record that the person confirmed these stored facts again, unchanged.

        Moves `reconfirm_by` on, never past the original `expires_at`, so retention is not
        extended. Returns the fields that were stored, unexpired and consented.
        """
        ...

    def read_application_references(
        self, scope: MemoryScope
    ) -> list[ApplicationReference]: ...

    def save_application_reference(
        self, scope: MemoryScope, reference: ApplicationReference
    ) -> None: ...

    def forget_household(self, scope: MemoryScope) -> None: ...

    def list_facts(self, scope: MemoryScope) -> list[MemoryFact]:
        """The household's stored, unexpired, consented facts, including ones due for reconfirmation."""
        ...

    def delete_fact(self, scope: MemoryScope, field: str) -> bool:
        """Delete one remembered fact; False when none was stored. A citizen's action only."""
        ...

    def delete_application_reference(self, scope: MemoryScope, application_id: str) -> bool:
        """Delete one remembered application from the scope owner's list; False when not listed."""
        ...

    def purge_expired(self) -> int:
        """Delete expired facts, references and consents; return how many records went."""
        ...


# An operator's consent is not one blanket agreement: the person being helped agrees for each
# application, and that agreement is recorded under a reference with this prefix and ends with it.
PER_APPLICATION_CONSENT_PREFIX = "in-person-"


def remove_application(service: MemoryService, scope: MemoryScope, application_id: str) -> bool:
    """Remove one saved application, and the in-person agreement recorded for it alone.

    An agreement that covers more than one application (a citizen's, or an operator's earlier
    blanket one) is left in place, because withdrawing it would delete the others too.
    """
    reference = next(
        (r for r in service.read_application_references(scope) if r.application_id == application_id), None
    )
    removed = service.delete_application_reference(scope, application_id)
    if removed and reference and reference.consent_reference.startswith(PER_APPLICATION_CONSENT_PREFIX):
        try:
            service.withdraw_consent(scope, reference.consent_reference)
        except ValueError:
            pass  # already gone, which is what was wanted
    return removed
