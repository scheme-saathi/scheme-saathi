"""Stage 4: LangSmith traces with metadata only, sent without ever blocking or breaking a run."""

import logging
import queue
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from fastapi import FastAPI

from observability import (
    Metrics,
    RunRecorder,
    Settings,
    Tracer,
    activate,
    configure_tracing,
    install_observability,
    record_llm_call,
    record_tool_call,
    set_metrics,
    set_tracer,
    settings,
)
from observability import tracing
from observability.config import sample_rate_from
from observability.runs import MAX_SPANS
from observability.tracing import TraceItem, active_tracer, hide_inputs, hide_outputs, make_client

PREFIX = "scheme_saathi_"
THREAD = "thread-7f3a9c11"
PRIVATE = "Aadhaar 1234 5678 9012 private prompt text"


@pytest.fixture
def metrics():
    recording = Metrics()
    set_metrics(recording)
    activate()
    return recording


@pytest.fixture
def client():
    return Mock()


@pytest.fixture
def tracer(metrics, client):
    tracer = Tracer(client, "test-project", 1.0, "test-salt")
    set_tracer(tracer)
    return tracer


def value(metrics, name, **labels):
    return metrics.registry.get_sample_value(PREFIX + name, labels) or 0


def posted(client):
    return [call.kwargs for call in client.create_run.call_args_list]


def one_run(tracer, kind="chat_turn", thread=THREAD, fail=False):
    try:
        with RunRecorder(kind) as run:
            run.set_thread(thread)
            record_tool_call("rule_engine", "evaluate", "success", 0.02)
            record_llm_call("specialist", "vendor/model-one", 0.5, 1000, 500, 0.25)
            if fail:
                raise RuntimeError(f"failed for {PRIVATE}")
    except RuntimeError:
        pass
    assert tracer.flush()


def test_a_run_becomes_one_trace_with_a_span_per_model_and_tool_call(tracer, client, metrics):
    one_run(tracer)

    root, *children = posted(client)
    assert root["name"] == "scheme-saathi chat_turn"
    assert root["session_name"] == "test-project"
    assert root.get("parent_run_id") is None
    meta = root["extra"]["metadata"]
    assert meta["kind"] == "chat_turn" and meta["outcome"] == "completed"
    assert (meta["llm_calls"], meta["tool_calls"]) == (1, 1)
    assert (meta["input_tokens"], meta["output_tokens"], meta["cost_usd"]) == (1000, 500, 0.25)
    assert {c["name"] for c in children} == {"rule_engine.evaluate", "specialist vendor/model-one"}
    assert all(c["parent_run_id"] == root["id"] and c["trace_id"] == root["trace_id"] for c in children)
    llm = next(c for c in children if c["run_type"] == "llm")
    assert llm["extra"]["metadata"]["ls_model_name"] == "vendor/model-one"
    assert llm["outputs"] == {"usage_metadata": {"input_tokens": 1000, "output_tokens": 500, "total_tokens": 1500, "total_cost": 0.25}}
    assert value(metrics, "traces_total", result="exported") == 1


def test_the_conversation_is_a_salted_hash_never_the_thread_id(tracer, client):
    one_run(tracer)
    one_run(tracer)
    other = Tracer(client, "p", 1.0, "another-salt")

    roots = [call for call in posted(client) if call["name"].startswith("scheme-saathi")]
    first, second = (r["extra"]["metadata"]["thread_id"] for r in roots)
    assert first == second != THREAD and THREAD not in str(posted(client))
    assert other.thread_label(THREAD) != first
    assert tracer.thread_label(None) is None


def test_a_run_without_a_thread_has_no_thread_key(tracer, client):
    with RunRecorder("chat_turn"):
        pass
    assert tracer.flush()

    assert "thread_id" not in posted(client)[0]["extra"]["metadata"]


def test_the_thread_of_a_streamed_run_comes_from_its_result_event(tracer, client):
    run = RunRecorder("application_start")
    list(run.watch(iter([("result", {"thread_id": THREAD, "verdicts": {}})])))
    assert tracer.flush()

    assert posted(client)[0]["extra"]["metadata"]["thread_id"] == tracer.thread_label(THREAD)


def test_no_prompt_reply_or_error_message_reaches_the_backend(tracer, client):
    with pytest.raises(RuntimeError):
        with RunRecorder("chat_turn"):
            record_llm_call("specialist", "vendor/model-one", 0.1, error=RuntimeError(PRIVATE))
            record_tool_call("mock_portal", "submit", "error", 0.1, error_code="tool_error")
            raise RuntimeError(PRIVATE)
    assert tracer.flush()

    sent = str(posted(client))
    for text in ("1234 5678", "private", "Aadhaar"):
        assert text not in sent
    root, *children = posted(client)
    assert root["error"] == "RuntimeError" and root["outputs"] == {} and root["inputs"] == {}
    assert {c["error"] for c in children} == {"RuntimeError", "tool_error"}


def test_the_client_drops_inputs_and_every_output_but_token_usage(monkeypatch):
    made = {}
    monkeypatch.setattr("langsmith.Client", lambda **kwargs: made.update(kwargs) or "client")

    assert make_client() == "client"
    assert made["hide_inputs"] is hide_inputs and made["hide_outputs"] is hide_outputs
    assert hide_inputs({"messages": [PRIVATE]}) == {}
    assert hide_outputs({"text": PRIVATE, "usage_metadata": {"input_tokens": 1}}) == {"usage_metadata": {"input_tokens": 1}}
    assert hide_outputs(None) == {}


def test_sampling_skips_a_run_but_a_failed_run_is_always_kept(metrics, client):
    tracer = Tracer(client, "p", 0.0, None)
    set_tracer(tracer)

    one_run(tracer)
    assert posted(client) == [] and value(metrics, "traces_total", result="sampled_out") == 1

    one_run(tracer, fail=True)
    assert len(posted(client)) == 3 and value(metrics, "traces_total", result="exported") == 1


def test_a_run_that_the_caller_got_wrong_is_sampled_like_any_other(metrics, client):
    tracer = Tracer(client, "p", 0.0, None)
    set_tracer(tracer)

    with RunRecorder("chat_turn") as run:
        run.set_outcome("not_found")

    assert posted(client) == [] and value(metrics, "traces_total", result="sampled_out") == 1


def test_a_full_queue_drops_the_trace_without_blocking(metrics, client, monkeypatch):
    tracer = Tracer(client, "p", 1.0, None)
    monkeypatch.setattr(tracer, "_start_worker", lambda: None)
    tracer._queue = queue.Queue(maxsize=1)
    item = TraceItem("chat_turn", "completed", None, datetime.now(timezone.utc), 1.0, None, 0, 0, 0, 0, 0, 0, 0, 0.0, (), 0, False)

    tracer.submit(item)
    tracer.submit(item)

    assert value(metrics, "traces_total", result="dropped") == 1


def test_a_backend_outage_never_breaks_a_run_and_is_counted(tracer, client, metrics):
    client.create_run.side_effect = ConnectionError(f"cannot reach langsmith {PRIVATE}")

    with RunRecorder("chat_turn") as run:
        run.set_outcome("answered")
    assert tracer.flush()

    assert value(metrics, "runs_total", kind="chat_turn", outcome="answered") == 1
    assert value(metrics, "traces_total", result="failed") == 1
    assert value(metrics, "traces_total", result="exported") == 0


def test_the_backend_failing_to_prepare_a_trace_never_breaks_a_run(metrics, client, monkeypatch):
    tracer = Tracer(client, "p", 1.0, None)
    monkeypatch.setattr(tracer, "submit", Mock(side_effect=RuntimeError("boom")))
    set_tracer(tracer)

    with RunRecorder("chat_turn") as run:
        run.set_outcome("answered")

    assert value(metrics, "runs_total", kind="chat_turn", outcome="answered") == 1


def test_a_trace_keeps_at_most_the_span_limit(tracer, client):
    with RunRecorder("chat_turn"):
        for _ in range(MAX_SPANS + 5):
            record_tool_call("rule_engine", "evaluate", "success", 0.001)
    assert tracer.flush()

    root, *children = posted(client)
    assert len(children) == MAX_SPANS
    assert root["extra"]["metadata"]["spans_dropped"] == 5
    assert root["extra"]["metadata"]["tool_calls"] == MAX_SPANS + 5


def test_nothing_is_kept_for_tracing_while_it_is_off(metrics):
    from observability import current_run

    with RunRecorder("chat_turn"):
        record_tool_call("rule_engine", "evaluate", "success", 0.001)
        assert active_tracer() is None
        assert current_run().keep_spans is False and current_run().spans == []


def test_tracing_is_inactive_while_observability_is_off(client):
    set_tracer(Tracer(client, "p", 1.0, None))

    assert active_tracer() is None
    with RunRecorder("chat_turn"):
        pass
    assert posted(client) == []


def config(**changes):
    return Settings(**{"enabled": True, "metrics_token": "t", **changes})


def test_none_and_unknown_backends_leave_tracing_off(caplog):
    assert configure_tracing(config()) == "none"
    with caplog.at_level(logging.WARNING):
        assert configure_tracing(config(tracing_backend="langfuse")) == "none"
    assert "tracing is off" in caplog.text and active_tracer() is None


def test_langsmith_without_an_api_key_stays_off(caplog):
    with caplog.at_level(logging.WARNING):
        assert configure_tracing(config(tracing_backend="langsmith")) == "none"
    assert "LANGSMITH_API_KEY" in caplog.text


def test_langsmith_with_a_client_turns_tracing_on(metrics, client):
    assert configure_tracing(config(tracing_backend="langsmith", sample_rate=0.5, project="proj"), client=client) == "langsmith"

    tracer = active_tracer()
    assert (tracer.project, tracer.sample_rate) == ("proj", 0.5)


def test_a_client_that_cannot_be_built_leaves_tracing_off(monkeypatch, caplog):
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.setattr(tracing, "make_client", Mock(side_effect=ValueError("bad endpoint")))

    with caplog.at_level(logging.WARNING):
        assert configure_tracing(config(tracing_backend="langsmith")) == "none"
    assert "tracing is off" in caplog.text


def test_langchains_own_tracing_is_warned_about_because_it_would_send_prompts(client, monkeypatch, caplog):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")

    with caplog.at_level(logging.WARNING):
        configure_tracing(config(tracing_backend="langsmith"), client=client)

    assert "full prompts" in caplog.text


def test_installing_observability_reports_the_backend_in_build_info(monkeypatch, client):
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "test-token")
    monkeypatch.setenv("TRACING_BACKEND", "langsmith")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.setattr(tracing, "make_client", lambda: client)
    metrics = Metrics()

    assert install_observability(FastAPI(), metrics) is True

    samples = [s for f in metrics.registry.collect() for s in f.samples if s.name == PREFIX + "build_info"]
    assert [s.labels["tracing_backend"] for s in samples] == ["langsmith"]
    assert active_tracer() is not None


def test_settings_read_the_tracing_environment(monkeypatch):
    monkeypatch.setenv("TRACING_BACKEND", " LangSmith ")
    monkeypatch.setenv("TRACING_SAMPLE_RATE", "0.25")
    monkeypatch.setenv("TRACING_HASH_SALT", "salty")
    monkeypatch.setenv("LANGSMITH_PROJECT", "my-project")

    found = settings()

    assert (found.tracing_backend, found.sample_rate, found.hash_salt, found.project) == ("langsmith", 0.25, "salty", "my-project")


def test_settings_default_to_no_tracing_and_a_full_sample():
    found = settings()

    assert (found.tracing_backend, found.sample_rate, found.hash_salt, found.project) == ("none", 1.0, None, "scheme-saathi")


@pytest.mark.parametrize(
    ("text", "expected"),
    [("0.5", 0.5), ("2", 1.0), ("-1", 0.0), ("lots", 1.0), ("nan", 1.0), ("0", 0.0)],
)
def test_the_sample_rate_is_clamped_and_a_bad_value_samples_everything(text, expected):
    assert sample_rate_from(text) == expected
