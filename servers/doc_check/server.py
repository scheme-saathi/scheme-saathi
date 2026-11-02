from __future__ import annotations

import re
from typing import Any

from fastmcp import FastMCP

mcp = FastMCP(
    "doc-check",
    instructions="Read-only document comparison for identity and field-level matches. This server never writes anything.",
)


def _canonicalize(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9]", "", text)
    return text


def _pick_field(document: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in document:
            return document[name]
    return None


@mcp.tool()
def compare_document_fields(
    document_a: dict[str, Any],
    document_b: dict[str, Any],
    fields: list[str] | None = None,
) -> dict[str, Any]:
    """Read-only comparison of selected fields between two identity or support documents.

    Args:
        document_a: First document payload with field names like ``name`` or ``dob``.
        document_b: Second document payload.
        fields: Optional explicit field list; defaults to common identity checks.

    Returns:
        A JSON object with ``ok`` and ``data`` summarising field matches.
    """
    compare_fields = fields or ["name", "full_name", "dob", "date_of_birth", "date"]
    differences: dict[str, dict[str, Any]] = {}
    matches: dict[str, bool] = {}

    for field_name in compare_fields:
        left = _pick_field(document_a, field_name)
        right = _pick_field(document_b, field_name)
        if left is None and right is None:
            continue
        if left is None or right is None:
            matches[field_name] = False
            differences[field_name] = {"left": left, "right": right}
            continue
        normalized_left = _canonicalize(left)
        normalized_right = _canonicalize(right)
        is_match = normalized_left == normalized_right
        matches[field_name] = is_match
        if not is_match:
            differences[field_name] = {"left": left, "right": right}

    name_matches = matches.get("name", False) or matches.get("full_name", False)
    date_matches = matches.get("dob", False) or matches.get("date_of_birth", False) or matches.get("date", False)

    return {
        "ok": True,
        "access": "read",
        "data": {
            "name_matches": name_matches,
            "date_matches": date_matches,
            "matches": matches,
            "differences": differences,
        },
    }


if __name__ == "__main__":
    mcp.run()
