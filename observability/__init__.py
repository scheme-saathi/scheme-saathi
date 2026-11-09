"""Observability: metrics for Prometheus and, in later stages, traces for Langfuse or LangSmith.

Nothing here runs unless OBSERVABILITY_ENABLED is on, so the app behaves as before without it.
Telemetry never carries personal data: see `observability.metrics.ALLOWED_LABELS`.
"""

from observability.config import Settings, settings
from observability.http import install_observability
from observability.metrics import Metrics, get_metrics, set_metrics

__all__ = ["Metrics", "Settings", "get_metrics", "install_observability", "set_metrics", "settings"]
