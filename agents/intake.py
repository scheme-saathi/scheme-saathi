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
    IntakeAnswer,
    IntakeAnswerInput,
    IntakeAskInput,
    IntakeExtraction,
    IntakeExtractInput,
    IntakeInput,
    IntakeQuestion,
    IntakeQuestionText,
    IntakeResult,
    SchemeChoice,
    SchemeChoiceInput,
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
pending_question in reply_kind. Set subject to "other" when the request is about someone
else (your mother, a neighbour, a client) or when it is unclear whose facts these are, and
"self" only when the user clearly speaks about themselves. For "other", give relation as one
lowercase word such as "mother" or "neighbour"; never a name or a number. For "self", relation
is null. Never record Aadhaar, bank-account numbers or other sensitive
identifiers. Never decide eligibility or claim that a fact has been saved."""

ASK_INSTRUCTIONS = """You write the next question for Scheme Saathi's intake. Ask exactly
one short, polite question that collects only the given field. Write it in the given
language (en English, hi Hindi, mr Marathi); if it is unknown, use the language of the
request. Keep the question gender neutral: never use he, she, him, her, his or hers. Use
"you" when the request is about the user, and the relation the request names when it is
about someone else ("your mother", "your son"). Any amount is in Indian rupees: write it
with ₹ or "rupees", never $ or another currency.
Never show the raw field name; say in everyday words what it means, keeping every part of
it (social_category is "social (caste) category", not just "category").
For a bool field, ask a yes/no question. For a number field, ask for one number and name its
unit (years, rupees, people). For a str field, never ask a yes/no question: when
known_values are given, list them as the choices in plain words and let the person say
another answer. For a date field, ask for the full date in DD/MM/YYYY form (for example 05/03/1962). When period is given, ask for the amount per that
period ("per month" or "per year") and say so in the question. Do not mention eligibility, schemes or
rules, and never ask for Aadhaar, bank-account numbers or other sensitive
identifiers."""

ANSWER_INSTRUCTIONS = """You answer a question about Indian government schemes using only the
given passages, never outside knowledge. Set found to false when the passages do not answer the
question. When found, write a short answer in the given language (en English, hi Hindi, mr Marathi;
if it is unknown, use the language of the question) and put the id of every passage you used in
cited_passage_ids. Say what the scheme documents state, in general terms ("The scheme is for widows
aged 40 to 79 from BPL households"). Never say whether the user or anyone they mention qualifies:
do not answer yes or no about them, and do not write "you can get", "she is eligible" or similar.
If the question is about their own eligibility, state the scheme's conditions and add that Scheme
Saathi can check their eligibility step by step. Never ask for Aadhaar, bank-account numbers or
other sensitive identifiers."""

CHOOSE_INSTRUCTIONS = """You pick which government schemes are worth checking for a person.
Given the person's request and a list of schemes (scheme_id, name, description), return the
scheme_ids of the schemes that plausibly fit what the person describes or asks about (their
occupation, age, gender, family, need). known_facts holds what the person has already answered
(field: value); use it together with the request. Return only ids from the list, best fit first, at most
8. Return an empty list when none fit. You never decide eligibility; rules do that later."""

_FIELD_TYPES = {"number": int | float, "bool": bool, "str": str,
                # The rule engine works ages out of this date, so it must be a real ISO date.
                "date": Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]}

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
        if spec["type"] == "date":
            # Indian users write the day first: without this a model may read 05/03/1962 as 3 May.
            hint = (" The person writes dates day first (DD/MM/YYYY, as in India): 05/03/1962 is"
                    " 5 March 1962. Write it as YYYY-MM-DD (1962-03-05); leave it empty if the day,"
                    " month or year is missing.")
        kind = Amount if spec["type"] == "number" and income_period(name) else _FIELD_TYPES[spec["type"]]
        fields[name] = (kind | None, Field(None, description=f"{spec['type']}.{hint}"))
    return create_model("HouseholdProfile", __config__=ConfigDict(extra="forbid", strict=True), **fields)


class IntakeAgent(StructuredGPTAgent[IntakeInput, IntakeResult]):
    def __init__(self, model: BaseChatModel) -> None:
        super().__init__(model, IntakeInput, IntakeResult, INSTRUCTIONS)
        self._asker = StructuredGPTAgent(model, IntakeAskInput, IntakeQuestionText, ASK_INSTRUCTIONS)
        self._answerer = StructuredGPTAgent(model, IntakeAnswerInput, IntakeAnswer, ANSWER_INSTRUCTIONS)
        self._chooser = StructuredGPTAgent(model, SchemeChoiceInput, SchemeChoice, CHOOSE_INSTRUCTIONS)

    def choose_schemes(self, value: SchemeChoiceInput | dict) -> list[str]:
        """Schemes worth checking for this person, best fit first. Ids outside the list are dropped."""
        request = SchemeChoiceInput.model_validate(value)
        allowed = {option.scheme_id for option in request.schemes}
        chosen = self._chooser.invoke(request).scheme_ids
        return [scheme_id for scheme_id in dict.fromkeys(chosen) if scheme_id in allowed]

    def extract(self, value: IntakeExtractInput | dict, specs: dict[str, dict[str, Any]]) -> IntakeExtraction:
        """Typed facts from the message. Each field is checked on its own, so one bad value
        is dropped without losing the rest."""
        request = IntakeExtractInput.model_validate(value)
        result = self._extract_once(request, specs)
        pending = request.pending_field
        if pending in specs and pending not in result.facts and len(specs) > 1:
            # Against a wide schema the model read a bare "No" as dont_know; one field alone it reads reliably.
            narrow = self._extract_once(request, {pending: specs[pending]})
            result = IntakeExtraction(
                facts={**result.facts, **narrow.facts},
                rejected_fields=result.rejected_fields + narrow.rejected_fields,
                dont_know=narrow.dont_know,
                subject=result.subject,
                relation=result.relation,
            )
        return result

    def _extract_once(self, request: IntakeExtractInput, specs: dict[str, dict[str, Any]]) -> IntakeExtraction:
        profile = profile_model(specs)
        output = create_model(
            "IntakeExtractionOutput",
            facts=(profile, ...),
            reply_kind=(ReplyKind, "other"),
            subject=(Literal["self", "other"], ...),
            relation=(str | None, None),
        )
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
        # A missing or unrecognised subject counts as someone else, so nothing is remembered by mistake.
        subject = raw.get("subject") if raw.get("subject") in ("self", "other") else "other"
        relation = raw.get("relation") if isinstance(raw.get("relation"), str) else None
        return IntakeExtraction(
            facts=facts,
            rejected_fields=rejected,
            dont_know=dont_know,
            subject=subject,
            relation=relation,
        )

    def ask(self, value: IntakeAskInput | dict) -> IntakeQuestion:
        """One question for one field; the field comes from the caller, never from the model."""
        request = IntakeAskInput.model_validate(value)
        return IntakeQuestion(field=request.field, question=self._asker.invoke(request).question)

    def answer(self, value: IntakeAnswerInput | dict) -> IntakeAnswer:
        """A cited answer from the given passages. A citation outside them voids the answer."""
        request = IntakeAnswerInput.model_validate(value)
        result = self._answerer.invoke(request)
        cited = set(result.cited_passage_ids)
        if not (result.found and result.answer.strip() and cited) or not cited <= {p.id for p in request.passages}:
            return IntakeAnswer(found=False)
        return result
