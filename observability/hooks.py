"""Small functions the rest of the app calls to report what happened. Each is a no-op while observability is off.

They take only fixed names (a server, a tool, an outcome, an action) and numbers, never a household,
thread or application identifier, a fact value or a message, so a call site cannot leak one by mistake.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from observability.metrics import active_metrics
from observability.runs import current_run, error_type, outcome_for_exception
from observability.safety import guarded
from observability.tracing import Span

# The values the app reports, by label. A value outside a set is recorded as "other", so a call site that
# passes an identifier or free text by mistake cannot add a series per value.
TOOL_OUTCOMES = frozenset({"success", "error", "denied"})
TOOL_ERROR_CODES = frozenset({"tool_error", "transport_error", "authorization_denied", "budget_exceeded"})
APPROVAL_ACTIONS = frozenset({"approve", "edit", "reject", "invalid"})
APPROVAL_RESULTS = frozenset({"accepted", "rejected", "invalid"})
MEMORY_OPERATIONS = frozenset({"load", "save", "reference", "consent_granted", "consent_withdrawn", "forget"})
MEMORY_RESULTS = frozenset({"hit", "miss", "saved", "skipped", "changed", "unchanged", "partial", "success", "error"})
SENSITIVE_STAGES = frozenset({"input", "output"})
ID_TYPES = frozenset({"aadhar", "pan", "ifsc", "bank_account", "phone", "otp", "password", "field"})
EXPIRED_KINDS = frozenset({"agent", "chat_session", "application"})
EXPIRED_REASONS = frozenset({"cleanup", "on_use"})


def bounded(value: object, allowed: frozenset[str]) -> str:
    return value if isinstance(value, str) and value in allowed else "other"


@guarded
def record_tool_call(server: str, tool: str, outcome: str, duration_seconds: float, error_code: str = "") -> None:
    """One tool call (an MCP server tool). It also counts toward the run it was made in."""
    outcome = bounded(outcome, TOOL_OUTCOMES)
    if error_code:
        error_code = bounded(error_code, TOOL_ERROR_CODES)
    run = current_run()
    if run is not None:
        run.add_tool_call(failed=outcome != "success")
        if run.keep_spans:
            duration = max(duration_seconds, 0.0)
            run.add_span(
                Span(
                    name=f"{server}.{tool}",
                    run_type="tool",
                    start=datetime.now(timezone.utc) - timedelta(seconds=duration),
                    duration=duration,
                    metadata={"server": server, "tool": tool, "outcome": outcome},
                    error=(error_code or "error") if outcome != "success" else None,
                )
            )
    metrics = active_metrics()
    if metrics is None:
        return
    metrics.tool_calls.labels(server=server, tool=tool, outcome=outcome).inc()
    metrics.tool_duration.labels(server=server, tool=tool).observe(max(duration_seconds, 0.0))
    if error_code:
        metrics.tool_errors.labels(server=server, tool=tool, error_code=error_code).inc()


@guarded
def record_approval(action: str, result: str) -> None:
    """An approval decision on an application form: approve, edit, reject or invalid, and how it ended."""
    metrics = active_metrics()
    if metrics is not None:
        metrics.approvals.labels(
            action=bounded(action, APPROVAL_ACTIONS), result=bounded(result, APPROVAL_RESULTS)
        ).inc()


@guarded
def record_memory_operation(operation: str, result: str) -> None:
    """A long-term memory operation: load, save, reference, consent or forget, and how it ended."""
    metrics = active_metrics()
    if metrics is not None:
        metrics.memory_operations.labels(
            operation=bounded(operation, MEMORY_OPERATIONS), result=bounded(result, MEMORY_RESULTS)
        ).inc()


@guarded
def record_thread_expired(kind: str, reason: str, count: int = 1) -> None:
    """Workflow threads or chat sessions that expired; `reason` is "cleanup" (the timer) or "on_use"."""
    metrics = active_metrics()
    if metrics is not None and count > 0:
        metrics.threads_expired.labels(
            kind=bounded(kind, EXPIRED_KINDS), reason=bounded(reason, EXPIRED_REASONS)
        ).inc(count)


@guarded
def note_run_error(error: BaseException) -> None:
    """Tell the current run why it failed, for a failure that is sent as an event rather than raised."""
    run = current_run()
    if run is None or run.error_type is not None:
        return
    run.outcome = outcome_for_exception(error)
    run.error_type = error_type(error)


@guarded
def record_sensitive_id(stage: str, id_type: str | None) -> None:
    """An ID number refused in input or removed from output. Only its type is recorded, never the value."""
    metrics = active_metrics()
    if metrics is not None:
        metrics.sensitive_ids.labels(stage=bounded(stage, SENSITIVE_STAGES), id_type=bounded(id_type, ID_TYPES)).inc()


@guarded
def record_conversation_started() -> None:
    """A chat conversation got its first turn."""
    metrics = active_metrics()
    if metrics is not None:
        metrics.conversations_started.inc()
