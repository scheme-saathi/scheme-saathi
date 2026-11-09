"""Observability settings, read from the environment each time so tests and `.env` changes apply."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

ENABLED_ENV = "OBSERVABILITY_ENABLED"
METRICS_TOKEN_ENV = "METRICS_BEARER_TOKEN"
_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    enabled: bool
    metrics_token: str | None  # required to read /metrics; without it the endpoint refuses everyone


def settings() -> Settings:
    load_dotenv()
    enabled = os.environ.get(ENABLED_ENV, "").strip().lower() in _TRUE
    token = os.environ.get(METRICS_TOKEN_ENV, "").strip() or None
    return Settings(enabled=enabled, metrics_token=token)
