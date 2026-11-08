"""Which household owns each workflow thread and when it was last used.

This lets a thread be found by its household without reading its saved state, refuses a thread
to anyone but its owner even after a restart, and lets idle or old threads expire: after 24 hours
without use, or 7 days after they started, whichever comes first.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Callable, Iterable
from datetime import timedelta
from enum import Enum
from pathlib import Path

IDLE_LIMIT = timedelta(hours=24)
ABSOLUTE_LIMIT = timedelta(days=7)


class TouchResult(Enum):
    """What happened when a household tried to use a thread."""

    USABLE = "usable"  # the owner's, in date: its last-used time was refreshed
    EXPIRED = "expired"  # past the idle or absolute limit: never refreshed, never revived
    NOT_OWNER = "not_owner"  # in date, but another household's


class ThreadRegistry:
    """Thread owners for one kind of workflow ("agent" or "application").

    It keeps its rows in memory, or in the SQLite file at `path` so they survive a restart.
    Several kinds can share one file.
    """

    def __init__(
        self,
        kind: str,
        path: str | Path | None = None,
        idle_limit: timedelta = IDLE_LIMIT,
        absolute_limit: timedelta = ABSOLUTE_LIMIT,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.kind = kind
        self.idle_seconds = idle_limit.total_seconds()
        self.absolute_seconds = absolute_limit.total_seconds()
        self._clock = clock
        self._lock = threading.Lock()
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(path) if path else ":memory:", timeout=10, check_same_thread=False)
        with self._lock, self._connection:
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS workflow_threads ("
                "kind TEXT NOT NULL, thread_id TEXT NOT NULL, household_id TEXT NOT NULL, "
                "created_at REAL NOT NULL, last_active REAL NOT NULL, PRIMARY KEY (kind, thread_id))"
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS workflow_threads_household ON workflow_threads (kind, household_id)"
            )

    def touch(self, thread_id: str, household_id: str) -> TouchResult:
        """Record use of a thread by its owner, unless it has expired or is another household's.

        An expired thread is never refreshed, so a request that arrives before cleanup runs cannot
        bring it back. The expiry rule is the one `expired()` uses. An unknown thread is created
        for the caller. Each statement is atomic, so two processes sharing one file cannot both
        revive the same thread.
        """
        now = self._clock()
        idle_cutoff, absolute_cutoff = now - self.idle_seconds, now - self.absolute_seconds
        with self._lock, self._connection:
            refreshed = self._connection.execute(
                "UPDATE workflow_threads SET last_active = ? WHERE kind = ? AND thread_id = ? "
                "AND household_id = ? AND last_active >= ? AND created_at >= ?",
                (now, self.kind, thread_id, household_id, idle_cutoff, absolute_cutoff),
            )
            if refreshed.rowcount:
                return TouchResult.USABLE
            created = self._connection.execute(
                "INSERT OR IGNORE INTO workflow_threads (kind, thread_id, household_id, created_at, last_active) "
                "VALUES (?, ?, ?, ?, ?)",
                (self.kind, thread_id, household_id, now, now),
            )
            if created.rowcount:
                return TouchResult.USABLE
            row = self._connection.execute(
                "SELECT last_active, created_at FROM workflow_threads WHERE kind = ? AND thread_id = ?",
                (self.kind, thread_id),
            ).fetchone()
        if row is None or row[0] < idle_cutoff or row[1] < absolute_cutoff:
            return TouchResult.EXPIRED
        return TouchResult.NOT_OWNER

    def owner_of(self, thread_id: str) -> str | None:
        """The household that owns an in-date thread; None for an unknown or expired one."""
        now = self._clock()
        with self._lock:
            row = self._connection.execute(
                "SELECT household_id FROM workflow_threads WHERE kind = ? AND thread_id = ? "
                "AND last_active >= ? AND created_at >= ?",
                (self.kind, thread_id, now - self.idle_seconds, now - self.absolute_seconds),
            ).fetchone()
        return row[0] if row else None

    def is_expired(self, thread_id: str) -> bool:
        """True when the thread is known but past the idle or absolute limit."""
        now = self._clock()
        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM workflow_threads WHERE kind = ? AND thread_id = ? "
                "AND (last_active < ? OR created_at < ?)",
                (self.kind, thread_id, now - self.idle_seconds, now - self.absolute_seconds),
            ).fetchone()
        return row is not None

    def threads_of(self, household_id: str) -> set[str]:
        """Every thread the household owns, expired ones included, so forgetting finds them."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT thread_id FROM workflow_threads WHERE kind = ? AND household_id = ?",
                (self.kind, household_id),
            ).fetchall()
        return {row[0] for row in rows}

    def now(self) -> float:
        return self._clock()

    def expired(self) -> list[str]:
        """Threads idle for longer than the idle limit, or older than the absolute limit."""
        now = self._clock()
        with self._lock:
            rows = self._connection.execute(
                "SELECT thread_id FROM workflow_threads WHERE kind = ? AND (last_active < ? OR created_at < ?)",
                (self.kind, now - self.idle_seconds, now - self.absolute_seconds),
            ).fetchall()
        return [row[0] for row in rows]

    def forget(self, thread_ids: Iterable[str]) -> None:
        with self._lock, self._connection:
            self._connection.executemany(
                "DELETE FROM workflow_threads WHERE kind = ? AND thread_id = ?",
                [(self.kind, thread_id) for thread_id in thread_ids],
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()
