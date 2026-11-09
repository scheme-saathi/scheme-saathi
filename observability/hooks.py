"""Small functions the rest of the app calls to report what happened. Each is a no-op while observability is off.

They take only fixed names (a server, a tool, an outcome, an action) and numbers, never a household,
thread or application identifier, a fact value or a message, so a call site cannot leak one by mistake.
"""

from __future__ import annotations

from observability.metrics import active_metrics
from observability.runs import current_run, error_type, outcome_for_exception


def record_tool_call(server: str, tool: str, outcome: str, duration_seconds: float, error_code: str = "") -> None:
    """One tool call (an MCP server tool). It also counts toward the run it was made in."""
    run = current_run()
    if run is not None:
        run.add_tool_call(failed=outcome != "success")
    metrics = active_metrics()
    if metrics is None:
        return
    metrics.tool_calls.labels(server=server, tool=tool, outcome=outcome).inc()
    metrics.tool_duration.labels(server=server, tool=tool).observe(max(duration_seconds, 0.0))
    if error_code:
        metrics.tool_errors.labels(server=server, tool=tool, error_code=error_code).inc()


def record_approval(action: str, result: str) -> None:
    """An approval decision on an application form: approve, edit, reject or invalid, and how it ended."""
    metrics = active_metrics()
    if metrics is not None:
        metrics.approvals.labels(action=action, result=result).inc()


def record_memory_operation(operation: str, result: str) -> None:
    """A long-term memory operation: load, save, reference, consent or forget, and how it ended."""
    metrics = active_metrics()
    if metrics is not None:
        metrics.memory_operations.labels(operation=operation, result=result).inc()


def record_thread_expired(kind: str, reason: str, count: int = 1) -> None:
    """Workflow threads or chat sessions that expired; `reason` is "cleanup" (the timer) or "on_use"."""
    metrics = active_metrics()
    if metrics is not None and count > 0:
        metrics.threads_expired.labels(kind=kind, reason=reason).inc(count)


def note_run_error(error: BaseException) -> None:
    """Tell the current run why it failed, for a failure that is sent as an event rather than raised."""
    run = current_run()
    if run is None or run.error_type is not None:
        return
    run.outcome = outcome_for_exception(error)
    run.error_type = error_type(error)
