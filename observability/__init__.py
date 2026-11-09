"""Observability: metrics for Prometheus and, in later stages, traces for Langfuse or LangSmith.

Nothing here runs unless OBSERVABILITY_ENABLED is on, so the app behaves as before without it.
Telemetry never carries personal data: see `observability.metrics.ALLOWED_LABELS`.
"""

from observability.config import Settings, settings
from observability.hooks import (
    note_run_error,
    record_approval,
    record_memory_operation,
    record_thread_expired,
    record_tool_call,
)
from observability.http import install_observability
from observability.llm import record_llm_call
from observability.metrics import Metrics, activate, active_metrics, get_metrics, set_metrics
from observability.runs import RunRecorder, current_run

__all__ = [
    "Metrics",
    "RunRecorder",
    "Settings",
    "activate",
    "active_metrics",
    "current_run",
    "get_metrics",
    "install_observability",
    "note_run_error",
    "record_approval",
    "record_llm_call",
    "record_memory_operation",
    "record_thread_expired",
    "record_tool_call",
    "set_metrics",
    "settings",
]
