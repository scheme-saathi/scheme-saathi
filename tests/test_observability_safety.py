"""Observability can never break the app: recording failures are skipped, and a missing package leaves it off."""

import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from observability import (
    Metrics,
    RunRecorder,
    Tracer,
    activate,
    active_metrics,
    install_observability,
    note_run_error,
    record_approval,
    record_llm_call,
    record_memory_operation,
    record_thread_expired,
    record_tool_call,
    set_metrics,
    set_tracer,
)
from observability import safety

ROOT = Path(__file__).resolve().parent.parent
PRIVATE = "household-1 thread-private-42 Aadhaar 1234 5678 9012"


class Exploding:
    """Stands in for a metric that fails whenever it is used."""

    def __getattr__(self, name):
        raise RuntimeError(PRIVATE)


def collector_names():
    return [name for name, value in vars(Metrics()).items() if hasattr(value, "labels") and not name.startswith("_")]


def events():
    yield "progress", {"node": "start"}
    yield "result", {"thread_id": "t-1", "approval": {"form": {}}, "verdicts": {"A": {"verdict": "eligible"}}}


def a_busy_run():
    with RunRecorder("chat_turn") as run:
        run.set_thread("t-1")
        run.set_verdicts({"A": {"verdict": "eligible"}})
        record_tool_call("rule-engine", "evaluate_scheme", "success", 0.01)
        record_tool_call("rule-engine", "evaluate_scheme", "error", 0.01, "tool_error")
        record_llm_call("specialist", "vendor/model-one", 0.2, 1000, 500, 0.01)
        record_approval("approve", "accepted")
        record_memory_operation("load", "hit")
        record_thread_expired("agent", "on_use")
        note_run_error(ValueError("x"))
        run.set_outcome("eligibility_checked")
    return "done"


@pytest.mark.parametrize("broken", collector_names())
def test_a_failing_metric_never_breaks_a_run_a_stream_or_the_original_error(broken):
    metrics = Metrics()
    setattr(metrics, broken, Exploding())
    set_metrics(metrics)
    activate()
    tracer = Tracer(Mock(), "p", 1.0, None)
    set_tracer(tracer)

    assert a_busy_run() == "done"
    assert [name for name, _ in RunRecorder("application_start").watch(events())] == ["progress", "result"]
    with pytest.raises(ValueError, match="the application's own error"):
        with RunRecorder("chat_turn"):
            record_tool_call("rule-engine", "evaluate_scheme", "success", 0.01)
            raise ValueError("the application's own error")
    with pytest.raises(KeyError):
        with RunRecorder("chat_turn").attach():
            raise KeyError("raised by the app")

    assert tracer.flush(10)
    assert tracer._worker is None or tracer._worker.is_alive()


def test_a_stream_that_raises_still_raises_the_same_error(metrics_on):
    def broken_events():
        yield "progress", {}
        raise ConnectionError("upstream failed")

    run = RunRecorder("application_start")
    with pytest.raises(ConnectionError, match="upstream failed"):
        list(run.watch(broken_events()))


@pytest.fixture
def metrics_on():
    metrics = Metrics()
    set_metrics(metrics)
    activate()
    return metrics


def test_a_failing_step_is_reported_once_by_class_name_only(metrics_on, caplog, monkeypatch):
    monkeypatch.setattr(safety, "_reported", set())
    metrics_on.approvals = Exploding()

    with caplog.at_level(logging.DEBUG):
        for _ in range(3):
            record_approval("approve", "accepted")

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "record_approval" in r.getMessage()]
    assert len(warnings) == 1 and "RuntimeError" in warnings[0].getMessage()
    assert PRIVATE not in caplog.text


def test_guarded_returns_none_and_lets_base_exceptions_through():
    @safety.guarded
    def fails():
        raise RuntimeError("x")

    @safety.guarded
    def interrupted():
        raise KeyboardInterrupt

    assert fails() is None
    with pytest.raises(KeyboardInterrupt):
        interrupted()


# The HTTP side ----------------------------------------------------------------------------


def sample_app():
    app = FastAPI()

    @app.get("/ok")
    def ok():
        return {"ok": True}

    @app.get("/boom")
    def boom():
        raise ValueError("an application bug")

    return app


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "test-token")


def test_a_failing_request_metric_never_breaks_a_response(enabled):
    metrics = Metrics()
    for name in ("http_in_progress", "http_requests", "http_duration", "http_exceptions"):
        setattr(metrics, name, Exploding())
    app = sample_app()

    assert install_observability(app, metrics) is True

    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/ok").json() == {"ok": True}
    assert client.get("/boom").status_code == 500


def test_a_failure_while_setting_observability_up_leaves_the_app_running(enabled, monkeypatch, caplog):
    monkeypatch.setattr("observability.http.configure_tracing", Mock(side_effect=RuntimeError(PRIVATE)))
    app = sample_app()

    with caplog.at_level(logging.WARNING):
        assert install_observability(app, Metrics()) is False

    assert active_metrics() is None
    assert TestClient(app).get("/ok").json() == {"ok": True}
    assert "RuntimeError" in caplog.text and PRIVATE not in caplog.text


def test_a_failure_to_serve_metrics_does_not_affect_the_rest_of_the_app(enabled):
    metrics = Metrics()
    app = sample_app()
    install_observability(app, metrics)
    metrics.registry = Exploding()  # reading /metrics now fails

    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/metrics", headers={"Authorization": "Bearer test-token"}).status_code == 500
    assert client.get("/ok").json() == {"ok": True}


# A missing package ------------------------------------------------------------------------

MISSING_PACKAGE = """
import sys
sys.modules["prometheus_client"] = None  # makes "import prometheus_client" fail, as if it were not installed
from fastapi import FastAPI
from fastapi.testclient import TestClient
import agents.model_factory
from observability import RunRecorder, active_metrics, install_observability, record_llm_call, record_tool_call

app = FastAPI()

@app.get("/ok")
def ok():
    return {"ok": True}

assert install_observability(app) is False
record_tool_call("rule-engine", "evaluate_scheme", "success", 0.1)
record_llm_call("specialist", "vendor/model-one", 0.1, 1, 1, 0.1)
with RunRecorder("chat_turn") as run:
    run.set_outcome("answered")
assert active_metrics() is None
assert TestClient(app).get("/ok").json() == {"ok": True}
print("app still works")
"""


def test_the_app_starts_and_works_when_prometheus_client_is_not_installed():
    environment = {
        **os.environ,
        "OBSERVABILITY_ENABLED": "true",
        "METRICS_BEARER_TOKEN": "test-token",
        "TRACING_BACKEND": "",
    }
    result = subprocess.run(
        [sys.executable, "-c", MISSING_PACKAGE],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert result.returncode == 0, result.stderr
    assert "app still works" in result.stdout
    assert "prometheus-client is not installed" in result.stderr
