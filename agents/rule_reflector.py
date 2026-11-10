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
Find the patterns behind these mistakes: what in the clause's wording led the extractor
wrong. Write one lesson per pattern seen in at least two schemes, at most three lessons. Each
lesson names the wording that triggers it and the exact rule to write (or not to write).

CONSTRAINTS
- Concrete, never generic. A lesson must quote or describe the triggering wording ("is
  eligible only in subsequent years", "receive priority", "State/UT Government") and say
  exactly what to do with it ("write no rule", "write field eq false", "one rule with
  or_conditions"). Lessons that only say "ensure", "make sure", "accurately", "correctly" or
  "use the right field" are useless: don't write them.
- General across schemes: don't name one scheme. Name a field only if it should always be
  reused for that meaning (e.g. "use age for a person's age, never for pregnancy weeks").
- Base each lesson on the examples; don't add conventions of your own.
- Two lessons must never contradict each other or an existing lesson. Don't repeat an
  existing lesson. If no pattern repeats across schemes, return no lessons.
- keywords are specific words or phrases from the example clauses that signal the lesson
  applies ("priority", "terminate", "panchayat"), never common words ("or", "is", "must",
  "all", "not", "eligible", "applicant"). Use an empty list only for a lesson that truly
  applies to every scheme.
- If a "gold" rule looks wrong to you, say so in doubts, naming the scheme and clause, instead
  of writing a lesson against it. Leave doubts empty otherwise.

FORMAT
lessons: each with text, applies_when (a short condition), keywords (2-6 lower-case words or
short phrases found in scheme text, or empty if it always applies) and examples (scheme ids it
comes from). doubts: anything a reviewer should look at.

EXAMPLES (the shape of a good lesson; these errors are illustrations, not from your input)
Error: wrong_operator. Examples: "age below 60" gold age lt 60, draft age lte 60; "income
below Rs 1 lakh" gold lt, draft lte.
Bad lesson: "Make sure the right operator is used for limits." (generic)
Good lesson: "When a limit says 'below' or 'less than', the limit itself is not included: use
lt, not lte." applies_when: "an age or income limit worded 'below' or 'less than'".
keywords: ["below", "less than"].

Error: missing_rule. Examples: "aged 18 to 40 years" gold age gte 18 and age lte 40, draft only
age gte 18; "between 21 and 60 years" the same.
Good lesson: "When a scheme gives an age range ('18 to 40', 'between 21 and 60'), write two
rules, one for each end, and include both ends unless the text says otherwise."
applies_when: "an age range". keywords: ["between", "years of age", "age group"]."""


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
