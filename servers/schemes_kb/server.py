from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

ROOT = Path(__file__).resolve().parents[2]
SCHEME_DIR = ROOT / "data" / "schemes"
RULES_DIR = ROOT / "data" / "rules"
MIN_RERANK_SCORE = 5  # of 10; reranked passages below this don't answer the question

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


@mcp.tool()
def search_scheme_evidence(question: str, top_k: int = 5, scheme_id: str | None = None) -> dict[str, Any]:
    """Read-only evidence search over approved scheme pages and PDFs (hybrid BM25 + vectors, LLM reranked).

    Args:
        question: The user's question, at most 2000 characters.
        top_k: Passages to return, 1 to 20.
        scheme_id: Optional scheme to search within.

    Returns:
        A JSON object whose ``data`` lists passages with citations. Passages are evidence,
        not eligibility verdicts; an empty list means nothing relevant was found.
    """
    from servers.schemes_kb.keyword_search import visible_text
    from servers.schemes_kb.search import search_schemes as search_index

    try:
        response = search_index(question, top_k=top_k, scheme_id=scheme_id, method="hybrid", rerank=True)
    except ValueError as error:
        return {"ok": False, "access": "read", "error": {"code": "invalid_search", "message": str(error)}}
    # Without a rerank (it failed), scores are not 0-10, so the caller's answer step decides relevance.
    reranked = response["ranking"].endswith("llm_rerank")
    passages = [
        {
            "id": row["id"], "scheme_id": row["scheme_id"], "source_type": row["source_type"],
            "section": row["section"], "page": row["page"], "citations": row["citations"],
            "text": visible_text(row["text"]) if row["kind"] == "table" else row["text"],
        }
        for row in response["results"]
        if not reranked or (row["rank_score"] or 0) >= MIN_RERANK_SCORE
    ]
    return {"ok": True, "access": "read", "data": passages}


if __name__ == "__main__":
    mcp.run()
