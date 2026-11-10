"""Rule extractor: a scheme's eligibility text in, draft JSON rules out (signature challenge A).

Its output is always a draft. Extracted rules never go live without a person reviewing them
(data/rules/REVIEW_STATUS.md), and they never decide eligibility: the rule engine does, from
reviewed rules only. The Reflexion loop improves this agent through reviewed lessons.
"""

from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

from agents.base import StructuredGPTAgent

Operator = Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in"]
Value = bool | float | str | list[str]

# The prompt in L3's six slots: role, context, task, constraints, format, examples.
# {lessons} is filled from the playbook: reviewed lessons relevant to this scheme, or nothing.
INSTRUCTIONS = """ROLE
You turn the eligibility section of an Indian government scheme into machine-readable rules.
You never decide whether anyone is eligible; a rule engine evaluates your rules later, and a
person reviews them before they are used.

CONTEXT
The input holds the scheme's name and its source clauses, each with a clause_id (elig-N for
eligibility sentences, excl-N for exclusions), and the shared field list: the profile fields
already in use, with their type and the values rules compare against.

TASK
Write one rule for each condition a person must meet to be eligible. An exclusion ("X is not
eligible") becomes a rule that the person is not X. Cite the clause each rule comes from.

CONSTRAINTS
- Use a field from the field list when one means the same thing; use its listed values.
  Only if none fits, make a new snake_case field name that says exactly what it asks.
- A range is two rules, one for each end (e.g. age gte 18 and age lte 40).
- "below"/"less than" is lt; "up to"/"not more than"/"maximum" is lte; "above"/"more than" is
  gt; "at least"/"minimum" is gte.
- When a condition can be met in more than one way ("BPL card OR income up to Rs 21,000"),
  write one rule whose or_conditions hold the other ways.
- Amounts are rupees as plain numbers (Rs 1,20,000 is 120000).
- rule_logic is "all" when every rule must hold, "any" when one is enough.
- Skip headings, documents to submit, benefits, preferences and priority lists.
- Do not invent conditions the text does not state. List anything unclear in open_questions.
{lessons}
FORMAT
Return rules, rule_logic and open_questions. Each rule has field, op (eq, ne, gt, gte, lt,
lte, in, not_in), value (true/false, a number, a string, or a list of strings for in/not_in),
clause_id, and optional or_conditions (each with field, op, value, clause_id).

EXAMPLE
Clauses: elig-1 "The applicant should be a resident of the state."; elig-2 "Age between 21
and 60 years."; elig-3 "Family income below Rs 50,000 or holding an Antyodaya card.";
excl-1 "Income tax payers are not eligible."
Rules: is_state_resident eq true (elig-1); age gte 21 (elig-2); age lte 60 (elig-2);
annual_family_income lt 50000 (elig-3) with or_conditions [ration_card_type eq "antyodaya"
(elig-3)]; is_income_tax_payer eq false (excl-1). rule_logic: all."""

LESSONS_HEADER = "\nLESSONS FROM REVIEWED EXTRACTIONS (apply each only when its condition holds)\n"


class SourceClause(BaseModel):
    clause_id: str
    text: str


class FieldOption(BaseModel):
    field: str
    type: Literal["bool", "number", "str"]
    known_values: list[str] = Field(default_factory=list)


class ExtractionInput(BaseModel):
    scheme_id: str
    name: str
    clauses: list[SourceClause]
    fields: list[FieldOption]


class ExtractedCondition(BaseModel):
    field: str
    op: Operator
    value: Value
    clause_id: str


class ExtractedRule(ExtractedCondition):
    or_conditions: list[ExtractedCondition] = Field(default_factory=list)


class Extraction(BaseModel):
    rules: list[ExtractedRule]
    rule_logic: Literal["all", "any"] = "all"
    open_questions: list[str] = Field(default_factory=list)


def instructions_with(lessons: list[str]) -> str:
    """The extractor's instructions with the given reviewed lessons in their slot."""
    # The prompt is a template: braces in a lesson would read as a variable, so they are escaped.
    safe = [text.replace("{", "{{").replace("}", "}}") for text in lessons]
    block = (LESSONS_HEADER + "\n".join(f"- {text}" for text in safe) + "\n") if safe else ""
    return INSTRUCTIONS.replace("{lessons}", block)


class RuleExtractor:
    """One extraction per call; the lessons can differ per scheme, so the prompt is built per call."""

    def __init__(self, model: BaseChatModel) -> None:
        self._model = model

    def extract(self, value: ExtractionInput | dict, lessons: list[str] | None = None) -> Extraction:
        agent = StructuredGPTAgent(self._model, ExtractionInput, Extraction, instructions_with(lessons or []))
        return agent.invoke(ExtractionInput.model_validate(value))
