from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from .rules import evaluate
from .scheme import RuleSet, SchemeRecord, live_conditions, preview_conditions

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
        whose rules are all reviewed (or every scheme with rules in preview mode).
    """
    records = _rule_records()
    if scheme_ids:
        unknown = [s for s in scheme_ids if s not in records]
        if unknown:
            return _error("scheme_not_found", f"No rule record for scheme(s): {', '.join(unknown)}")
        return {"ok": True, "access": "read", "data": list(scheme_ids)}
    ready = [s for s, record in records.items() if _conditions(record, include_draft).ready]
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
            if rule.field not in fields:
                fields.append(rule.field)
    return {"ok": True, "access": "read", "data": fields}


@mcp.tool()
def evaluate_profile(profile: dict[str, object], scheme_id: str, include_draft: bool = False) -> dict[str, Any]:
    """Read-only evaluation of a household profile against a reviewed scheme ruleset.

    Args:
        profile: Household facts keyed by field name.
        scheme_id: The scheme identifier to evaluate.
        include_draft: Preview only: evaluate unreviewed draft rules. Never use for advice or decisions.

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

    try:
        result = evaluate(profile, _conditions(scheme, include_draft))
    except Exception as exc:  # pragma: no cover - defensive guard for invalid runtime input
        return {
            "ok": False,
            "access": "read",
            "error": {"code": "evaluation_failed", "message": str(exc)},
        }

    return {"ok": True, "access": "read", "data": result.model_dump(mode="json")}


if __name__ == "__main__":
    mcp.run()
