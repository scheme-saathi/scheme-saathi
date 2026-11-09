"""Deleting everything held for a household, one store at a time, and saying what happened."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def household_threads(saver: Any, household_id: str) -> set[str]:
    """Threads whose saved workflow state belongs to the household, even if nothing else still names them."""
    if saver is None:
        return set()
    threads: set[str] = set()
    for item in saver.list(None):
        values = (item.checkpoint or {}).get("channel_values") or {}
        if values.get("actor_id") == household_id:
            threads.add(item.config["configurable"]["thread_id"])
    return threads


def run_forgetting(
    steps: list[tuple[str, Callable[[], int | None]]],
    depends_on: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Run every deletion step in order and report each one, whether or not another failed.

    A step named in `depends_on` is skipped when the step it needs failed, because the failed
    one still needs the information that step would remove. Deletion can be repeated safely.
    """
    depends_on = depends_on or {}
    results: dict[str, dict[str, Any]] = {}
    for name, step in steps:
        needs = depends_on.get(name)
        if needs and results.get(needs, {}).get("status") != "deleted":
            results[name] = {"status": "skipped"}
            continue
        try:
            count = step()
        except Exception as error:
            logger.error("Could not delete the %s held for a household (%s).", name, type(error).__name__)
            results[name] = {"status": "failed"}
        else:
            results[name] = {"status": "deleted"} if count is None else {"status": "deleted", "count": count}
    return results


def all_deleted(results: dict[str, dict[str, Any]]) -> bool:
    """True only when every store was cleared; a skipped or failed one is not success."""
    return all(result["status"] in {"deleted", "not_applicable"} for result in results.values())


def unfinished(results: dict[str, dict[str, Any]]) -> list[str]:
    return [name for name, result in results.items() if result["status"] not in {"deleted", "not_applicable"}]
