"""Local storage for uploaded supporting documents."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class DocumentStorageError(RuntimeError):
    """A stored document could not be safely stored or retrieved."""


class LocalDocumentStore:
    """Store supporting document bytes and metadata on the local filesystem."""

    DIRECTORY_ENV = "SCHEME_SAATHI_DOCUMENT_STORE_DIR"
    RETENTION = timedelta(days=30)
    MAINTENANCE_INTERVAL = 15 * 60
    _locks: dict[Path, Lock] = {}
    _locks_lock = Lock()

    def __init__(
        self,
        root: Path,
        *,
        start_maintenance: bool = True,
    ) -> None:
        self.root = root.resolve()
        self.manifest_path = self.root / "manifest.json"
        with self._locks_lock:
            self._lock = self._locks.setdefault(self.root, Lock())
        self._stop_maintenance = Event()
        self._maintenance_thread: Thread | None = None
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise DocumentStorageError(
                "Could not create the local document storage directory."
            ) from error
        if self.manifest_path.exists():
            self.purge_expired()
        if start_maintenance:
            self._maintenance_thread = Thread(
                target=self._maintenance_loop,
                name="scheme-saathi-document-expiry",
                daemon=True,
            )
            self._maintenance_thread.start()

    @classmethod
    def configured_directory(cls) -> Path:
        load_dotenv()
        configured = os.environ.get(cls.DIRECTORY_ENV)
        return (
            Path(configured).expanduser()
            if configured
            else Path(__file__).resolve().parents[1]
            / "data"
            / "private_documents"
        )

    @classmethod
    def from_environment(cls) -> LocalDocumentStore:
        load_dotenv()
        return cls(cls.configured_directory())

    def store(
        self,
        *,
        thread_id: str,
        scheme_id: str,
        document_type: str,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> dict[str, Any]:
        record_key = self._record_key(thread_id, scheme_id, document_type)
        now = datetime.now(timezone.utc)
        file_id = uuid4().hex
        expires_at = now + self.RETENTION
        metadata = {
            "thread_id": thread_id,
            "scheme_id": scheme_id,
            "document_type": document_type,
            "filename": filename,
            "content_type": content_type,
            "file_size": len(content),
            "uploaded_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "file_id": file_id,
        }
        with self._lock:
            records = self._read_records()
            self._purge_locked(records, now)
            self._write_document_file(self._file_path(file_id), content)
            previous = records.get(record_key)
            records[record_key] = metadata
            try:
                self._write_records(records)
            except DocumentStorageError:
                self._unlink(self._file_path(file_id))
                raise
            if previous:
                self._unlink(self._file_path(previous["file_id"]))
        return self._public_metadata(metadata)

    def list_documents(
        self, thread_id: str, scheme_id: str | None = None
    ) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        with self._lock:
            records = self._read_records()
            self._purge_locked(records, now)
            return [
                self._public_metadata(record)
                for record in records.values()
                if record["thread_id"] == thread_id
                and (scheme_id is None or record["scheme_id"] == scheme_id)
            ]

    def get_document(
        self, thread_id: str, scheme_id: str, document_type: str
    ) -> tuple[bytes, dict[str, Any]]:
        record_key = self._record_key(thread_id, scheme_id, document_type)
        now = datetime.now(timezone.utc)
        with self._lock:
            records = self._read_records()
            self._purge_locked(records, now)
            metadata = records.get(record_key)
            if metadata is None:
                raise FileNotFoundError("The supporting document is unavailable.")
            path = self._file_path(metadata["file_id"])
            try:
                content = path.read_bytes()
            except FileNotFoundError as error:
                raise DocumentStorageError(
                    "The stored supporting document is missing."
                ) from error
            except OSError as error:
                raise DocumentStorageError(
                    "The stored supporting document could not be read."
                ) from error
            return content, self._public_metadata(metadata)

    def delete_thread(self, thread_id: str) -> int:
        with self._lock:
            records = self._read_records()
            matches = [
                (record_key, metadata)
                for record_key, metadata in records.items()
                if metadata["thread_id"] == thread_id
            ]
            for record_key, metadata in matches:
                del records[record_key]
            if matches:
                self._write_records(records)
                for _, metadata in matches:
                    self._unlink(self._file_path(metadata["file_id"]))
            return len(matches)

    def purge_expired(self) -> int:
        now = datetime.now(timezone.utc)
        with self._lock:
            records = self._read_records()
            return self._purge_locked(records, now)

    def close(self) -> None:
        self._stop_maintenance.set()
        if self._maintenance_thread:
            self._maintenance_thread.join(timeout=2)

    def _maintenance_loop(self) -> None:
        while not self._stop_maintenance.wait(self.MAINTENANCE_INTERVAL):
            try:
                self.purge_expired()
            except (DocumentStorageError, OSError):
                logger.exception("Could not purge expired supporting documents.")

    @staticmethod
    def _record_key(thread_id: str, scheme_id: str, document_type: str) -> str:
        return json.dumps([thread_id, scheme_id, document_type], ensure_ascii=True)

    def _file_path(self, file_id: str) -> Path:
        if len(file_id) != 32 or any(char not in "0123456789abcdef" for char in file_id):
            raise DocumentStorageError("The stored document index is invalid.")
        return self.root / f"{file_id}.bin"

    def _read_records(self) -> dict[str, dict[str, Any]]:
        if not self.manifest_path.exists():
            return {}
        try:
            records = json.loads(self.manifest_path.read_bytes())
        except (OSError, json.JSONDecodeError) as error:
            raise DocumentStorageError(
                "The local document index could not be read."
            ) from error
        if not isinstance(records, dict):
            raise DocumentStorageError("The local document index is invalid.")
        return records

    def _write_records(self, records: dict[str, dict[str, Any]]) -> None:
        serialized = json.dumps(records, ensure_ascii=True).encode("utf-8")
        temporary_path = self.root / f".manifest-{uuid4().hex}.tmp"
        try:
            temporary_path.write_bytes(serialized)
            temporary_path.replace(self.manifest_path)
        except OSError as error:
            self._unlink(temporary_path)
            raise DocumentStorageError(
                "Could not persist the local document index."
            ) from error

    def _write_document_file(self, path: Path, content: bytes) -> None:
        temporary_path = self.root / f".document-{uuid4().hex}.tmp"
        try:
            temporary_path.write_bytes(content)
            temporary_path.replace(path)
        except OSError as error:
            self._unlink(temporary_path)
            raise DocumentStorageError(
                "Could not persist the supporting document."
            ) from error

    def _purge_locked(
        self, records: dict[str, dict[str, Any]], now: datetime
    ) -> int:
        expired = [
            record_key
            for record_key, metadata in records.items()
            if datetime.fromisoformat(metadata["expires_at"]) <= now
        ]
        expired_records = [records.pop(record_key) for record_key in expired]
        if expired_records:
            self._write_records(records)
            for metadata in expired_records:
                self._unlink(self._file_path(metadata["file_id"]))
        return len(expired_records)

    @staticmethod
    def _public_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in metadata.items()
            if key != "file_id"
        }

    @staticmethod
    def _unlink(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            raise DocumentStorageError(
                "Could not remove a supporting document."
            ) from error
