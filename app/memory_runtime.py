"""The API's long-term memory store: created on first use and cleaned up on a timer."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from threading import Event, Thread

from dotenv import load_dotenv

from agents.memory import MemoryScope, MemoryService
from app.auth import AuthenticatedHousehold

logger = logging.getLogger(__name__)

DIRECTORY_ENV = "SCHEME_SAATHI_MEMORY_DIR"
CLEANUP_INTERVAL = 300  # seconds; expired records are unusable at once, this only deletes them


class MemoryCleanup:
    """Deletes expired memory records now and then every CLEANUP_INTERVAL seconds."""

    def __init__(self, service: MemoryService, interval: float = CLEANUP_INTERVAL) -> None:
        self._service = service
        self._interval = interval
        self._stop = Event()
        self._thread = Thread(target=self._run, name="memory-cleanup", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def _run(self) -> None:
        while True:
            try:
                removed = self._service.purge_expired()
                if removed:
                    logger.info("Removed %d expired memory records.", removed)
            except Exception:
                logger.exception("Could not remove expired memory records.")
            if self._stop.wait(self._interval):
                return


@lru_cache(maxsize=1)
def get_memory_service() -> MemoryService | None:
    """The shared memory store, or None when ChromaDB is not installed."""
    load_dotenv()
    try:
        from agents.chromadb_memory_service import ChromaDBMemoryService
    except ImportError:
        logger.warning("chromadb is not installed, so remembering details is turned off.")
        return None
    service = ChromaDBMemoryService(persist_directory=os.environ.get(DIRECTORY_ENV) or None)
    MemoryCleanup(service)
    return service


def memory_scope(principal: AuthenticatedHousehold) -> MemoryScope:
    """The scope for the signed-in person, built from the verified token only."""
    return MemoryScope(
        actor_id=principal.subject, household_id=principal.household_id, actor_role=principal.role
    )


def forget_memory(service: MemoryService, scope: MemoryScope) -> None:
    """Delete what the signed-in person's memory holds.

    A citizen's whole household goes. An operator has no household memory to delete, only the
    list of applications they chose to keep, which is cleared by withdrawing its consent.
    """
    if scope.actor_role == "citizen":
        service.forget_household(scope)
        return
    for _ in range(10):  # a person holds at most one active consent per purpose
        consent = service.active_consent(scope, "application_references")
        if consent is None:
            break
        service.withdraw_consent(scope, consent.consent_reference)
    for reference in service.read_application_references(scope):
        service.delete_application_reference(scope, reference.application_id)
