#!/usr/bin/env python3
"""Freeze the rule extractor's playbook before the held-out run (E3).

    python tests/evaluation/freeze_playbook.py --by Sharika

Every lesson must be reviewed. The approved lessons get a version hash; after this the playbook
can't change, and a held-out run (--final) refuses a playbook that isn't frozen or has changed.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evaluation.playbook import PLAYBOOK_FILE, Playbook  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--by", required=True, help="who decided to freeze")
    parser.add_argument("--on", default=date.today().isoformat(), help="date, YYYY-MM-DD")
    args = parser.parse_args()
    playbook = Playbook.load()
    version = playbook.freeze(on=args.on, by=args.by)
    playbook.save()
    print(f"Frozen {len(playbook.approved())} approved lessons on {args.on} by {args.by}: version {version}")
    for lesson in playbook.approved():
        print(f"  {lesson.lesson_id} {lesson.text[:100]}")
    print(f"\nCommit {PLAYBOOK_FILE.relative_to(ROOT)} before the held-out runs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
