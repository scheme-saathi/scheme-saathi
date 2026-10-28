import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from statistics import mean
from time import perf_counter

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class TableText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, text):
        self.parts.append(text)


def normalized(text, is_html=False):
    if is_html:
        parser = TableText()
        parser.feed(text)
        text = " ".join(parser.parts)
    return " ".join(re.findall(r"\w+", unescape(text).casefold()))


def evidence_matches(reference, result):
    if result["scheme_id"] != reference["scheme_id"] or result["source_type"] != reference["source_type"]:
        return False
    if reference["source_type"] == "scheme_page":
        location_matches = any(c.get("source_path") == reference["source_path"] and
                               c.get("source_url") == reference["source_url"] for c in result["citations"])
    else:
        location_matches = any(c.get("document_id") == reference["document_id"] and
                               c.get("file_sha256") == reference["file_sha256"] and
                               c.get("page") == reference["page"] for c in result["citations"])
        if "table_id" in reference:
            location_matches = location_matches and result.get("kind") == "table" and result["id"].endswith(":" + reference["table_id"])
    quote = normalized(reference["evidence_text"])
    text = normalized(result["text"], result.get("kind") == "table")
    return bool(location_matches and quote and quote in text)


def score_case(case, results):
    behavior = case["expected_behavior"]
    if behavior == "abstain":
        return {"status": "not_supported", "reason": "Retriever does not generate answers or decide abstention."}
    if behavior == "no_results":
        return {"status": "scored", "filter_pass": not results}
    groups = case["required_evidence_groups"]
    matched = [g["group_id"] for g in groups
               if any(evidence_matches(ref, result) for ref in g["any_of"] for result in results)]
    return {"status": "scored", "scheme_hit": bool(set(case["expected_scheme_ids"]) & {r["scheme_id"] for r in results}),
            "evidence_groups_matched": matched, "evidence_group_count": len(groups),
            "evidence_coverage": len(matched) / len(groups) if groups else None,
            "all_evidence_found": len(matched) == len(groups)}


def summarize(rows):
    positive = [r for r in rows if r["expected_behavior"] == "retrieve_evidence"]
    filters = [r for r in rows if r["expected_behavior"] == "no_results"]
    latencies = sorted(r["latency_ms"] for r in rows if r.get("latency_ms") is not None)
    return {
        "case_count": len(rows), "positive_cases": len(positive),
        "scheme_hit_at_k": mean(r.get("scheme_hit", False) for r in positive) if positive else None,
        "mean_exact_evidence_coverage_at_k": mean(r.get("evidence_coverage", 0) or 0 for r in positive) if positive else None,
        "all_evidence_found_rate": mean(r.get("all_evidence_found", False) for r in positive) if positive else None,
        "filter_cases": len(filters),
        "filter_pass_rate": mean(r.get("filter_pass", False) for r in filters) if filters else None,
        "unsupported_cases": sum(r["status"] == "not_supported" for r in rows),
        "errors": sum(r["status"] == "error" for r in rows),
        "mean_latency_ms": mean(latencies) if latencies else None,
        "p95_latency_ms": latencies[max(0, (95 * len(latencies) + 99) // 100 - 1)] if latencies else None,
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate retrieval against source-labelled cases.")
    parser.add_argument("--dataset", type=Path, default=PROJECT_ROOT / "tests/evaluation/retrieval_gold_v1.json")
    parser.add_argument("--method", choices=["vector", "bm25", "hybrid"], default="vector")
    parser.add_argument("--split", choices=["development", "held_out"], default="development")
    parser.add_argument("--allow-pending", action="store_true", help="Run provisional comparisons with unreviewed labels.")
    parser.add_argument("--top-k", type=int, choices=range(1, 21), default=5)
    args = parser.parse_args()
    if not args.dataset.is_file():
        parser.error("Evaluation dataset is not bundled. Provide a local file with --dataset PATH.")
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    cases = [c for c in dataset["cases"] if c["split"] == args.split]
    if not cases:
        parser.error("No cases in the requested split.")
    pending = [c for c in cases if c["label_status"] != "approved"]
    if pending and not args.allow_pending:
        parser.error("Labels need human review. Use --allow-pending only for a provisional run.")
    for source in dataset["corpus_manifest"]:
        if "path" in source:
            path = PROJECT_ROOT / source["path"]
            if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
                parser.error(f"Corpus differs from the labelled snapshot: {source['path']}")

    from servers.schemes_kb.search import get_client, get_model, search_schemes
    from functools import partial
    search = partial(search_schemes, method=args.method)
    client = get_client()
    snapshots = []
    for collection in client.list_collections():
        if collection.name not in ["schemes_bge_m3_body_v1", "scheme_pdf_review_v1"]:
            continue
        stored = collection.get(include=["documents", "metadatas"])
        entries = sorted(zip(stored["ids"], stored["documents"], stored["metadatas"]))
        fingerprint = hashlib.sha256(json.dumps(entries, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        snapshots.append({"collection": collection.name, "count": collection.count(),
                          "content_metadata_sha256": fingerprint, "configuration": collection.metadata})
    if any(c["include_review_pdfs"] for c in cases):
        try:
            pdfs = client.get_collection("scheme_pdf_review_v1", embedding_function=None).get(include=["metadatas"])
        except Exception as error:
            parser.error(f"PDF review index is required for this split: {error}")
        indexed = {(m["document_id"], m["file_sha256"]) for m in pdfs["metadatas"]}
        required = {(r["document_id"], r["file_sha256"]) for c in cases for g in c["required_evidence_groups"]
                    for r in g["any_of"] if r["source_type"] == "pdf"}
        if not required <= indexed:
            parser.error("Expected PDF version is absent from the index; ingest it before evaluating.")

    started = perf_counter()
    if args.method != "bm25":
        get_model()
    model_load_ms = (perf_counter() - started) * 1000 if args.method != "bm25" else 0
    rows = []
    for case in cases:
        row = {k: case[k] for k in ["case_id", "intent_group", "language", "expected_behavior", "label_status"]}
        if case["expected_behavior"] == "abstain":
            row.update(score_case(case, []))
        else:
            started = perf_counter()
            try:
                response = search(case["question"], top_k=args.top_k, **case["filters"],
                                  include_review_pdfs=case["include_review_pdfs"])
                row["latency_ms"] = (perf_counter() - started) * 1000
                row.update(score_case(case, response["results"]))
                row["results"] = response["results"]
                row["warnings"] = response["warnings"]
            except Exception as error:
                row.update(status="error", error=str(error), latency_ms=(perf_counter() - started) * 1000)
        rows.append(row)
        print(case["case_id"], row["status"], "coverage:", row.get("evidence_coverage", "n/a"))
    languages = sorted({r["language"] for r in rows})
    report = {
        "dataset_id": dataset["dataset_id"], "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        "method": args.method, "split": args.split, "top_k": args.top_k,
        "provisional": bool(pending), "label_statuses": sorted({c["label_status"] for c in cases}),
        "model_load_ms": model_load_ms, "index_snapshots": snapshots,
        "retrieval_settings": {"candidate_k": args.top_k if args.method == "vector" else 20, "bm25_k1": 1.2, "bm25_b": 0.75, "rrf_constant": 60, "tokenizer": "NFC-casefold-Unicode-LNM", "lexical_statistics": "filtered eligible corpus"},
        "summary": summarize(rows), "by_language": {lang: summarize([r for r in rows if r["language"] == lang]) for lang in languages},
        "metric_notes": "Exact normalized evidence text plus matching citation; conservative proxy, not semantic grading. Errors count as failed cases. Translation pairs are correlated. Latency excludes initial model load; first-query warmup may remain. Abstention is unsupported, not counted as passed.",
        "cases": rows,
    }
    output = PROJECT_ROOT / "data/evaluation-runs" / f"{args.method}-{args.split}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"Report: {output}")
    if report["summary"]["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
