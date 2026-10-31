"""Intake agent: identify the request and propose facts for user confirmation."""

from langchain_core.language_models.chat_models import BaseChatModel

from agents.base import StructuredGPTAgent
from agents.contracts import IntakeInput, IntakeResult

INSTRUCTIONS = """You are Scheme Saathi's intake specialist.
Identify the user's language and task, extract only directly stated candidate facts,
and ask concise questions only when needed. A candidate fact is not verified or
consented memory. Mark every candidate as requiring user confirmation. Do not ask
for Aadhaar, bank-account numbers, or other sensitive identifiers. Never decide
eligibility or claim that a fact has been saved."""


class IntakeAgent(StructuredGPTAgent[IntakeInput, IntakeResult]):
    def __init__(self, model: BaseChatModel) -> None:
        super().__init__(model, IntakeInput, IntakeResult, INSTRUCTIONS)
