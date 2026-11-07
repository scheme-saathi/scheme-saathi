"""Typed contracts shared by the GPT agents and their orchestrator."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

Language = Literal["en", "hi", "mr", "unknown"]
Intent = Literal["discover", "eligibility", "documents", "application", "follow_up", "other"]
Route = Literal["intake", "eligibility", "document_checker", "application", "respond"]
FactMap = dict[str, JsonValue]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IntakeInput(Contract):
    request: str = Field(min_length=1)
    known_facts: FactMap = Field(default_factory=dict)


class CandidateFact(Contract):
    field: str = Field(min_length=1)
    value: str | int | float | bool | None
    confidence: Literal["high", "medium", "low"]
    requires_confirmation: Literal[True] = True


class IntakeResult(Contract):
    language: Language
    intent: Intent
    candidate_facts: list[CandidateFact] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)


class IntakeExtractInput(Contract):
    # No earlier facts: given them, the model restates them and re-applies conversions
    # (monthly income x12 a second time). The graph merges new facts into known_facts.
    request: str = Field(min_length=1)
    pending_field: str | None = None  # the field the last question asked for
    pending_question: str | None = None  # its wording, so "8000" is read in the period it asked


class IntakeExtraction(Contract):
    facts: FactMap = Field(default_factory=dict)  # typed rule-field values; unconfirmed
    rejected_fields: list[str] = Field(default_factory=list)
    dont_know: bool = False  # the user can't or won't answer pending_field


class IntakeAskInput(Contract):
    field: str = Field(min_length=1)
    field_type: Literal["number", "bool", "str"]
    known_values: list[str] = Field(default_factory=list)
    period: Literal["month", "year"] | None = None  # for income fields: ask per this period
    language: Language = "unknown"
    request: str = Field(min_length=1)  # the message that started intake, so "she" stays "she"


class SchemeOption(Contract):
    scheme_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""


class SchemeChoiceInput(Contract):
    request: str = Field(min_length=1)
    schemes: list[SchemeOption]


class SchemeChoice(Contract):
    scheme_ids: list[str] = Field(default_factory=list)


class IntakeQuestionText(Contract):
    question: str = Field(min_length=1)


class IntakeQuestion(Contract):
    field: str = Field(min_length=1)
    question: str = Field(min_length=1)


class EvidencePassage(Contract):
    id: str = Field(min_length=1)
    scheme_id: str
    text: str


class IntakeAnswerInput(Contract):
    question: str = Field(min_length=1)
    language: Language = "unknown"
    passages: list[EvidencePassage] = Field(min_length=1)


class IntakeAnswer(Contract):
    found: bool
    answer: str = ""
    cited_passage_ids: list[str] = Field(default_factory=list)


class DocumentCheckInput(Contract):
    scheme_id: str = Field(min_length=1)
    required_documents: list[str] = Field(default_factory=list)
    available_documents: list[str] = Field(default_factory=list)
    household_persona: FactMap = Field(default_factory=dict)


class DocumentCheckResult(Contract):
    missing_documents: list[str] = Field(default_factory=list)
    possible_inconsistencies: list[str] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)
    authenticity_verified: Literal[False] = False


class SupervisorInput(Contract):
    request: str = Field(min_length=1)
    intake: IntakeResult | None = None  # Optional: None on first call, populated after Intake runs
    selected_scheme_id: str | None = None
    document_check: DocumentCheckResult | None = None


class SupervisorPlan(Contract):
    next_agent: Route
    reason: str = Field(min_length=1)
    scheme_question: bool = Field(
        False,
        description="True when the user asks a factual question about a scheme (benefits, age or "
        "income limits, how to apply) without asking to check their own eligibility. Route it to respond.",
    )
    language: Language = Field(
        "unknown",
        description="Language of the user's message; replies use it. Hindi and Marathi both use "
        "Devanagari: Marathi has words like आहे, माझी, आणि, काय; Hindi has है, मेरी, और, क्या.",
    )


class EligibilityInput(Contract):
    scheme_id: str = Field(min_length=1)
    evaluation: FactMap


class EligibilityNarrative(Contract):
    explanation: str = Field(min_length=1)
    clarifying_questions: list[str] = Field(default_factory=list)


class ApplicationInput(Contract):
    scheme_id: str = Field(min_length=1)
    confirmed_facts: FactMap
    required_fields: list[str]
    field_mapping: dict[str, str]


class ApplicationNarrativeInput(Contract):
    scheme_id: str
    populated_fields: list[str]
    missing_fields: list[str]


class ApplicationNarrative(Contract):
    review_summary: str = Field(min_length=1)


class ApplicationDraft(Contract):
    scheme_id: str
    fields: FactMap
    missing_fields: list[str]
    review_summary: str
