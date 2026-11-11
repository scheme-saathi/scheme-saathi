"""Code-controlled citizen journey and rule-result-driven revisions."""

from typing import Literal, TypedDict

PlanDisposition = Literal["conditional", "ready", "not_eligible", "cant_tell"]


class PlanRevision(TypedDict):
    previous: PlanDisposition
    current: PlanDisposition
    reason: str


class JourneyPlan(TypedDict):
    steps: list[str]
    disposition: PlanDisposition
    revisions: list[PlanRevision]


def new_journey_plan() -> JourneyPlan:
    return {
        "steps": ["profile", "schemes", "rules", "documents", "draft"],
        "disposition": "conditional",
        "revisions": [],
    }


def revise_journey_plan(plan: JourneyPlan, verdict: str) -> JourneyPlan:
    if verdict not in ("eligible", "not_eligible", "cant_tell"):
        raise ValueError(f"Unknown rule-engine verdict: {verdict}")
    disposition: PlanDisposition = "ready" if verdict == "eligible" else verdict
    previous = plan["disposition"]
    if disposition == previous:
        return plan
    reasons = {
        "ready": "rule_engine_eligible",
        "not_eligible": "rule_engine_not_eligible",
        "cant_tell": "rule_engine_cant_tell",
    }
    return {
        **plan,
        "disposition": disposition,
        "revisions": [
            *plan["revisions"],
            {"previous": previous, "current": disposition, "reason": reasons[disposition]},
        ],
    }


def defer_journey_plan(plan: JourneyPlan) -> JourneyPlan:
    if plan["disposition"] == "conditional":
        return plan
    return {
        **plan,
        "disposition": "conditional",
        "revisions": [
            *plan["revisions"],
            {"previous": plan["disposition"], "current": "conditional", "reason": "facts_pending"},
        ],
    }
