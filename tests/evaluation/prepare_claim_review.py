#!/usr/bin/env python3
"""Prepare unlabelled synthetic development-run messages for human review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def prepare(run_dirs: list[Path], limit: int) -> dict:
    if limit < 20:
        raise ValueError("Choose at least 20 messages for calibration.")
    queues = []
    for run_dir in run_dirs:
        meta = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        if meta.get("split") != "development":
            raise ValueError(f"{run_dir}: only development runs may be used for review.")
        rows = [json.loads(line) for line in (run_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        case_queues = []
        for row in rows:
            if row.get("error"):
                raise ValueError(f"{run_dir}: a case failed; inspect the run before preparing review.")
            messages = []
            for index, turn in enumerate(row["result"]["transcript"]):
                text = turn.get("text")
                if turn.get("role") == "agent" and isinstance(text, str) and text.strip():
                    messages.append({"id": f"{run_dir.name}:{row['case_id']}:{index}", "text": text, "has_claim": None})
            if messages:
                case_queues.append(iter(messages))

        def interleave_cases(case_iterators):
            while case_iterators:
                active = []
                for iterator in case_iterators:
                    item = next(iterator, None)
                    if item is not None:
                        active.append(iterator)
                        yield item
                case_iterators = active

        queues.append(iter(interleave_cases(case_queues)))
    selected = []
    while len(selected) < limit and queues:
        active = []
        for queue in queues:
            item = next(queue, None)
            if item is not None:
                active.append(queue)
                if len(selected) < limit:
                    selected.append(item)
        queues = active
    if len(selected) < limit:
        raise ValueError(f"Only {len(selected)} agent messages were available; requested {limit}.")
    ids = [item["id"] for item in selected]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate message IDs; ensure each run directory is supplied only once.")
    return {"synthetic_only": True, "items": selected}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, action="append", required=True)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError(f"Output already exists: {args.output}")
    result = prepare(args.run, args.limit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(f"Prepared {len(result['items'])} messages in {args.output}. Review for sensitive data and label each item.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
