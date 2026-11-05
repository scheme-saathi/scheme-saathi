"""Intake agent: build a typed household profile and phrase one question at a time.

The agent never chooses what to ask: the graph picks the field that settles the most
open verdicts (graph.tools.next_question). The model only reads facts from the message
and words the question.
"""

from typing import Annotated, Any, Literal

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from agents.base import StructuredGPTAgent, untrusted_prompt
from agents.contracts import (
    IntakeAskInput,
    IntakeExtraction,
    IntakeExtractInput,
    IntakeInput,
    IntakeQuestion,
    IntakeQuestionText,
    IntakeResult,
)

INSTRUCTIONS = """You are Scheme Saathi's intake specialist.
Identify the user's language and task, extract only directly stated candidate facts,
and ask concise questions only when needed. A candidate fact is not verified or
consented memory. Mark every candidate as requiring user confirmation. Do not ask
for Aadhaar, bank-account numbers, or other sensitive identifiers. Never decide
eligibility or claim that a fact has been saved."""

EXTRACT_INSTRUCTIONS = """You are Scheme Saathi's intake specialist. Fill the household
profile only with facts the user states directly in the request; leave every other field
null and never guess. When pending_field is set, read a short reply such as "yes" or
"1 lakh" as the answer to pending_question, which asked for that field. Values must match
each field's type. For an income field, give the amount in rupees exactly as the user said
it (1 lakh = 100000, 15 hazaar = 15000, 10k = 10000) and its period: "month" or "year" when
the user says so or pending_question asked for that period, otherwise "unstated". Never
convert between periods or multiply by 12; that is done for you. Classify the reply to
pending_question in reply_kind. Never record Aadhaar, bank-account numbers or other sensitive
identifiers. Never decide eligibility or claim that a fact has been saved."""

ASK_INSTRUCTIONS = """You write the next question for Scheme Saathi's intake. Ask exactly
one short, polite question that collects only the given field. Write it in the given
language (en English, hi Hindi, mr Marathi); if it is unknown, use the language of the
request. Refer to the person the way the request does (for example "she" for a mother).
For a bool field, ask a yes/no question. When period is given, ask for the amount per that
period ("per month" or "per year") and say so in the question. Do not mention eligibility, schemes, rules or
field names, and never ask for Aadhaar, bank-account numbers or other sensitive
identifiers."""

_FIELD_TYPES = {"number": int | float, "bool": bool, "str": str}

# A forced choice with examples: as a plain dont_know flag, the model set it for "hmm" and "hello".
ReplyKind = Annotated[
    Literal["answer", "dont_know", "other"],
    Field(
        description='"answer": the request gives a value for pending_field. "dont_know": the user '
        'says they do not know it or will not say it ("I don\'t know", "pata nahi", "not sure"). '
        '"other": anything else, such as "hmm", "ok", a greeting or a different question; '
        'also use "other" when there is no pending_field.'
    ),
]


class Amount(BaseModel):
    """An income as the user said it. Code, not the model, converts it to the field's period."""

    model_config = ConfigDict(extra="forbid", strict=True)
    amount: int | float = Field(ge=0, description="Rupees, exactly as said.")
    period: Literal["month", "year", "unstated"]


def income_period(field: str) -> Literal["month", "year"] | None:
    """The period an income rule field is measured in; None for other fields."""
    # shortcut: read from the field name, upgrade when rule records carry units.
    if "income" not in field:
        return None
    return "month" if "monthly" in field else "year"


def to_field_period(field: str, amount: Amount, pending_field: str | None) -> int | float | None:
    """The amount in the field's own period, or None when the period would be a guess."""
    own = income_period(field)
    said = amount.period
    if said == "unstated":
        if field != pending_field:  # no question of ours set the period
            return None
        said = own  # our questions ask in the field's own period
    if said == own:
        return amount.amount
    return amount.amount * 12 if own == "year" else amount.amount / 12


def profile_model(specs: dict[str, dict[str, Any]]) -> type[BaseModel]:
    """A typed household profile with exactly the rule fields in ``specs`` (from get_field_specs).

    Strict: the rule engine never coerces, so "67" for age must be rejected here, not stored.
    Income fields hold an ``Amount``; ``to_field_period`` turns it into the stored number.
    """
    fields = {}
    for name, spec in specs.items():
        hint = f" Known values: {', '.join(spec['known_values'])}." if spec.get("known_values") else ""
        kind = Amount if spec["type"] == "number" and income_period(name) else _FIELD_TYPES[spec["type"]]
        fields[name] = (kind | None, Field(None, description=f"{spec['type']}.{hint}"))
    return create_model("HouseholdProfile", __config__=ConfigDict(extra="forbid", strict=True), **fields)


class IntakeAgent(StructuredGPTAgent[IntakeInput, IntakeResult]):
    def __init__(self, model: BaseChatModel) -> None:
        super().__init__(model, IntakeInput, IntakeResult, INSTRUCTIONS)
        self._asker = StructuredGPTAgent(model, IntakeAskInput, IntakeQuestionText, ASK_INSTRUCTIONS)

    def extract(self, value: IntakeExtractInput | dict, specs: dict[str, dict[str, Any]]) -> IntakeExtraction:
        """Typed facts from the message. Each field is checked on its own, so one bad value
        is dropped without losing the rest."""
        request = IntakeExtractInput.model_validate(value)
        profile = profile_model(specs)
        output = create_model("IntakeExtractionOutput", facts=(profile, ...), reply_kind=(ReplyKind, "other"))
        # A JSON schema, not the model class: the reply comes back as a dict and is validated below.
        chain = untrusted_prompt(EXTRACT_INSTRUCTIONS) | self._model.with_structured_output(
            output.model_json_schema()
        )
        raw = chain.invoke({"payload": request.model_dump_json(exclude_none=True)}) or {}

        facts: dict[str, Any] = {}
        rejected: list[str] = []
        pending = request.pending_field
        for field, fact in (raw.get("facts") or {}).items():
            if fact is None:
                continue
            try:
                value = getattr(profile.model_validate({field: fact}), field)
            except ValidationError:
                rejected.append(field)
                continue
            if isinstance(value, Amount):
                value = to_field_period(field, value, pending)
                if value is None:
                    rejected.append(field)
                    continue
            facts[field] = value
        dont_know = raw.get("reply_kind") == "dont_know" and pending is not None and pending not in facts
        return IntakeExtraction(facts=facts, rejected_fields=rejected, dont_know=dont_know)

    def ask(self, value: IntakeAskInput | dict) -> IntakeQuestion:
        """One question for one field; the field comes from the caller, never from the model."""
        request = IntakeAskInput.model_validate(value)
        return IntakeQuestion(field=request.field, question=self._asker.invoke(request).question)
