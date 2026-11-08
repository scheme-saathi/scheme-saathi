"""Run one experiment config over a gold-set split and score it against the human labels.

    python tests/evaluation/run_eval.py --config tests/evaluation/configs/c0_fixed_workflow.json
    python tests/evaluation/run_eval.py --config ... --split held_out --final   # final evaluation only

Each experiment is a config file, not a code branch (brief, "Four experiments, one harness").
Results go to data/evaluation-runs/<time>_<config>_<split>/: cases.jsonl (one row per case)
and summary.json. That folder is git-ignored.

Systems
    fixed_workflow  C0: graph/workflow.py, no model. Code picks each question (the one that
                    settles most open verdicts) and the answer comes straight from the case's
                    hidden profile; a null answer is "don't know".
    agent_team      C2: graph/agent_workflow.py (supervisor + specialists) talking to the
                    simulated citizen in simulated_citizen.py. The team picks its own schemes
                    (scheme_selection "system"); the confirm step is approved as shown, and any
                    confirmed fact that differs from the hidden profile is recorded.
    single_agent    C1: graph/baseline.py with the same tools (not built yet).
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from graph import tools  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
GOLD_DIR = EVAL_DIR / "eligibility_gold_v1"
RUNS_DIR = ROOT / "data" / "evaluation-runs"
SPLITS = ("development", "held_out")


def load_cases(split: str) -> list[dict]:
    path = GOLD_DIR / split / "cases.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_config(path: str | Path) -> dict:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("name", "system", "scheme_selection"):
        if key not in config:
            raise ValueError(f"config {path} is missing '{key}'")
    if config["scheme_selection"] not in {"candidates", "system"}:
        raise ValueError("scheme_selection must be 'candidates' or 'system'")
    if config["system"] == "agent_team" and config["scheme_selection"] != "system":
        raise ValueError("agent_team picks its own schemes: use scheme_selection 'system'")
    return config


# ---------------------------------------------------------------- systems

def run_fixed_workflow(case: dict, config: dict) -> dict:
    """C0: the deterministic workflow answers its own questions from the hidden profile."""
    from graph.workflow import build_graph

    citizen = {field: value for field, value in case["hidden_profile"].items() if value is not None}
    request: dict[str, Any] = {"simulated_citizen": citizen}
    if config["scheme_selection"] == "candidates":
        request["scheme_ids"] = list(case["candidate_scheme_ids"])
    graph = build_graph()
    thread = {"configurable": {"thread_id": f"eval-{case['case_id']}-{uuid.uuid4().hex[:8]}"}}
    with tools.tool_call_budget(config.get("tool_call_limit", 1200)) as budget:
        state = graph.invoke(request, thread)
    asked = [field for field in state.get("profile", {})]
    return {
        "verdicts": {scheme: v["verdict"] for scheme, v in state.get("verdicts", {}).items()},
        "questions_asked": state.get("questions_asked", 0),
        "asked_fields": asked,
        "tool_calls": budget.used,
        "stopped_at": "approval" if "__interrupt__" in state else "end",
    }


ACTOR_ID = "eval-runner"


def _pending(graph: Any, thread: dict) -> dict | None:
    """What the graph is waiting for (confirm step or approval gate), or None."""
    for task in graph.get_state(thread).tasks:
        for pending in task.interrupts:
            return pending.value
    return None


def run_agent_team(case: dict, config: dict, graph: Any = None, citizen: Any = None) -> dict:
    """C2: the agent team holds the whole conversation with the simulated citizen."""
    from langchain_core.callbacks import get_usage_metadata_callback
    from langgraph.types import Command

    if graph is None:
        from langgraph.checkpoint.memory import MemorySaver
        from graph.agent_workflow import build_agent_graph
        graph = build_agent_graph(checkpointer=MemorySaver())
    if citizen is None:
        sys.path.insert(0, str(EVAL_DIR))
        from simulated_citizen import SimulatedCitizen
        citizen = SimulatedCitizen.from_environment(case, config.get("allow_same_model_family", False))
    thread = {"configurable": {"thread_id": f"eval-{case['case_id']}-{uuid.uuid4().hex[:8]}"}}
    transcript = [{"role": "citizen", "text": case["opening_message"]}]
    questions = confirmations = 0
    fact_errors: list[str] = []
    stopped_at = "max_turns"
    with tools.tool_call_budget(config.get("tool_call_limit", 400)) as budget, \
            get_usage_metadata_callback() as usage:
        result = graph.invoke({"request": case["opening_message"], "actor_id": ACTOR_ID}, thread)
        for _ in range(config.get("max_turns", 20)):
            pending = _pending(graph, thread)
            if pending is not None and pending.get("kind") == "confirm_facts":
                confirmations += 1
                for field, value in pending.get("facts", {}).items():
                    truth = case["hidden_profile"].get(field)
                    if field in case["hidden_profile"] and value != truth:
                        fact_errors.append(f"{field}: confirmed {value!r}, hidden profile {truth!r}")
                transcript.append({"role": "confirm", "text": json.dumps(pending.get("facts", {}), ensure_ascii=False)})
                result = graph.invoke(Command(resume={"action": "approve", "payload_hash": pending["payload_hash"]}), thread)
                continue
            if pending is not None:
                stopped_at = "awaiting_approval"
                break
            status = result.get("status")
            if status == "needs_information":
                questions += 1
                question = result.get("response", "")
                answer = citizen.answer(question)
                transcript += [{"role": "agent", "text": question}, {"role": "citizen", "text": answer}]
                result = graph.invoke({"request": answer, "actor_id": ACTOR_ID}, thread)
                continue
            transcript.append({"role": "agent", "text": result.get("response", "")})
            stopped_at = status or "end"
            break
    values = graph.get_state(thread).values
    return {
        "verdicts": {scheme: v["verdict"] for scheme, v in (values.get("verdicts") or {}).items()},
        "shortlist": values.get("shortlist", []),
        "questions_asked": questions,
        "confirmations": confirmations,
        "fact_errors": fact_errors,
        "tool_calls": budget.used,
        "tokens": {model: dict(u) for model, u in usage.usage_metadata.items()},
        "stopped_at": stopped_at,
        "transcript": transcript,
    }


def _not_built(name: str) -> Callable[[dict, dict], dict]:
    def run(case: dict, config: dict) -> dict:
        raise NotImplementedError(f"system '{name}' is not built yet")
    return run


SYSTEMS: dict[str, Callable[[dict, dict], dict]] = {
    "fixed_workflow": run_fixed_workflow,
    "agent_team": run_agent_team,
    "single_agent": _not_built("single_agent"),
}


# ---------------------------------------------------------------- scoring

def score_case(case: dict, result: dict) -> dict:
    """Compare a system's verdicts with the gold labels, on the case's candidate schemes only."""
    per_scheme = {}
    for scheme_id in case["candidate_scheme_ids"]:
        gold = case["expected"][scheme_id]["verdict"]
        got = result.get("verdicts", {}).get(scheme_id, "missing")
        per_scheme[scheme_id] = {"gold": gold, "got": got, "correct": gold == got}
    return {
        "per_scheme": per_scheme,
        "case_correct": bool(per_scheme) and all(s["correct"] for s in per_scheme.values()),
        # schemes the system evaluated beyond the gold candidates are reported, never scored
        "unscored_schemes": sorted(set(result.get("verdicts", {})) - set(case["candidate_scheme_ids"])),
    }


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[index]


def summarise(rows: list[dict]) -> dict:
    scored = [r for r in rows if r["error"] is None]
    verdicts = [s for r in scored for s in r["score"]["per_scheme"].values()]
    confusion = Counter(f"{s['gold']}->{s['got']}" for s in verdicts)
    by_scheme: dict[str, list[bool]] = defaultdict(list)
    for r in scored:
        for scheme_id, s in r["score"]["per_scheme"].items():
            by_scheme[scheme_id].append(s["correct"])
    got_by_case = {r["case_id"]: r["result"]["verdicts"] for r in scored}
    consistency = []
    for r in scored:
        source = r.get("variant_of")
        if source and source in got_by_case:
            same = all(got_by_case[r["case_id"]].get(s) == got_by_case[source].get(s) for s in r["score"]["per_scheme"])
            consistency.append(same)
    latencies = [r["latency_ms"] for r in rows]
    questions = [r["result"]["questions_asked"] for r in scored]
    tool_calls = [r["result"]["tool_calls"] for r in scored if "tool_calls" in r["result"]]
    return {
        "cases": len(rows),
        "errors": len(rows) - len(scored),
        "error_cases": [r["case_id"] for r in rows if r["error"] is not None],
        "verdicts_scored": len(verdicts),
        "verdict_accuracy": round(sum(s["correct"] for s in verdicts) / len(verdicts), 4) if verdicts else None,
        "case_success": sum(r["score"]["case_correct"] for r in scored),
        "case_success_rate": round(sum(r["score"]["case_correct"] for r in scored) / len(rows), 4) if rows else None,
        "cant_tell_rate": round(sum(s["got"] == "cant_tell" for s in verdicts) / len(verdicts), 4) if verdicts else None,
        "confusion": dict(sorted(confusion.items())),
        "accuracy_by_scheme": {k: round(sum(v) / len(v), 4) for k, v in sorted(by_scheme.items())},
        "wrong": [f"{r['case_id']} {k}: gold {s['gold']}, got {s['got']}"
                  for r in scored for k, s in r["score"]["per_scheme"].items() if not s["correct"]],
        "language_consistency": {"pairs": len(consistency), "same_verdicts": sum(consistency)},
        "questions_per_case": {"mean": round(statistics.mean(questions), 2) if questions else None,
                               "median": statistics.median(questions) if questions else None,
                               "max": max(questions) if questions else None},
        "tool_calls_per_case": {"mean": round(statistics.mean(tool_calls), 2) if tool_calls else None,
                                "max": max(tool_calls) if tool_calls else None},
        "latency_ms": {"median": _percentile(latencies, 50), "p95": _percentile(latencies, 95)},
        "cases_with_fact_errors": sum(bool(r["result"].get("fact_errors")) for r in scored),
        "tokens_by_model": _token_totals(scored),
    }


def _token_totals(rows: list[dict]) -> dict:
    totals: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        for model, used in r["result"].get("tokens", {}).items():
            totals[model].update({k: v for k, v in used.items() if isinstance(v, int)})
    return {model: dict(c) for model, c in totals.items()}


# ---------------------------------------------------------------- running

def run(config: dict, split: str, limit: int | None = None) -> tuple[list[dict], dict]:
    system = SYSTEMS[config["system"]]
    cases = load_cases(split)[:limit] if limit else load_cases(split)
    rows = []
    for case in cases:
        started = time.perf_counter()
        try:
            result, error = system(case, config), None
        except Exception as exc:  # a failed or timed-out run is reported, never dropped
            result, error = {"verdicts": {}, "questions_asked": 0}, f"{type(exc).__name__}: {exc}"
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        rows.append({
            "case_id": case["case_id"], "family_id": case["family_id"], "language": case["language"],
            "variant_of": case.get("variant_of"), "result": result, "error": error,
            "score": score_case(case, result), "latency_ms": latency_ms,
        })
    return rows, summarise(rows)


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def write_run(config: dict, split: str, rows: list[dict], summary: dict, runs_dir: Path = RUNS_DIR) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = runs_dir / f"{stamp}_{config['name']}_{split}"
    out.mkdir(parents=True, exist_ok=False)
    (out / "cases.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    meta = {"config": config, "split": split, "git_commit": _git_commit(), "finished_at": stamp}
    (out / "summary.json").write_text(json.dumps({**meta, "summary": summary}, indent=2, ensure_ascii=False),
                                      encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", required=True)
    parser.add_argument("--split", choices=SPLITS, default="development")
    parser.add_argument("--final", action="store_true", help="required for the held-out split")
    parser.add_argument("--limit", type=int, help="run only the first N cases")
    args = parser.parse_args()
    if args.split == "held_out" and not args.final:
        parser.error("held-out cases are for the final evaluation only; add --final if this is it")
    config = load_config(args.config)
    rows, summary = run(config, args.split, args.limit)
    out = write_run(config, args.split, rows, summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nWritten to {out.relative_to(ROOT)}")
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
