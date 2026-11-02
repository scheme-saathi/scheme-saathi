from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

ROOT = Path(__file__).resolve().parents[2]
SCHEME_DIR = ROOT / "data" / "schemes"
RULES_DIR = ROOT / "data" / "rules"

mcp = FastMCP(
    "schemes-kb",
    instructions="Read-only scheme catalogue and document checklist retrieval for policy and eligibility lookup.",
)


def _load_scheme_records() -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for path in sorted(SCHEME_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        scheme_id = payload.get("scheme_id")
        if scheme_id:
            records[str(scheme_id)] = payload
    return records


@mcp.tool()
def search_schemes() -> list[str]:
    """Read-only lookup for all available scheme identifiers.

    Returns:
        A sorted list of scheme IDs that have a machine-readable record.
    """
    return sorted(_load_scheme_records())


@mcp.tool()
def get_scheme_details(scheme_id: str) -> dict[str, Any]:
    """Read-only scheme metadata lookup for a single scheme ID.

    Args:
        scheme_id: The scheme identifier to retrieve.

    Returns:
        A JSON object with an ``ok`` flag, a ``data`` payload, or an ``error`` payload.
    """
    records = _load_scheme_records()
    record = records.get(scheme_id)
    if record is None:
        return {
            "ok": False,
            "access": "read",
            "error": {
                "code": "scheme_not_found",
                "message": f"No scheme metadata found for '{scheme_id}'.",
            },
        }
    return {"ok": True, "access": "read", "data": record}


@mcp.tool()
def get_required_documents(scheme_id: str) -> dict[str, Any]:
    """Read-only retrieval of the required document checklist for a scheme.

    Args:
        scheme_id: The scheme identifier to inspect.

    Returns:
        A JSON object with the document list under ``data`` when available.
    """
    records = _load_scheme_records()
    record = records.get(scheme_id)
    if record is None:
        return {
            "ok": False,
            "access": "read",
            "error": {
                "code": "scheme_not_found",
                "message": f"No scheme metadata found for '{scheme_id}'.",
            },
        }
    items = list(record.get("documents_required", []))
    if not items:
        # Hand-coded rule records hold the checklist for schemes whose source record has none at top level.
        for path in sorted(RULES_DIR.glob("*.json")):
            try:
                rule_record = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if rule_record.get("scheme_id") == scheme_id:
                items = list(rule_record.get("documents_required", []))
                break
    return {"ok": True, "access": "read", "data": items}


if __name__ == "__main__":
    mcp.run()
