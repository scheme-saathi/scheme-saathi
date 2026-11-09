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
    }
)

# Seconds. Wide enough for a model call or a streamed workflow, which can take a minute or more.
LATENCY_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120)

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


def get_metrics() -> Metrics:
    """The app's metrics, created on first use."""
    global _metrics
    if _metrics is None:
        _metrics = Metrics()
    return _metrics


def set_metrics(metrics: Metrics | None) -> None:
    """Replace the app's metrics (tests); None makes the next `get_metrics()` build a fresh set."""
    global _metrics
    _metrics = metrics
