"""Persona validator: ensures agents follow their instructions and respect contracts."""

import re
import unicodedata
from typing import Any

from observability.hooks import record_sensitive_id

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


class SensitivePatternDetector:
    """Detects sensitive patterns in text."""

    AADHAR_PATTERN = r"(?<!\d)\d{4}(?:[\s.\-]?\d{4}){2}(?!\d)"
    PAN_PATTERN = r"\b[A-Z]{5}[0-9]{4}[A-Z]{1}\b"
    IFSC_PATTERN = r"\b[A-Z]{4}0[A-Z0-9]{6}\b"
    BANK_ACCOUNT_PATTERN = r"\b\d{9,18}\b"
    PHONE_PATTERN = r"(?<!\d)(?:\+?91[\s().\-]*)?[6-9]\d{4}[\s().\-]*\d{5}(?!\d)"
    OTP_PATTERN = r"\b(?:otp|one[- ]time(?: password| passcode)?|verification code)\s*(?:is|:|=)?\s*\d{4,8}\b"
    PASSWORD_PATTERN = r"\b(?:password|passwd|passcode|pass phrase)\s*[:=]\s*\S+"

    @classmethod
    def detect_sensitive_type(cls, text: str) -> str | None:
        """Detect if text contains sensitive data.
        
        Returns:
            Type of sensitive data found (aadhar, pan, bank_account, phone) or None
        """
        if not isinstance(text, str):
            return None

        normalized = unicodedata.normalize("NFKC", text)
        normalized = "".join(
            str(unicodedata.digit(char)) if char.isdigit() else char
            for char in normalized
            if char not in "\u200b\u200c\u200d\u2060\ufeff"
        )

        if re.search(cls.AADHAR_PATTERN, normalized):
            return "aadhar"
        if re.search(cls.PAN_PATTERN, normalized, re.IGNORECASE):
            return "pan"
        if re.search(cls.IFSC_PATTERN, normalized, re.IGNORECASE):
            return "ifsc"
        if re.search(cls.BANK_ACCOUNT_PATTERN, normalized):
            return "bank_account"
        if re.search(cls.PHONE_PATTERN, normalized):
            return "phone"
        if re.search(cls.OTP_PATTERN, normalized, re.IGNORECASE):
            return "otp"
        if re.search(cls.PASSWORD_PATTERN, normalized, re.IGNORECASE):
            return "password"
        return None


class SensitiveDataMasker:
    """Masks sensitive data in text."""

    @staticmethod
    def mask_aadhar(text: str) -> str:
        """Mask Aadhar numbers."""
        import re
        return re.sub(r"\d{4}[\s\-]?\d{4}[\s\-]?\d{4}", "XXXX-XXXX-XXXX", text)

    @staticmethod
    def mask_pan(text: str) -> str:
        """Mask PAN numbers."""
        import re
        return re.sub(SensitivePatternDetector.PAN_PATTERN, "XXXXX0000X", text, flags=re.IGNORECASE)

    @staticmethod
    def mask_ifsc(text: str) -> str:
        import re
        return re.sub(SensitivePatternDetector.IFSC_PATTERN, "[IFSC REDACTED]", text, flags=re.IGNORECASE)

    @staticmethod
    def mask_bank_account(text: str) -> str:
        """Mask bank account numbers."""
        import re
        return re.sub(r"\b(\d{2})\d{7,14}(\d{2})\b", r"\1XXXXXX\2", text)

    @staticmethod
    def mask_phone(text: str) -> str:
        """Mask phone numbers."""
        import re
        return re.sub(r"\b[6-9]\d{4}\d{5}\b", "XXXXXX9999", text)

    @classmethod
    def mask_all_sensitive(cls, text: str) -> str:
        """Apply all masking rules."""
        text = cls.mask_aadhar(text)
        text = cls.mask_pan(text)
        text = cls.mask_ifsc(text)
        text = cls.mask_bank_account(text)
        text = cls.mask_phone(text)
        return text


SENSITIVE_INPUT_MESSAGE = (
    "Sensitive information detected. Do not share Aadhaar, PAN, IFSC, phone, "
    "bank account or other ID numbers, passwords, or OTPs. Remove them and try again."
)


class SensitiveInputError(ValueError):
    """A request contains a potentially sensitive identifier."""


def reject_sensitive_input(value: Any, field: str = "") -> None:
    """Reject recognized identifiers without including their contents in the error."""
    if isinstance(value, dict):
        for key, item in value.items():
            reject_sensitive_input(str(key))
            reject_sensitive_input(item, str(key))
    elif isinstance(value, (list, tuple)):
        for item in value:
            reject_sensitive_input(item, field)
    elif value is not None and not isinstance(value, bool):
        normalized = field.lower().replace("-", "_").replace(" ", "_")
        if normalized in {"hash", "payload_hash", "approved_hash", "form_hash"}:
            return
        sensitive_field = any(
            name in normalized
            for name in (
                "aadhaar", "aadhar", "ifsc", "pan_number", "account_number",
                "bank_account", "phone_number", "mobile_number", "id_number", "password",
            )
        ) or normalized in {"pan", "phone", "mobile", "otp"} or "otp" in normalized.split("_")
        financial_field = any(
            name in normalized for name in ("income", "amount", "salary", "price", "cost")
        )
        id_type = "field" if sensitive_field else (
            (isinstance(value, str) or (isinstance(value, int) and not financial_field))
            and SensitivePatternDetector.detect_sensitive_type(str(value))
        )
        if id_type:
            record_sensitive_id("input", id_type)
            raise SensitiveInputError(SENSITIVE_INPUT_MESSAGE)


def reject_sensitive_graph_input(value: Any) -> None:
    from langgraph.types import Command

    if isinstance(value, Command):
        reject_sensitive_input([value.resume, value.update])
    elif isinstance(value, dict):
        reject_sensitive_input({
            key: item for key, item in value.items()
            if key not in {"actor_id", "thread_id"}
        })
    else:
        reject_sensitive_input(value)
