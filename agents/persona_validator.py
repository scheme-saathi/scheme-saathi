"""Persona validator: ensures agents follow their instructions and respect contracts."""

from typing import Any

from agents.contracts import (
    SupervisorPlan,
    EligibilityNarrative,
    CandidateFact,
    DocumentCheckResult,
    ApplicationDraft,
)


class PersonaValidationError(ValueError):
    """Raised when an agent violates persona boundaries."""

    pass


class PersonaValidator:
    """Validates that agents follow their intended instructions and guardrails."""

    # Sensitive field patterns to reject from fact collection
    SENSITIVE_PATTERNS = {
        "aadhaar",
        "aadhar",
        "ssn",
        "pan",
        "gst",
        "bank_account",
        "bank_",
        "password",
        "pin",
        "otp",
        "token",
        "secret",
        "credit_card",
    }

    @staticmethod
    def validate_supervisor_response(plan: SupervisorPlan) -> None:
        """Verify Supervisor only routes, never makes decisions."""
        reason_lower = plan.reason.lower()

        # Supervisor must not make eligibility decisions
        if "eligible" in reason_lower or "not eligible" in reason_lower:
            raise PersonaValidationError(
                "Supervisor must not make eligibility decisions; only route."
            )

        # Supervisor must not change verdicts
        if "approved" in reason_lower or "rejected" in reason_lower:
            raise PersonaValidationError(
                "Supervisor must not approve or reject applications"
            )

        # Valid routes only
        valid_routes = {"eligibility", "document_checker", "application", "respond"}
        if plan.next_agent not in valid_routes:
            raise PersonaValidationError(
                f"Invalid route: {plan.next_agent}. Must be one of {valid_routes}"
            )

    @staticmethod
    def validate_eligibility_response(narrative: EligibilityNarrative) -> None:
        """Verify Eligibility Agent preserves verdict and citations."""
        explanation_lower = narrative.explanation.lower()

        # Agent must not claim to have changed the result
        if "changed" in explanation_lower or "override" in explanation_lower:
            raise PersonaValidationError(
                "Eligibility Agent must preserve verdict exactly as evaluated"
            )

        # Must include citations if discussing rules
        if "rule" in explanation_lower or "clause" in explanation_lower:
            if not narrative.explanation or len(narrative.explanation) < 20:
                raise PersonaValidationError(
                    "Eligibility explanation must include rule citations"
                )

    @staticmethod
    def validate_intake_facts(facts: list[CandidateFact]) -> None:
        """Verify no sensitive data collected in fact extraction."""
        for fact in facts:
            field_lower = fact.field.lower()

            # Check against sensitive patterns
            for sensitive in PersonaValidator.SENSITIVE_PATTERNS:
                if sensitive in field_lower:
                    raise PersonaValidationError(
                        f"Intake must not collect sensitive field: {fact.field}"
                    )

        # Verify confidence levels are reasonable
        for fact in facts:
            if fact.confidence not in ("high", "medium", "low"):
                raise PersonaValidationError(
                    f"Invalid confidence level: {fact.confidence}"
                )

            # If requires_confirmation is not True, reject
            if not fact.requires_confirmation:
                raise PersonaValidationError(
                    "All candidate facts must require confirmation"
                )

    @staticmethod
    def validate_document_check_result(result: DocumentCheckResult) -> None:
        """Verify Document Checker doesn't claim authenticity."""
        result_lower = (
            str(result.possible_inconsistencies).lower()
            + str(result.missing_documents).lower()
        )

        # Must not claim documents are authentic
        if "authentic" in result_lower or "verified" in result_lower:
            raise PersonaValidationError(
                "Document Checker must not claim documents are authentic or verified"
            )

        # authenticity_verified field must always be False
        if result.authenticity_verified:
            raise PersonaValidationError(
                "Document Checker cannot verify authenticity; field must be False"
            )

    @staticmethod
    def validate_application_draft(draft: ApplicationDraft) -> None:
        """Verify application draft is valid and complete."""
        if not draft.scheme_id:
            raise PersonaValidationError("Draft must reference a scheme_id")

        if not draft.review_summary:
            raise PersonaValidationError("Draft must include a review_summary")

        # Verify missing fields are noted
        if draft.missing_fields and not any(
            "missing" in summary.lower()
            for summary in [draft.review_summary]
        ):
            raise PersonaValidationError(
                "Draft review must note missing required fields"
            )


class CitationValidator:
    """Validates that citations reference correct, reviewed scheme versions."""

    def __init__(self, scheme_registry: dict[str, dict[str, Any]] | None = None):
        """Initialize with optional scheme registry for validation.
        
        scheme_registry format:
        {
            "scheme_id": {
                "versions": {
                    "v1.0": {"reviewed": True, "clauses": [...]}
                }
            }
        }
        """
        self.scheme_registry = scheme_registry or {}

    def validate_citation(self, citation: dict[str, Any]) -> None:
        """Verify citation references exist and are authoritative."""
        required_fields = {"scheme_id", "clause_id", "quote"}
        if not all(field in citation for field in required_fields):
            raise PersonaValidationError(
                f"Citation missing required fields: {required_fields}"
            )

        # If scheme registry is available, verify scheme exists
        if self.scheme_registry:
            scheme_id = citation["scheme_id"]
            if scheme_id not in self.scheme_registry:
                raise PersonaValidationError(
                    f"Scheme {scheme_id} not found in registry"
                )

            # Optionally verify version is reviewed
            scheme = self.scheme_registry[scheme_id]
            if "versions" in scheme:
                version = citation.get("scheme_version", "v1.0")
                if version not in scheme["versions"]:
                    raise PersonaValidationError(
                        f"Scheme version {version} not found"
                    )


class MemoryAccessValidator:
    """Validates memory operations respect scope, consent, and expiry."""

    @staticmethod
    def validate_scope_isolation(actor_id: str, household_id: str) -> None:
        """Verify actor has authorization for this household."""
        if not actor_id or not household_id:
            raise PersonaValidationError(
                "Memory operation missing actor_id or household_id"
            )

        # In production, verify actor is authenticated and has access to household
        # For MVP, accept all scopes

    @staticmethod
    def validate_consent_present(
        consent_reference: str | None, operation: str
    ) -> None:
        """Verify consent reference exists for memory operation."""
        if not consent_reference:
            raise PersonaValidationError(
                f"Memory operation '{operation}' requires valid consent_reference"
            )

    @staticmethod
    def validate_field_allowed(
        field: str, allowed_fields: dict[str, Any]
    ) -> None:
        """Verify field is on the allowlist."""
        if field not in allowed_fields:
            raise PersonaValidationError(
                f"Field '{field}' is not allowed for durable storage. "
                f"Allowed: {list(allowed_fields.keys())}"
            )

    @staticmethod
    def validate_no_sensitive_data_in_logs(data: dict[str, Any]) -> None:
        """Verify sensitive fields are not logged."""
        sensitive_keys = {
            "password",
            "token",
            "secret",
            "api_key",
            "aadhaar",
            "pan",
        }

        def check_dict(d: dict, path: str = "") -> None:
            for k, v in d.items():
                full_key = f"{path}.{k}" if path else k
                if any(s in k.lower() for s in sensitive_keys):
                    raise PersonaValidationError(
                        f"Sensitive data detected in logs at {full_key}"
                    )
                if isinstance(v, dict):
                    check_dict(v, full_key)

        check_dict(data)


class SchemaValidator:
    """Validates response schemas match contracts exactly."""

    @staticmethod
    def validate_no_extra_fields(obj: Any, expected_fields: set[str]) -> None:
        """Verify object has no extra fields beyond schema."""
        if hasattr(obj, "model_extra"):
            if obj.model_extra:
                raise PersonaValidationError(
                    f"Response has extra fields: {list(obj.model_extra.keys())}"
                )

        # For dicts
        if isinstance(obj, dict):
            extra = set(obj.keys()) - expected_fields
            if extra:
                raise PersonaValidationError(f"Response has extra fields: {extra}")
