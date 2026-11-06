"""Application agent: populate a draft from confirmed facts without submission."""

import logging

from langchain_core.language_models.chat_models import BaseChatModel

from agents.base import StructuredGPTAgent
from agents.contracts import (
    ApplicationDraft,
    ApplicationInput,
    ApplicationNarrative,
    ApplicationNarrativeInput,
)

logger = logging.getLogger(__name__)

INSTRUCTIONS = """Prepare a review summary for a draft whose fields were populated
deterministically from confirmed facts. Do not invent, transform, or supply applicant
values. List missing required fields clearly. You cannot approve or submit an
application."""


class ApplicationAgent:
    def __init__(self, model: BaseChatModel) -> None:
        self._narrative = StructuredGPTAgent(
            model,
            ApplicationNarrativeInput,
            ApplicationNarrative,
            INSTRUCTIONS,
        )

    def invoke(self, value: ApplicationInput) -> ApplicationDraft:
        request = ApplicationInput.model_validate(value)
        required_fields = set(request.required_fields)
        if len(required_fields) != len(request.required_fields):
            raise ValueError("Application required_fields must be unique.")

        unknown_fields = set(request.field_mapping) - required_fields
        if unknown_fields:
            raise ValueError(
                "Field mapping contains fields outside the reviewed application "
                f"schema: {', '.join(sorted(unknown_fields))}."
            )

        fields = {
            form_field: request.confirmed_facts[source_field]
            for form_field, source_field in request.field_mapping.items()
            if source_field in request.confirmed_facts
        }
        missing_fields = sorted(required_fields - fields.keys())
        narrative_input = ApplicationNarrativeInput(
            scheme_id=request.scheme_id,
            populated_fields=sorted(fields),
            missing_fields=missing_fields,
        )
        try:
            review_summary = self._narrative.invoke(narrative_input).review_summary
        except Exception:
            logger.warning("Application narrative model failed; using the deterministic summary.")
            review_summary = _deterministic_summary(narrative_input)
        return ApplicationDraft(
            scheme_id=request.scheme_id,
            fields=fields,
            missing_fields=missing_fields,
            review_summary=review_summary,
        )


def _deterministic_summary(value: ApplicationNarrativeInput) -> str:
    """Built from field names only, so it never states an applicant value."""
    summary = f"Draft for scheme {value.scheme_id}: {len(value.populated_fields)} field(s) filled"
    if value.populated_fields:
        summary += " (" + ", ".join(value.populated_fields) + ")"
    if value.missing_fields:
        return summary + ". Missing required: " + ", ".join(value.missing_fields) + ". Not ready for approval."
    return summary + ". All required fields are filled. Please check every value before approving."
