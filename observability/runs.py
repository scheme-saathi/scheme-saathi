"""Runs: one workflow invocation, recorded with its duration, outcome, errors and tool calls.

A run is a chat turn, a chat decision, an application start or decision, or a legacy chat turn. The
recorder wraps the API call that makes it (a plain call, or a streamed response that lasts until its
last event). Everything is a no-op while observability is off.

Labels stay low-cardinality and non-personal: the kind and outcome come from the closed sets below,
and an error is recorded by its exception class name, never its message.
"""

from __future__ import annotations

import contextvars
import logging
import re
import threading
import time
import weakref
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from observability.metrics import Metrics, active_metrics
from observability.safety import guarded
from observability.tracing import Span, TraceItem, active_tracer

logger = logging.getLogger(__name__)

RUN_KINDS = frozenset(
    {
        "chat_turn",  # POST /api/chat: one message through the agent graph
        "chat_decision",  # POST /api/chat/{id}/decision: approve, edit or reject in the agent graph
        "application_start",  # POST /api/analyze: the application workflow
        "application_decision",  # POST /api/threads/{id}/decision
        "legacy_chat",  # POST /api/chat/legacy
    }
)

# Every outcome a run can be recorded with. Anything else becomes "other".
OUTCOMES = frozenset(
    {
        "needs_information",
        "awaiting_confirmation",
        "awaiting_approval",
        "eligibility_checked",
        "intake_stopped",
        "facts_rejected",
        "confirmation_invalid",
        "draft_edited",
        "draft_needs_information",
        "draft_ready_for_review",
        "documents_checked",
        "submitted",
        "approval_rejected",
        "approval_invalid",
        "answered",
        "answer_not_found",
        "output_blocked",
        "validation_error",
        "applications_listed",
        "no_applications",
        "responded",
        "completed",
        "needs_human",
        "cancelled",  # the client went away before the stream finished
        "refused",  # not the caller's thread
        "not_found",  # unknown or expired thread
        "conflict",  # nothing waiting for approval, or one is
        "invalid_request",
        "tool_error",
        "budget_exceeded",
        "storage_error",
        "error",  # anything unexpected
        "other",
    }
)

# Outcomes that mean the server failed, as opposed to the caller asking for something it cannot have.
SERVER_SIDE_ERRORS = frozenset({"error", "tool_error", "budget_exceeded", "storage_error"})

# A run that reached a settled eligibility result, so its verdicts are final and are counted.
FINAL_CHECK_OUTCOMES = frozenset(
    {
        "eligibility_checked",
        "awaiting_approval",
        "draft_ready_for_review",
        "documents_checked",
        "needs_human",
        "completed",
    }
)
VERDICT_KINDS = frozenset({"chat_turn", "legacy_chat", "application_start"})
# In the chat graph the verdicts arrive when the person confirms their facts, which is a decision run. Only that
# outcome counts, so approving or editing a draft does not count the same verdicts again.
DECISION_VERDICT_OUTCOME = "eligibility_checked"
VERDICTS = frozenset({"eligible", "not_eligible", "cant_tell"})
TRACE_RESULTS = ("exported", "sampled_out", "dropped", "failed")

# Outcomes that leave a waiting draft where it was: the caller was refused, or the server failed before deciding.
KEEPS_APPROVAL_WAITING = SERVER_SIDE_ERRORS | {"refused", "conflict", "invalid_request", "validation_error", "cancelled"}
# A thread idle this long is deleted by the expiry timer (app/api.py), and its waiting draft with it.
APPROVAL_EXPIRY_SECONDS = 24 * 60 * 60
_waiting_approvals: dict[str, float] = {}  # thread -> when its draft was shown; in memory only, never exported
_waiting_lock = threading.Lock()


def note_approval_state(thread: str | None, outcome: str) -> None:
    """Track which threads have a draft waiting for approval, from how each run on the thread ended."""
    if not thread:
        return
    with _waiting_lock:
        if outcome == "awaiting_approval":
            _waiting_approvals[thread] = time.monotonic()
        elif outcome not in KEEPS_APPROVAL_WAITING:
            _waiting_approvals.pop(thread, None)


def approvals_waiting() -> int:
    """Drafts waiting now. shortcut: an expired thread is dropped by age, not by the expiry timer itself,
    and the count restarts at 0 with the app; read it from the store if that matters."""
    cutoff = time.monotonic() - APPROVAL_EXPIRY_SECONDS
    with _waiting_lock:
        for thread in [t for t, shown in _waiting_approvals.items() if shown < cutoff]:
            del _waiting_approvals[thread]
        return len(_waiting_approvals)


def start_series_at_zero(metrics: Metrics) -> None:
    """Create the series that alerts and ratios read, at 0.

    Prometheus's rate() and increase() miss the first increment of a series it never saw at 0, so the first
    error, can't-tell verdict or lost trace would otherwise not count, and an error ratio would be empty, not 0.
    """
    for kind in RUN_KINDS:
        for outcome in SERVER_SIDE_ERRORS:
            metrics.runs.labels(kind=kind, outcome=outcome)
    for verdict in VERDICTS:
        metrics.verdicts.labels(verdict=verdict)
    for result in TRACE_RESULTS:
        metrics.traces.labels(result=result)
    for stage in ("input", "output"):
        metrics.guardrail_blocks.labels(stage=stage)
    metrics.approvals_waiting.set_function(approvals_waiting)

_OUTCOME_ALIASES = {"needs_details": "needs_information"}

# The exception classes the app raises, by name, so this package imports nothing from the app.
_EXCEPTION_OUTCOMES = {
    "ThreadAccessError": "refused",
    "ThreadNotFoundError": "not_found",
    "SessionNotFoundError": "not_found",
    "ApprovalPendingError": "conflict",
    "NoPendingApprovalError": "conflict",
    "WorkflowConflictError": "conflict",
    "DocumentStorageError": "storage_error",
    "ValidationError": "invalid_request",
    "ValueError": "invalid_request",
}

_CLASS_NAME = re.compile(r"[^A-Za-z0-9_]")


def normalise_outcome(status: Any) -> str:
    """A status from a result as one of the closed set of outcomes."""
    if not isinstance(status, str):
        return "other"
    status = _OUTCOME_ALIASES.get(status, status)
    return status if status in OUTCOMES else "other"


def outcome_for_exception(error: BaseException) -> str:
    """How a failure counts: a tool failure, a refused or missing thread, a conflict, or a plain error."""
    for cls in type(error).__mro__:
        if cls.__name__ == "ToolCallError":
            return "budget_exceeded" if getattr(error, "code", "") == "budget_exceeded" else "tool_error"
        outcome = _EXCEPTION_OUTCOMES.get(cls.__name__)
        if outcome:
            return outcome
    return "error"


def error_type(error: BaseException) -> str:
    """The exception class name, nothing from its message."""
    return _CLASS_NAME.sub("", type(error).__name__)[:64] or "unknown"


def outcome_from_payload(kind: str, payload: dict[str, Any]) -> str:
    """What a streamed "result" event says happened."""
    if kind in {"application_start", "application_decision"}:
        if payload.get("submission"):
            return "submitted"
        approval_status = payload.get("approval_status")
        if approval_status == "rejected":
            return "approval_rejected"
        if approval_status == "invalid":
            return "approval_invalid"
        if payload.get("approval"):
            return "awaiting_approval"
        if payload.get("needs_human"):
            return "needs_human"
        if payload.get("application"):
            return "draft_ready_for_review"
        return "eligibility_checked" if payload.get("verdicts") else "completed"
    return normalise_outcome(payload.get("status"))


MAX_SPANS = 200


@dataclass
class RunRecord:
    """What one run has done so far. Worker threads share it, so counts are guarded."""

    kind: str
    tool_calls: int = 0
    tool_errors: int = 0
    outcome: str | None = None
    error_type: str | None = None
    verdicts: Any = None
    llm_calls: int = 0
    llm_errors: int = 0
    unpriced_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    thread: str | None = None
    keep_spans: bool = False
    spans: list[Span] = field(default_factory=list)
    spans_dropped: int = 0
    started_wall: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add_span(self, span: Span) -> None:
        if not self.keep_spans:
            return
        with self._lock:
            if len(self.spans) < MAX_SPANS:
                self.spans.append(span)
            else:
                self.spans_dropped += 1

    def add_tool_call(self, failed: bool) -> None:
        with self._lock:
            self.tool_calls += 1
            self.tool_errors += int(failed)

    def add_llm_call(
        self, failed: bool, input_tokens: int = 0, output_tokens: int = 0, cost: float | None = None
    ) -> None:
        """A model call. `cost` is None for a successful call that could not be priced."""
        with self._lock:
            self.llm_calls += 1
            self.llm_errors += int(failed)
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens
            if cost is not None:
                self.cost += cost
            elif not failed:
                self.unpriced_calls += 1


_current: contextvars.ContextVar[RunRecord | None] = contextvars.ContextVar("scheme_saathi_run", default=None)


def current_run() -> RunRecord | None:
    """The run the calling code is part of, if any. It follows the call into worker threads."""
    return _current.get()


def _reset_context(token: contextvars.Token) -> None:
    try:
        _current.reset(token)
    except (ValueError, RuntimeError):  # reset from a different context: nothing to undo there
        pass


class RunRecorder:
    """Records one run. Use it as a context manager for a plain call, or `attach()` plus `watch()` for a stream."""

    def __init__(self, kind: str) -> None:
        self.kind = kind if kind in RUN_KINDS else "other"
        self._metrics: Metrics | None = None
        self._record = RunRecord(self.kind)
        self._tracer = None
        self._started = time.perf_counter()
        self._finished = False
        self._lock = threading.Lock()
        self._token: contextvars.Token | None = None
        self._begin()

    @guarded
    def _begin(self) -> None:
        metrics = active_metrics()
        if metrics is None:
            return
        metrics.runs_in_progress.labels(kind=self.kind).inc()
        # Set only once the run is counted, so a recording failure leaves the run unrecorded rather than half-recorded.
        self._metrics = metrics
        self._tracer = active_tracer()
        self._record.keep_spans = self._tracer is not None

    @property
    def active(self) -> bool:
        return self._metrics is not None

    # A plain call ---------------------------------------------------------------------------

    def __enter__(self) -> "RunRecorder":
        if self.active:
            self._token = _current.set(self._record)
        return self

    def __exit__(self, exc_type: Any, error: BaseException | None, traceback: Any) -> bool:
        if self._token is not None:
            _reset_context(self._token)
            self._token = None
        if error is not None:
            self.fail(error)
        else:
            self.finish()
        return False

    # What the run reports -------------------------------------------------------------------

    @guarded
    def set_outcome(self, status: Any) -> None:
        if self.active and status is not None:
            self._record.outcome = normalise_outcome(status)

    @guarded
    def set_verdicts(self, verdicts: Any) -> None:
        if self.active:
            self._record.verdicts = verdicts

    @guarded
    def set_thread(self, thread_id: Any) -> None:
        """The conversation this run belongs to. It is hashed before it goes to a tracing backend."""
        if self.active and isinstance(thread_id, str) and thread_id:
            self._record.thread = thread_id

    @guarded
    def note_error(self, error: BaseException) -> None:
        """Say why a run failed when the failure is reported as an event rather than raised."""
        if not self.active:
            return
        self._record.outcome = outcome_for_exception(error)
        self._record.error_type = error_type(error)

    @guarded
    def fail(self, error: BaseException) -> None:
        if not self.active:
            return
        if self._record.error_type is None:  # a failure already explained by note_error keeps that explanation
            self.note_error(error)
        self.finish()

    @guarded
    def finish(self, outcome: Any = None) -> None:
        """End the run once; a second call changes nothing."""
        with self._lock:
            if self._finished:
                return
            self._finished = True
        metrics = self._metrics
        if metrics is None:
            return
        final = normalise_outcome(outcome) if outcome else (self._record.outcome or "completed")
        duration = time.perf_counter() - self._started
        self._record_metrics(metrics, final, duration)
        self._export_trace(final, duration)

    @guarded
    def _record_metrics(self, metrics: Metrics, final: str, duration: float) -> None:
        kind = self.kind
        metrics.runs_in_progress.labels(kind=kind).dec()
        metrics.runs.labels(kind=kind, outcome=final).inc()
        metrics.run_duration.labels(kind=kind).observe(duration)
        metrics.run_tool_calls.labels(kind=kind).observe(self._record.tool_calls)
        self._observe_models(metrics)
        note_approval_state(self._record.thread, final)
        if final in SERVER_SIDE_ERRORS:
            metrics.run_errors.labels(kind=kind, error_type=self._record.error_type or "unknown").inc()
        if final == "output_blocked":
            metrics.guardrail_blocks.labels(stage="output").inc()
        elif final == "validation_error":
            metrics.guardrail_blocks.labels(stage="input").inc()
        settled = (kind in VERDICT_KINDS and final in FINAL_CHECK_OUTCOMES) or (
            kind == "chat_decision" and final == DECISION_VERDICT_OUTCOME
        )
        if settled and isinstance(self._record.verdicts, dict):
            for verdict in self._record.verdicts.values():
                name = verdict.get("verdict") if isinstance(verdict, dict) else None
                if name in VERDICTS:
                    metrics.verdicts.labels(verdict=name).inc()

    def _export_trace(self, outcome: str, duration: float) -> None:
        tracer = self._tracer
        if tracer is None:
            return
        try:
            record = self._record
            with record._lock:
                item = TraceItem(
                    kind=self.kind,
                    outcome=outcome,
                    error_type=record.error_type,
                    started=record.started_wall,
                    duration=duration,
                    thread=record.thread,
                    llm_calls=record.llm_calls,
                    llm_errors=record.llm_errors,
                    unpriced_calls=record.unpriced_calls,
                    tool_calls=record.tool_calls,
                    tool_errors=record.tool_errors,
                    input_tokens=record.input_tokens,
                    output_tokens=record.output_tokens,
                    cost=record.cost,
                    spans=tuple(record.spans),
                    spans_dropped=record.spans_dropped,
                    server_side_error=outcome in SERVER_SIDE_ERRORS,
                )
            tracer.submit(item)
        except Exception:
            logger.warning("A run trace could not be prepared.")

    @guarded
    def _observe_models(self, metrics: Metrics) -> None:
        record, kind = self._record, self.kind
        with record._lock:
            calls, cost = record.llm_calls, record.cost
            input_tokens, output_tokens, unpriced = record.input_tokens, record.output_tokens, record.unpriced_calls
        metrics.run_llm_calls.labels(kind=kind).observe(calls)
        if not calls:
            return
        metrics.run_cost.labels(kind=kind).observe(cost)
        metrics.run_tokens.labels(kind=kind, direction="input").inc(input_tokens)
        metrics.run_tokens.labels(kind=kind, direction="output").inc(output_tokens)
        if unpriced:
            metrics.runs_with_unpriced_calls.labels(kind=kind).inc()

    # A stream -------------------------------------------------------------------------------

    @contextmanager
    def attach(self) -> Iterator["RunRecorder"]:
        """Run a block as part of this run, such as setting a stream up. A failure ends the run and is re-raised."""
        if not self.active:
            yield self
            return
        token = _current.set(self._record)
        try:
            yield self
        except BaseException as error:
            self.fail(error)
            raise
        finally:
            _reset_context(token)

    def watch(self, events: Iterable[tuple[str, Any]]) -> Iterable[tuple[str, Any]]:
        """Pass a stream of (name, payload) events through unchanged, recording the run as it goes.

        Each step of the stream runs as part of this run, so its tool calls are counted. The run
        ends with the stream: the outcome comes from the "result" event, and a stream that is closed
        early is "cancelled".
        """
        if not self.active:
            return events
        stream = self._watch(iter(events))
        # A client that leaves before the stream starts never runs its body, so closing it ends nothing.
        # Finishing when the stream is discarded keeps runs_in_progress from staying one too high.
        weakref.finalize(stream, self._abandoned).atexit = False
        return stream

    def _abandoned(self) -> None:
        self.finish(None if self._record.outcome else "cancelled")

    def _watch(self, iterator: Iterator[tuple[str, Any]]) -> Iterator[tuple[str, Any]]:
        first = True
        try:
            while True:
                token = _current.set(self._record)
                try:
                    name, payload = next(iterator)
                except StopIteration:
                    break
                finally:
                    _reset_context(token)
                if first:
                    first = False
                    self._first_event()
                self._see(name, payload)
                yield name, payload
        except GeneratorExit:
            self.finish(None if self._record.outcome else "cancelled")  # a result already seen means the run did finish
            raise
        except Exception as error:
            self.fail(error)
            raise
        self.finish()

    @guarded
    def _first_event(self) -> None:
        self._metrics.stream_first_event.labels(kind=self.kind).observe(time.perf_counter() - self._started)

    @guarded
    def _see(self, name: str, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        if name == "result":
            self._record.outcome = outcome_from_payload(self.kind, payload)
            self._record.verdicts = payload.get("verdicts")
            self.set_thread(payload.get("thread_id"))
        elif name == "error" and self._record.outcome is None:
            self._record.outcome = "error"
