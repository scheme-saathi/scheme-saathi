#!/usr/bin/env python3
"""E4, the signature ablation: the LLM decides eligibility directly from the scheme text, against
the rule engine, on the gold personas; boundary errors counted separately.

    python tests/evaluation/run_e4.py --config tests/evaluation/e4_configs/e4_llm_direct_gpt41mini.json --limit 3
    python tests/evaluation/run_e4.py --config ... --split held_out --final --repeat 3

For every case and candidate scheme, the model gets the scheme's own eligibility and exclusion
sentences (perfect retrieval, the model's best case) and the case's facts, the same facts the
rule engine gets, and returns a verdict. Both are scored against the human labels. A verdict is a
boundary verdict when a numeric fact sits at or next to one of the scheme's limits. The question-
order half of E4 needs no model: run_eval.py with c0_fixed_workflow against c0_fixed_questionnaire.
"""

from __future__ import annotations

import argparse
import contextvars
import json
import statistics
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evaluation import e4  # noqa: E402

RUNS_DIR = ROOT / "data" / "evaluation-runs"
GOLD = ROOT / "tests" / "evaluation" / "eligibility_gold_v1"
SPLITS = ("development", "held_out")


def load_cases(split: str) -> list[dict[str, Any]]:
    text = (GOLD / split / "cases.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def items(split: str, limit: int | None = None) -> list[dict[str, Any]]:
    """One item per case and candidate scheme, with its label and boundary tag."""
    cases = load_cases(split)[:limit] if limit else load_cases(split)
    out = []
    for case in cases:
        for scheme_id in case["candidate_scheme_ids"]:
            out.append({"case_id": case["case_id"], "scheme_id": scheme_id, "language": case["language"],
                        "gold": case["expected"][scheme_id]["verdict"],
                        "boundary": e4.boundary_conditions(case, scheme_id), "case": case})
    return out


def rule_engine_verdicts(work: list[dict[str, Any]]) -> list[str]:
    from graph import tools

    return [tools.evaluate_scheme(item["case"]["hidden_profile"], item["scheme_id"])["verdict"] for item in work]


def default_decider(config: dict[str, Any]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """The LLM-direct checker on the config's model (this run only), else SPECIALIST_MODEL."""
    import os

    from dotenv import load_dotenv

    from agents.model_factory import create_chat_model

    load_dotenv()
    chosen, before = (config.get("model") or "").strip(), os.environ.get("SPECIALIST_MODEL")
    try:
        if chosen:
            os.environ["SPECIALIST_MODEL"] = chosen
        checker = e4.LLMDirectChecker(create_chat_model("specialist"))
    finally:
        if chosen:
            if before is None:
                os.environ.pop("SPECIALIST_MODEL", None)
            else:
                os.environ["SPECIALIST_MODEL"] = before
    return lambda value: checker.decide(value).model_dump()


def llm_run(work: list[dict[str, Any]], decide: Callable, workers: int) -> tuple[list[dict[str, Any]], dict]:
    from langchain_core.callbacks import get_usage_metadata_callback

    def one(item: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            answer, error = decide(e4.direct_input(item["case"], item["scheme_id"])), None
        except Exception as exc:  # a failed call is reported, never dropped
            answer, error = {"verdict": "error", "reason": "", "clauses": []}, f"{type(exc).__name__}: {exc}"
        return {**answer, "error": error, "latency_ms": round((time.perf_counter() - started) * 1000, 1)}

    with get_usage_metadata_callback() as usage, ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(contextvars.copy_context().run, one, item) for item in work]
        results = [f.result() for f in futures]
    tokens = {model: dict(u) for model, u in usage.usage_metadata.items()}
    return results, tokens


def score(work: list[dict[str, Any]], verdicts: list[str]) -> dict[str, Any]:
    def accuracy(selected: list[int]) -> float | None:
        return round(sum(verdicts[i] == work[i]["gold"] for i in selected) / len(selected), 4) if selected else None

    everything = list(range(len(work)))
    boundary = [i for i in everything if work[i]["boundary"]]
    other = [i for i in everything if not work[i]["boundary"]]
    wrong = [i for i in everything if verdicts[i] != work[i]["gold"]]
    return {
        "verdicts": len(work),
        "accuracy": accuracy(everything),
        "boundary_verdicts": len(boundary),
        "boundary_accuracy": accuracy(boundary),
        "boundary_errors": sum(1 for i in boundary if i in wrong),
        "other_accuracy": accuracy(other),
        "errors": len(wrong),
        "confusion": dict(Counter(f"{work[i]['gold']}->{verdicts[i]}" for i in wrong)),
        "wrong": [f"{work[i]['case_id']} {work[i]['scheme_id']}: gold {work[i]['gold']}, got {verdicts[i]}"
                  + (f" (boundary: {'; '.join(work[i]['boundary'])})" if work[i]["boundary"] else "")
                  for i in wrong],
    }


def spread(values: list[float]) -> dict[str, float]:
    return {"mean": round(statistics.mean(values), 4), "min": min(values), "max": max(values)}


def run(config: dict[str, Any], split: str, repeat: int = 1, limit: int | None = None,
        decide: Callable | None = None, workers: int = 8, quiet: bool = False) -> tuple[list, dict]:
    work = items(split, limit)
    engine = rule_engine_verdicts(work)
    decide = decide or default_decider(config)
    runs, rows = [], []
    for number in range(1, repeat + 1):
        if not quiet:
            print(f"LLM run {number}/{repeat}: {len(work)} verdicts...", file=sys.stderr, flush=True)
        results, tokens = llm_run(work, decide, workers)
        verdicts = [r["verdict"] for r in results]
        runs.append({**score(work, verdicts), "failed_calls": sum(1 for r in results if r["error"]),
                     "tokens": tokens, "latency_ms_median": statistics.median(r["latency_ms"] for r in results)})
        rows += [{"run": number, "case_id": w["case_id"], "scheme_id": w["scheme_id"], "language": w["language"],
                  "gold": w["gold"], "rule_engine": e, "llm": r["verdict"], "llm_reason": r.get("reason", ""),
                  "llm_clauses": r.get("clauses", []), "error": r["error"], "boundary": w["boundary"]}
                 for w, e, r in zip(work, engine, results)]
        if not quiet:
            print(f"  accuracy {runs[-1]['accuracy']}, boundary {runs[-1]['boundary_accuracy']} "
                  f"({runs[-1]['boundary_errors']} boundary errors)", file=sys.stderr, flush=True)
    summary = {
        "verdicts": len(work), "boundary_verdicts": sum(1 for w in work if w["boundary"]), "repeat": repeat,
        "rule_engine": score(work, engine),
        "llm_runs": runs,
        "llm": {key: spread([r[key] for r in runs]) for key in ("accuracy", "boundary_accuracy", "other_accuracy",
                                                              "errors", "boundary_errors")
                if all(r[key] is not None for r in runs)},
    }
    return rows, summary


def markdown(meta: dict[str, Any], summary: dict[str, Any]) -> str:
    eng, llm = summary["rule_engine"], summary["llm"]
    # A group can be empty (a short --limit run may have no boundary or no other verdicts).
    fmt = lambda s: "—" if s is None else f"{s['mean']:.3f} ({s['min']:.3f}–{s['max']:.3f})"
    cnt = lambda s: "—" if s is None else f"{s['mean']:.1f} ({s['min']}–{s['max']})"
    one = lambda v: "—" if v is None else f"{v:.3f}"
    lines = [
        "# E4: the LLM deciding directly, against the rule engine", "",
        f"Split: {meta['split']}, {summary['verdicts']} verdicts ({summary['boundary_verdicts']} at a boundary). "
        f"Model: `{meta['config'].get('model')}`. LLM runs: {summary['repeat']}, mean (min–max).", "",
        "| | Rule engine | LLM directly from the text |", "| --- | --- | --- |",
        f"| Accuracy, all verdicts | {one(eng['accuracy'])} | {fmt(llm.get('accuracy'))} |",
        f"| Accuracy, boundary verdicts | {one(eng['boundary_accuracy'])} | {fmt(llm.get('boundary_accuracy'))} |",
        f"| Accuracy, other verdicts | {one(eng['other_accuracy'])} | {fmt(llm.get('other_accuracy'))} |",
        f"| Wrong verdicts | {eng['errors']} | {cnt(llm.get('errors'))} |",
        f"| Boundary errors | {eng['boundary_errors']} | {cnt(llm.get('boundary_errors'))} |", "",
        "LLM errors in the first run:", "",
    ]
    lines += [f"- {w}" for w in summary["llm_runs"][0]["wrong"]] or ["- none"]
    return "\n".join(lines) + "\n"


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def write_run(config: dict, split: str, rows: list, summary: dict, runs_dir: Path = RUNS_DIR) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = runs_dir / f"{stamp}_{config['name']}_{split}"
    out.mkdir(parents=True, exist_ok=False)
    (out / "verdicts.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    meta = {"config": config, "split": split, "git_commit": _git_commit(), "finished_at": stamp}
    (out / "summary.json").write_text(json.dumps({**meta, "summary": summary}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "e4_report.md").write_text(markdown(meta, summary), encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", required=True)
    parser.add_argument("--split", choices=SPLITS, default="development")
    parser.add_argument("--final", action="store_true", help="required for the held-out split")
    parser.add_argument("--repeat", type=int, default=1, help="LLM runs (the brief: 3 for the final comparison)")
    parser.add_argument("--limit", type=int, help="only the first N cases")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.split == "held_out" and not args.final:
        parser.error("held-out cases are for the final evaluation only; add --final if this is it")
    config = e4.load_config(args.config)
    rows, summary = run(config, args.split, args.repeat, args.limit, workers=args.workers)
    out = write_run(config, args.split, rows, summary)
    print(markdown({"config": config, "split": args.split}, summary))
    print(f"Written to {out.relative_to(ROOT)}")
    return 1 if any(r["failed_calls"] for r in summary["llm_runs"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
