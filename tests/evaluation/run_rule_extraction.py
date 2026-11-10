#!/usr/bin/env python3
"""Run the rule extractor on a split and score it against the human-reviewed rules.

Signature challenge A: the extractor turns each scheme's eligibility sentences into draft JSON
rules; code scores each draft against data/rules/ and names every error by type. Drafts are
written only to the run folder (data/evaluation-runs/, git-ignored), never to data/rules/.

    python tests/evaluation/run_rule_extraction.py --config tests/evaluation/rule_extraction_configs/rx0_no_playbook.json
    python tests/evaluation/run_rule_extraction.py --config ... --limit 3
    python tests/evaluation/run_rule_extraction.py --config ... --split held_out --final

The held-out split (the 15 hand-coded gold schemes) is for the final evaluation only.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evaluation import rule_extraction as rx  # noqa: E402

RUNS_DIR = ROOT / "data" / "evaluation-runs"
SPLITS = ("development", "held_out")


def load_config(path: str | Path) -> dict[str, Any]:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("name", "system"):
        if key not in config:
            raise ValueError(f"config {path} is missing '{key}'")
    if config["system"] != "rule_extractor":
        raise ValueError("system must be 'rule_extractor'")
    return config


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def default_extractor(config: dict[str, Any]) -> Callable[[dict[str, Any], list[str]], dict[str, Any]]:
    """The extractor on SPECIALIST_MODEL; returns a callable (input, lessons) -> extraction dict."""
    from agents.model_factory import create_chat_model
    from agents.rule_extractor import RuleExtractor

    extractor = RuleExtractor(create_chat_model("specialist"))
    return lambda value, lessons: extractor.extract(value, lessons).model_dump()


def playbook_store(config: dict[str, Any], final: bool = False):
    """The approved lessons in a LangGraph store, or None for a run without a playbook."""
    if not config.get("playbook"):
        return None
    from evaluation.playbook import Playbook, to_store

    playbook = Playbook.load(ROOT / config["playbook"])
    if final:
        playbook.check_frozen()  # held-out runs use the frozen playbook only
    return to_store(playbook)


def lessons_for(value: dict[str, Any], store, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Reviewed lessons relevant to this scheme, read from the store; none without a playbook."""
    if store is None:
        return []
    from evaluation.playbook import TOP_K, relevant_lessons

    text = " ".join(c["text"] for c in value["clauses"])
    return relevant_lessons(store, text, config.get("top_k", TOP_K))


def run(config: dict[str, Any], split: str, limit: int | None = None,
        extract: Callable[[dict[str, Any], list[str]], dict[str, Any]] | None = None,
        quiet: bool = False, final: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from langchain_core.callbacks import get_usage_metadata_callback

    scheme_ids = rx.load_split()[split][:limit] if limit else rx.load_split()[split]
    store = playbook_store(config, final=final)
    extract = extract or default_extractor(config)
    vocabulary = rx.field_vocabulary()
    rows = []
    if not quiet:
        _progress(f"Running {config['name']} on {len(scheme_ids)} {split} schemes...")
    for number, scheme_id in enumerate(scheme_ids, 1):
        value = rx.extraction_input(scheme_id, vocabulary)
        lessons = lessons_for(value, store, config)
        started = time.perf_counter()
        with get_usage_metadata_callback() as usage:
            try:
                draft, error = extract(value, [lesson["text"] for lesson in lessons]), None
            except Exception as exc:  # a failed extraction is reported, never dropped
                draft, error = {"rules": [], "rule_logic": "all"}, f"{type(exc).__name__}: {exc}"
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        result = rx.score(draft, rx.load_gold(scheme_id), value["clauses"])
        rows.append({
            "scheme_id": scheme_id, "error": error, "lessons": [lesson["lesson_id"] for lesson in lessons],
            "draft": draft, "score": result,
            "latency_ms": latency_ms,
            "tokens": {model: dict(u) for model, u in usage.usage_metadata.items()},
        })
        if not quiet:
            outcome = f"ERROR {error[:200]}" if error else (
                f"{result['draft_rules']} of {result['gold_rules']} rules, "
                + ("exact" if result["scheme_exact"] else f"{len(result['errors'])} errors"))
            _progress(f"[{number}/{len(scheme_ids)}] {scheme_id}: {outcome} ({latency_ms / 1000:.1f} s)")
    return rows, summarise(rows)


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = rx.summarise([r["score"] for r in rows])
    tokens: dict[str, Counter] = {}
    for r in rows:
        for model, used in r["tokens"].items():
            tokens.setdefault(model, Counter()).update({k: v for k, v in used.items() if isinstance(v, int)})
    latencies = [r["latency_ms"] for r in rows]
    summary.update({
        "errors": sum(1 for r in rows if r["error"]),
        "error_schemes": [r["scheme_id"] for r in rows if r["error"]],
        "exact_schemes": [r["scheme_id"] for r in rows if r["score"]["scheme_exact"]],
        "lessons_used": sum(len(r["lessons"]) for r in rows),
        "lessons_by_id": dict(Counter(lesson for r in rows for lesson in r["lessons"])),
        "latency_ms": {"median": statistics.median(latencies) if latencies else None,
                       "max": max(latencies) if latencies else None},
        "tokens_by_model": {model: dict(c) for model, c in tokens.items()},
    })
    return summary


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def write_run(config: dict[str, Any], split: str, rows: list[dict[str, Any]], summary: dict[str, Any],
              runs_dir: Path = RUNS_DIR) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = runs_dir / f"{stamp}_{config['name']}_{split}"
    out.mkdir(parents=True, exist_ok=False)
    (out / "schemes.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                       encoding="utf-8")
    meta = {"config": config, "split": split, "git_commit": _git_commit(), "finished_at": stamp}
    (out / "summary.json").write_text(json.dumps({**meta, "summary": summary}, indent=2, ensure_ascii=False),
                                      encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", required=True)
    parser.add_argument("--split", choices=SPLITS, default="development")
    parser.add_argument("--final", action="store_true", help="required for the held-out split")
    parser.add_argument("--limit", type=int, help="run only the first N schemes")
    args = parser.parse_args()
    if args.split == "held_out" and not args.final:
        parser.error("held-out schemes are for the final evaluation only; add --final if this is it")
    config = load_config(args.config)
    rows, summary = run(config, args.split, args.limit, final=args.final)
    out = write_run(config, args.split, rows, summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "exact_schemes"}, indent=2, ensure_ascii=False))
    print(f"\nWritten to {out.relative_to(ROOT)}")
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
