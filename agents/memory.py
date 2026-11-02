"""Service boundary for consented long-term memory; no storage backend is implied."""

from datetime import datetime
from typing import Literal, Protocol

from pydantic import Field, JsonValue, model_validator

from agents.contracts import Contract, FactMap


class MemoryScope(Contract):
    """Trusted authorization context created by the application backend."""

    actor_id: str = Field(min_length=1)
    household_id: str = Field(min_length=1)
    actor_role: Literal["citizen", "operator"]
    grant_id: str | None = None


class MemoryConsent(Contract):
    purpose: Literal["profile_facts", "application_references"]
    granted: bool
    notice_version: str = Field(min_length=1)
    decided_at: datetime
    expires_at: datetime
    consent_reference: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_expiry(self) -> "MemoryConsent":
        if self.expires_at <= self.decided_at:
            raise ValueError("Memory consent must expire after it is recorded.")
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
        if not self.confirmed_at <= self.reconfirm_by <= self.expires_at:
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

    @model_validator(mode="after")
    def validate_expiry(self) -> "ApplicationReference":
        if self.expires_at <= self.submitted_at:
            raise ValueError("Application references must expire after submission.")
        return self


class MemoryService(Protocol):
    """Implementations must enforce authorization, consent, allowlists, and expiry."""

    def record_consent(
        self, scope: MemoryScope, consent: MemoryConsent
    ) -> None: ...

    def withdraw_consent(
        self, scope: MemoryScope, consent_reference: str
    ) -> None: ...

    def read_facts(
        self, scope: MemoryScope, fields: list[str]
    ) -> FactMap: ...

    def save_confirmed_fact(
        self, scope: MemoryScope, fact: MemoryFact
    ) -> None: ...

    def read_application_references(
        self, scope: MemoryScope
    ) -> list[ApplicationReference]: ...

    def save_application_reference(
        self, scope: MemoryScope, reference: ApplicationReference
    ) -> None: ...

    def forget_household(self, scope: MemoryScope) -> None: ...
