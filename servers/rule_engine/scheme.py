"""Validated, clause-linked rule records used by the eligibility evaluator."""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Text fields shared across schemes have one list of values (decision F2), so rules agree on spelling.
SHARED_VALUES: dict[str, list[str]] = {
    field: values
    for field, values in json.loads(
        (Path(__file__).resolve().parents[2] / "data" / "field_values.json").read_text(encoding="utf-8")
    ).items()
    if not field.startswith("_")
}


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(Record):
    url: str = Field(min_length=1)
    collected_on: str = Field(min_length=1)


class Clause(Record):
    clause_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)


Operator = Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in"]


def _check_operand(op: str, value: Any) -> None:
    if op in {"in", "not_in"}:
        if not isinstance(value, list) or not value:
            raise ValueError(f"{op} requires a non-empty list value")
        value_types = {type(item) for item in value}
        if len(value_types) != 1 or type(None) in value_types:
            raise ValueError("membership values must have one consistent, non-null type")
    elif isinstance(value, (dict, list, tuple, set)) or value is None:
        raise ValueError("comparison value must be a non-null scalar")
    if op in {"gt", "gte", "lt", "lte"} and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        raise ValueError(f"{op} requires a numeric value")


class Condition(Record):
    """One comparison of a profile field. An alternative may cite its own clause."""

    field: str = Field(min_length=1)
    op: Operator
    value: Any
    clause_id: str | None = None

    @model_validator(mode="after")
    def validate_operand(self) -> "Condition":
        _check_operand(self.op, self.value)
        return self


class Rule(Record):
    field: str = Field(min_length=1)
    op: Operator
    value: Any
    clause_id: str = Field(min_length=1)
    status: Literal["reviewed", "draft"] = "draft"
    # The rule also passes when any of these alternatives holds: one level of OR inside a
    # scheme, so code (not a model) decides clauses like "BPL card OR income <= 21,000".
    or_conditions: list[Condition] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_operand(self) -> "Rule":
        _check_operand(self.op, self.value)
        return self

    def conditions(self) -> list[Condition]:
        """The rule's own condition followed by its alternatives, each with a clause."""
        own = Condition(field=self.field, op=self.op, value=self.value, clause_id=self.clause_id)
        return [own, *(c.model_copy(update={"clause_id": c.clause_id or self.clause_id}) for c in self.or_conditions)]


class SchemeRecord(Record):
    scheme_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    level: str = Field(min_length=1)
    state: str | None = None
    source: Source
    clauses: list[Clause] = Field(min_length=1)
    documents_required: list[str] = Field(default_factory=list)
    rules: list[Rule] = Field(default_factory=list)
    # Flat rule lists are combined using one connective. Mixed/nested expressions
    # can be added when a reviewed scheme actually requires them.
    rule_logic: Literal["all", "any"] = "all"
    # Decision F1: schemes for organisations are left out of the citizen scheme list.
    applicant_type: Literal["individual", "institution", "mixed"] = "individual"

    @model_validator(mode="after")
    def validate_clause_references(self) -> "SchemeRecord":
        clause_ids = [clause.clause_id for clause in self.clauses]
        if len(clause_ids) != len(set(clause_ids)):
            raise ValueError("clause_id values must be unique within a scheme")
        known_clauses = set(clause_ids)
        for rule in self.rules:
            for condition in rule.conditions():
                if condition.clause_id not in known_clauses:
                    raise ValueError(f"rule references unknown clause_id: {condition.clause_id}")
                allowed = SHARED_VALUES.get(condition.field)
                values = condition.value if isinstance(condition.value, list) else [condition.value]
                if allowed is not None and not set(values) <= set(allowed):
                    raise ValueError(f"{condition.field} values must come from data/field_values.json: {values}")
        return self


class RuleSet(Record):
    """Rules and citations, with readiness preserved for fail-closed evaluation."""

    rules: list[Rule] = Field(default_factory=list)
    logic: Literal["all", "any"] = "all"
    clauses: list[Clause] = Field(default_factory=list)
    ready: bool = False


def live_conditions(scheme: SchemeRecord) -> RuleSet:
    """Return a rule set only when the entire declared set has been reviewed.

    An incomplete set must not produce an apparently definitive verdict: an
    unreviewed condition could change the result.
    """
    ready = bool(scheme.rules) and all(rule.status == "reviewed" for rule in scheme.rules)
    return RuleSet(
        rules=scheme.rules if ready else [],
        logic=scheme.rule_logic,
        clauses=scheme.clauses,
        ready=ready,
    )


def preview_conditions(scheme: SchemeRecord) -> RuleSet:
    """Draft preview only: evaluate every rule as if reviewed, on in-memory copies."""
    rules = [rule.model_copy(update={"status": "reviewed"}) for rule in scheme.rules]
    return RuleSet(rules=rules, logic=scheme.rule_logic, clauses=scheme.clauses, ready=bool(rules))
