"""Optional SQLite-backed replay protection for mock-portal capabilities."""

from __future__ import annotations

import os
import sqlite3
import time
from collections.abc import Generator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path


class NonceStore:
    def __init__(self, path: str) -> None:
        if path == ":memory:":
            raise ValueError("MOCK_PORTAL_NONCE_DB must be a persistent file.")
        file = Path(path).expanduser()
        file.parent.mkdir(parents=True, exist_ok=True)
        if file.is_symlink():
            raise ValueError("MOCK_PORTAL_NONCE_DB must not be a symlink.")
        fd = os.open(file, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(fd, 0o600)
            else:
                os.chmod(file, 0o600)
        finally:
            os.close(fd)
        self.path = str(file)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS used_nonces "
                "(nonce TEXT PRIMARY KEY, expires_at REAL NOT NULL)"
            )

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def consume_nonce(self, nonce: str, expires_at: float) -> bool:
        with self.connect() as db:
            db.execute("DELETE FROM used_nonces WHERE expires_at < ?", (time.time(),))
            result = db.execute(
                "INSERT OR IGNORE INTO used_nonces (nonce, expires_at) VALUES (?, ?)",
                (nonce, expires_at),
            )
        return result.rowcount == 1


@lru_cache(maxsize=8)
def _store(path: str) -> NonceStore:
    return NonceStore(path)


def nonce_store() -> NonceStore | None:
    path = os.getenv("MOCK_PORTAL_NONCE_DB", "").strip()
    return _store(path) if path else None
