"""Run a cleanup function now and then on an interval, in a background thread."""

from __future__ import annotations

import logging
from collections.abc import Callable
from threading import Event, Thread

logger = logging.getLogger(__name__)

EXPIRY_INTERVAL = 300  # seconds; an expired thread is refused at once, this only deletes it


class PeriodicTask:
    """Calls `task` immediately and then every `interval` seconds until stopped."""

    def __init__(self, name: str, task: Callable[[], int | None], interval: float = EXPIRY_INTERVAL) -> None:
        self.name = name
        self._task = task
        self._interval = interval
        self._stop = Event()
        self._thread = Thread(target=self._run, name=name, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def _run(self) -> None:
        while True:
            try:
                removed = self._task()
                if removed:
                    logger.info("%s removed %d expired items.", self.name, removed)
            except Exception as error:
                logger.error("%s failed (%s).", self.name, type(error).__name__)
            if self._stop.wait(self._interval):
                return
 