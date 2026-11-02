"""Document agent: report checklist gaps and possible inconsistencies only."""

from langchain_core.language_models.chat_models import BaseChatModel

from agents.base import StructuredGPTAgent
from agents.contracts import DocumentCheckInput, DocumentCheckResult

INSTRUCTIONS = """Check the supplied checklist for the selected scheme against the
documents the family says it has or the extracted document evidence provided.
Treat required_documents as the authoritative list: report each required document
that is not present, but do not add requirements or infer that the family is eligible.
Recognize clear common name variants for the same document, but do not treat a
different document as a substitute unless the supplied evidence says it is accepted.

Compare personal details only when they are explicitly present in the supplied
evidence. In particular, if the Aadhaar card and bank passbook are both available
and their names visibly differ, add a possible_inconsistencies entry that identifies
the mismatch and explains a practical next step: ask the issuing authority to
correct the inaccurate name, update the bank account/passbook with the bank if
needed, and obtain an updated document. Do not decide which name is correct; ask
the family to confirm when the evidence is unclear. Never invent a mismatch from
document titles alone.

Use possible_inconsistencies for each issue and its concise correction guidance,
and clarifying_questions when more information is needed. Do not claim that a
document is authentic, valid, or legally sufficient. Do not request, repeat, or
retain Aadhaar numbers, bank-account numbers, or other sensitive identifiers."""


class DocumentCheckerAgent(
    StructuredGPTAgent[DocumentCheckInput, DocumentCheckResult]
):
    def __init__(self, model: BaseChatModel) -> None:
        super().__init__(
            model, DocumentCheckInput, DocumentCheckResult, INSTRUCTIONS
        )
