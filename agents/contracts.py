"""Typed contracts shared by the GPT agents and their orchestrator."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

Language = Literal["en", "hi", "mr", "unknown"]
Intent = Literal["discover", "eligibility", "documents", "application", "follow_up", "other"]
Route = Literal["eligibility", "document_checker", "application", "respond"]
FactMap = dict[str, JsonValue]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IntakeInput(Contract):
    request: str = Field(min_length=1)
    known_facts: FactMap = Field(default_factory=dict)


class CandidateFact(Contract):
    field: str = Field(min_length=1)
    value: str | int | float | bool | None
    confidence: Literal["high", "medium", "low"]
    requires_confirmation: Literal[True] = True


class IntakeResult(Contract):
    language: Language
    intent: Intent
    candidate_facts: list[CandidateFact] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)


class SupervisorInput(Contract):
    request: str = Field(min_length=1)
    intake: IntakeResult
    selected_scheme_id: str | None = None


class SupervisorPlan(Contract):
    next_agent: Route
    reason: str = Field(min_length=1)


class EligibilityInput(Contract):
    scheme_id: str = Field(min_length=1)
    evaluation: FactMap


class EligibilityNarrative(Contract):
    explanation: str = Field(min_length=1)
    clarifying_questions: list[str] = Field(default_factory=list)


class DocumentCheckInput(Contract):
    scheme_id: str = Field(min_length=1)
    required_documents: list[str] = Field(default_factory=list)
    available_documents: list[str] = Field(default_factory=list)


class DocumentCheckResult(Contract):
    missing_documents: list[str] = Field(default_factory=list)
    possible_inconsistencies: list[str] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)
    authenticity_verified: Literal[False] = False


class ApplicationInput(Contract):
    scheme_id: str = Field(min_length=1)
    confirmed_facts: FactMap
    required_fields: list[str]
    field_mapping: dict[str, str]


class ApplicationNarrativeInput(Contract):
    scheme_id: str
    populated_fields: list[str]
    missing_fields: list[str]


class ApplicationNarrative(Contract):
    review_summary: str = Field(min_length=1)


class ApplicationDraft(Contract):
    scheme_id: str
    fields: FactMap
    missing_fields: list[str]
    review_summary: str
