"""Reflection step of the Reflexion loop: extraction errors in, short proposed lessons out.

The scorer (code) names each error; this agent turns one type of error, seen across development
schemes, into at most a few short lessons that say when they apply. Every lesson is only a
proposal: a person approves, edits or rejects it before it reaches the extractor.
"""

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

from agents.base import StructuredGPTAgent

ERROR_MEANINGS = {
    "missing_rule": "the reviewed rules have a condition the extraction left out",
    "extra_rule": "the extraction wrote a rule the reviewed rules don't have",
    "wrong_field": "right clause and comparison, but a different field name",
    "wrong_operator": "right field, wrong comparison (for example lt where the text means lte)",
    "wrong_value": "right field and comparison, wrong value (for example true where it should be false)",
    "wrong_or": "the alternatives (or_conditions) differ from the reviewed rules",
    "wrong_clause": "right rule, but it cites a different source clause",
    "wrong_logic": "rule_logic (all/any) differs",
}

# L3's six slots: role, context, task, constraints, format, examples.
INSTRUCTIONS = """ROLE
You review mistakes made by a rule extractor, which turns the eligibility text of Indian
government schemes into JSON rules (field, op, value, clause_id, or_conditions).

CONTEXT
The input holds one type of error and examples of it from several schemes: the source clause,
the rule a person reviewed and approved ("gold", the right answer) and what the extractor wrote
("draft"). It also lists lessons the extractor already has.

TASK
Write the fewest short lessons that would stop this type of error, at most three. Each lesson
says when it applies and what to do, in one or two sentences, and gives the words in a
scheme's text that signal it applies.

CONSTRAINTS
- A lesson is general: it must not name one scheme, one field or one value unless that field is
  meant to be reused (e.g. "use age, not age_years").
- Base each lesson on the examples; don't add rules of your own.
- Don't repeat an existing lesson. If the examples show no common pattern, return no lessons.
- If a "gold" rule looks wrong to you, say so in doubts instead of writing a lesson against it.

FORMAT
lessons: each with text, applies_when (a short condition), keywords (2-6 lower-case words or
short phrases found in scheme text, or empty if it always applies) and examples (scheme ids it
comes from). doubts: anything a reviewer should look at.

EXAMPLE
Error: wrong_operator. Examples: "age below 60" gold age lt 60, draft age lte 60; "income
below Rs 1 lakh" gold lt, draft lte.
Lesson: "When a limit says 'below' or 'less than', the limit itself is not included: use lt,
not lte." applies_when: "an age or income limit worded 'below' or 'less than'". keywords:
["below", "less than"]."""


class ErrorExample(BaseModel):
    scheme_id: str
    clause: str
    gold: str | None = None
    draft: str | None = None


class ReflectionInput(BaseModel):
    error_type: str
    meaning: str
    examples: list[ErrorExample]
    existing_lessons: list[str] = Field(default_factory=list)


class ProposedLesson(BaseModel):
    text: str
    applies_when: str
    keywords: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)


class Reflection(BaseModel):
    lessons: list[ProposedLesson] = Field(default_factory=list)
    doubts: list[str] = Field(default_factory=list)


class RuleReflector:
    def __init__(self, model: BaseChatModel) -> None:
        self._agent = StructuredGPTAgent(model, ReflectionInput, Reflection, INSTRUCTIONS)

    def reflect(self, value: ReflectionInput | dict) -> Reflection:
        result = self._agent.invoke(ReflectionInput.model_validate(value))
        return result.model_copy(update={"lessons": result.lessons[:3]})
