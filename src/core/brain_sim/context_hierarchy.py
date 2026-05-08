"""
Context Hierarchy — Cross-Session Learned Context Manager.

Persists project context across task executions in a 5-level hierarchy:
  L1: Immutable facts (language, framework, architecture style)
  L2: Stable conventions (test framework, naming, CI tool)
  L3: Decisions (ADR-backed choices, with confidence decay)
  L4: Preferences (team style, with confidence decay)
  L5: Historical (past incidents, patterns, with confidence decay)

The orchestrator queries L1-L2 at dispatch time and injects them into
the SCD. L3-L5 are available on-demand via the query API.

Confidence decay: L3-L5 items lose confidence over time unless
revalidated. This prevents stale context from misleading agents.

DynamoDB table: fde-dev-context-hierarchy
  PK: project_id (S)
  SK: level_item_key (S) — e.g., "L1#language", "L3#auth_pattern_decision"

Ref: docs/design/fde-core-brain-development.md Section 3.2
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_DECAY_HALF_LIFE_DAYS = {3: 90, 4: 60, 5: 45}
_STALE_CONFIDENCE_THRESHOLD = 0.3


class ContextLevel(IntEnum):
    """Hierarchy levels for project context."""

    L1_IMMUTABLE = 1
    L2_CONVENTIONS = 2
    L3_DECISIONS = 3
    L4_PREFERENCES = 4
    L5_HISTORICAL = 5


@dataclass
class ContextItem:
    """A single item in the context hierarchy."""

    project_id: str
    level: ContextLevel
    key: str
    value: Any
    confidence: float = 1.0
    source: str = ""
    created_at: str = ""
    last_validated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.last_validated_at:
            self.last_validated_at = now

    @property
    def level_item_key(self) -> str:
        return f"L{self.level}#{self.key}"

    @property
    def is_stale(self) -> bool:
        return self.confidence < _STALE_CONFIDENCE_THRESHOLD

    def compute_current_confidence(self) -> float:
        """Compute current confidence with time-based decay."""
        if self.level <= 2:
            return 1.0
        half_life = _DECAY_HALF_LIFE_DAYS.get(int(self.level), 90)
        try:
            last_validated = datetime.fromisoformat(self.last_validated_at)
            days_since = (datetime.now(timezone.utc) - last_validated).days
            decay_factor = math.pow(0.5, days_since / half_life)
            return round(max(0.0, self.confidence * decay_factor), 4)
        except (ValueError, TypeError):
            return self.confidence


class ContextHierarchy:
    """
    Manages the cross-session context hierarchy for a project.

    Usage:
        ctx = ContextHierarchy(project_id="my-repo")
        ctx.store(ContextLevel.L1_IMMUTABLE, "language", "python", source="onboarding")
        l1_l2 = ctx.get_dispatch_context()
    """

    def __init__(self, project_id: str = "", table_name: str | None = None):
        self._project_id = project_id or os.environ.get("PROJECT_ID", "global")
        self._table_name = table_name or os.environ.get("CONTEXT_HIERARCHY_TABLE", "")
        self._dynamodb = boto3.resource("dynamodb")

    def store(self, level: ContextLevel, key: str, value: Any, source: str = "", confidence: float = 1.0, metadata: dict[str, Any] | None = None) -> ContextItem:
        """Store or update a context item."""
        item = ContextItem(project_id=self._project_id, level=level, key=key, value=value, confidence=confidence, source=source, metadata=metadata or {})
        self._persist_item(item)
        logger.debug("Context stored: L%d#%s = %s (source: %s)", level, key, str(value)[:50], source)
        return item

    def get_dispatch_context(self) -> list[ContextItem]:
        """Get L1 + L2 context items for orchestrator dispatch injection."""
        items = []
        for level in (ContextLevel.L1_IMMUTABLE, ContextLevel.L2_CONVENTIONS):
            items.extend(self.get_level(level))
        return items

    def get_level(self, level: ContextLevel, include_stale: bool = False) -> list[ContextItem]:
        """Get all items at a specific hierarchy level."""
        raw_items = self._query_level(level)
        items = []
        for raw in raw_items:
            item = self._deserialize_item(raw)
            if item:
                item.confidence = item.compute_current_confidence()
                if include_stale or not item.is_stale:
                    items.append(item)
        return items

    def get_item(self, level: ContextLevel, key: str) -> ContextItem | None:
        """Get a specific context item by level and key."""
        if not self._table_name:
            return None
        table = self._dynamodb.Table(self._table_name)
        try:
            response = table.get_item(Key={"project_id": self._project_id, "level_item_key": f"L{level}#{key}"})
            if "Item" in response:
                item = self._deserialize_item(response["Item"])
                if item:
                    item.confidence = item.compute_current_confidence()
                return item
            return None
        except ClientError as e:
            logger.warning("Failed to get context item L%d#%s: %s", level, key, str(e))
            return None

    def revalidate(self, key: str, level: ContextLevel) -> bool:
        """Revalidate a context item (resets confidence decay timer)."""
        if not self._table_name:
            return False
        table = self._dynamodb.Table(self._table_name)
        now = datetime.now(timezone.utc).isoformat()
        try:
            table.update_item(
                Key={"project_id": self._project_id, "level_item_key": f"L{level}#{key}"},
                UpdateExpression="SET last_validated_at = :now, confidence = :conf",
                ExpressionAttributeValues={":now": now, ":conf": "1.0"},
            )
            return True
        except ClientError as e:
            logger.warning("Failed to revalidate L%d#%s: %s", level, key, str(e))
            return False

    def remove(self, key: str, level: ContextLevel) -> bool:
        """Remove a context item."""
        if not self._table_name:
            return False
        table = self._dynamodb.Table(self._table_name)
        try:
            table.delete_item(Key={"project_id": self._project_id, "level_item_key": f"L{level}#{key}"})
            return True
        except ClientError as e:
            logger.warning("Failed to remove L%d#%s: %s", level, key, str(e))
            return False

    def get_stale_items(self) -> list[ContextItem]:
        """Get all items that have decayed below confidence threshold."""
        stale = []
        for level in (ContextLevel.L3_DECISIONS, ContextLevel.L4_PREFERENCES, ContextLevel.L5_HISTORICAL):
            items = self.get_level(level, include_stale=True)
            stale.extend(item for item in items if item.is_stale)
        return stale

    def _persist_item(self, item: ContextItem) -> None:
        if not self._table_name:
            return
        table = self._dynamodb.Table(self._table_name)
        try:
            table.put_item(Item={
                "project_id": item.project_id, "level_item_key": item.level_item_key,
                "level": f"L{item.level}", "key": item.key,
                "value": json.dumps(item.value), "confidence": str(item.confidence),
                "source": item.source, "created_at": item.created_at,
                "last_validated_at": item.last_validated_at, "metadata": json.dumps(item.metadata),
            })
        except ClientError as e:
            logger.error("Failed to persist context item: %s", str(e))

    def _query_level(self, level: ContextLevel) -> list[dict[str, Any]]:
        if not self._table_name:
            return []
        table = self._dynamodb.Table(self._table_name)
        try:
            response = table.query(
                KeyConditionExpression="project_id = :pid AND begins_with(level_item_key, :prefix)",
                ExpressionAttributeValues={":pid": self._project_id, ":prefix": f"L{level}#"},
            )
            return response.get("Items", [])
        except ClientError as e:
            logger.warning("Failed to query context level L%d: %s", level, str(e))
            return []

    def _deserialize_item(self, raw: dict[str, Any]) -> ContextItem | None:
        try:
            level_num = int(raw.get("level", "L1").replace("L", ""))
            value_raw = raw.get("value", '""')
            try:
                value = json.loads(value_raw)
            except (json.JSONDecodeError, TypeError):
                value = value_raw
            metadata_raw = raw.get("metadata", "{}")
            try:
                metadata = json.loads(metadata_raw)
            except (json.JSONDecodeError, TypeError):
                metadata = {}
            return ContextItem(
                project_id=raw.get("project_id", self._project_id),
                level=ContextLevel(level_num), key=raw.get("key", ""),
                value=value, confidence=float(raw.get("confidence", 1.0)),
                source=raw.get("source", ""), created_at=raw.get("created_at", ""),
                last_validated_at=raw.get("last_validated_at", ""), metadata=metadata,
            )
        except (ValueError, TypeError) as e:
            logger.warning("Failed to deserialize context item: %s", str(e))
            return None
