"""Stage 2: runs, outcomes, tool calls, approvals, memory and expiry, as Prometheus metrics."""

from typing import TypedDict

import pytest
from fastapi.testclient import TestClient
from langgraph.graph import END, START, StateGraph
from prometheus_client import generate_latest

from app import api
from app.auth import AuthenticatedHousehold, authenticated_household
from app.business_logic import SessionNotFoundError, WorkflowConflictError
from app.business_logic import ThreadAccessError as DemoThreadAccessError
from graph import tools
from graph.tools import ToolCallError
from observability import (
    Metrics,
    RunRecorder,
    activate,
    current_run,
    note_run_error,
    record_approval,
    record_memory_operation,
    record_thread_expired,
    record_tool_call,
    set_metrics,
)
from observability.runs import error_type, normalise_outcome, outcome_for_exception, outcome_from_payload, start_series_at_zero

PREFIX = "scheme_saathi_"


@pytest.fixture
def metrics():
    recording = Metrics()
    set_metrics(recording)
    activate()
    return recording


def value(metrics, name, **labels):
    return metrics.registry.get_sample_value(PREFIX + name, labels) or 0


def runs(metrics, kind, outcome):
    return value(metrics, "runs_total", kind=kind, outcome=outcome)


VERDICTS = {
    "A": {"verdict": "eligible"},
    "B": {"verdict": "cant_tell"},
    "C": {"verdict": "not_eligible"},
}


# Switched off -------------------------------------------------------------------------------


def test_everything_is_a_no_op_while_observability_is_off():
    run = RunRecorder("chat_turn")
    assert run.active is False
    events = iter([("result", {})])
    assert run.watch(events) is events
    with run:
        assert current_run() is None
        record_tool_call("rule-engine", "list_rule_schemes", "success", 0.1)
        record_approval("approve", "accepted")
        record_memory_operation("load", "hit")
        record_thread_expired("application", "cleanup", 3)
        note_run_error(RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        with RunRecorder("chat_turn"):
            raise RuntimeError("still raised")


# Outcome rules -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error, outcome",
    [
        (api.ThreadAccessError("t"), "refused"),
        (api.ThreadNotFoundError("t"), "not_found"),
        (SessionNotFoundError("x"), "not_found"),
        (DemoThreadAccessError("x"), "refused"),
        (api.ApprovalPendingError("x"), "conflict"),
        (api.NoPendingApprovalError("x"), "conflict"),
        (WorkflowConflictError("x"), "conflict"),
        (ValueError("x"), "invalid_request"),
        (ToolCallError("rule-engine", "t", "budget_exceeded", "m"), "budget_exceeded"),
        (ToolCallError("rule-engine", "t", "tool_error", "m"), "tool_error"),
        (RuntimeError("x"), "error"),
    ],
)
def test_exceptions_map_to_a_closed_set_of_outcomes(error, outcome):
    assert outcome_for_exception(error) == outcome


def test_an_error_type_is_a_class_name_and_never_the_message():
    assert error_type(RuntimeError("household hh-1 is 62")) == "RuntimeError"


def test_unknown_statuses_become_other():
    assert normalise_outcome("something_new") == "other"
    assert normalise_outcome(None) == "other"
    assert normalise_outcome("needs_details") == "needs_information"
    assert normalise_outcome("submitted") == "submitted"


@pytest.mark.parametrize(
    "payload, outcome",
    [
        ({"submission": {"application_id": "a"}}, "submitted"),
        ({"approval_status": "rejected"}, "approval_rejected"),
        ({"approval_status": "invalid"}, "approval_invalid"),
        ({"approval": {"form": {}}}, "awaiting_approval"),
        ({"needs_human": True}, "needs_human"),
        ({"application": {"scheme_id": "C01"}}, "draft_ready_for_review"),
        ({"verdicts": VERDICTS}, "eligibility_checked"),
        ({}, "completed"),
    ],
)
def test_an_application_result_is_summed_up_by_how_far_it_got(payload, outcome):
    assert outcome_from_payload("application_start", payload) == outcome


# A plain run -------------------------------------------------------------------------------


def test_a_finished_run_is_counted_with_its_duration_and_verdicts(metrics):
    with RunRecorder("chat_turn") as run:
        assert value(metrics, "runs_in_progress", kind="chat_turn") == 1
        run.set_outcome("eligibility_checked")
        run.set_verdicts(VERDICTS)

    assert runs(metrics, "chat_turn", "eligibility_checked") == 1
    assert value(metrics, "run_duration_seconds_count", kind="chat_turn") == 1
    assert value(metrics, "runs_in_progress", kind="chat_turn") == 0
    for verdict in ("eligible", "not_eligible", "cant_tell"):
        assert value(metrics, "eligibility_verdicts_total", verdict=verdict) == 1


def test_verdicts_of_an_unfinished_check_are_not_counted(metrics):
    with RunRecorder("chat_turn") as run:
        run.set_outcome("needs_information")
        run.set_verdicts(VERDICTS)
    assert runs(metrics, "chat_turn", "needs_information") == 1
    assert value(metrics, "eligibility_verdicts_total", verdict="eligible") == 0


def test_a_run_without_an_outcome_counts_as_completed(metrics):
    with RunRecorder("chat_turn"):
        pass
    assert runs(metrics, "chat_turn", "completed") == 1


def test_a_failed_run_is_counted_by_error_type_and_the_error_still_propagates(metrics):
    with pytest.raises(RuntimeError):
        with RunRecorder("chat_turn"):
            raise RuntimeError("household hh-12345 has age 62")
    assert runs(metrics, "chat_turn", "error") == 1
    assert value(metrics, "run_errors_total", kind="chat_turn", error_type="RuntimeError") == 1
    assert value(metrics, "runs_in_progress", kind="chat_turn") == 0


def test_a_caller_mistake_is_an_outcome_but_not_a_server_error(metrics):
    with pytest.raises(api.ThreadNotFoundError):
        with RunRecorder("chat_decision"):
            raise api.ThreadNotFoundError("t")
    assert runs(metrics, "chat_decision", "not_found") == 1
    assert value(metrics, "run_errors_total", kind="chat_decision", error_type="ThreadNotFoundError") == 0


def test_guardrail_stops_are_counted_by_stage(metrics):
    with RunRecorder("chat_turn") as run:
        run.set_outcome("output_blocked")
    with RunRecorder("chat_turn") as run:
        run.set_outcome("validation_error")
    assert value(metrics, "guardrail_blocks_total", stage="output") == 1
    assert value(metrics, "guardrail_blocks_total", stage="input") == 1


def test_finishing_twice_counts_once(metrics):
    run = RunRecorder("chat_turn")
    run.finish("answered")
    run.finish("answered")
    assert runs(metrics, "chat_turn", "answered") == 1
    assert value(metrics, "runs_in_progress", kind="chat_turn") == 0


# A stream ----------------------------------------------------------------------------------


def stream_of(*events):
    yield from events


def test_a_stream_passes_through_unchanged_and_records_its_result(metrics):
    run = RunRecorder("application_start")
    events = [
        ("progress", {"node": "start"}),
        ("result", {"approval": {"form": {}}, "verdicts": VERDICTS}),
    ]
    assert list(run.watch(stream_of(*events))) == events

    assert runs(metrics, "application_start", "awaiting_approval") == 1
    assert value(metrics, "stream_time_to_first_event_seconds_count", kind="application_start") == 1
    assert value(metrics, "eligibility_verdicts_total", verdict="eligible") == 1


def test_a_stream_closed_early_is_cancelled(metrics):
    run = RunRecorder("application_start")
    stream = run.watch(stream_of(("progress", {}), ("progress", {}), ("result", {})))
    next(stream)
    stream.close()
    assert runs(metrics, "application_start", "cancelled") == 1
    assert value(metrics, "runs_in_progress", kind="application_start") == 0


def test_a_stream_closed_after_its_result_keeps_the_result(metrics):
    run = RunRecorder("application_start")
    stream = run.watch(stream_of(("result", {"submission": {"application_id": "a"}}), ("progress", {})))
    next(stream)
    stream.close()
    assert runs(metrics, "application_start", "submitted") == 1
    assert runs(metrics, "application_start", "cancelled") == 0


def test_a_stream_that_raises_is_a_failed_run(metrics):
    def broken():
        yield "progress", {}
        raise RuntimeError("household hh-1")

    stream = RunRecorder("application_decision").watch(broken())
    with pytest.raises(RuntimeError):
        list(stream)
    assert runs(metrics, "application_decision", "error") == 1
    assert value(metrics, "run_errors_total", kind="application_decision", error_type="RuntimeError") == 1


def test_an_error_event_carries_its_reason_through_note_run_error(metrics):
    def reports_failure():
        yield "progress", {}
        try:
            raise ToolCallError("rule-engine", "list_rule_schemes", "budget_exceeded", "too many")
        except ToolCallError as error:
            note_run_error(error)
            yield "error", {"detail": "A required workflow tool call could not be completed."}

    list(RunRecorder("legacy_chat").watch(reports_failure()))
    assert runs(metrics, "legacy_chat", "budget_exceeded") == 1
    assert value(metrics, "run_errors_total", kind="legacy_chat", error_type="ToolCallError") == 1


def test_an_error_event_with_no_reason_is_still_an_error(metrics):
    list(RunRecorder("legacy_chat").watch(stream_of(("error", {"detail": "no"}))))
    assert runs(metrics, "legacy_chat", "error") == 1
    assert value(metrics, "run_errors_total", kind="legacy_chat", error_type="unknown") == 1


def test_a_setup_failure_ends_the_run_and_is_raised(metrics):
    run = RunRecorder("application_start")
    with pytest.raises(SessionNotFoundError):
        with run.attach():
            raise SessionNotFoundError("x")
    assert runs(metrics, "application_start", "not_found") == 1
    assert value(metrics, "runs_in_progress", kind="application_start") == 0


# Tool calls --------------------------------------------------------------------------------


def test_tool_calls_are_counted_by_server_tool_and_outcome(metrics):
    record_tool_call("rule-engine", "evaluate_scheme", "success", 0.02)
    record_tool_call("rule-engine", "evaluate_scheme", "error", 0.5, "tool_error")
    assert value(metrics, "tool_calls_total", server="rule-engine", tool="evaluate_scheme", outcome="success") == 1
    assert value(metrics, "tool_calls_total", server="rule-engine", tool="evaluate_scheme", outcome="error") == 1
    assert value(metrics, "tool_call_duration_seconds_count", server="rule-engine", tool="evaluate_scheme") == 2
    assert value(metrics, "tool_errors_total", server="rule-engine", tool="evaluate_scheme", error_code="tool_error") == 1


def test_a_real_tool_call_is_recorded_and_counted_in_its_run(metrics):
    with RunRecorder("chat_turn"):
        tools.call_tool(tools.RULE_ENGINE, "list_rule_schemes", scheme_ids=None, include_draft=False)

    assert value(metrics, "tool_calls_total", server="rule-engine", tool="list_rule_schemes", outcome="success") == 1
    assert value(metrics, "run_tool_calls_sum", kind="chat_turn") == 1


def test_a_denied_tool_call_is_recorded_with_the_denial(metrics):
    with pytest.raises(ToolCallError):
        tools.call_tool("rule-engine", "not_a_tool")
    assert value(metrics, "tool_calls_total", server="rule-engine", tool="unknown", outcome="denied") == 1
    assert value(metrics, "tool_errors_total", server="rule-engine", tool="unknown", error_code="authorization_denied") == 1


def test_an_unknown_tool_server_is_not_a_label_value(metrics):
    with pytest.raises(ToolCallError):
        tools.call_tool("attacker-server-hh-12345", "x")
    assert b"attacker-server" not in generate_latest(metrics.registry)


def test_a_stream_step_counts_the_tool_calls_it_makes(metrics):
    def calls_a_tool():
        yield "progress", {}
        record_tool_call("schemes-kb", "search_schemes", "success", 0.01)
        record_tool_call("schemes-kb", "search_schemes", "success", 0.01)
        yield "result", {"verdicts": {}}

    list(RunRecorder("application_start").watch(calls_a_tool()))
    assert value(metrics, "run_tool_calls_sum", kind="application_start") == 2


class FanOutState(TypedDict, total=False):
    left: int
    right: int


def test_tool_calls_from_parallel_graph_nodes_count_toward_the_run(metrics):
    def left(state):
        record_tool_call("rule-engine", "a", "success", 0.001)
        return {"left": 1}

    def right(state):
        record_tool_call("rule-engine", "b", "success", 0.001)
        return {"right": 1}

    builder = StateGraph(FanOutState)
    builder.add_node("left", left)
    builder.add_node("right", right)
    builder.add_edge(START, "left")
    builder.add_edge(START, "right")
    builder.add_edge("left", END)
    builder.add_edge("right", END)

    with RunRecorder("chat_turn"):
        builder.compile().invoke({})
    assert value(metrics, "run_tool_calls_sum", kind="chat_turn") == 2


# Approvals, memory, expiry -------------------------------------------------------------------


def test_approval_decisions_are_counted_through_the_audit_hook(metrics):
    tools.audit_approval_event("approve", "accepted", True)
    tools.audit_approval_event("approve", "invalid", True)
    tools.audit_approval_event("reject", "rejected", False)
    assert value(metrics, "approvals_total", action="approve", result="accepted") == 1
    assert value(metrics, "approvals_total", action="approve", result="invalid") == 1
    assert value(metrics, "approvals_total", action="reject", result="rejected") == 1


def test_memory_and_expiry_hooks_count(metrics):
    record_memory_operation("load", "hit")
    record_memory_operation("load", "miss")
    record_thread_expired("application", "cleanup", 3)
    record_thread_expired("application", "cleanup", 0)
    record_thread_expired("agent", "on_use")
    assert value(metrics, "memory_operations_total", operation="load", result="hit") == 1
    assert value(metrics, "memory_operations_total", operation="load", result="miss") == 1
    assert value(metrics, "threads_expired_total", kind="application", reason="cleanup") == 3
    assert value(metrics, "threads_expired_total", kind="agent", reason="on_use") == 1


# Through the API ---------------------------------------------------------------------------


class FakeWorkflow:
    def __init__(self):
        self.result = {
            "thread_id": "conv_abc",
            "status": "eligibility_checked",
            "response": "done",
            "data": {"verdicts": VERDICTS},
        }
        self.error = None

    def execute_workflow(self, **kwargs):
        if self.error:
            raise self.error
        return self.result

    def submit_decision(self, *args, **kwargs):
        if self.error:
            raise self.error
        return self.result


class FakeDemo:
    def __init__(self):
        self.events = []
        self.setup_error = None

    def _stream(self, *args):
        if self.setup_error:
            raise self.setup_error
        return iter(self.events)

    analyze = decide = chat_turn = _stream

    def thread_subject(self, thread_id):
        return "self", None


@pytest.fixture
def served(monkeypatch, metrics):
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "test-token")
    monkeypatch.setattr(api.memory_runtime, "get_memory_service", lambda: None)
    workflow, demo = FakeWorkflow(), FakeDemo()
    monkeypatch.setattr(api, "get_workflow_service", lambda: workflow)
    application = api.create_api(service=demo)
    application.dependency_overrides[authenticated_household] = lambda: AuthenticatedHousehold(
        "household-1", "test|household-1"
    )
    return TestClient(application, raise_server_exceptions=False), workflow, demo


CHAT = {"message": "Am I eligible?"}


def test_a_chat_turn_through_the_api_is_recorded(served, metrics):
    client, _, _ = served
    assert client.post("/api/chat", json=CHAT).status_code == 200
    assert runs(metrics, "chat_turn", "eligibility_checked") == 1
    assert value(metrics, "eligibility_verdicts_total", verdict="eligible") == 1
    assert value(metrics, "eligibility_verdicts_total", verdict="cant_tell") == 1


@pytest.mark.parametrize(
    "error, status_code, outcome",
    [
        (api.ThreadNotFoundError("t"), 404, "not_found"),
        (api.ThreadAccessError("t"), 403, "refused"),
        (api.ApprovalPendingError("pending"), 409, "conflict"),
        (ToolCallError("rule-engine", "t", "budget_exceeded", "m"), 503, "budget_exceeded"),
        (ToolCallError("rule-engine", "t", "tool_error", "m"), 503, "tool_error"),
        (RuntimeError("household hh-12345 has age 62"), 500, "error"),
    ],
)
def test_a_failed_chat_turn_is_recorded_with_how_it_failed(served, metrics, error, status_code, outcome):
    client, workflow, _ = served
    workflow.error = error
    assert client.post("/api/chat", json=CHAT).status_code == status_code
    assert runs(metrics, "chat_turn", outcome) == 1
    assert value(metrics, "runs_in_progress", kind="chat_turn") == 0


def test_a_chat_decision_is_recorded(served, metrics):
    client, workflow, _ = served
    workflow.result = {**workflow.result, "status": "submitted", "data": {}}
    assert client.post("/api/chat/conv_abc/decision", json={"action": "approve"}).status_code == 200
    assert runs(metrics, "chat_decision", "submitted") == 1

    workflow.error = api.NoPendingApprovalError("nothing waiting")
    assert client.post("/api/chat/conv_abc/decision", json={"action": "approve"}).status_code == 409
    assert runs(metrics, "chat_decision", "conflict") == 1


@pytest.mark.parametrize("status", ["eligibility_checked", "awaiting_approval", "draft_needs_information"])
def test_verdicts_count_once_when_facts_are_confirmed_however_the_run_ends(served, metrics, status):
    client, workflow, _ = served
    workflow.result = {**workflow.result, "status": status, "answered": "confirm_facts"}
    assert client.post("/api/chat/conv_abc/decision", json={"action": "approve"}).status_code == 200
    assert value(metrics, "eligibility_verdicts_total", verdict="eligible") == 1

    # Editing or approving the draft afterwards carries the same verdicts in its state; they are not counted again.
    for later in ("awaiting_approval", "draft_needs_information", "submitted"):
        workflow.result = {**workflow.result, "status": later, "answered": "approve_application"}
        assert client.post("/api/chat/conv_abc/decision", json={"action": "edit"}).status_code == 200
    assert value(metrics, "eligibility_verdicts_total", verdict="eligible") == 1


def test_an_application_stream_is_recorded_when_it_ends(served, metrics):
    client, _, demo = served
    demo.events = [
        ("progress", {"node": "start"}),
        ("result", {"approval": {"form": {}}, "verdicts": VERDICTS}),
    ]
    response = client.post("/api/analyze", json={"citizen": {"age": 30}})
    assert response.status_code == 200
    assert "event: result" in response.text
    assert runs(metrics, "application_start", "awaiting_approval") == 1
    assert value(metrics, "eligibility_verdicts_total", verdict="not_eligible") == 1


def test_an_application_decision_stream_is_recorded(served, metrics):
    client, _, demo = served
    demo.events = [("result", {"submission": {"application_id": "a1"}})]
    assert client.post("/api/threads/t1/decision", json={"action": "approve"}).status_code == 200
    assert runs(metrics, "application_decision", "submitted") == 1


@pytest.mark.parametrize(
    "error, status_code, outcome",
    [
        (DemoThreadAccessError("x"), 403, "refused"),
        (SessionNotFoundError("x"), 404, "not_found"),
        (WorkflowConflictError("x"), 409, "conflict"),
        (ValueError("x"), 422, "invalid_request"),
    ],
)
def test_an_application_decision_refused_before_it_starts_is_recorded(
    served, metrics, error, status_code, outcome
):
    client, _, demo = served
    demo.setup_error = error
    assert client.post("/api/threads/t1/decision", json={"action": "approve"}).status_code == status_code
    assert runs(metrics, "application_decision", outcome) == 1
    assert value(metrics, "runs_in_progress", kind="application_decision") == 0


def test_a_legacy_chat_error_event_is_an_error_run(served, metrics):
    client, _, demo = served
    demo.events = [("error", {"detail": "The chat session was not found."})]
    assert client.post("/api/chat/legacy", json={"user_input": "hello"}).status_code == 200
    assert runs(metrics, "legacy_chat", "error") == 1


# Privacy -----------------------------------------------------------------------------------


def test_no_identifier_or_fact_reaches_the_metrics(served, metrics):
    client, workflow, demo = served
    workflow.result = {**workflow.result, "thread_id": "conv-LEAKTHREAD"}
    client.post("/api/chat", json={"message": "my aadhaar is LEAKAADHAAR and I am LEAKAGE"})
    workflow.error = RuntimeError("household hh-LEAKHOUSEHOLD has income LEAKINCOME")
    client.post("/api/chat", json=CHAT)
    demo.events = [("result", {"approval": {"form": {"name": "LEAKNAME"}}, "verdicts": VERDICTS})]
    client.post("/api/analyze", json={"citizen": {"name": "LEAKNAME", "age": 62}})
    record_tool_call("rule-engine", "evaluate_scheme", "error", 0.1, "tool_error")

    scrape = generate_latest(metrics.registry).decode()
    assert "scheme_saathi_runs_total" in scrape  # the runs above were recorded, so the check below means something
    for secret in ("LEAK", "household-1", "conv_abc", "test|household-1"):
        assert secret not in scrape


def test_the_series_alerts_read_exist_at_zero_before_anything_happens(metrics):
    start_series_at_zero(metrics)
    sample = metrics.registry.get_sample_value
    assert sample(PREFIX + "runs_total", {"kind": "chat_turn", "outcome": "error"}) == 0
    assert sample(PREFIX + "eligibility_verdicts_total", {"verdict": "cant_tell"}) == 0
    assert sample(PREFIX + "traces_total", {"result": "failed"}) == 0
    assert sample(PREFIX + "guardrail_blocks_total", {"stage": "input"}) == 0
    assert sample(PREFIX + "runs_total", {"kind": "chat_turn", "outcome": "needs_information"}) == 0
    assert sample(PREFIX + "runs_total", {"kind": "chat_decision", "outcome": "needs_information"}) == 0
    assert sample(PREFIX + "sensitive_ids_detected_total", {"stage": "input", "id_type": "aadhar"}) == 0
    assert sample(PREFIX + "sensitive_ids_detected_total", {"stage": "output", "id_type": "other"}) == 0


def test_the_first_question_and_first_sensitive_id_are_seen_as_an_increase_from_zero(metrics):
    """increase() needs the series scraped at 0 before its first event, or that event is lost."""
    from observability import record_sensitive_id

    start_series_at_zero(metrics)
    before = generate_latest(metrics.registry).decode()
    assert 'kind="chat_decision",outcome="needs_information"} 0.0' in before
    assert 'id_type="pan",stage="input"} 0.0' in before

    with RunRecorder("chat_decision") as run:  # a confirmation edit that reopens intake asks a question
        run.set_outcome("needs_information")
    record_sensitive_id("input", "pan")
    assert runs(metrics, "chat_decision", "needs_information") == 1
    assert value(metrics, "sensitive_ids_detected_total", stage="input", id_type="pan") == 1


def test_waiting_approvals_follow_how_runs_on_the_thread_end(metrics, monkeypatch):
    from observability import runs as run_module

    monkeypatch.setattr(run_module, "_waiting_approvals", set())
    run_module.start_series_at_zero(metrics)
    waiting = lambda: metrics.registry.get_sample_value(PREFIX + "approvals_waiting")

    run_module.note_approval_state("t1", "awaiting_approval")
    run_module.note_approval_state("t2", "awaiting_approval")
    run_module.note_approval_state("t1", "refused")  # another household poking at it changes nothing
    run_module.note_approval_state("t1", "error")  # nor does a server failure before a decision
    assert waiting() == 2
    run_module.note_approval_state("t1", "submitted")
    run_module.note_approval_state("t2", "approval_rejected")
    assert waiting() == 0



def test_a_waiting_draft_stops_counting_when_its_thread_is_deleted_or_expires(metrics, monkeypatch):
    from datetime import timedelta

    from app.thread_registry import ThreadRegistry
    from observability import runs as run_module

    monkeypatch.setattr(run_module, "_waiting_approvals", set())
    run_module.start_series_at_zero(metrics)
    waiting = lambda: metrics.registry.get_sample_value(PREFIX + "approvals_waiting")
    now = [0.0]
    registry = ThreadRegistry("agent", clock=lambda: now[0])
    for thread in ("deleted", "idle", "active"):
        registry.touch(thread, "hh1")
        run_module.note_approval_state(thread, "awaiting_approval")

    registry.forget({"deleted"})  # deleting a conversation or forgetting a household
    assert waiting() == 2

    now[0] = timedelta(hours=23).total_seconds()
    registry.touch("active", "hh1")  # still in use, so not idle however long ago its draft was shown
    now[0] = timedelta(hours=25).total_seconds()
    registry.forget(registry.expired())  # the expiry timer
    assert waiting() == 1


def test_sensitive_ids_and_conversations_are_counted_by_type_only(metrics):
    from agents.persona_validator import SensitiveInputError, reject_sensitive_input
    from observability import record_conversation_started, record_sensitive_id

    with pytest.raises(SensitiveInputError):
        reject_sensitive_input({"note": "my aadhaar is 2345 6789 0123"})
    record_sensitive_id("output", "1234 5678 9012")  # a value passed by mistake becomes "other", never a label
    record_conversation_started()

    assert value(metrics, "sensitive_ids_detected_total", stage="input", id_type="aadhar") == 1
    assert value(metrics, "sensitive_ids_detected_total", stage="output", id_type="other") == 1
    assert value(metrics, "conversations_started_total") == 1
    assert "1234" not in generate_latest(metrics.registry).decode()


def test_verdicts_count_when_confirming_facts_settles_the_check_but_not_again_on_a_draft_decision(served, metrics):
    client, workflow, _ = served
    verdicts = {"C06": {"verdict": "cant_tell"}, "M01": {"verdict": "eligible"}}
    workflow.result = {
        **workflow.result, "status": "eligibility_checked", "data": {"verdicts": verdicts}, "answered": "confirm_facts"
    }
    assert client.post("/api/chat/conv_abc/decision", json={"action": "approve"}).status_code == 200
    workflow.result = {**workflow.result, "status": "submitted", "answered": "approve_application"}  # same verdicts echoed
    assert client.post("/api/chat/conv_abc/decision", json={"action": "approve"}).status_code == 200

    assert value(metrics, "eligibility_verdicts_total", verdict="cant_tell") == 1
    assert value(metrics, "eligibility_verdicts_total", verdict="eligible") == 1
