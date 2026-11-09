"""Observability must never break the app: a failure while recording is skipped and reported, not raised.

`guarded` wraps the recording steps the app calls. The first failure of each step is logged as a warning with
the exception class name only (never its message, which could hold content); later ones are logged at debug level
so a persistent fault cannot flood the log.
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

_reported: set[str] = set()

F = TypeVar("F", bound=Callable[..., Any])


def report_failure(step: str, error: BaseException) -> None:
    first = step not in _reported
    _reported.add(step)
    (logger.warning if first else logger.debug)(
        "Observability step %s failed (%s) and was skipped.", step, type(error).__name__
    )


def guarded(function: F) -> F:
    """Run `function`; on any ordinary exception, report it and return None."""

    @functools.wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return function(*args, **kwargs)
        except Exception as error:
            report_failure(function.__qualname__, error)
            return None

    return wrapper  # type: ignore[return-value]
