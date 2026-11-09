"""The metrics the app exposes, declared in one place so every label can be checked.

Every metric label must be in ALLOWED_LABELS. The list holds only low-cardinality, non-personal
names (a route template, a status class, an outcome, an exception type), so a household, thread,
application or user identifier, or a fact value, cannot become a label by accident.
"""

from __future__ import annotations

from importlib import metadata
from typing import Sequence

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    GCCollector,
    Histogram,
    PlatformCollector,
    ProcessCollector,
)

PREFIX = "scheme_saathi_"

ALLOWED_LABELS = frozenset(
    {
        "method",
        "route",
        "status_class",
        "error_type",
        "version",
        "tracing_backend",
        "kind",
        "outcome",
        "server",
        "tool",
        "error_code",
        "verdict",
        "action",
        "result",
        "stage",
        "operation",
        "reason",
    }
)

# Seconds. Wide enough for a model call or a streamed workflow, which can take a minute or more.
LATENCY_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120)
# A tool call is a local call, so most take milliseconds.
TOOL_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)
COUNT_BUCKETS = (0, 1, 2, 3, 5, 8, 13, 21, 34, 55)

HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})


def _version() -> str:
    try:
        return metadata.version("scheme-saathi")
    except metadata.PackageNotFoundError:
        return "unknown"


class Metrics:
    """One registry of metrics. Tests build their own so counts never leak between them."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        ProcessCollector(registry=self.registry)
        PlatformCollector(registry=self.registry)
        GCCollector(registry=self.registry)

        self.http_requests = self._counter(
            "http_requests_total",
            "HTTP requests by method, route template and status class.",
            ["method", "route", "status_class"],
        )
        self.http_duration = self._histogram(
            "http_request_duration_seconds",
            "Seconds from the request arriving to its response being fully sent (a stream counts to its end).",
            ["method", "route"],
        )
        self.http_in_progress = self._gauge(
            "http_requests_in_progress", "HTTP requests being handled right now.", []
        )
        self.http_exceptions = self._counter(
            "http_exceptions_total",
            "Unhandled exceptions while handling a request, by route template and exception type.",
            ["route", "error_type"],
        )
        build = self._gauge("build_info", "The running version and tracing backend; always 1.", ["version", "tracing_backend"])
        build.labels(version=_version(), tracing_backend="none").set(1)

        # Runs: one workflow invocation (a chat turn, a decision, an application step, a legacy chat turn).
        self.runs = self._counter(
            "runs_total", "Finished runs by kind and outcome (see observability.runs.OUTCOMES).", ["kind", "outcome"]
        )
        self.run_duration = self._histogram(
            "run_duration_seconds", "Seconds from a run starting to it finishing, streams included.", ["kind"]
        )
        self.runs_in_progress = self._gauge("runs_in_progress", "Runs that have started and not finished.", ["kind"])
        self.run_errors = self._counter(
            "run_errors_total",
            "Runs that ended in a server-side error, by exception type (never its message).",
            ["kind", "error_type"],
        )
        self.run_tool_calls = self._histogram(
            "run_tool_calls", "Tool calls made during one run.", ["kind"], buckets=COUNT_BUCKETS
        )
        self.stream_first_event = self._histogram(
            "stream_time_to_first_event_seconds", "Seconds until a streamed run sent its first event.", ["kind"]
        )

        # Tool calls (the MCP servers: rule engine, schemes knowledge base, document checker, mock portal).
        self.tool_calls = self._counter(
            "tool_calls_total", "Tool calls by server, tool and outcome.", ["server", "tool", "outcome"]
        )
        self.tool_duration = self._histogram(
            "tool_call_duration_seconds", "Seconds a tool call took.", ["server", "tool"], buckets=TOOL_BUCKETS
        )
        self.tool_errors = self._counter(
            "tool_errors_total", "Failed tool calls by error code.", ["server", "tool", "error_code"]
        )

        # What the app decided and did.
        self.approvals = self._counter(
            "approvals_total", "Application approval decisions by action and result.", ["action", "result"]
        )
        self.verdicts = self._counter(
            "eligibility_verdicts_total",
            "Final eligibility verdicts (eligible, not_eligible, cant_tell), one per scheme checked.",
            ["verdict"],
        )
        self.guardrail_blocks = self._counter(
            "guardrail_blocks_total", "Requests or answers the guardrails stopped, by stage (input or output).", ["stage"]
        )
        self.memory_operations = self._counter(
            "memory_operations_total", "Long-term memory operations by operation and result.", ["operation", "result"]
        )
        self.threads_expired = self._counter(
            "threads_expired_total",
            "Workflow threads and chat sessions that expired, found by the cleanup timer or when used.",
            ["kind", "reason"],
        )

    def _check(self, labels: Sequence[str]) -> None:
        unknown = set(labels) - ALLOWED_LABELS
        if unknown:
            raise ValueError(f"Metric labels not on the allowlist: {sorted(unknown)}")

    def _counter(self, name: str, help_text: str, labels: Sequence[str]) -> Counter:
        self._check(labels)
        return Counter(PREFIX + name, help_text, labels, registry=self.registry)

    def _gauge(self, name: str, help_text: str, labels: Sequence[str]) -> Gauge:
        self._check(labels)
        return Gauge(PREFIX + name, help_text, labels, registry=self.registry)

    def _histogram(
        self, name: str, help_text: str, labels: Sequence[str], buckets: Sequence[float] = LATENCY_BUCKETS
    ) -> Histogram:
        self._check(labels)
        return Histogram(PREFIX + name, help_text, labels, buckets=buckets, registry=self.registry)


_metrics: Metrics | None = None
_active = False


def get_metrics() -> Metrics:
    """The app's metrics, created on first use."""
    global _metrics
    if _metrics is None:
        _metrics = Metrics()
    return _metrics


def set_metrics(metrics: Metrics | None) -> None:
    """Replace the app's metrics (tests); None makes the next `get_metrics()` build a fresh set.

    It also switches recording off, so call `activate()` afterwards to record into them.
    """
    global _metrics, _active
    _metrics = metrics
    _active = False


def activate() -> None:
    """Start recording runs, tool calls and the rest. `install_observability` calls this."""
    global _active
    _active = True


def active_metrics() -> Metrics | None:
    """The metrics to record into, or None while observability is off (every hook is then a no-op)."""
    return get_metrics() if _active else None
