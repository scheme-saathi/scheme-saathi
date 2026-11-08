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
import re
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
VERDICTS = {"eligible", "not_eligible", "cant_tell"}


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
    working = {scheme: v["verdict"] for scheme, v in (values.get("verdicts") or {}).items()}
    return {
        **final_answer(working, confirmations, stopped_at),
        "unbacked_eligibility_claims": eligibility_claims(transcript),
        "shortlist": values.get("shortlist", []),
        "questions_asked": questions,
        "confirmations": confirmations,
        "fact_errors": fact_errors,
        "tool_calls": budget.used,
        "tokens": {model: dict(u) for model, u in usage.usage_metadata.items()},
        "stopped_at": stopped_at,
        "transcript": transcript,
    }


# Statuses at which the person has been given the rule engine's answer on confirmed facts.
FINAL_STATUSES = {"eligibility_checked", "awaiting_approval", "documents_checked", "draft_needs_information", "submitted"}


def final_answer(working: dict[str, str], confirmations: int, stopped_at: str) -> dict:
    """Split the verdicts the person was told from the graph's working verdicts.

    A verdict counts only once the conversation reached a final, confirmed answer. When intake
    stops or a question is answered elsewhere, the person hears no verdict, so none is scored.
    """
    told = confirmations > 0 and stopped_at in FINAL_STATUSES
    return {"verdicts": dict(working) if told else {}, "working_verdicts": dict(working)}


_ENGINE_LINE = re.compile(r"^\s*[CM]\d{2}:\s*(eligible|not_eligible|cant_tell)\b", re.M)
_CLAIM_PATTERNS = [re.compile(p, re.I) for p in (
    r"\b(?:you|she|he|they|your \w+|the applicant)\s+(?:can|could|will|may|should|would)\s+(?:also\s+)?"
    r"(?:get|receive|avail|join|apply for|qualify|be eligible)\b",
    r"\b(?:is|are|am)\s+(?:not\s+)?eligible\b",
    r"\b(?:in)?eligible for\b",
    r"\bqualif(?:y|ies)\b",
    r"पात्र", r"मिल सकत", r"मिलेग[ीा]", r"मिळू शकत", r"मिळेल",
)]


def _safe_fallbacks() -> set[str]:
    """The workflow's own replies offering a proper eligibility check; they are not claims."""
    try:
        from graph.agent_workflow import CHECK_ELIGIBILITY_INSTEAD
    except ImportError:  # an older workflow without it
        return set()
    return {text.strip() for text in CHECK_ELIGIBILITY_INSTEAD.values()}


def eligibility_claims(transcript: list[dict]) -> list[str]:
    """Agent statements that tell the person they qualify (or don't) without the rule engine.

    Rule-engine verdict lines ("C06: eligible: ...") and questions are not claims. This is a
    keyword check, so it can miss a claim or flag a harmless sentence; an LLM judge can
    confirm the flagged ones.
    """
    claims = []
    safe = _safe_fallbacks()
    for turn in transcript:
        text = turn.get("text", "")
        if turn.get("role") != "agent" or text.rstrip().endswith("?") or _ENGINE_LINE.search(text):
            continue
        if text.strip() in safe:
            continue
        if any(p.search(text) for p in _CLAIM_PATTERNS):
            claims.append(text)
    return claims


def normalise_result(result: dict, system: str) -> dict:
    """Bring a result saved by an older runner version up to the current scoring rules."""
    if system != "agent_team" or "working_verdicts" in result:
        return result
    return {
        **result,
        **final_answer(result.get("verdicts", {}), result.get("confirmations", 0), result.get("stopped_at", "")),
        "unbacked_eligibility_claims": eligibility_claims(result.get("transcript", [])),
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
    told = result.get("verdicts", {})
    evaluated = result.get("working_verdicts", told)
    per_scheme = {}
    for scheme_id in case["candidate_scheme_ids"]:
        gold = case["expected"][scheme_id]["verdict"]
        if scheme_id in told:
            got = told[scheme_id]
        elif scheme_id in evaluated:
            got = "no_final_answer"  # checked, but the person was never told a verdict
        else:
            got = "not_evaluated"  # never shortlisted or checked
        per_scheme[scheme_id] = {"gold": gold, "got": got, "correct": gold == got,
                                 "evaluated": scheme_id in evaluated}
    return {
        "per_scheme": per_scheme,
        "case_correct": bool(per_scheme) and all(s["correct"] for s in per_scheme.values()),
        # schemes the system evaluated beyond the gold candidates are reported, never scored
        "unscored_schemes": sorted(set(evaluated) - set(case["candidate_scheme_ids"])),
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
    answered = [s for s in verdicts if s["got"] in VERDICTS]
    claims = [r["case_id"] for r in scored if r["result"].get("unbacked_eligibility_claims")]
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
        "shortlist_recall": round(sum(s["evaluated"] for s in verdicts) / len(verdicts), 4) if verdicts else None,
        "answered_rate": round(len(answered) / len(verdicts), 4) if verdicts else None,
        "accuracy_when_answered": round(sum(s["correct"] for s in answered) / len(answered), 4) if answered else None,
        "cases_with_unbacked_eligibility_claims": len(claims),
        "unbacked_eligibility_claim_cases": claims,
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
        # how each conversation ended, e.g. eligibility_checked, intake_stopped, answered, output_blocked
        "stopped_at": dict(Counter(r["result"].get("stopped_at", "unknown") for r in scored).most_common()),
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


def rescore(run_dir: str | Path) -> tuple[list[dict], dict]:
    """Score a saved run again with the current rules; the model is not called."""
    run_dir = Path(run_dir)
    meta = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    cases = {c["case_id"]: c for c in load_cases(meta["split"])}
    rows = []
    for line in (run_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        row["result"] = normalise_result(row["result"], meta["config"]["system"])
        row["score"] = score_case(cases[row["case_id"]], row["result"])
        rows.append(row)
    summary = summarise(rows)
    (run_dir / "summary_rescored.json").write_text(
        json.dumps({**meta, "rescored_at": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
                    "rescored_with_commit": _git_commit(), "summary": summary}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    return rows, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rescore", metavar="RUN_DIR", help="score a saved run again; writes summary_rescored.json")
    parser.add_argument("--config")
    parser.add_argument("--split", choices=SPLITS, default="development")
    parser.add_argument("--final", action="store_true", help="required for the held-out split")
    parser.add_argument("--limit", type=int, help="run only the first N cases")
    args = parser.parse_args()
    if args.rescore:
        _, summary = rescore(args.rescore)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        print(f"\nWritten to {Path(args.rescore) / 'summary_rescored.json'}")
        return 0
    if not args.config:
        parser.error("--config is required (or --rescore RUN_DIR)")
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
