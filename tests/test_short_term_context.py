"""Short-term context (L9): the models never receive the transcript, so their input does not grow.

Each turn the supervisor sees only that turn's message; earlier turns live in typed state
(known_facts, pending_field, pending_question), not in the prompt. See docs/memory-policy.md,
"Short-term context".
"""

from langgraph.checkpoint.memory import MemorySaver

from agents.contracts import ApplicationDraft, DocumentCheckResult, IntakeResult, SupervisorPlan
from graph.agent_workflow import AgentSet, build_agent_graph
from tests.test_intake_flow import CountingSupervisor, StubAgent


class RecordingSupervisor(CountingSupervisor):
    def __init__(self, *plans):
        super().__init__(*plans)
        self.inputs = []

    def invoke(self, value):
        self.inputs.append(value)
        return super().invoke(value)


def test_supervisor_input_holds_only_the_current_turn_over_twenty_turns():
    supervisor = RecordingSupervisor(SupervisorPlan(next_agent="respond", reason="Hello."))
    graph = build_agent_graph(
        AgentSet(
            intake=StubAgent(IntakeResult(language="en", intent="other")),
            supervisor=supervisor,
            eligibility=StubAgent(None),
            document_checker=StubAgent(DocumentCheckResult()),
            application=StubAgent(ApplicationDraft(scheme_id="s", fields={}, missing_fields=[], review_summary="-")),
        ),
        checkpointer=MemorySaver(),
    )
    config = {"configurable": {"thread_id": "long-chat"}}
    messages = [f"turn {n:02d}: tell me about scheme number {n}" for n in range(20)]
    for message in messages:
        graph.invoke({"request": message}, config)

    assert len(supervisor.inputs) == 20
    for n, sent in enumerate(supervisor.inputs):
        payload = sent.model_dump_json()
        assert sent.request == messages[n]
        assert not any(earlier in payload for earlier in messages[:n])  # no earlier turn leaks in
    sizes = [len(sent.model_dump_json()) for sent in supervisor.inputs]
    assert max(sizes) - min(sizes) <= 2  # turn 20's input is the size of turn 1's
