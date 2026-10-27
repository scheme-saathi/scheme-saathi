"""Three-valued, deterministic evaluation for reviewed scheme conditions."""

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .scheme import Clause, Rule, RuleSet


class Verdict(StrEnum):
    ELIGIBLE = "eligible"
    NOT_ELIGIBLE = "not_eligible"
    CANT_TELL = "cant_tell"


class ConditionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    op: str
    clause_id: str
    outcome: Literal["true", "false", "unknown"]


class Evaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Verdict
    reason: str
    missing_fields: list[str] = Field(default_factory=list)
    unresolved_fields: list[str] = Field(default_factory=list)
    conditions: list[ConditionResult] = Field(default_factory=list)
    citations: list[Clause] = Field(default_factory=list)


def _same_value_type(actual: object, expected: object) -> bool:
    """Avoid Python's bool-is-an-int behavior and implicit string coercion."""
    if isinstance(expected, bool):
        return isinstance(actual, bool)
    if isinstance(expected, (int, float)):
        return isinstance(actual, (int, float)) and not isinstance(actual, bool)
    return type(actual) is type(expected)


def _condition(rule: Rule, profile: Mapping[str, object]) -> tuple[str, bool]:
    if rule.field not in profile or profile[rule.field] is None:
        return "unknown", True

    actual = profile[rule.field]
    expected = rule.value
    if rule.op in {"in", "not_in"}:
        if not any(_same_value_type(actual, item) for item in expected):
            return "unknown", False
        matched = any(_same_value_type(actual, item) and actual == item for item in expected)
        return ("true" if matched else "false", False) if rule.op == "in" else (
            "false" if matched else "true",
            False,
        )

    if not _same_value_type(actual, expected):
        return "unknown", False

    if rule.op == "eq":
        result = actual == expected
    elif rule.op == "ne":
        result = actual != expected
    elif rule.op == "gt":
        result = actual > expected
    elif rule.op == "gte":
        result = actual >= expected
    elif rule.op == "lt":
        result = actual < expected
    else:  # lte; operator values are validated by Rule.
        result = actual <= expected
    return ("true" if result else "false", False)


def _combine(outcomes: Sequence[str], logic: Literal["all", "any"]) -> str:
    if logic == "all":
        if "false" in outcomes:
            return "false"
        return "true" if all(value == "true" for value in outcomes) else "unknown"
    if "true" in outcomes:
        return "true"
    return "false" if all(value == "false" for value in outcomes) else "unknown"


def evaluate(
    profile: Mapping[str, object],
    conditions: RuleSet | Sequence[Rule],
) -> Evaluation:
    """Evaluate profile facts without coercion; absent/invalid facts stay unknown.

    A RuleSet produced by ``live_conditions`` retains whether the complete rule
    set is reviewed. Passing a bare rule sequence assumes the caller has already
    established that it is reviewed.
    """
    if isinstance(conditions, RuleSet):
        rules = conditions.rules
        logic = conditions.logic
        clauses = conditions.clauses
        ready = conditions.ready
    else:
        rules = list(conditions)
        logic = "all"
        clauses = []
        ready = bool(rules)

    if not ready or not rules or any(rule.status != "reviewed" for rule in rules):
        return Evaluation(
            verdict=Verdict.CANT_TELL,
            reason="There is no complete, fully reviewed rule set for this scheme.",
        )

    rows: list[ConditionResult] = []
    missing: set[str] = set()
    unresolved: set[str] = set()
    for rule in rules:
        outcome, is_missing = _condition(rule, profile)
        rows.append(
            ConditionResult(
                field=rule.field,
                op=rule.op,
                clause_id=rule.clause_id,
                outcome=outcome,
            )
        )
        if outcome == "unknown":
            unresolved.add(rule.field)
            if is_missing:
                missing.add(rule.field)

    combined = _combine([row.outcome for row in rows], logic)
    verdict = {
        "true": Verdict.ELIGIBLE,
        "false": Verdict.NOT_ELIGIBLE,
        "unknown": Verdict.CANT_TELL,
    }[combined]
    reasons = {
        Verdict.ELIGIBLE: "All required reviewed conditions are satisfied."
        if logic == "all"
        else "At least one reviewed alternative condition is satisfied.",
        Verdict.NOT_ELIGIBLE: "The reviewed rule expression is not satisfied.",
        Verdict.CANT_TELL: "One or more facts needed to decide the reviewed rules are missing or invalid.",
    }
    cited_ids = {row.clause_id for row in rows}
    cited_clauses = [clause for clause in clauses if clause.clause_id in cited_ids]
    return Evaluation(
        verdict=verdict,
        reason=reasons[verdict],
        missing_fields=sorted(missing),
        unresolved_fields=sorted(unresolved),
        conditions=rows,
        citations=cited_clauses,
    )