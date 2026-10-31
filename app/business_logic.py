"""Adapters between the demo API and Scheme Saathi's existing rule workflow."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import Lock
from typing import Any, Iterator
from uuid import uuid4

from langgraph.types import Command

from graph import tools
from graph.tools import ToolCallError
from graph.workflow import build_graph

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_DOCUMENT_SIZE = 10 * 1024 * 1024
ALLOWED_DOCUMENTS = {
    ".pdf": ("application/pdf", b"%PDF-"),
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
    ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
}
NODE_LABELS = {
    "plan": "Preparing the eligibility check",
    "intake": "Checking profile details",
    "eligibility": "Evaluating reviewed scheme rules",
    "documents": "Finding required documents",
    "draft": "Preparing an application draft",
    "validate": "Validating the draft",
    "approval": "Waiting for your approval",
    "submit": "Recording the mock submission",
    "escalate": "Flagging the case for human review",
}


class SessionNotFoundError(LookupError):
    """Raised when an API request refers to an unknown workflow session."""


class WorkflowConflictError(RuntimeError):
    """Raised when a workflow action is not valid for its current state."""


class DemoService:
    """Run reviewed rules and mock application workflows for the local demo."""

    def __init__(self) -> None:
        self.workflow = build_graph()
        self._uploads: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
        self._uploads_lock = Lock()

    def available_schemes(self) -> list[dict[str, Any]]:
        """Return schemes with reviewed rules and their intake/document requirements."""
        scheme_ids = tools.search_schemes({})
        names = {scheme_id: scheme_id for scheme_id in scheme_ids}
        for directory in (
            PROJECT_ROOT / "data" / "schemes",
            PROJECT_ROOT / "data" / "rules",
        ):
            for path in directory.glob("*.json"):
                record = json.loads(path.read_text(encoding="utf-8"))
                scheme_id = record.get("scheme_id")
                if scheme_id in names:
                    names[scheme_id] = record.get("name", scheme_id)

        return [
            {
                "scheme_id": scheme_id,
                "name": names[scheme_id],
                "required_fields": tools.required_fields([scheme_id]),
                "required_documents": tools.list_documents(scheme_id),
            }
            for scheme_id in scheme_ids
        ]

    def analyze(
        self, citizen: dict[str, Any], scheme_ids: list[str] | None = None
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        """Validate schemes and return a stream for a new eligibility workflow."""
        tools.search_schemes({}, scheme_ids)
        thread_id = str(uuid4())
        config = {"configurable": {"thread_id": thread_id}}
        run_input: dict[str, Any] = {"simulated_citizen": citizen}
        if scheme_ids:
            run_input["scheme_ids"] = scheme_ids
        return self._stream_run(run_input, config, thread_id)

    def decide(
        self, thread_id: str, action: str, payload_hash: str | None, changes: dict[str, Any]
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        """Validate an application decision and resume the matching workflow."""
        snapshot = self._get_snapshot(thread_id)
        if "approval" not in snapshot.next:
            raise WorkflowConflictError(
                "This application is not waiting for approval."
            )

        config = {"configurable": {"thread_id": thread_id}}
        decision: dict[str, Any] = {"action": action}
        if action == "approve":
            if not payload_hash:
                raise ValueError("Approving requires the current application hash.")
            application = snapshot.values.get("application", {})
            scheme_id = application.get("scheme_id")
            missing = self._missing_documents(thread_id, scheme_id)
            if missing:
                raise WorkflowConflictError(
                    "Upload all required documents before submitting: "
                    + ", ".join(missing)
                )
            decision["payload_hash"] = payload_hash
        elif action == "edit":
            decision["changes"] = changes
        return self._stream_run(Command(resume=decision), config, thread_id)

    def upload_document(
        self,
        thread_id: str,
        scheme_id: str,
        document_type: str,
        filename: str,
        content_type: str | None,
        content: bytes,
    ) -> dict[str, Any]:
        """Validate a required document and retain upload metadata only."""
        if not content or len(content) > MAX_DOCUMENT_SIZE:
            raise ValueError("Choose a non-empty document smaller than 10 MB.")

        safe_filename = Path(filename.replace("\\", "/")).name
        extension = Path(safe_filename).suffix.lower()
        expected = ALLOWED_DOCUMENTS.get(extension)
        mime_type = (content_type or "").split(";", maxsplit=1)[0].strip().lower()
        if (
            expected is None
            or (mime_type not in (expected[0], "application/octet-stream", ""))
            or not content.startswith(expected[1])
        ):
            raise ValueError("Upload a valid PDF, PNG, or JPEG document.")

        snapshot = self._get_snapshot(thread_id)
        if "approval" not in snapshot.next:
            raise WorkflowConflictError(
                "This application is not waiting for approval."
            )
        required_documents = snapshot.values.get("documents", {}).get(scheme_id)
        if required_documents is None:
            raise ValueError("That scheme is not part of this application.")
        if document_type not in required_documents:
            raise ValueError("That document is not required for the selected scheme.")

        upload = {
            "document_type": document_type,
            "filename": safe_filename,
            "file_size": len(content),
        }
        with self._uploads_lock:
            self._uploads.setdefault(thread_id, {}).setdefault(scheme_id, {})[
                document_type
            ] = upload
            uploaded_documents = list(self._uploads[thread_id][scheme_id])

        return {
            "status": "success",
            **upload,
            "uploaded_documents": uploaded_documents,
            "required_documents": required_documents,
        }

    def _missing_documents(self, thread_id: str, scheme_id: str | None) -> list[str]:
        if not scheme_id:
            return []
        snapshot = self._get_snapshot(thread_id)
        required = snapshot.values.get("documents", {}).get(scheme_id, [])
        with self._uploads_lock:
            uploaded = self._uploads.get(thread_id, {}).get(scheme_id, {})
            return [document for document in required if document not in uploaded]

    def _get_snapshot(self, thread_id: str) -> Any:
        snapshot = self.workflow.get_state(
            {"configurable": {"thread_id": thread_id}}
        )
        if not snapshot.values:
            raise SessionNotFoundError("The application session was not found.")
        return snapshot

    def _stream_run(
        self, run_input: Any, config: dict[str, Any], thread_id: str
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        yield "progress", {"node": "start", "label": "Starting the workflow"}
        try:
            for update in self.workflow.stream(
                run_input, config, stream_mode="updates"
            ):
                for node in update:
                    yield "progress", {
                        "node": node,
                        "label": NODE_LABELS.get(
                            node, node.replace("_", " ").title()
                        ),
                    }
            yield "result", self._snapshot_payload(
                thread_id, self.workflow.get_state(config)
            )
        except ToolCallError as error:
            logger.exception("A Scheme Saathi workflow tool failed.")
            yield "error", {"detail": str(error)}

    @staticmethod
    def _snapshot_payload(thread_id: str, snapshot: Any) -> dict[str, Any]:
        values = snapshot.values
        approval = next(
            (
                interrupt.value
                for task in snapshot.tasks
                for interrupt in task.interrupts
            ),
            None,
        )
        return {
            "thread_id": thread_id,
            "profile": values.get("profile", {}),
            "verdicts": values.get("verdicts", {}),
            "documents": values.get("documents", {}),
            "application": values.get("application", {}),
            "approval": approval,
            "approval_status": values.get("approval_status"),
            "submission": values.get("submission"),
            "needs_human": values.get("needs_human", False),
            "critique": values.get("critique", []),
        }
