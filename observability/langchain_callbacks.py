"""A LangChain callback that reports each model call to `observability.llm.record_llm_call`.

It reads only token counts, a provider-reported cost and timing from the result, never the prompt or
the response text, and it never raises into the model call it is watching.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from observability.llm import record_llm_call
from observability.metrics import active_metrics
from observability.runs import current_run
from observability.safety import guarded

logger = logging.getLogger(__name__)


def usage_from_result(result: Any) -> tuple[Any, Any, Any]:
    """(input tokens, output tokens, provider cost) from an LLMResult, with None for what is missing."""
    input_tokens = output_tokens = cost = None
    for generation in (g for group in (getattr(result, "generations", None) or []) for g in group):
        message = getattr(generation, "message", None)
        usage = getattr(message, "usage_metadata", None)
        if isinstance(usage, dict):
            input_tokens, output_tokens = usage.get("input_tokens"), usage.get("output_tokens")
        metadata = getattr(message, "response_metadata", None)
        raw = metadata.get("token_usage") if isinstance(metadata, dict) else None
        if isinstance(raw, dict) and cost is None:
            cost = raw.get("cost")
        if input_tokens is not None:
            break
    llm_output = getattr(result, "llm_output", None)
    raw = llm_output.get("token_usage") if isinstance(llm_output, dict) else None
    if isinstance(raw, dict):
        if input_tokens is None:
            input_tokens = raw.get("prompt_tokens")
        if output_tokens is None:
            output_tokens = raw.get("completion_tokens")
        if cost is None:
            cost = raw.get("cost")
    return input_tokens, output_tokens, cost


class ModelCallRecorder(BaseCallbackHandler):
    """One per model object. `role` and `model` are fixed when the model is built."""

    run_inline = True
    raise_error = False

    def __init__(self, role: str, model: str) -> None:
        self.role = role
        self.model = model
        self._started: dict[UUID, float] = {}
        self._lock = threading.Lock()

    @guarded
    def _begin(self, run_id: UUID) -> None:
        if active_metrics() is None and current_run() is None:
            return
        with self._lock:
            self._started[run_id] = time.perf_counter()

    def _elapsed(self, run_id: UUID) -> float | None:
        with self._lock:
            started = self._started.pop(run_id, None)
        return None if started is None else time.perf_counter() - started

    def on_chat_model_start(self, serialized: Any, messages: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self._begin(run_id)

    def on_llm_start(self, serialized: Any, prompts: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self._begin(run_id)

    def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        elapsed = self._elapsed(run_id)
        if elapsed is None:
            return
        try:
            input_tokens, output_tokens, cost = usage_from_result(response)
            record_llm_call(self.role, self.model, elapsed, input_tokens, output_tokens, cost)
        except Exception:
            logger.warning("A model call could not be recorded.")

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        elapsed = self._elapsed(run_id)
        if elapsed is None:
            return
        try:
            record_llm_call(self.role, self.model, elapsed, error=error)
        except Exception:
            logger.warning("A model call could not be recorded.")
