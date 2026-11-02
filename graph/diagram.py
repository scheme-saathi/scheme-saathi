"""Render the workflow graph as Mermaid, taken from the compiled graph so it cannot drift."""

import sys
from pathlib import Path

from graph.agent_workflow import AgentSet, build_agent_graph
from agents.contracts import (
    IntakeResult,
    SupervisorPlan,
    EligibilityNarrative,
    DocumentCheckResult,
    ApplicationDraft,
)

DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "workflow-graph.md"
HEADER = """# Workflow graph

Generated from `graph/agent_workflow.py` by `python -m graph.diagram --write`; do not edit by hand.
Supervisor-first architecture: All requests flow through Supervisor FIRST for input validation,
language/intent detection, and routing to specialists (Intake, Eligibility, DocumentChecker, Application).
Dashed arrows are conditional edges based on Supervisor's routing decision.

"""


class StubAgent:
    """Stub agent for diagram generation (no model needed)."""
    def __init__(self, result):
        self.result = result

    def invoke(self, value):
        return self.result


def render() -> str:
    # Create mock agents for diagram generation (no models needed)
    mock_agents = AgentSet(
        intake=StubAgent(IntakeResult(language="en", intent="eligibility")),
        supervisor=StubAgent(SupervisorPlan(next_agent="eligibility", reason="Check eligibility.")),
        eligibility=StubAgent(EligibilityNarrative(explanation="Reviewed result.")),
        document_checker=StubAgent(DocumentCheckResult()),
        application=StubAgent(ApplicationDraft(
            scheme_id="test-scheme",
            fields={},
            missing_fields=[],
            review_summary="Application review.",
        )),
    )
    return HEADER + "```mermaid\n" + build_agent_graph(mock_agents).get_graph().draw_mermaid().rstrip() + "\n```\n"


def main(argv: list[str]) -> int:
    if "--write" in argv:
        DOC_PATH.write_text(render(), encoding="utf-8")
        print(f"Wrote {DOC_PATH}")
    else:
        print(render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
