"""Eligibility agent: explain deterministic rule-engine results without changing them."""

from collections.abc import Mapping

from langchain_core.language_models.chat_models import BaseChatModel

from agents.base import StructuredGPTAgent
from agents.contracts import EligibilityInput, EligibilityNarrative

INSTRUCTIONS = """You explain a result produced by Scheme Saathi's deterministic rule
engine. Preserve its verdict, missing fields, unresolved fields, and citations exactly.
Do not infer eligibility from prose, add rules, or invent citations. Ask only questions
that could resolve a missing or invalid rule field."""


class EligibilityAgent(StructuredGPTAgent[EligibilityInput, EligibilityNarrative]):
    def __init__(self, model: BaseChatModel) -> None:
        super().__init__(
            model, EligibilityInput, EligibilityNarrative, INSTRUCTIONS
        )

    def _build_deterministic_narrative(self, evaluation: Mapping[str, object]) -> EligibilityNarrative:
        verdict = str(evaluation.get("verdict", "cant_tell")).lower()
        reason = str(evaluation.get("reason") or "No rule-based reason was supplied.")
        missing_fields = evaluation.get("missing_fields") or []
        unresolved_fields = evaluation.get("unresolved_fields") or []
        citations = evaluation.get("citations") or []

        parts: list[str] = [f"{verdict}: {reason}"]

        required_fields = [
            item for item in list(missing_fields) + list(unresolved_fields) if item not in (None, "")
        ]
        if required_fields:
            parts.append(
                "Missing or unresolved fields: " + ", ".join(str(item) for item in required_fields)
            )

        if citations:
            citation_summary = "; ".join(
                str(c.get("quote") or c.get("text") or c.get("clause_id") or "citation")
                for c in citations
                if isinstance(c, Mapping)
            )
            if citation_summary:
                parts.append(f"Rule citations: {citation_summary}")

        explanation = " ".join(parts)
        clarifying_questions = [
            f"Please confirm the value for '{field}' before deciding this scheme."
            for field in required_fields
        ]
        return EligibilityNarrative(
            explanation=explanation,
            clarifying_questions=clarifying_questions,
        )

    def invoke(self, value: EligibilityInput | dict) -> EligibilityNarrative:
        request = EligibilityInput.model_validate(value)
        evaluation = request.evaluation
        if evaluation:
            return self._build_deterministic_narrative(evaluation)
        return super().invoke(request)
