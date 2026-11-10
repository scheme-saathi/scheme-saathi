#!/usr/bin/env python3
"""Apply a person's review decisions to the playbook's proposed lessons.

    python tests/evaluation/review_lessons.py --decisions <decisions.json> --reviewer Sharika

The decisions file holds one entry per lesson: {"lesson_id", "decision": "approved" | "rejected",
"text"? (an edit), "keywords"? (an edit), "note"?}. Every proposed lesson must be decided; the
command refuses a file that misses one or names a lesson that isn't proposed, and changes
nothing in that case.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evaluation.playbook import PLAYBOOK_FILE, Playbook  # noqa: E402


def apply(playbook: Playbook, decisions: list[dict], reviewer: str, on: str) -> list[str]:
    proposed = {lesson.lesson_id for lesson in playbook.lessons if lesson.status == "proposed"}
    named = [d["lesson_id"] for d in decisions]
    if sorted(named) != sorted(proposed):
        missing, unknown = sorted(proposed - set(named)), sorted(set(named) - proposed)
        raise ValueError(f"decide every proposed lesson exactly once: missing {missing}, not proposed {unknown}")
    lines = []
    for d in decisions:
        if d["decision"] not in ("approved", "rejected"):
            raise ValueError(f"{d['lesson_id']}: decision must be approved or rejected")
        lesson = playbook.review(d["lesson_id"], d["decision"], reviewer, text=d.get("text"),
                                 note=d.get("note"), on=on, keywords=d.get("keywords"))
        edited = " (edited)" if d.get("text") or d.get("keywords") is not None else ""
        lines.append(f"{lesson.lesson_id}: {lesson.status}{edited}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--decisions", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--on", default=date.today().isoformat(), help="review date, YYYY-MM-DD")
    args = parser.parse_args()
    playbook = Playbook.load()
    lines = apply(playbook, json.loads(Path(args.decisions).read_text(encoding="utf-8")), args.reviewer, args.on)
    playbook.save()
    print("\n".join(lines))
    approved = len(playbook.approved())
    print(f"\n{approved} approved lessons in {PLAYBOOK_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
