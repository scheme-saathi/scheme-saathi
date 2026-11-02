"""Application agent: populate a draft from confirmed facts without submission."""

from langchain_core.language_models.chat_models import BaseChatModel

from agents.base import StructuredGPTAgent
from agents.contracts import (
    ApplicationDraft,
    ApplicationInput,
    ApplicationNarrative,
    ApplicationNarrativeInput,
)

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
        narrative = self._narrative.invoke(
            ApplicationNarrativeInput(
                scheme_id=request.scheme_id,
                populated_fields=sorted(fields),
                missing_fields=missing_fields,
            )
        )
        return ApplicationDraft(
            scheme_id=request.scheme_id,
            fields=fields,
            missing_fields=missing_fields,
            review_summary=narrative.review_summary,
        )
