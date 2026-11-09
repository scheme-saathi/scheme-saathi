"""Observability settings, read from the environment each time so tests and `.env` changes apply."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

ENABLED_ENV = "OBSERVABILITY_ENABLED"
METRICS_TOKEN_ENV = "METRICS_BEARER_TOKEN"
TRACING_BACKEND_ENV = "TRACING_BACKEND"
SAMPLE_RATE_ENV = "TRACING_SAMPLE_RATE"
HASH_SALT_ENV = "TRACING_HASH_SALT"
LANGSMITH_PROJECT_ENV = "LANGSMITH_PROJECT"
_TRUE = {"1", "true", "yes", "on"}
DEFAULT_PROJECT = "scheme-saathi"


@dataclass(frozen=True)
class Settings:
    enabled: bool
    metrics_token: str | None  # required to read /metrics; without it the endpoint refuses everyone
    tracing_backend: str = "none"  # "none" or "langsmith"; anything else is reported and treated as none
    sample_rate: float = 1.0  # share of runs sent to the tracing backend; failed runs are always sent
    hash_salt: str | None = None
    project: str = DEFAULT_PROJECT


def sample_rate_from(text: str) -> float:
    try:
        rate = float(text)
    except ValueError:
        return 1.0
    return min(max(rate, 0.0), 1.0) if rate == rate else 1.0


def settings() -> Settings:
    load_dotenv()
    enabled = os.environ.get(ENABLED_ENV, "").strip().lower() in _TRUE
    token = os.environ.get(METRICS_TOKEN_ENV, "").strip() or None
    return Settings(
        enabled=enabled,
        metrics_token=token,
        tracing_backend=os.environ.get(TRACING_BACKEND_ENV, "").strip().lower() or "none",
        sample_rate=sample_rate_from(os.environ.get(SAMPLE_RATE_ENV, "").strip() or "1"),
        hash_salt=os.environ.get(HASH_SALT_ENV, "").strip() or None,
        project=os.environ.get(LANGSMITH_PROJECT_ENV, "").strip() or DEFAULT_PROJECT,
    )
