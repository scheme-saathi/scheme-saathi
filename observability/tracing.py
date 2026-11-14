"""Traces: one LangSmith trace per run, with a child span for each model and tool call.

A trace holds names, numbers and outcomes only. The prompt, the reply, tool arguments, fact values and
error messages are never given to this module, and the LangSmith client is built to drop inputs and
any output other than token usage, so a mistake elsewhere cannot send content. The conversation is
identified by a salted hash of its thread ID, never the ID itself or a household ID.

Sending happens on a background thread behind a bounded queue, so a slow or unreachable LangSmith
cannot delay a request. When the queue is full a trace is dropped and counted. A run is sampled at
`TRACING_SAMPLE_RATE`, except that a run that failed on the server side is always kept.
"""

from __future__ import annotations

import hashlib
import logging
import os
import queue
import random
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from observability.config import Settings
from observability.metrics import active_metrics
from observability.safety import guarded

logger = logging.getLogger(__name__)

BACKENDS = ("none", "langsmith")
QUEUE_SIZE = 200


@dataclass(frozen=True)
class Span:
    """One model or tool call inside a run. Holds names and numbers, no content."""

    name: str
    run_type: str  # "llm" or "tool"
    start: datetime
    duration: float
    metadata: dict[str, Any]
    outputs: dict[str, Any] = field(default_factory=dict)
    error: str | None = None  # an exception class name or an error code


@dataclass(frozen=True)
class TraceItem:
    """A finished run, as handed to the tracer."""

    kind: str
    outcome: str
    error_type: str | None
    started: datetime
    duration: float
    thread: str | None
    llm_calls: int
    llm_errors: int
    unpriced_calls: int
    tool_calls: int
    tool_errors: int
    input_tokens: int
    output_tokens: int
    cost: float
    spans: tuple[Span, ...]
    spans_dropped: int
    server_side_error: bool


def hide_inputs(inputs: dict) -> dict:
    return {}


def hide_outputs(outputs: dict) -> dict:
    """Token usage is the only output a trace may carry."""
    return {key: value for key, value in (outputs or {}).items() if key == "usage_metadata"}


def make_client() -> Any:
    from langsmith import Client

    # Send on our own exporter thread, not LangSmith's batch thread: a rejected trace (bad key, outage) then
    # raises in `_send` and is counted as failed instead of exported, and nothing is left unsent at exit.
    return Client(hide_inputs=hide_inputs, hide_outputs=hide_outputs, auto_batch_tracing=False)


class Tracer:
    def __init__(self, client: Any, project: str, sample_rate: float, salt: str | None) -> None:
        self.client = client
        self.project = project
        self.sample_rate = sample_rate
        self._salt = salt or secrets.token_hex(16)
        self._queue: queue.Queue[TraceItem] = queue.Queue(maxsize=QUEUE_SIZE)
        self._worker: threading.Thread | None = None
        self._worker_lock = threading.Lock()

    def thread_label(self, thread: str | None) -> str | None:
        if not thread:
            return None
        return hashlib.sha256(f"{self._salt}:{thread}".encode()).hexdigest()[:16]

    def submit(self, item: TraceItem) -> None:
        """Queue a finished run for sending. It never blocks and never raises."""
        try:
            if not item.server_side_error and random.random() >= self.sample_rate:
                self._count("sampled_out")
                return
            self._start_worker()
            self._queue.put_nowait(item)
        except queue.Full:
            self._count("dropped")
        except Exception:
            self._count("failed")

    def flush(self, timeout: float = 5.0) -> bool:
        """Wait until everything queued has been sent. For tests and shutdown."""
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.005)
        return not self._queue.unfinished_tasks

    def _start_worker(self) -> None:
        if self._worker is not None:
            return
        with self._worker_lock:
            if self._worker is None:
                worker = threading.Thread(target=self._run, name="trace-exporter", daemon=True)
                worker.start()
                self._worker = worker

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                self._send(item)
                self._count("exported")
            except Exception as error:
                self._count("failed")
                logger.warning("A run trace could not be sent (%s).", type(error).__name__)
            finally:
                self._queue.task_done()

    @staticmethod
    @guarded
    def _count(result: str) -> None:
        metrics = active_metrics()
        if metrics is not None:
            metrics.traces.labels(result=result).inc()

    def _send(self, item: TraceItem) -> None:
        from langsmith.run_trees import RunTree

        ended = item.started + timedelta(seconds=item.duration)
        metadata = {
            "kind": item.kind,
            "outcome": item.outcome,
            "duration_seconds": round(item.duration, 4),
            "llm_calls": item.llm_calls,
            "llm_errors": item.llm_errors,
            "unpriced_llm_calls": item.unpriced_calls,
            "tool_calls": item.tool_calls,
            "tool_errors": item.tool_errors,
            "input_tokens": item.input_tokens,
            "output_tokens": item.output_tokens,
            "cost_usd": round(item.cost, 8),
            "spans_dropped": item.spans_dropped,
        }
        if item.error_type:
            metadata["error_type"] = item.error_type
        label = self.thread_label(item.thread)
        if label:
            metadata["thread_id"] = label  # LangSmith groups traces that share this key into a thread

        root = RunTree(
            name=f"scheme-saathi {item.kind}",
            run_type="chain",
            inputs={},
            start_time=item.started,
            client=self.client,
            project_name=self.project,
            tags=[item.kind],
            extra={"metadata": metadata},
        )
        children = []
        for span in item.spans:
            child = root.create_child(
                name=span.name,
                run_type=span.run_type,
                inputs={},
                start_time=span.start,
                extra={"metadata": span.metadata},
            )
            child.end(outputs=span.outputs, error=span.error, end_time=span.start + timedelta(seconds=span.duration))
            children.append(child)
        root.end(outputs={}, error=item.error_type if item.server_side_error else None, end_time=ended)
        root.post()
        for child in children:
            child.post()


_tracer: Tracer | None = None


def set_tracer(tracer: Tracer | None) -> None:
    global _tracer
    _tracer = tracer


def active_tracer() -> Tracer | None:
    """The tracer to send runs to, or None: tracing is off, or observability itself is."""
    return _tracer if active_metrics() is not None else None


def _auto_tracing_on() -> bool:
    return any(
        os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}
        for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING")
    )


def configure_tracing(config: Settings, client: Any = None) -> str:
    """Set up the tracing backend named in the settings and return the one now in use ("none" if it cannot start)."""
    set_tracer(None)
    backend = config.tracing_backend
    if backend == "none":
        return "none"
    if backend != "langsmith":
        logger.warning("TRACING_BACKEND is not one of %s, so tracing is off.", ", ".join(BACKENDS))
        return "none"
    try:
        if client is None:
            if not (os.environ.get("LANGSMITH_API_KEY", "").strip() or os.environ.get("LANGCHAIN_API_KEY", "").strip()):
                logger.warning("TRACING_BACKEND is langsmith but LANGSMITH_API_KEY is not set, so tracing is off.")
                return "none"
            client = make_client()
    except Exception as error:
        logger.warning("The LangSmith client could not be created (%s), so tracing is off.", type(error).__name__)
        return "none"
    set_tracer(Tracer(client, config.project, config.sample_rate, config.hash_salt))
    if _auto_tracing_on():
        logger.warning(
            "LANGSMITH_TRACING or LANGCHAIN_TRACING_V2 is on. LangChain would then send full prompts and replies to "
            "LangSmith itself. Unset it: Scheme Saathi traces carry metadata only."
        )
    return "langsmith"
