#!/usr/bin/env python3
"""Reflection step: turn the errors of a development run into proposed lessons for review.

    python tests/evaluation/reflect_rule_extraction.py --run data/evaluation-runs/<run folder>

For each type of error the scorer found, the reflection model sees examples from several
schemes and proposes at most three short lessons. They are added to the playbook
(data/playbook/rule_extractor.json) as "proposed"; none reaches the extractor until a person
approves it. Held-out runs are refused: lessons are learned on development schemes only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agents.rule_reflector import ERROR_MEANINGS, ErrorExample, Reflection, ReflectionInput  # noqa: E402
from evaluation import rule_extraction as rx  # noqa: E402
from evaluation.playbook import PLAYBOOK_FILE, Lesson, Playbook  # noqa: E402

MAX_EXAMPLES = 8  # per error type, spread over schemes


def _clause_of(shown: str | None) -> str | None:
    match = re.search(r"\[([a-z]+-\d+)\]", shown or "")
    return match.group(1) if match else None


def error_examples(rows: list[dict[str, Any]], max_examples: int = MAX_EXAMPLES) -> dict[str, list[ErrorExample]]:
    """Examples of each error type, at most one per scheme first so one scheme can't dominate."""
    texts = {}
    by_type: dict[str, list[list[ErrorExample]]] = defaultdict(list)
    for row in rows:
        if row.get("error"):
            continue  # a failed call says nothing about how the extractor reads text
        sid = row["scheme_id"]
        texts[sid] = {c["clause_id"]: c["text"] for c in rx.source_clauses(rx.load_scheme(sid))}
        per_scheme: dict[str, list[ErrorExample]] = defaultdict(list)
        for error in row["score"]["errors"]:
            if error["type"] == "wrong_logic":
                clause = "rule_logic"
            else:
                cid = _clause_of(error.get("gold")) or _clause_of(error.get("draft"))
                clause = texts[sid].get(cid, cid or "")
            per_scheme[error["type"]].append(ErrorExample(
                scheme_id=sid, clause=clause, gold=str(error.get("gold")) if error.get("gold") else None,
                draft=str(error.get("draft")) if error.get("draft") else None))
        for kind, items in per_scheme.items():
            by_type[kind].append(items)
    chosen: dict[str, list[ErrorExample]] = {}
    for kind, schemes in by_type.items():
        picked, depth = [], 0
        while len(picked) < max_examples and any(depth < len(s) for s in schemes):
            picked += [s[depth] for s in schemes if depth < len(s)][: max_examples - len(picked)]
            depth += 1
        chosen[kind] = picked
    return chosen


def default_reflector() -> Callable[[ReflectionInput], Reflection]:
    from agents.model_factory import create_chat_model
    from agents.rule_reflector import RuleReflector

    reflector = RuleReflector(create_chat_model("supervisor"))
    return reflector.reflect


def propose(run_dir: Path, playbook: Playbook, reflect: Callable[[ReflectionInput], Reflection] | None = None,
            today: str | None = None) -> tuple[list[Lesson], dict[str, Any]]:
    from langchain_core.callbacks import get_usage_metadata_callback

    meta = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    if meta["split"] != "development":
        raise ValueError("lessons are learned on development schemes only")
    rows = [json.loads(line) for line in (run_dir / "schemes.jsonl").read_text(encoding="utf-8").splitlines() if line]
    reflect = reflect or default_reflector()
    existing = [lesson.text for lesson in playbook.lessons if lesson.status in ("approved", "proposed")]
    next_number = 1 + max((int(l.lesson_id[1:]) for l in playbook.lessons if l.lesson_id[1:].isdigit()), default=0)
    proposals, doubts, tokens = [], [], Counter()
    for kind, examples in sorted(error_examples(rows).items()):
        with get_usage_metadata_callback() as usage:
            result = reflect(ReflectionInput(error_type=kind, meaning=ERROR_MEANINGS[kind], examples=examples,
                                             existing_lessons=existing))
        for used in usage.usage_metadata.values():
            tokens.update({k: v for k, v in used.items() if isinstance(v, int)})
        doubts += [f"{kind}: {d}" for d in result.doubts]
        for item in result.lessons:
            proposals.append(Lesson(
                lesson_id=f"L{next_number:03d}", text=item.text, applies_when=item.applies_when,
                keywords=item.keywords, error_type=kind, examples=item.examples,
                proposed_on=today or date.today().isoformat(), proposed_by_run=run_dir.name))
            next_number += 1
    playbook.add_proposals(proposals)
    report = {"run": run_dir.name, "proposed": [p.lesson_id for p in proposals], "doubts": doubts,
              "reflection_tokens": dict(tokens)}
    return proposals, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", required=True, help="a development run folder in data/evaluation-runs/")
    args = parser.parse_args()
    run_dir = Path(args.run)
    playbook = Playbook.load()
    proposals, report = propose(run_dir, playbook)
    playbook.save()
    (run_dir / "reflection.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    for lesson in proposals:
        print(f"{lesson.lesson_id} [{lesson.error_type}] {lesson.text}\n    applies when: {lesson.applies_when}; "
              f"keywords: {', '.join(lesson.keywords) or '(always)'}")
    if report["doubts"]:
        print("\nDoubts for the reviewer:\n- " + "\n- ".join(report["doubts"]))
    print(f"\n{len(proposals)} lessons proposed in {PLAYBOOK_FILE.relative_to(ROOT)}; tokens {report['reflection_tokens']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
