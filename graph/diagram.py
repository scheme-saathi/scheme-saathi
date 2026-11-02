"""Render the workflow graph as Mermaid, taken from the compiled graph so it cannot drift."""

import sys
from pathlib import Path

from graph.workflow import build_graph

DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "workflow-graph.md"
HEADER = """# Workflow graph

Generated from `graph/workflow.py` by `python -m graph.diagram --write`; do not edit by hand.
Dashed arrows are conditional edges.

- `validate` is the self-correction check: a failed draft returns to `draft` (at most 3 attempts), then goes to `escalate` for a person.
- `approval` pauses with `interrupt()`. Approve must carry the hash of the exact form; edit re-runs `eligibility` and needs a new approval; anything else ends the run.

"""


def render() -> str:
    return HEADER + "```mermaid\n" + build_graph().get_graph().draw_mermaid().rstrip() + "\n```\n"


def main(argv: list[str]) -> int:
    if "--write" in argv:
        DOC_PATH.write_text(render(), encoding="utf-8")
        print(f"Wrote {DOC_PATH}")
    else:
        print(render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
