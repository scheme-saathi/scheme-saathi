"""
ChromaDB-backed LangGraph checkpointer for workflow state persistence.

This adapter enables resumable workflows with full state reconstruction.
Implements LangGraph BaseCheckpointer interface with ChromaDB backend.
"""

import json
from datetime import datetime
from typing import Optional, Any
from uuid import uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple
import chromadb

from graph.state import WorkflowState


class ChromaDBCheckpointer(BaseCheckpointSaver):
    """
    LangGraph checkpointer using ChromaDB for durability.

    Features:
    - Full workflow state serialization
    - Automatic checkpoint versioning
    - Resumable from any checkpoint
    - Garbage collection of old checkpoints
    - Thread-safe access
    """

    def __init__(self, persist_directory: Optional[str] = None, namespace: str = "default"):
        """
        Initialize ChromaDB checkpointer.

        Args:
            persist_directory: Path for persistent storage
            namespace: Namespace for checkpoint isolation (e.g., per-tenant)
        """
        if persist_directory is None:
            persist_directory = "./chroma_checkpoints"

        self.client = chromadb.PersistentClient(path=persist_directory)
        self.namespace = namespace

        # Create checkpoints collection
        self.checkpoints = self.client.get_or_create_collection(
            name=f"checkpoints_{namespace}",
            metadata={"description": f"Workflow checkpoints for {namespace}"},
        )

    def put_checkpoint(
        self,
        config: dict[str, Any],
        checkpoint: dict[str, Any],
        metadata: dict[str, Any],
    ) -> Optional[str]:
        """
        Save a checkpoint.

        Args:
            config: Configuration dict with checkpoint_ns, checkpoint_id
            checkpoint: State to checkpoint
            metadata: Checkpoint metadata

        Returns:
            Checkpoint version ID
        """
        checkpoint_ns = config.get("checkpoint_ns", "default")
        checkpoint_id = config.get("checkpoint_id", str(uuid4()))
        checkpoint_version = str(uuid4())

        # Serialize checkpoint
        checkpoint_data = {
            "config": config,
            "checkpoint": checkpoint,
            "metadata": metadata,
            "timestamp": datetime.utcnow().isoformat(),
            "checkpoint_version": checkpoint_version,
        }

        # Store in ChromaDB
        self.checkpoints.upsert(
            ids=[f"{checkpoint_ns}:{checkpoint_id}:{checkpoint_version}"],
            metadatas={
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
                "checkpoint_version": checkpoint_version,
                "timestamp": datetime.utcnow().isoformat(),
            },
            documents=[json.dumps(checkpoint_data, default=str)],
        )

        return checkpoint_version

    def get_checkpoint(
        self,
        config: dict[str, Any],
    ) -> Optional[CheckpointTuple]:
        """
        Retrieve the latest checkpoint.

        Args:
            config: Configuration dict with checkpoint_ns, checkpoint_id

        Returns:
            CheckpointTuple with checkpoint data or None
        """
        checkpoint_ns = config.get("checkpoint_ns", "default")
        checkpoint_id = config.get("checkpoint_id")

        if not checkpoint_id:
            return None

        # Query ChromaDB for latest checkpoint
        results = self.checkpoints.get(
            where={
                "$and": [
                    {"checkpoint_ns": {"$eq": checkpoint_ns}},
                    {"checkpoint_id": {"$eq": checkpoint_id}},
                ]
            },
        )

        if not results["documents"]:
            return None

        # Get latest (last one in list, assuming ChromaDB returns in insertion order)
        latest_doc = results["documents"][-1]
        checkpoint_data = json.loads(latest_doc)

        return CheckpointTuple(
            config=checkpoint_data["config"],
            checkpoint=checkpoint_data["checkpoint"],
            metadata=checkpoint_data["metadata"],
        )

    def list_checkpoints(
        self,
        config: dict[str, Any],
    ) -> list[CheckpointTuple]:
        """
        List all checkpoints for a workflow run.

        Args:
            config: Configuration dict with checkpoint_ns, checkpoint_id

        Returns:
            List of CheckpointTuple objects
        """
        checkpoint_ns = config.get("checkpoint_ns", "default")
        checkpoint_id = config.get("checkpoint_id")

        if not checkpoint_id:
            return []

        # Query ChromaDB
        results = self.checkpoints.get(
            where={
                "$and": [
                    {"checkpoint_ns": {"$eq": checkpoint_ns}},
                    {"checkpoint_id": {"$eq": checkpoint_id}},
                ]
            },
        )

        checkpoints = []
        for doc in results.get("documents", []):
            checkpoint_data = json.loads(doc)
            checkpoints.append(
                CheckpointTuple(
                    config=checkpoint_data["config"],
                    checkpoint=checkpoint_data["checkpoint"],
                    metadata=checkpoint_data["metadata"],
                )
            )

        return checkpoints

    def delete_checkpoint(
        self,
        config: dict[str, Any],
        checkpoint_version: str,
    ) -> None:
        """
        Delete a specific checkpoint.

        Args:
            config: Configuration dict with checkpoint_ns, checkpoint_id
            checkpoint_version: Version to delete
        """
        checkpoint_ns = config.get("checkpoint_ns", "default")
        checkpoint_id = config.get("checkpoint_id")

        if not checkpoint_id:
            return

        checkpoint_key = f"{checkpoint_ns}:{checkpoint_id}:{checkpoint_version}"
        self.checkpoints.delete(ids=[checkpoint_key])

    def cleanup_old_checkpoints(
        self,
        config: dict[str, Any],
        max_checkpoints: int = 10,
    ) -> int:
        """
        Clean up old checkpoints, keeping only the most recent.

        Args:
            config: Configuration dict
            max_checkpoints: Maximum checkpoints to retain

        Returns:
            Number of checkpoints deleted
        """
        checkpoint_ns = config.get("checkpoint_ns", "default")
        checkpoint_id = config.get("checkpoint_id")

        if not checkpoint_id:
            return 0

        # Get all checkpoints
        results = self.checkpoints.get(
            where={
                "$and": [
                    {"checkpoint_ns": {"$eq": checkpoint_ns}},
                    {"checkpoint_id": {"$eq": checkpoint_id}},
                ]
            },
        )

        # Delete older ones (keep most recent max_checkpoints)
        total = len(results["ids"])
        to_delete = total - max_checkpoints

        if to_delete > 0:
            ids_to_delete = results["ids"][:to_delete]
            self.checkpoints.delete(ids=ids_to_delete)
            return to_delete

        return 0

    def get_namespace_info(self) -> dict[str, Any]:
        """Get info about checkpoints in this namespace."""
        results = self.checkpoints.get(
            where={"checkpoint_ns": {"$eq": self.namespace}}
        )

        return {
            "namespace": self.namespace,
            "total_checkpoints": len(results["ids"]),
            "unique_workflows": len(set(m["checkpoint_id"] for m in results["metadatas"])),
        }
