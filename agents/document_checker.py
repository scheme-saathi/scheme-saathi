"""Document agent: report checklist gaps and possible inconsistencies only."""

from langchain_core.language_models.chat_models import BaseChatModel

from agents.base import StructuredGPTAgent
from agents.contracts import DocumentCheckInput, DocumentCheckResult

INSTRUCTIONS = """Compare the supplied document checklist with the supplied document
names or extracted evidence. Report possible gaps and inconsistencies, and ask for
confirmation when evidence is ambiguous. Do not claim that a document is authentic,
valid, or legally sufficient. Do not retain or request raw identity numbers."""


class DocumentCheckerAgent(
    StructuredGPTAgent[DocumentCheckInput, DocumentCheckResult]
):
    def __init__(self, model: BaseChatModel) -> None:
        super().__init__(
            model, DocumentCheckInput, DocumentCheckResult, INSTRUCTIONS
        )
