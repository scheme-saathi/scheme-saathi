#!/usr/bin/env python3
"""Compare saved C0/C1/C2 runs for E1.

    python tests/evaluation/e1_report.py --c0 <run> --c1 <run> --c2 <run>

Runs must use identical cases and MCP call budgets and name the same model. C0 itself
does not call a model. Model spend uses the configured local price table and is marked
unknown if any model in a run has no price.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = ROOT / "data" / "evaluation-runs"
EXPECTED = {"c0": "fixed_workflow", "c1": "single_agent", "c2": "agent_team"}


def load_run(path: str | Path) -> dict[str, Any]:
    folder = Path(path)
    meta = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in (folder / "cases.jsonl").read_text(encoding="utf-8").splitlines() if line]
    return {"name": folder.name, "meta": meta, "summary": meta["summary"], "rows": rows}


def validate(runs: dict[str, dict[str, Any]]) -> None:
    if set(runs) != set(EXPECTED):
        raise ValueError(f"Provide exactly these systems: {', '.join(EXPECTED)}.")
    for label, run in runs.items():
        config = run["meta"]["config"]
        if config.get("system") != EXPECTED[label]:
            raise ValueError(f"{label} must be a {EXPECTED[label]} run.")
    configs = [run["meta"]["config"] for run in runs.values()]
    models = {c.get("model") for c in configs}
    if len(models) != 1 or None in models or "" in models:
        raise ValueError("C0, C1 and C2 run metadata must name the same explicit model.")
    budgets = {c.get("tool_call_limit") for c in configs}
    if len(budgets) != 1 or None in budgets:
        raise ValueError("All three systems must use the same explicit MCP tool-call limit.")
    splits = {run["meta"].get("split") for run in runs.values()}
    if len(splits) != 1:
        raise ValueError("All systems must use the same gold-set split.")
    case_sets = [{row["case_id"] for row in run["rows"]} for run in runs.values()]
    if any(cases != case_sets[0] for cases in case_sets[1:]):
        raise ValueError("All systems must run exactly the same cases.")


def report(runs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    validate(runs)
    return {
        "model": next(iter(runs.values()))["meta"]["config"]["model"],
        "split": next(iter(runs.values()))["meta"]["split"],
        "tool_call_limit": next(iter(runs.values()))["meta"]["config"]["tool_call_limit"],
        "runs": {
            label: {
                "run": run["name"],
                "cases": run["summary"]["cases"],
                "errors": run["summary"]["errors"],
                "task_success": run["summary"]["case_success"],
                "task_success_rate": run["summary"]["case_success_rate"],
                "verdict_accuracy": run["summary"]["verdict_accuracy"],
                "answered_rate": run["summary"]["answered_rate"],
                "unbacked_eligibility_claim_cases": run["summary"]["cases_with_unbacked_eligibility_claims"],
                "fact_error_cases": run["summary"]["cases_with_fact_errors"],
                "questions_per_case": run["summary"]["questions_per_case"],
                "tool_calls_per_case": run["summary"]["tool_calls_per_case"],
                "latency_ms": run["summary"]["latency_ms"],
                "estimated_cost_usd_per_case": run["summary"].get("estimated_cost_usd_per_case"),
                "unpriced_model_cases": run["summary"].get("unpriced_model_cases"),
            }
            for label, run in runs.items()
        },
        "note": (
            "C0 is deterministic and uses no model. C1 receives the case profile through bound "
            "tools and is given the complete single-agent tool set; C2 uses role-scoped graph "
            "tools, interacts with a separate simulated-citizen model and selects its own scheme "
            "shortlist. These tool-interface, interaction and scheme-selection differences limit "
            "causal attribution to agent architecture. Cost is an estimate from "
            "observability/model_prices.json, not a provider invoice."
        ),
    }


def markdown(data: dict[str, Any]) -> str:
    lines = [
        "# E1: does the agent team justify its cost?",
        "",
        f"Split: `{data['split']}`; model: `{data['model']}`; MCP-call limit per case: "
        f"{data['tool_call_limit']}. C0 is deterministic; C1 and C2 use the named model.",
        "",
        "| System | Task success | Verdict accuracy | Answered | Unbacked claims | Fact errors | Questions/case | Tool calls/case | Latency median / p95 (ms) | Estimated model cost/case (USD) | Errors |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label in ("c0", "c1", "c2"):
        row = data["runs"][label]
        latency = row["latency_ms"]
        questions = row["questions_per_case"]
        calls = row["tool_calls_per_case"]
        cost = row["estimated_cost_usd_per_case"]
        lines.append(
            f"| {label.upper()} | {row['task_success']}/{row['cases']} "
            f"({row['task_success_rate']}) | {row['verdict_accuracy']} | {row['answered_rate']} | "
            f"{row['unbacked_eligibility_claim_cases']} | {row['fact_error_cases']} | "
            f"{questions['mean']} | {calls['mean']} | {latency['median']} / {latency['p95']} | "
            f"{'unknown' if cost is None else f'{cost:.8f}'} | {row['errors']} |"
        )
    lines += ["", data["note"], ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for label in EXPECTED:
        parser.add_argument(f"--{label}", required=True, help=f"saved {label.upper()} run directory")
    args = parser.parse_args()
    runs = {label: load_run(getattr(args, label)) for label in EXPECTED}
    data = report(runs)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = RUNS_DIR / f"{stamp}_e1_report"
    output.mkdir(parents=True, exist_ok=False)
    (output / "e1_report.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    (output / "e1_report.md").write_text(markdown(data), encoding="utf-8")
    print(markdown(data))
    print(f"\nWritten to {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
