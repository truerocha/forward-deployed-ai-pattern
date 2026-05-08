"""
Memory Manager — Unified Memory API (Activity 3.09).

Provides a unified memory API for storing, recalling, consolidating,
and forgetting memory items. All memory is persisted to DynamoDB for
cross-session durability.

Operations:
  - store(memory_type, content, metadata): Persist a memory item
  - recall(query, memory_type, limit): Retrieve relevant memories
  - consolidate(): Merge redundant memories (weekly job)
  - forget(memory_id): Remove a specific memory

Memory types:
  - "decision": Architectural or design decisions made
  - "outcome": Results of actions taken
  - "error_pattern": Recurring error patterns observed
  - "adr": Architecture Decision Records
  - "learning": Lessons learned from task execution

DynamoDB table: fde-dev-memory
  PK: project_id
  SK: memory_key (format: "memory#{memory_type}#{uuid}")

Ref: docs/design/fde-core-brain-development.md Section 3 (Wave 3)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

VALID_MEMORY_TYPES = frozenset({"decision", "outcome", "error_pattern", "adr", "learning"})

_CONSOLIDATION_SIMILARITY_THRESHOLD = 0.85
_CONSOLIDATION_BATCH_SIZE = 100


@dataclass
class MemoryItem:
    """A single memory item stored in the system."""

    memory_id: str
    memory_type: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""
    created_at: str = ""
    updated_at: str = ""
    access_count: int = 0
    last_accessed: str = ""
    consolidated_from: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
        if not self.content_hash:
            self.content_hash = hashlib.sha256(self.content.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dictionary."""
        return {
            "memory_id": self.memory_id,
            "memory_type": self.memory_type,
            "content": self.content,
            "metadata": self.metadata,
            "content_hash": self.content_hash,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed,
            "consolidated_from": self.consolidated_from,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryItem:
        """Deserialize from dictionary."""
        return cls(
            memory_id=data.get("memory_id", ""),
            memory_type=data.get("memory_type", ""),
            content=data.get("content", ""),
            metadata=data.get("metadata", {}),
            content_hash=data.get("content_hash", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            access_count=data.get("access_count", 0),
            last_accessed=data.get("last_accessed", ""),
            consolidated_from=data.get("consolidated_from", []),
        )


class MemoryManager:
    """
    Unified memory API for cross-session persistence.

    Stores memory items in DynamoDB with support for keyword-based
    recall, consolidation of duplicates, and selective forgetting.

    Usage:
        mm = MemoryManager(project_id="my-repo", memory_table="fde-dev-memory")
        mm.store("decision", "Use DynamoDB for state", {"context": "ADR-009"})
        results = mm.recall("DynamoDB state management")
        mm.consolidate()
        mm.forget("memory-id-123")
    """

    def __init__(
        self,
        project_id: str,
        memory_table: str | None = None,
    ):
        self._project_id = project_id or os.environ.get("PROJECT_ID", "global")
        self._memory_table = memory_table or os.environ.get(
            "MEMORY_TABLE", "fde-dev-memory"
        )
        self._dynamodb = boto3.resource("dynamodb")

    @property
    def project_id(self) -> str:
        """The project ID this manager operates on."""
        return self._project_id

    def store(
        self,
        memory_type: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryItem:
        """
        Persist a memory item to DynamoDB.

        Args:
            memory_type: One of: decision, outcome, error_pattern, adr, learning.
            content: The memory content text.
            metadata: Optional metadata (tags, source, context).

        Returns:
            The stored MemoryItem.

        Raises:
            ValueError: If memory_type is not valid.
        """
        if memory_type not in VALID_MEMORY_TYPES:
            raise ValueError(
                f"Invalid memory_type '{memory_type}'. Must be one of: {sorted(VALID_MEMORY_TYPES)}"
            )

        memory_id = str(uuid.uuid4())
        item = MemoryItem(
            memory_id=memory_id,
            memory_type=memory_type,
            content=content,
            metadata=metadata or {},
        )

        table = self._dynamodb.Table(self._memory_table)
        try:
            table.put_item(
                Item={
                    "project_id": self._project_id,
                    "memory_key": f"memory#{memory_type}#{memory_id}",
                    "memory_id": memory_id,
                    "memory_type": memory_type,
                    "content": content,
                    "content_hash": item.content_hash,
                    "data": json.dumps(item.to_dict()),
                    "created_at": item.created_at,
                    "updated_at": item.updated_at,
                }
            )
            logger.info(
                "Stored memory: project=%s type=%s id=%s",
                self._project_id, memory_type, memory_id,
            )
        except ClientError as e:
            logger.error("Failed to store memory: %s", e)
            raise

        return item

    def recall(
        self,
        query: str,
        memory_type: str | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        """
        Retrieve relevant memories using keyword matching on DynamoDB.

        Args:
            query: Search query string (keywords matched against content).
            memory_type: Optional filter by memory type.
            limit: Maximum number of results to return.

        Returns:
            List of matching MemoryItem objects, ranked by relevance.
        """
        table = self._dynamodb.Table(self._memory_table)
        prefix = f"memory#{memory_type}#" if memory_type else "memory#"

        try:
            response = table.query(
                KeyConditionExpression="project_id = :pid AND begins_with(memory_key, :prefix)",
                ExpressionAttributeValues={
                    ":pid": self._project_id,
                    ":prefix": prefix,
                },
                ScanIndexForward=False,
            )
        except ClientError as e:
            logger.warning("Failed to recall memories: %s", e)
            return []

        items = response.get("Items", [])

        # Handle pagination for large result sets
        while "LastEvaluatedKey" in response:
            try:
                response = table.query(
                    KeyConditionExpression="project_id = :pid AND begins_with(memory_key, :prefix)",
                    ExpressionAttributeValues={
                        ":pid": self._project_id,
                        ":prefix": prefix,
                    },
                    ScanIndexForward=False,
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))
            except ClientError:
                break

        # Keyword-based relevance scoring
        query_keywords = set(query.lower().split())
        scored: list[tuple[float, MemoryItem]] = []

        for item in items:
            data = json.loads(item.get("data", "{}"))
            if not data:
                continue
            memory = MemoryItem.from_dict(data)
            content_lower = memory.content.lower()

            # Score by keyword overlap
            content_words = set(content_lower.split())
            overlap = query_keywords & content_words
            if not overlap:
                continue

            score = len(overlap) / len(query_keywords) if query_keywords else 0.0
            scored.append((score, memory))

        # Sort by relevance score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # Update access metadata for returned items
        results = [memory for _, memory in scored[:limit]]
        self._update_access_metadata(results)

        return results

    def consolidate(self) -> dict[str, Any]:
        """
        Merge redundant memories by finding duplicates via content similarity.

        Intended to run as a weekly maintenance job. Finds pairs of memories
        with high content similarity and merges them into a single item.

        Returns:
            Summary of consolidation: items_scanned, duplicates_found, items_merged.
        """
        table = self._dynamodb.Table(self._memory_table)
        summary = {"items_scanned": 0, "duplicates_found": 0, "items_merged": 0}

        try:
            response = table.query(
                KeyConditionExpression="project_id = :pid AND begins_with(memory_key, :prefix)",
                ExpressionAttributeValues={
                    ":pid": self._project_id,
                    ":prefix": "memory#",
                },
                Limit=_CONSOLIDATION_BATCH_SIZE,
            )
        except ClientError as e:
            logger.warning("Failed to query for consolidation: %s", e)
            return summary

        items = response.get("Items", [])
        memories: list[MemoryItem] = []
        for item in items:
            data = json.loads(item.get("data", "{}"))
            if data:
                memories.append(MemoryItem.from_dict(data))

        summary["items_scanned"] = len(memories)

        # Find duplicates by content similarity
        merged_ids: set[str] = set()
        for i, mem_a in enumerate(memories):
            if mem_a.memory_id in merged_ids:
                continue
            for mem_b in memories[i + 1:]:
                if mem_b.memory_id in merged_ids:
                    continue
                if mem_a.memory_type != mem_b.memory_type:
                    continue

                similarity = SequenceMatcher(
                    None, mem_a.content, mem_b.content
                ).ratio()

                if similarity >= _CONSOLIDATION_SIMILARITY_THRESHOLD:
                    summary["duplicates_found"] += 1
                    # Keep the older one, merge metadata
                    self._merge_memories(mem_a, mem_b)
                    merged_ids.add(mem_b.memory_id)
                    summary["items_merged"] += 1

        # Delete merged items
        for memory_id in merged_ids:
            self._delete_by_id(memory_id)

        logger.info(
            "Consolidation complete: scanned=%d duplicates=%d merged=%d",
            summary["items_scanned"], summary["duplicates_found"], summary["items_merged"],
        )
        return summary

    def forget(self, memory_id: str) -> bool:
        """
        Remove a specific memory by its ID.

        Args:
            memory_id: The unique identifier of the memory to remove.

        Returns:
            True if the memory was successfully removed, False otherwise.
        """
        return self._delete_by_id(memory_id)

    def get(self, memory_id: str) -> MemoryItem | None:
        """
        Retrieve a specific memory by ID.

        Args:
            memory_id: The unique identifier of the memory.

        Returns:
            MemoryItem or None if not found.
        """
        table = self._dynamodb.Table(self._memory_table)
        try:
            response = table.query(
                KeyConditionExpression="project_id = :pid AND begins_with(memory_key, :prefix)",
                FilterExpression="memory_id = :mid",
                ExpressionAttributeValues={
                    ":pid": self._project_id,
                    ":prefix": "memory#",
                    ":mid": memory_id,
                },
            )
            items = response.get("Items", [])
            if not items:
                return None
            data = json.loads(items[0].get("data", "{}"))
            return MemoryItem.from_dict(data) if data else None
        except ClientError as e:
            logger.warning("Failed to get memory %s: %s", memory_id, e)
            return None

    def exists_by_hash(self, content_hash: str) -> bool:
        """
        Check if a memory with the given content hash already exists.

        Args:
            content_hash: SHA-256 prefix hash of the content.

        Returns:
            True if a memory with this hash exists.
        """
        table = self._dynamodb.Table(self._memory_table)
        try:
            response = table.query(
                KeyConditionExpression="project_id = :pid AND begins_with(memory_key, :prefix)",
                FilterExpression="content_hash = :hash",
                ExpressionAttributeValues={
                    ":pid": self._project_id,
                    ":prefix": "memory#",
                    ":hash": content_hash,
                },
                Limit=1,
            )
            return len(response.get("Items", [])) > 0
        except ClientError as e:
            logger.warning("Failed to check hash existence: %s", e)
            return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _update_access_metadata(self, memories: list[MemoryItem]) -> None:
        """Update access count and last_accessed for recalled memories."""
        now = datetime.now(timezone.utc).isoformat()
        table = self._dynamodb.Table(self._memory_table)

        for memory in memories:
            memory.access_count += 1
            memory.last_accessed = now
            try:
                table.update_item(
                    Key={
                        "project_id": self._project_id,
                        "memory_key": f"memory#{memory.memory_type}#{memory.memory_id}",
                    },
                    UpdateExpression="SET #data = :data, updated_at = :now",
                    ExpressionAttributeNames={"#data": "data"},
                    ExpressionAttributeValues={
                        ":data": json.dumps(memory.to_dict()),
                        ":now": now,
                    },
                )
            except ClientError:
                pass  # Non-critical: access tracking is best-effort

    def _merge_memories(self, primary: MemoryItem, duplicate: MemoryItem) -> None:
        """Merge duplicate into primary memory item."""
        now = datetime.now(timezone.utc).isoformat()

        # Combine metadata
        for key, value in duplicate.metadata.items():
            if key not in primary.metadata:
                primary.metadata[key] = value

        # Track consolidation lineage
        primary.consolidated_from.append(duplicate.memory_id)
        primary.access_count += duplicate.access_count
        primary.updated_at = now

        # Persist updated primary
        table = self._dynamodb.Table(self._memory_table)
        try:
            table.put_item(
                Item={
                    "project_id": self._project_id,
                    "memory_key": f"memory#{primary.memory_type}#{primary.memory_id}",
                    "memory_id": primary.memory_id,
                    "memory_type": primary.memory_type,
                    "content": primary.content,
                    "content_hash": primary.content_hash,
                    "data": json.dumps(primary.to_dict()),
                    "created_at": primary.created_at,
                    "updated_at": now,
                }
            )
        except ClientError as e:
            logger.warning("Failed to update merged memory: %s", e)

    def _delete_by_id(self, memory_id: str) -> bool:
        """Delete a memory item by scanning for its memory_key."""
        table = self._dynamodb.Table(self._memory_table)
        try:
            # Find the item first to get its full key
            response = table.query(
                KeyConditionExpression="project_id = :pid AND begins_with(memory_key, :prefix)",
                FilterExpression="memory_id = :mid",
                ExpressionAttributeValues={
                    ":pid": self._project_id,
                    ":prefix": "memory#",
                    ":mid": memory_id,
                },
            )
            items = response.get("Items", [])
            if not items:
                logger.warning("Memory not found for deletion: %s", memory_id)
                return False

            # Delete the item
            memory_key = items[0]["memory_key"]
            table.delete_item(
                Key={
                    "project_id": self._project_id,
                    "memory_key": memory_key,
                }
            )
            logger.info("Forgot memory: project=%s id=%s", self._project_id, memory_id)
            return True
        except ClientError as e:
            logger.warning("Failed to delete memory %s: %s", memory_id, e)
            return False
