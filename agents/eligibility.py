"""Eligibility agent: explain deterministic rule-engine results without changing them."""

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
