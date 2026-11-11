#!/usr/bin/env python3
"""Compare saved C0/C1/C2 runs for E1, with repeated runs and their spread.

    python tests/evaluation/e1_report.py --c0 <run> --c1 <run> <run> <run> --c2 <run> <run> <run>

The brief: compare C0, C1 and C2 on held-out, with the same model, tools and budget, and repeat
the final comparison three times, reporting the spread. C0 is deterministic, so one run is
enough. The report refuses a comparison that isn't fair: every run must be on the same split and
the same cases, name the same model and MCP call limit, and the models that actually used tokens
must match (C1 only the named model; C2 the named model plus one simulated citizen, the same in
every C2 run). Values are mean (min-max) over runs. Model spend uses the local price table.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = ROOT / "data" / "evaluation-runs"
EXPECTED = {"c0": "fixed_workflow", "c1": "single_agent", "c2": "agent_team"}
REPEATS = 3  # the brief's number of runs for the final comparison (C1 and C2)

# (label, how to read it from a run's summary)
MEASURES: list[tuple[str, Any]] = [
    ("Verdict accuracy", lambda s: s["verdict_accuracy"]),
    ("Cases fully right (rate)", lambda s: s["case_success_rate"]),
    ("Verdicts answered", lambda s: s["answered_rate"]),
    ("Right when answered", lambda s: s.get("accuracy_when_answered")),
    ("Shortlist recall", lambda s: s.get("shortlist_recall")),
    ("Cases flagged for unbacked claims (keyword check, unreviewed)",
     lambda s: s["cases_with_unbacked_eligibility_claims"]),
    ("Cases with fact errors", lambda s: s.get("cases_with_fact_errors")),
    ("Questions per case, mean", lambda s: s["questions_per_case"]["mean"]),
    ("Tool calls per case, mean", lambda s: s["tool_calls_per_case"]["mean"]),
    ("Latency median (s)", lambda s: _seconds(s["latency_ms"]["median"])),
    ("Latency p95 (s)", lambda s: _seconds(s["latency_ms"]["p95"])),
    ("Estimated cost per case (USD)", lambda s: s.get("estimated_cost_usd_per_case")),
    ("Failed cases (errors)", lambda s: s["errors"]),
]


def _seconds(ms: float | None) -> float | None:
    return None if ms is None else round(ms / 1000, 2)


def load_run(path: str | Path) -> dict[str, Any]:
    folder = Path(path)
    meta = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in (folder / "cases.jsonl").read_text(encoding="utf-8").splitlines() if line]
    return {"name": folder.name, "meta": meta, "summary": meta["summary"], "rows": rows}


def model_name(model_id: str) -> str:
    """'openai/gpt-4o-mini' and 'gpt-4o-mini-2024-07-18' -> 'gpt-4o-mini', to compare the configured
    model with the names the provider reports in token usage."""
    name = model_id.strip().lower().rsplit("/", 1)[-1]
    return re.sub(r"-(\d{4}-\d{2}-\d{2}|\d{8})$", "", name)


def other_models(run: dict[str, Any]) -> list[str]:
    """Models that used tokens in a run, other than the configured agent model."""
    agent = model_name(run["meta"]["config"].get("model") or "")
    return sorted(m for m in run["summary"].get("tokens_by_model", {}) if model_name(m) != agent)


def validate(runs: dict[str, list[dict[str, Any]]]) -> None:
    """Refuse a comparison that isn't fair."""
    if set(runs) != set(EXPECTED) or any(not runs[label] for label in EXPECTED):
        raise ValueError(f"Provide at least one run for each of: {', '.join(EXPECTED)}.")
    every = [run for label in EXPECTED for run in runs[label]]
    for label, items in runs.items():
        for run in items:
            if run["meta"]["config"].get("system") != EXPECTED[label]:
                raise ValueError(f"{label} must be a {EXPECTED[label]} run ({run.get('name', '?')}).")
    models = {run["meta"]["config"].get("model") for run in every}
    if len(models) != 1 or None in models or "" in models:
        raise ValueError("C0, C1 and C2 run metadata must name the same explicit model.")
    budgets = {run["meta"]["config"].get("tool_call_limit") for run in every}
    if len(budgets) != 1 or None in budgets:
        raise ValueError("All three systems must use the same explicit MCP tool-call limit.")
    if len({run["meta"].get("split") for run in every}) != 1:
        raise ValueError("All systems must use the same gold-set split.")
    case_sets = [{row["case_id"] for row in run["rows"]} for run in every]
    if any(cases != case_sets[0] for cases in case_sets[1:]):
        raise ValueError("All systems must run exactly the same cases.")
    # The models that really ran: a model set elsewhere (e.g. ROUTER_MODEL) would show up here.
    for run in runs["c1"]:
        if other_models(run):
            raise ValueError(f"C1 run {run.get('name', '?')} used other models: {', '.join(other_models(run))}.")
    citizens = set()
    for run in runs["c2"]:
        extra = other_models(run)
        if len(extra) > 1:
            raise ValueError(f"C2 run {run.get('name', '?')} used more than one model besides the agents' "
                             f"(only the simulated citizen should differ): {', '.join(extra)}.")
        citizens.add(model_name(extra[0]) if extra else None)
    if len(citizens) > 1:
        raise ValueError(f"Every C2 run must use the same simulated citizen, got {sorted(map(str, citizens))}.")


def spread(values: list[Any]) -> dict[str, Any] | None:
    values = [v for v in values if v is not None]
    if not values:
        return None
    return {"mean": round(statistics.mean(values), 4), "min": min(values), "max": max(values), "runs": len(values)}


def report(runs: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    validate(runs)
    first = runs["c0"][0]["meta"]
    citizen = next((m for run in runs["c2"] for m in other_models(run)), None)
    notes = []
    for label in ("c1", "c2"):
        if len(runs[label]) < REPEATS:
            notes.append(f"{label.upper()} has {len(runs[label])} run(s); the brief asks for {REPEATS} "
                         "in the final comparison.")
    commits = {run["meta"].get("git_commit") for label in ("c1", "c2") for run in runs[label]}
    if len(commits) > 1:
        notes.append(f"C1/C2 runs come from different commits: {', '.join(sorted(map(str, commits)))}.")
    return {
        "model": first["config"]["model"],
        "citizen_model": citizen,
        "split": first["split"],
        "tool_call_limit": first["config"]["tool_call_limit"],
        "cases": len(runs["c0"][0]["rows"]),
        "runs": {label: [{"run": run.get("name"), "git_commit": run["meta"].get("git_commit"),
                          "models_used": sorted(run["summary"].get("tokens_by_model", {}))}
                         for run in runs[label]] for label in EXPECTED},
        "measures": {name: {label: spread([read(run["summary"]) for run in runs[label]]) for label in EXPECTED}
                     for name, read in MEASURES},
        "notes": notes,
        "comparison_limits": (
            "C0 is deterministic and uses no model. C0 and C1 evaluate the gold candidate schemes; C1 is "
            "given the case profile through bound tools and asks no questions, and its verdicts are read "
            "from its rule-engine tool results, not from what its final reply told the person. C2 selects "
            "its own shortlist, interviews a separate simulated-citizen model, and a verdict counts only "
            "once the person was told it. C2's cost includes the simulated citizen, which stands in for "
            "the person. Cost is an estimate from observability/model_prices.json, not an invoice."
        ),
    }


def _fmt(value: dict[str, Any] | None) -> str:
    if value is None:
        return "—"
    one = lambda v: f"{v:.4g}" if isinstance(v, float) else str(v)
    if value["runs"] == 1 or value["min"] == value["max"]:
        return one(value["mean"]) if value["runs"] == 1 else f"{one(value['mean'])} (all runs)"
    return f"{one(value['mean'])} ({one(value['min'])}–{one(value['max'])})"


def markdown(data: dict[str, Any]) -> str:
    counts = {label: len(items) for label, items in data["runs"].items()}
    lines = [
        "# E1: does the agent team justify its cost?",
        "",
        f"Split: `{data['split']}`, {data['cases']} cases. Agent model: `{data['model']}`; simulated citizen "
        f"(C2): `{data['citizen_model']}`. MCP-call limit per case: {data['tool_call_limit']}. "
        f"Runs: C0 {counts['c0']}, C1 {counts['c1']}, C2 {counts['c2']}. Values are mean (min–max) over runs.",
        "",
        "| Measure | C0 fixed workflow | C1 single agent | C2 agent team |",
        "| --- | --- | --- | --- |",
    ]
    for name, values in data["measures"].items():
        lines.append(f"| {name} | {_fmt(values['c0'])} | {_fmt(values['c1'])} | {_fmt(values['c2'])} |")
    lines += ["", "## Runs", "", "| System | Run | Commit | Models that used tokens |", "| --- | --- | --- | --- |"]
    for label, items in data["runs"].items():
        for run in items:
            lines.append(f"| {label.upper()} | `{run['run']}` | `{run['git_commit']}` | "
                         f"{', '.join(run['models_used']) or 'none'} |")
    lines += ["", "## Limits of the comparison", "", data["comparison_limits"], ""]
    if data["notes"]:
        lines += ["## Notes", ""] + [f"- {note}" for note in data["notes"]] + [""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for label in EXPECTED:
        parser.add_argument(f"--{label}", nargs="+", required=True, metavar="RUN_DIR",
                            help=f"saved {label.upper()} run directories")
    args = parser.parse_args()
    runs = {label: [load_run(path) for path in getattr(args, label)] for label in EXPECTED}
    data = report(runs)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = RUNS_DIR / f"{stamp}_e1_report_{data['split']}"
    output.mkdir(parents=True, exist_ok=False)
    (output / "e1_report.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    (output / "e1_report.md").write_text(markdown(data), encoding="utf-8")
    print(markdown(data))
    print(f"Written to {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
