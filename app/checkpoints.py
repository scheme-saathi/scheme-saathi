"""Optional durable workflow state.

Without SCHEME_SAATHI_CHECKPOINT_DB every workflow keeps its state in memory, as before, and it
is lost on restart. With it, state and thread owners are kept in that SQLite file, so a paused
confirmation or approval can be resumed after a restart. Threads still expire (see
`app.thread_registry`), and "Forget my data" deletes them from the file.
"""

from __future__ import annotations

import os
import sqlite3
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.thread_registry import ThreadRegistry

DATABASE_ENV = "SCHEME_SAATHI_CHECKPOINT_DB"


def database_path() -> str | None:
    load_dotenv()
    return os.environ.get(DATABASE_ENV, "").strip() or None


@lru_cache(maxsize=1)
def get_checkpointer() -> BaseCheckpointSaver | None:
    """The shared durable saver, or None when no database is configured."""
    path = database_path()
    if path is None:
        return None
    from langgraph.checkpoint.sqlite import SqliteSaver  # needed only when a database is configured

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(path, timeout=10, check_same_thread=False))


def thread_registry(kind: str) -> ThreadRegistry:
    """A registry for one kind of workflow, in the same file as the saver when one is configured."""
    return ThreadRegistry(kind, database_path())
