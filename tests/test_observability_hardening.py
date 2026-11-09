"""Stage 6: no identifier can become a label, an abandoned stream is closed out, and tracing stays out of the way."""

import gc
import re
import threading
import time
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from prometheus_client import generate_latest

from app import api
from app.auth import AuthenticatedHousehold, authenticated_household
from graph import tools
from observability import (
    Metrics,
    RunRecorder,
    Tracer,
    activate,
    record_approval,
    record_llm_call,
    record_memory_operation,
    record_thread_expired,
    record_tool_call,
    set_metrics,
    set_tracer,
)
from observability import hooks
from observability.tracing import QUEUE_SIZE

PREFIX = "scheme_saathi_"
PRIVATE = "household-1 thread-private-42 Aadhaar 1234 5678 9012"


@pytest.fixture
def metrics():
    recording = Metrics()
    set_metrics(recording)
    activate()
    return recording


def value(metrics, name, **labels):
    return metrics.registry.get_sample_value(PREFIX + name, labels) or 0


def series(metrics):
    """Every (metric, label set) the app currently exposes."""
    return {(s.name, tuple(sorted(s.labels.items()))) for f in metrics.registry.collect() for s in f.samples if s.name.startswith(PREFIX)}


# Labels stay closed ------------------------------------------------------------------------


def test_a_value_outside_a_closed_set_is_recorded_as_other_not_as_a_new_series(metrics):
    for i in range(50):
        junk = f"household-{i}"
        record_approval(junk, junk)
        record_memory_operation(junk, junk)
        record_thread_expired(junk, junk)
        record_tool_call("rule-engine", "evaluate_scheme", junk, 0.1, junk)

    assert value(metrics, "approvals_total", action="other", result="other") == 50
    assert value(metrics, "memory_operations_total", operation="other", result="other") == 50
    assert value(metrics, "threads_expired_total", kind="other", reason="other") == 50
    assert value(metrics, "tool_calls_total", server="rule-engine", tool="evaluate_scheme", outcome="other") == 50
    assert value(metrics, "tool_errors_total", server="rule-engine", tool="evaluate_scheme", error_code="other") == 50
    assert "household" not in generate_latest(metrics.registry).decode()


def test_non_string_values_are_recorded_as_other(metrics):
    record_approval(None, 7)
    record_memory_operation(["load"], {"hit"})

    assert value(metrics, "approvals_total", action="other", result="other") == 1
    assert value(metrics, "memory_operations_total", operation="other", result="other") == 1


def test_every_value_the_app_reports_passes_through_unchanged(metrics):
    for action in hooks.APPROVAL_ACTIONS:
        for result in hooks.APPROVAL_RESULTS:
            record_approval(action, result)
    for operation in hooks.MEMORY_OPERATIONS:
        for result in hooks.MEMORY_RESULTS:
            record_memory_operation(operation, result)
    for kind in hooks.EXPIRED_KINDS:
        for reason in hooks.EXPIRED_REASONS:
            record_thread_expired(kind, reason)
    for outcome in hooks.TOOL_OUTCOMES:
        record_tool_call("rule-engine", "evaluate_scheme", outcome, 0.1)
    for code in hooks.TOOL_ERROR_CODES:
        record_tool_call("rule-engine", "evaluate_scheme", "error", 0.1, code)

    assert not [s for s in series(metrics) if ("action", "other") in s[1] or ("operation", "other") in s[1] or ("kind", "other") in s[1]]
    assert not [s for s in series(metrics) if ("outcome", "other") in s[1] or ("error_code", "other") in s[1]]
    assert not [s for s in series(metrics) if ("result", "other") in s[1] or ("reason", "other") in s[1]]


def test_the_values_the_workflow_really_reports_are_in_the_closed_sets():
    # Literals taken from the call sites in graph/workflow.py, graph/agent_workflow.py, app/memory_api.py and graph/tools.py.
    assert {"approve", "edit", "reject", "invalid"} <= hooks.APPROVAL_ACTIONS
    assert {"accepted", "rejected", "invalid"} <= hooks.APPROVAL_RESULTS
    assert {"consent_granted", "consent_withdrawn", "forget", "load", "save", "reference"} <= hooks.MEMORY_OPERATIONS
    assert {"hit", "miss", "saved", "skipped", "error", "changed", "unchanged", "partial", "success"} <= hooks.MEMORY_RESULTS
    assert {"agent", "chat_session", "application"} <= hooks.EXPIRED_KINDS
    assert {"tool_error", "transport_error", "authorization_denied", "budget_exceeded"} <= hooks.TOOL_ERROR_CODES


def test_a_tool_call_naming_an_identifier_is_labelled_unknown(metrics):
    tools._audit_tool_call("household-1", "thread-private-42", "success", time.perf_counter())

    assert value(metrics, "tool_calls_total", server="unknown", tool="unknown", outcome="success") == 1
    assert "household" not in generate_latest(metrics.registry).decode()


def test_model_labels_cannot_carry_markup_or_unbounded_text(metrics):
    for i in range(30):
        record_llm_call(f"household-{i}", 'bad "model"\n{x=1} ' + "x" * 500, 0.1, 1, 1, 0.1)

    keys = {dict(labels)["model"] for name, labels in series(metrics) if name == PREFIX + "llm_calls_total"}
    roles = {dict(labels)["role"] for name, labels in series(metrics) if name == PREFIX + "llm_calls_total"}
    assert roles == {"other"} and len(keys) == 1
    assert all(len(model) <= 80 and re.fullmatch(r"[A-Za-z0-9._:/@+-]+", model) for model in keys)


# Real traffic, many identifiers ------------------------------------------------------------


class FakeWorkflow:
    def __init__(self):
        self.result = {"thread_id": "conv_abc", "status": "eligibility_checked", "response": "done", "data": {}}
        self.error = None

    def execute_workflow(self, **kwargs):
        if self.error:
            raise self.error
        return self.result

    submit_decision = lambda self, *args, **kwargs: self.execute_workflow()  # noqa: E731


class FakeDemo:
    def __init__(self):
        self.events = []

    def _stream(self, *args):
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


def drive(client, count, start=0):
    for i in range(start, start + count):
        ident = f"thread-private-{i}"
        client.post(f"/api/chat/{ident}/decision", json={"action": "approve"})
        client.post("/api/chat", json={"message": f"Aadhaar 1234 5678 {i:04d}"}, headers={"X-Thread-Id": ident})
        client.get(f"/missing/{ident}")
        client.post(f"/api/threads/{ident}/decision", json={"action": "approve", "payload_hash": "h"})


def test_many_threads_and_paths_add_no_series_and_no_identifier_appears(served, metrics):
    client, _, _ = served
    drive(client, 5)
    before = series(metrics)

    drive(client, 150, start=5)

    assert series(metrics) == before
    exposed = generate_latest(metrics.registry).decode()
    for text in ("private", "household-1", "1234 5678", "conv_abc", "Aadhaar"):
        assert text not in exposed


def test_a_failed_request_with_identifiers_in_its_error_adds_no_text_to_the_metrics(served, metrics):
    client, workflow, _ = served
    workflow.error = RuntimeError(PRIVATE)

    for _ in range(20):
        assert client.post("/api/chat", json={"message": PRIVATE}).status_code == 500

    exposed = generate_latest(metrics.registry).decode()
    for text in ("household-1", "thread-private", "1234 5678"):
        assert text not in exposed
    assert value(metrics, "run_errors_total", kind="chat_turn", error_type="RuntimeError") == 20


# A stream the client leaves ----------------------------------------------------------------


def events():
    yield "progress", {"node": "start"}
    yield "result", {"thread_id": "t-1", "approval": {"form": {}}, "verdicts": {}}


def test_a_stream_dropped_before_it_starts_is_closed_out_as_cancelled(metrics):
    run = RunRecorder("application_start")
    assert value(metrics, "runs_in_progress", kind="application_start") == 1

    stream = run.watch(events())
    del stream
    gc.collect()

    assert value(metrics, "runs_in_progress", kind="application_start") == 0
    assert value(metrics, "runs_total", kind="application_start", outcome="cancelled") == 1


def test_a_stream_dropped_through_the_wrapping_generators_is_closed_out_too(metrics):
    def encode(source):
        for name, payload in source:
            yield f"event: {name}\n\n"

    run = RunRecorder("application_start")
    response_body = encode(run.watch(events()))
    del response_body
    gc.collect()

    assert value(metrics, "runs_in_progress", kind="application_start") == 0
    assert value(metrics, "runs_total", kind="application_start", outcome="cancelled") == 1


def test_a_stream_dropped_part_way_is_cancelled_once(metrics):
    run = RunRecorder("application_start")
    stream = run.watch(events())
    next(stream)
    del stream
    gc.collect()

    assert value(metrics, "runs_in_progress", kind="application_start") == 0
    assert value(metrics, "runs_total", kind="application_start", outcome="cancelled") == 1


def test_a_finished_stream_is_counted_once_even_after_it_is_discarded(metrics):
    run = RunRecorder("application_start")
    stream = run.watch(events())
    assert [name for name, _ in stream] == ["progress", "result"]
    del stream
    gc.collect()

    assert value(metrics, "runs_total", kind="application_start", outcome="awaiting_approval") == 1
    assert value(metrics, "runs_total", kind="application_start", outcome="cancelled") == 0
    assert value(metrics, "runs_in_progress", kind="application_start") == 0


def test_a_stream_dropped_after_its_result_keeps_the_outcome_it_reported(metrics):
    run = RunRecorder("application_start")
    stream = run.watch(events())
    next(stream)
    next(stream)
    del stream
    gc.collect()

    assert value(metrics, "runs_total", kind="application_start", outcome="awaiting_approval") == 1
    assert value(metrics, "runs_total", kind="application_start", outcome="cancelled") == 0


# Tracing never gets in the way -------------------------------------------------------------


@pytest.fixture
def blocked_backend():
    """A tracing backend that does not answer until released."""
    release = threading.Event()
    client = Mock()
    client.create_run.side_effect = lambda **kwargs: release.wait(15)
    yield client, release
    release.set()


def test_a_tracing_backend_that_never_answers_does_not_slow_a_request(served, metrics, blocked_backend):
    client, release = blocked_backend
    api_client, _, _ = served
    tracer = Tracer(client, "p", 1.0, None)
    set_tracer(tracer)

    started = time.perf_counter()
    for _ in range(5):
        assert api_client.post("/api/chat", json={"message": "hello"}).status_code == 200
    elapsed = time.perf_counter() - started

    assert elapsed < 5
    assert value(metrics, "runs_total", kind="chat_turn", outcome="eligibility_checked") == 5
    release.set()
    assert tracer.flush(10)
    assert value(metrics, "traces_total", result="exported") == 5


def test_a_full_export_queue_drops_traces_while_runs_carry_on(metrics, blocked_backend):
    client, release = blocked_backend
    tracer = Tracer(client, "p", 1.0, None)
    set_tracer(tracer)
    total = QUEUE_SIZE + 30

    started = time.perf_counter()
    for _ in range(total):
        with RunRecorder("chat_turn") as run:
            run.set_outcome("answered")
    elapsed = time.perf_counter() - started

    assert elapsed < 5
    assert value(metrics, "runs_total", kind="chat_turn", outcome="answered") == total
    # One trace is held by the worker, the queue holds QUEUE_SIZE, and the rest are dropped.
    assert value(metrics, "traces_total", result="dropped") >= total - QUEUE_SIZE - 1
    release.set()
    assert tracer.flush(15)


def test_a_failing_tracing_backend_never_changes_a_response(served, metrics):
    api_client, _, _ = served
    client = Mock()
    client.create_run.side_effect = ConnectionError(PRIVATE)
    tracer = Tracer(client, "p", 1.0, None)
    set_tracer(tracer)

    responses = [api_client.post("/api/chat", json={"message": "hello"}) for _ in range(3)]
    assert tracer.flush(10)

    assert [r.status_code for r in responses] == [200, 200, 200]
    assert value(metrics, "traces_total", result="failed") == 3
    assert PRIVATE not in generate_latest(metrics.registry).decode()


# Overhead ----------------------------------------------------------------------------------


def one_run(thread="t-1"):
    with RunRecorder("chat_turn") as run:
        run.set_thread(thread)
        for _ in range(3):
            record_tool_call("rule-engine", "evaluate_scheme", "success", 0.001)
        for _ in range(2):
            record_llm_call("specialist", "vendor/model-one", 0.2, 1000, 500, 0.01)


def per_run_seconds(count=300):
    started = time.perf_counter()
    for _ in range(count):
        one_run()
    return (time.perf_counter() - started) / count


def test_recording_a_run_costs_far_less_than_a_millisecond_against_a_model_call(metrics):
    # A model call takes hundreds of milliseconds. This bound is deliberately loose so a slow machine still passes.
    per_run_seconds(30)
    assert per_run_seconds() < 0.005


def test_recording_with_tracing_on_stays_within_the_same_bound(metrics):
    tracer = Tracer(Mock(), "p", 0.0, None)  # sampled out, so this measures building and queueing the run, not sending it
    set_tracer(tracer)
    per_run_seconds(30)

    assert per_run_seconds() < 0.005


def test_recording_does_nothing_and_costs_nothing_measurable_while_off():
    assert per_run_seconds() < 0.005


def test_pricing_a_call_does_not_re_read_the_environment_file_each_time(metrics, monkeypatch):
    from observability import pricing

    reads = []
    monkeypatch.setattr(pricing, "load_dotenv", lambda: reads.append(1))
    monkeypatch.setattr(pricing, "_dotenv_loaded", False)

    for _ in range(50):
        record_llm_call("specialist", "vendor/model-one", 0.1, 1000, 500, None)

    assert len(reads) == 1
