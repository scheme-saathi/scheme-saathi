"""Typed workflow state for LangGraph orchestrator."""

from typing import TypedDict, Literal, Any
from datetime import datetime

from agents.contracts import (
    Language,
    Intent,
    Route,
    CandidateFact,
    FactMap,
    ApplicationDraft,
)


class HouseholdScope(TypedDict, total=False):
    """Trusted authorization context created by backend."""

    actor_id: str
    household_id: str
    actor_role: Literal["citizen", "csc_operator"]
    authenticated_at: datetime
    expires_at: datetime


class WorkflowState(TypedDict, total=False):
    """Complete workflow state for LangGraph checkpointing."""

    # Input & session
    user_request: str
    household_scope: HouseholdScope
    conversation_history: list[tuple[str, str]]  # (role, message)

    # Current step tracking
    current_step: Literal[
        "intake", "eligibility", "documents", "application", "complete"
    ]
    step_entered_at: datetime

    # Intake phase results
    language: Language
    intent: Intent
    candidate_facts: list[CandidateFact]
    confirmed_facts: FactMap
    pending_clarifications: list[str]

    # Eligibility phase
    selected_scheme_id: str
    scheme_version: str
    eligibility_verdict: Literal["eligible", "not_eligible", "cannot_tell"]
    missing_fields_for_verdict: list[str]
    eligibility_citations: list[dict[str, Any]]
    eligibility_explanation: str

    # Document phase
    required_documents: list[str]
    available_documents: list[str]
    document_check_result: dict[str, Any]
    missing_documents: list[str]
    document_inconsistencies: list[str]

    # Application phase
    application_draft: ApplicationDraft
    draft_hash: str  # For approval verification
    user_approval: bool
    approval_timestamp: datetime
    submission_result: dict[str, Any]
    application_reference: str

    # Workflow control
    next_action: Literal[
        "respond", "clarify", "continue", "resume", "end", "error"
    ]
    error_message: str

    # Memory & checkpointing
    checkpoint_id: str
    last_checkpoint_at: datetime


class IntakePhaseState(TypedDict, total=False):
    """State during intake phase."""

    language: Language
    intent: Intent
    candidate_facts: list[CandidateFact]
    confirmed_facts: FactMap
    pending_clarifications: list[str]


class EligibilityPhaseState(TypedDict, total=False):
    """State during eligibility phase."""

    selected_scheme_id: str
    scheme_version: str
    eligibility_verdict: Literal["eligible", "not_eligible", "cannot_tell"]
    missing_fields_for_verdict: list[str]
    eligibility_citations: list[dict[str, Any]]
    eligibility_explanation: str


class DocumentPhaseState(TypedDict, total=False):
    """State during document checking phase."""

    required_documents: list[str]
    available_documents: list[str]
    document_check_result: dict[str, Any]
    missing_documents: list[str]
    document_inconsistencies: list[str]


class ApplicationPhaseState(TypedDict, total=False):
    """State during application preparation phase."""

    application_draft: ApplicationDraft
    draft_hash: str
    user_approval: bool
    approval_timestamp: datetime
    submission_result: dict[str, Any]
    application_reference: str
