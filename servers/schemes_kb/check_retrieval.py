"""Quick pass/fail smoke check of scheme retrieval (not the gold-set evaluation).

Searches each approved scheme by its own name and requires that scheme to appear in
the top-k results. Also runs labelled questions (tests/evaluation/retrieval_check_v1.json): each must
return its scheme with a chunk citing the clause that answers it. Also checks that every rule record in data/rules has an indexed
source scheme. Exits non-zero on any failure so it can run in CI or before a demo.
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMES_DIR = PROJECT_ROOT / "data" / "schemes"
QUESTIONS_FILE = PROJECT_ROOT / "tests" / "evaluation" / "retrieval_check_v1.json"
RULES_DIR = PROJECT_ROOT / "data" / "rules"


def approved_schemes(directory: Path = SCHEMES_DIR) -> dict[str, str]:
    """Map scheme_id to name for approved real source records."""
    found = {}
    for path in sorted(directory.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if "sections" in record and record.get("review_status") == "approved":
            found[record["scheme_id"]] = record["name"]
    return found


def rule_record_ids(directory: Path = RULES_DIR) -> list[str]:
    return [json.loads(p.read_text(encoding="utf-8"))["scheme_id"] for p in sorted(directory.glob("*.json"))]


def check(search, schemes: dict[str, str], rule_ids: list[str], top_k: int, method: str) -> list[dict]:
    """Return one row per check: {"check", "ok", "detail"}. `search(question, top_k, method)` returns scheme IDs."""
    rows = []
    for scheme_id, name in schemes.items():
        returned = search(name, top_k, method)
        rank = returned.index(scheme_id) + 1 if scheme_id in returned else None
        rows.append({"check": f"find {scheme_id} by name", "ok": rank is not None,
                     "detail": f"rank {rank}" if rank else f"not in top {top_k}: {returned}"})
    for scheme_id in rule_ids:
        rows.append({"check": f"rule record {scheme_id} has an indexed scheme", "ok": scheme_id in schemes,
                     "detail": "indexed" if scheme_id in schemes else "no approved source scheme"})
    return rows


def check_questions(search_full, questions: list[dict], top_k: int, method: str) -> list[dict]:
    """Each labelled question must return its scheme and a chunk citing its clause path in the top-k."""
    rows = []
    for q in questions:
        results = search_full(q["question"], top_k, method)
        scheme_rank = next((i for i, r in enumerate(results, 1) if r["scheme_id"] == q["scheme_id"]), None)
        clause_rank = next((i for i, r in enumerate(results, 1) if r["scheme_id"] == q["scheme_id"]
                            and any(c.get("source_path") == q["clause_path"] for c in r["citations"])), None)
        detail = f"scheme rank {scheme_rank or 'miss'}, clause rank {clause_rank or 'miss'}"
        rows.append({"check": f"{q['id']} {q['scheme_id']}: {q['question']}", "ok": clause_rank is not None, "detail": detail})
    return rows


def live_search_full(question: str, top_k: int, method: str) -> list[dict]:
    from servers.schemes_kb.search import search_schemes
    return search_schemes(question, top_k=top_k, method=method)["results"]


def live_search(question: str, top_k: int, method: str) -> list[str]:
    from servers.schemes_kb.search import search_schemes
    response = search_schemes(question, top_k=top_k, method=method)
    return list(dict.fromkeys(result["scheme_id"] for result in response["results"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-check scheme retrieval against the local index.")
    parser.add_argument("--method", choices=["vector", "bm25", "hybrid"], default="hybrid")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--questions", type=Path, default=QUESTIONS_FILE, help="Labelled questions JSON.")
    parser.add_argument("--skip-questions", action="store_true", help="Only run the name and rule-record checks.")
    parser.add_argument("--scheme-id", action="append", dest="scheme_ids", help="Check only this scheme (repeatable).")
    args = parser.parse_args(argv)
    if not 1 <= args.top_k <= 20:
        parser.error("top-k must be between 1 and 20.")
    schemes = approved_schemes()
    if args.scheme_ids:
        unknown = [s for s in args.scheme_ids if s not in schemes]
        if unknown:
            parser.error(f"Not an approved scheme: {', '.join(unknown)}")
        schemes = {s: schemes[s] for s in args.scheme_ids}
    try:
        rows = check(live_search, schemes, rule_record_ids(), args.top_k, args.method)
        if not args.skip_questions:
            labelled = json.loads(args.questions.read_text(encoding="utf-8"))["questions"]
            if args.scheme_ids:
                labelled = [q for q in labelled if q["scheme_id"] in args.scheme_ids]
            rows += check_questions(live_search_full, labelled, args.top_k, args.method)
    except Exception as error:
        print(f"Retrieval check could not run: {error}\nHave you run python -m servers.schemes_kb.import_schemes?",
              file=sys.stderr)
        return 2
    for row in rows:
        print(f"{'PASS' if row['ok'] else 'FAIL'}  {row['check']}: {row['detail']}")
    failed = sum(not row["ok"] for row in rows)
    print(f"\n{len(rows) - failed}/{len(rows)} checks passed ({args.method}, top-{args.top_k}).")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
