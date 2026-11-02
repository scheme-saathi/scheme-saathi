"""Render the workflow graph as Mermaid, taken from the compiled graph so it cannot drift."""

import sys
from pathlib import Path

from graph.agent_workflow import build_agent_graph

DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "workflow-graph.md"
HEADER = """# Workflow graph

Generated from `graph/agent_workflow.py` by `python -m graph.diagram --write`; do not edit by hand.
Supervisor-first architecture: All requests flow through Supervisor FIRST for input validation,
language/intent detection, and routing to specialists (Intake, Eligibility, DocumentChecker, Application).
Dashed arrows are conditional edges based on Supervisor's routing decision.

"""


def render() -> str:
    return HEADER + "```mermaid\n" + build_agent_graph().get_graph().draw_mermaid().rstrip() + "\n```\n"


def main(argv: list[str]) -> int:
    if "--write" in argv:
        DOC_PATH.write_text(render(), encoding="utf-8")
        print(f"Wrote {DOC_PATH}")
    else:
        print(render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
