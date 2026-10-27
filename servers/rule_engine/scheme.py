"""Validated, clause-linked rule records used by the eligibility evaluator."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(Record):
    url: str = Field(min_length=1)
    collected_on: str = Field(min_length=1)


class Clause(Record):
    clause_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)


class Rule(Record):
    field: str = Field(min_length=1)
    op: Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in"]
    value: Any
    clause_id: str = Field(min_length=1)
    status: Literal["reviewed", "draft"] = "draft"

    @model_validator(mode="after")
    def validate_operand(self) -> "Rule":
        value = self.value
        if self.op in {"in", "not_in"}:
            if not isinstance(value, list) or not value:
                raise ValueError(f"{self.op} requires a non-empty list value")
            value_types = {type(item) for item in value}
            if len(value_types) != 1 or type(None) in value_types:
                raise ValueError("membership values must have one consistent, non-null type")
        else:
            if isinstance(value, (dict, list, tuple, set)) or value is None:
                raise ValueError("comparison value must be a non-null scalar")

        if self.op in {"gt", "gte", "lt", "lte"} and (
            not isinstance(value, (int, float)) or isinstance(value, bool)
        ):
            raise ValueError(f"{self.op} requires a numeric value")
        return self


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

    @model_validator(mode="after")
    def validate_clause_references(self) -> "SchemeRecord":
        clause_ids = [clause.clause_id for clause in self.clauses]
        if len(clause_ids) != len(set(clause_ids)):
            raise ValueError("clause_id values must be unique within a scheme")
        known_clauses = set(clause_ids)
        for rule in self.rules:
            if rule.clause_id not in known_clauses:
                raise ValueError(f"rule references unknown clause_id: {rule.clause_id}")
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