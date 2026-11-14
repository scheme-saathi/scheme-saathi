from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from .rules import evaluate
from .ages import DOB_DERIVED, derive_age_fields
from .implied import derive_implied_facts
from .scheme import SHARED_VALUES, RuleSet, SchemeRecord, live_conditions, preview_conditions

ROOT = Path(__file__).resolve().parents[2]
SCHEME_DIR = ROOT / "data" / "schemes"
# Rule-format records live in both folders; source records (with "sections") are skipped.
RULE_DIRS = [SCHEME_DIR, ROOT / "data" / "rules"]

mcp = FastMCP(
    "rule-engine",
    instructions="Deterministic, fail-closed rule evaluation. The model can propose, but the code decides the verdict.",
)


def _rule_records() -> dict[str, SchemeRecord]:
    records: dict[str, SchemeRecord] = {}
    for directory in RULE_DIRS:
        for path in sorted(directory.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if "rules" not in payload or "sections" in payload:
                continue
            record = SchemeRecord.model_validate(payload)
            records[record.scheme_id] = record
    return records


def _load_scheme(scheme_id: str) -> SchemeRecord:
    try:
        return _rule_records()[scheme_id]
    except KeyError:
        raise ValueError(f"No rule record for scheme '{scheme_id}'.") from None


def _conditions(scheme: SchemeRecord, include_draft: bool) -> RuleSet:
    return preview_conditions(scheme) if include_draft else live_conditions(scheme)


def _error(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "access": "read", "error": {"code": code, "message": message}}


@mcp.tool()
def list_rule_schemes(scheme_ids: list[str] | None = None, include_draft: bool = False) -> dict[str, Any]:
    """Read-only list of schemes the engine can evaluate.

    Args:
        scheme_ids: Specific schemes to check; all schemes with rules when omitted.
        include_draft: Preview mode. Also accept schemes whose rules are not yet fully reviewed.

    Returns:
        With scheme_ids: those IDs (error if any has no rule record). Otherwise every scheme
        whose rules are all reviewed (or every scheme with rules in preview mode), leaving out
        schemes for organisations (``applicant_type`` "institution").
    """
    records = _rule_records()
    if scheme_ids:
        unknown = [s for s in scheme_ids if s not in records]
        if unknown:
            return _error("scheme_not_found", f"No rule record for scheme(s): {', '.join(unknown)}")
        return {"ok": True, "access": "read", "data": list(scheme_ids)}
    ready = [s for s, record in records.items()
             if _conditions(record, include_draft).ready and record.applicant_type != "institution"]
    return {"ok": True, "access": "read", "data": ready}


@mcp.tool()
def get_rule_fields(scheme_ids: list[str], include_draft: bool = False) -> dict[str, Any]:
    """Read-only list of profile fields used by the live rules of the given schemes, in rule order."""
    records = _rule_records()
    fields: list[str] = []
    for scheme_id in scheme_ids:
        if scheme_id not in records:
            return _error("scheme_not_found", f"No rule record for scheme '{scheme_id}'.")
        for rule in _conditions(records[scheme_id], include_draft).rules:
            for condition in rule.conditions():
                if condition.field not in fields:
                    fields.append(condition.field)
    return {"ok": True, "access": "read", "data": fields}


@mcp.tool()
def get_field_specs(scheme_ids: list[str], include_draft: bool = False) -> dict[str, Any]:
    """Read-only type of each profile field used by the given schemes' rules, in rule order.

    Returns:
        ``{field: {"type": "number" | "bool" | "str" | "date", "known_values": [...]}}``. ``known_values``
        lists the strings the rules compare against (the whole shared list for fields in
        data/field_values.json); other strings are still valid answers. When a rule uses an age
        worked out from the date of birth, ``date_of_birth`` (type "date", YYYY-MM-DD) is added.
    """
    records = _rule_records()
    specs: dict[str, dict[str, Any]] = {}
    for scheme_id in scheme_ids:
        if scheme_id not in records:
            return _error("scheme_not_found", f"No rule record for scheme '{scheme_id}'.")
        for condition in (c for rule in _conditions(records[scheme_id], include_draft).rules for c in rule.conditions()):
            values = condition.value if condition.op in {"in", "not_in"} else [condition.value]
            kind = "bool" if isinstance(values[0], bool) else "str" if isinstance(values[0], str) else "number"
            spec = specs.setdefault(condition.field, {"type": kind, "known_values": []})
            if spec["type"] != kind:
                return _error("field_type_conflict", f"Rules use '{condition.field}' as both {spec['type']} and {kind}.")
            if kind == "str":
                values = SHARED_VALUES.get(condition.field, values)  # offer the whole shared list
                spec["known_values"] += [v for v in values if v not in spec["known_values"]]
    if specs.keys() & DOB_DERIVED:  # these are worked out from the date of birth, never asked
        specs["date_of_birth"] = {"type": "date", "known_values": []}
    return {"ok": True, "access": "read", "data": specs}


@mcp.tool()
def evaluate_profile(profile: dict[str, object], scheme_id: str, include_draft: bool = False) -> dict[str, Any]:
    """Read-only evaluation of a household profile against a reviewed scheme ruleset.

    Args:
        profile: Household facts keyed by field name.
        scheme_id: The scheme identifier to evaluate.
        include_draft: Deprecated compatibility argument. Draft rules cannot produce a verdict.

    Returns:
        A JSON object with an ``ok`` flag and the evaluation payload under ``data``.
    """
    try:
        scheme = _load_scheme(scheme_id)
    except ValueError as exc:
        return {
            "ok": False,
            "access": "read",
            "error": {"code": "scheme_not_found", "message": str(exc)},
        }

    if include_draft:
        return _error(
            "draft_rules_not_allowed",
            "Draft rules cannot produce an eligibility verdict; use the reviewer-only preview.",
        )

    return _evaluate(scheme, profile, preview=False)


@mcp.tool()
def preview_profile(profile: dict[str, object], scheme_id: str) -> dict[str, Any]:
    """Reviewer-only informational preview; never an eligibility verdict or submission basis."""
    try:
        scheme = _load_scheme(scheme_id)
    except ValueError as exc:
        return {
            "ok": False,
            "access": "read",
            "error": {"code": "scheme_not_found", "message": str(exc)},
        }
    return _evaluate(scheme, profile, preview=True)


def _evaluate(scheme: SchemeRecord, profile: dict[str, object], preview: bool) -> dict[str, Any]:
    try:
        result = evaluate(derive_implied_facts(derive_age_fields(profile)), _conditions(scheme, preview))
    except Exception as exc:  # pragma: no cover - defensive guard for invalid runtime input
        return {
            "ok": False,
            "access": "read",
            "error": {"code": "evaluation_failed", "message": str(exc)},
        }

    return {"ok": True, "access": "read", "data": result.model_dump(mode="json")}


if __name__ == "__main__":
    mcp.run()
