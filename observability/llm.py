"""Model calls: latency, tokens, cost and errors, recorded per role and model and added to the current run.

Cost comes from the provider when it reports one (OpenRouter does when asked). Otherwise it is worked
out from the price table. A successful call with neither is counted as unpriced, never as free.

Only the role, the model ID from the environment, token counts and numbers are recorded: no prompt, no
response, and no error message.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from observability.metrics import active_metrics
from observability.pricing import number, price_for
from observability.runs import current_run, error_type
from observability.safety import guarded
from observability.tracing import Span

# The agent roles that call a model. Anything else is "other".
ROLES = frozenset({"supervisor", "specialist", "router", "other"})

_MODEL_LABEL = re.compile(r"[^A-Za-z0-9._:/@+-]")


def model_label(model: Any) -> str:
    """A model ID that is safe as a label value: a short string of plain characters."""
    cleaned = _MODEL_LABEL.sub("", model) if isinstance(model, str) else ""
    return cleaned[:80] or "unknown"


def role_label(role: Any) -> str:
    return role if role in ROLES else "other"


def count(value: Any) -> int:
    """A token count from provider data, which is untrusted: a non-negative whole number or zero."""
    number_ = number(value)
    return int(number_) if number_ is not None else 0


@guarded
def record_llm_call(
    role: str,
    model: str,
    duration_seconds: float,
    input_tokens: Any = None,
    output_tokens: Any = None,
    provider_cost: Any = None,
    error: BaseException | None = None,
) -> None:
    """One model call that has finished, successfully or not."""
    run = current_run()
    metrics = active_metrics()
    if run is None and metrics is None:
        return
    role, model = role_label(role), model_label(model)
    tokens_in, tokens_out = count(input_tokens), count(output_tokens)

    cost: float | None = None
    source = ""
    if error is None:
        reported = number(provider_cost)
        if reported is not None:
            cost, source = reported, "provider"
        elif tokens_in or tokens_out:
            price = price_for(model)
            if price is not None:
                cost, source = price.cost(tokens_in, tokens_out), "table"

    if run is not None:
        run.add_llm_call(failed=error is not None, input_tokens=tokens_in, output_tokens=tokens_out, cost=cost)
        if run.keep_spans:
            duration = max(duration_seconds, 0.0)
            usage = {"input_tokens": tokens_in, "output_tokens": tokens_out, "total_tokens": tokens_in + tokens_out}
            if cost is not None:
                usage["total_cost"] = cost
            run.add_span(
                Span(
                    name=f"{role} {model}",
                    run_type="llm",
                    start=datetime.now(timezone.utc) - timedelta(seconds=duration),
                    duration=duration,
                    metadata={"ls_model_name": model, "role": role, "cost_source": source or "none"},
                    outputs={"usage_metadata": usage},
                    error=error_type(error) if error is not None else None,
                )
            )
    if metrics is None:
        return

    outcome = "error" if error is not None else "success"
    metrics.llm_calls.labels(role=role, model=model, outcome=outcome).inc()
    metrics.llm_duration.labels(role=role, model=model).observe(max(duration_seconds, 0.0))
    if tokens_in:
        metrics.llm_tokens.labels(role=role, model=model, direction="input").inc(tokens_in)
    if tokens_out:
        metrics.llm_tokens.labels(role=role, model=model, direction="output").inc(tokens_out)
    if error is not None:
        metrics.llm_errors.labels(role=role, model=model, error_type=error_type(error)).inc()
    elif cost is None:
        metrics.llm_unpriced.labels(role=role, model=model).inc()
    else:
        metrics.llm_cost.labels(role=role, model=model, cost_source=source).inc(cost)
