"""Experiment E4, the signature ablation: eligibility decided by the LLM directly from the scheme
text, against the rule engine, on the gold personas; with boundary errors counted.

This is an ablation only. In the app the model never decides eligibility: the rule engine does.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

from agents.base import StructuredGPTAgent
from evaluation.rule_extraction import load_gold, load_scheme, source_clauses

ROOT = Path(__file__).resolve().parents[1]

# L3's six slots: role, context, task, constraints, format, examples.
INSTRUCTIONS = """ROLE
You decide whether a household qualifies for an Indian government scheme.

CONTEXT
The input holds the scheme's eligibility and exclusion sentences (each with a clause_id) and the
household's facts as field: value pairs. A value of null means the person doesn't know it.

TASK
Decide one verdict for this scheme: "eligible" if every condition is met and no exclusion
applies; "not_eligible" if any condition is not met or an exclusion applies; "cant_tell" if the
answer depends on a fact that is missing (null or not given).

CONSTRAINTS
- Use only the scheme sentences and the facts given; don't assume facts that aren't there.
- Read limits exactly: "below"/"less than" excludes the limit, "up to"/"not more than" includes it.
- Name the clause_ids your verdict rests on.

FORMAT
verdict, reason (one or two sentences), clauses (clause_ids).

EXAMPLE
Clauses: elig-1 "Age between 18 and 40 years."; excl-1 "Income tax payers are not eligible."
Facts: age 41, is_income_tax_payer false -> verdict not_eligible, reason "Age 41 is above the
upper limit of 40.", clauses ["elig-1"]."""


class DirectInput(BaseModel):
    scheme_id: str
    scheme_name: str
    clauses: list[dict[str, str]]
    facts: dict[str, Any]


class DirectVerdict(BaseModel):
    verdict: Literal["eligible", "not_eligible", "cant_tell"]
    reason: str = ""
    clauses: list[str] = Field(default_factory=list)


class LLMDirectChecker:
    """The ablation's system: the model reads the scheme text and decides by itself."""

    def __init__(self, model: BaseChatModel) -> None:
        self._agent = StructuredGPTAgent(model, DirectInput, DirectVerdict, INSTRUCTIONS)

    def decide(self, value: DirectInput | dict) -> DirectVerdict:
        return self._agent.invoke(DirectInput.model_validate(value))


def direct_input(case: dict[str, Any], scheme_id: str) -> dict[str, Any]:
    """The scheme's own eligibility and exclusion text (perfect retrieval) and the case's facts,
    the same facts the rule engine is given."""
    scheme = load_scheme(scheme_id)
    return {"scheme_id": scheme_id, "scheme_name": scheme["name"], "clauses": source_clauses(scheme),
            "facts": dict(case["hidden_profile"])}


def boundary_conditions(case: dict[str, Any], scheme_id: str) -> list[str]:
    """Numeric facts at or next to one of the scheme's numeric limits: within 1 for counts and
    ages (40 vs a limit of 40 or 41), within 2% for amounts. A wrong verdict here is a boundary
    error, the kind the gold personas were built to catch."""
    near = []
    profile = case["hidden_profile"]
    for rule in load_gold(scheme_id)["rules"]:
        for condition in [rule, *rule.get("or_conditions", [])]:
            limit, fact = condition["value"], profile.get(condition["field"])
            if (condition["op"] not in ("gt", "gte", "lt", "lte") or isinstance(fact, bool)
                    or not isinstance(fact, (int, float))):
                continue
            tolerance = 1 if abs(limit) <= 150 else max(1, 0.02 * abs(limit))
            if abs(fact - limit) <= tolerance:
                near.append(f"{condition['field']} {fact} vs {condition['op']} {limit}")
    return near


def load_config(path: str | Path) -> dict[str, Any]:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if config.get("system") != "llm_direct":
        raise ValueError("an E4 config must have system 'llm_direct'")
    return config
