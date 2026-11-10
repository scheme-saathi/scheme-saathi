#!/usr/bin/env python3
"""E3, did the lessons help? Compare held-out runs without and with the frozen playbook.

    python tests/evaluation/e3_report.py \
        --before data/evaluation-runs/<rx0 held-out run> <...> <...> \
        --after  data/evaluation-runs/<rx1 held-out run> <...> <...> \
        --reflection data/evaluation-runs/<development run>/reflection.json <...>

The brief: compare held-out results before and after adding the playbook, repeat the final
comparison three times and report the spread, include the cost of generating lessons, and
identify any lesson that made results worse. The report checks that every run is on the
held-out split, that both sides used the same model, that "before" runs had no lessons and that
every "after" run used the same frozen playbook. It writes e3_report.md and e3_report.json.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = ROOT / "data" / "evaluation-runs"

MEASURES = [  # (key in a run's summary, label, higher is better)
    ("condition_f1", "Condition F1", True),
    ("condition_precision", "Condition precision", True),
    ("condition_recall", "Condition recall", True),
    ("rule_exact_rate", "Rules exactly right", True),
    ("scheme_exact_rate", "Schemes exactly right", True),
]
ERROR_TYPES = ("missing_rule", "extra_rule", "wrong_field", "wrong_operator", "wrong_value",
               "wrong_or", "wrong_clause", "wrong_logic")


def load_run(path: str | Path) -> dict[str, Any]:
    folder = Path(path)
    meta = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in (folder / "schemes.jsonl").read_text(encoding="utf-8").splitlines() if line]
    return {"name": folder.name, "meta": meta, "summary": meta["summary"], "rows": {r["scheme_id"]: r for r in rows}}


def check(before: list[dict], after: list[dict]) -> None:
    """Refuse a comparison that isn't fair."""
    runs = before + after
    if any(r["meta"]["split"] != "held_out" for r in runs):
        raise ValueError("E3 compares held-out runs only")
    models = {r["meta"]["config"].get("model") for r in runs}
    if len(models) != 1:
        raise ValueError(f"before and after must use the same model, got {sorted(map(str, models))}")
    if any(r["meta"]["config"].get("playbook") for r in before):
        raise ValueError("a 'before' run used a playbook")
    versions = {(r["meta"].get("playbook") or {}).get("frozen_hash") for r in after}
    if None in versions or len(versions) != 1 or not all((r["meta"].get("playbook") or {}).get("frozen") for r in after):
        raise ValueError("every 'after' run must use the same frozen playbook")
    schemes = [set(r["rows"]) for r in runs]
    if any(s != schemes[0] for s in schemes):
        raise ValueError("all runs must cover the same schemes")


def spread(values: list[float]) -> dict[str, float]:
    return {"mean": round(statistics.mean(values), 4), "min": round(min(values), 4), "max": round(max(values), 4),
            "sd": round(statistics.stdev(values), 4) if len(values) > 1 else 0.0}


def _tokens(summaries: list[dict]) -> Counter:
    total = Counter()
    for s in summaries:
        for used in s.get("tokens_by_model", {}).values():
            total.update({k: v for k, v in used.items() if isinstance(v, int)})
    return total


def report(before: list[dict], after: list[dict], reflections: list[dict]) -> dict[str, Any]:
    check(before, after)
    measures = {key: {"label": label, "before": spread([r["summary"][key] for r in before]),
                      "after": spread([r["summary"][key] for r in after])} for key, label, _ in MEASURES}
    for m in measures.values():
        m["change"] = round(m["after"]["mean"] - m["before"]["mean"], 4)
        m["beyond_spread"] = m["after"]["min"] > m["before"]["max"] or m["after"]["max"] < m["before"]["min"]
    errors = {t: {"before": spread([r["summary"]["errors_by_type"][t] for r in before]),
                  "after": spread([r["summary"]["errors_by_type"][t] for r in after])} for t in ERROR_TYPES}

    # Per scheme: did the lessons it received help or hurt? Worse = every after run below every before run.
    schemes, by_lesson = {}, defaultdict(list)
    for sid in sorted(before[0]["rows"]):
        b = [r["rows"][sid]["score"]["condition_f1"] for r in before]
        a = [r["rows"][sid]["score"]["condition_f1"] for r in after]
        lessons = sorted({lid for r in after for lid in r["rows"][sid]["lessons"]})
        verdict = "better" if min(a) > max(b) else "worse" if max(a) < min(b) else "no clear change"
        schemes[sid] = {"before": spread(b), "after": spread(a), "lessons": lessons, "verdict": verdict}
        for lid in lessons:
            by_lesson[lid].append((sid, verdict, statistics.mean(a) - statistics.mean(b)))
    lessons = {lid: {"schemes": [s for s, _, _ in items],
                     "better": [s for s, v, _ in items if v == "better"],
                     "worse": [s for s, v, _ in items if v == "worse"],
                     "mean_f1_change": round(statistics.mean(d for _, _, d in items), 4)}
               for lid, items in sorted(by_lesson.items())}

    reflection_tokens = Counter()
    for item in reflections:
        reflection_tokens.update({k: v for k, v in item.get("reflection_tokens", {}).items() if isinstance(v, int)})
    meta = after[0]["meta"]
    return {
        "model": meta["config"].get("model"),
        "playbook": meta.get("playbook"),
        "before_runs": [r["name"] for r in before],
        "after_runs": [r["name"] for r in after],
        "schemes": len(before[0]["rows"]),
        "measures": measures,
        "errors_by_type": errors,
        "failed_extractions": {"before": [r["summary"].get("errors", 0) for r in before],
                               "after": [r["summary"].get("errors", 0) for r in after]},
        "per_scheme": schemes,
        "per_lesson": lessons,
        "lessons_that_made_results_worse": sorted(lid for lid, v in lessons.items() if v["worse"]),
        "cost": {
            "reflection_tokens": dict(reflection_tokens),
            "reflection_runs": len(reflections),
            "extraction_tokens_per_run_before": round(sum(_tokens([r["summary"]]).get("total_tokens", 0) for r in before) / len(before)),
            "extraction_tokens_per_run_after": round(sum(_tokens([r["summary"]]).get("total_tokens", 0) for r in after) / len(after)),
        },
    }


def markdown(result: dict[str, Any]) -> str:
    fmt = lambda s: f"{s['mean']:.3f} ({s['min']:.3f}–{s['max']:.3f})"
    lines = [
        "# E3: did the lessons help?",
        "",
        f"Held-out split: {result['schemes']} hand-coded gold schemes. Model: `{result['model']}`. "
        f"Playbook: {result['playbook']['approved_lessons']} approved lessons, frozen version "
        f"`{result['playbook']['frozen_hash']}`. {len(result['before_runs'])} runs without lessons, "
        f"{len(result['after_runs'])} with. Values are mean (min–max) over runs.",
        "",
        "| Measure | Without lessons | With frozen lessons | Change | Beyond run-to-run spread? |",
        "| --- | --- | --- | --- | --- |",
    ]
    for m in result["measures"].values():
        lines.append(f"| {m['label']} | {fmt(m['before'])} | {fmt(m['after'])} | {m['change']:+.3f} | "
                     f"{'yes' if m['beyond_spread'] else 'no'} |")
    lines += ["", "| Errors by type (mean per run) | Without | With |", "| --- | --- | --- |"]
    for t, e in result["errors_by_type"].items():
        lines.append(f"| {t} | {e['before']['mean']:.1f} | {e['after']['mean']:.1f} |")
    lines += ["", f"Failed extractions per run: without {result['failed_extractions']['before']}, "
                  f"with {result['failed_extractions']['after']}.", "",
              "## Schemes", "", "Better or worse means every run with lessons scored above (or below) every run without.", "",
              "| Scheme | F1 without | F1 with | Lessons received | Result |", "| --- | --- | --- | --- | --- |"]
    for sid, s in result["per_scheme"].items():
        lines.append(f"| {sid} | {fmt(s['before'])} | {fmt(s['after'])} | {', '.join(s['lessons']) or '—'} | {s['verdict']} |")
    lines += ["", "## Lessons", "", "| Lesson | Schemes it reached | Better | Worse | Mean F1 change on its schemes |",
              "| --- | --- | --- | --- | --- |"]
    for lid, v in result["per_lesson"].items():
        lines.append(f"| {lid} | {', '.join(v['schemes'])} | {', '.join(v['better']) or '—'} | "
                     f"{', '.join(v['worse']) or '—'} | {v['mean_f1_change']:+.3f} |")
    worse = result["lessons_that_made_results_worse"]
    lines += ["", f"Lessons that reached a scheme that got worse: {', '.join(worse) or 'none'}. A lesson can share a "
                  "scheme with others, so this names candidates, not proof.", "",
              "## Cost", "",
              f"- Generating lessons (reflection, {result['cost']['reflection_runs']} runs): "
              f"{result['cost']['reflection_tokens'].get('total_tokens', 0):,} tokens.",
              f"- Extraction per held-out run: {result['cost']['extraction_tokens_per_run_before']:,} tokens without "
              f"lessons, {result['cost']['extraction_tokens_per_run_after']:,} with (the lessons lengthen the prompt).", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--before", nargs="+", required=True, help="held-out run folders without lessons")
    parser.add_argument("--after", nargs="+", required=True, help="held-out run folders with the frozen playbook")
    parser.add_argument("--reflection", nargs="*", default=[], help="reflection.json files from development runs")
    args = parser.parse_args()
    result = report([load_run(p) for p in args.before], [load_run(p) for p in args.after],
                    [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.reflection])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = RUNS_DIR / f"{stamp}_e3_report"
    out.mkdir(parents=True, exist_ok=False)
    (out / "e3_report.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "e3_report.md").write_text(markdown(result), encoding="utf-8")
    print(markdown(result))
    print(f"Written to {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
