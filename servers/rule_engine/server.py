from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from .rules import evaluate
from .scheme import SchemeRecord, live_conditions

ROOT = Path(__file__).resolve().parents[2]
SCHEME_DIR = ROOT / "data" / "schemes"

mcp = FastMCP(
    "rule-engine",
    instructions="Deterministic, fail-closed rule evaluation. The model can propose, but the code decides the verdict.",
)


def _load_scheme(scheme_id: str) -> SchemeRecord:
    for path in sorted(SCHEME_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if payload.get("scheme_id") == scheme_id:
            return SchemeRecord.model_validate(payload)
    raise ValueError(f"No rule record for scheme '{scheme_id}'.")


@mcp.tool()
def evaluate_profile(profile: dict[str, object], scheme_id: str) -> dict[str, Any]:
    """Read-only evaluation of a household profile against a reviewed scheme ruleset.

    Args:
        profile: Household facts keyed by field name.
        scheme_id: The scheme identifier to evaluate.

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
        result = evaluate(profile, live_conditions(scheme))
    except Exception as exc:  # pragma: no cover - defensive guard for invalid runtime input
        return {
            "ok": False,
            "access": "read",
            "error": {"code": "evaluation_failed", "message": str(exc)},
        }

    return {"ok": True, "access": "read", "data": result.model_dump(mode="json")}


if __name__ == "__main__":
    mcp.run()
