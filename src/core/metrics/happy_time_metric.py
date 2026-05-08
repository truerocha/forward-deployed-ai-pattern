"""
Happy Time Metric — Creative Work vs Toil Ratio.

Tracks the ratio of creative-work-time vs toil-time for developers
interacting with the factory. This is a developer experience metric
that correlates with satisfaction and retention.

Creative time (high-value work):
  - Implementation (writing new code)
  - Architecture (design decisions)
  - Code review (reviewing PRs, providing feedback)

Toil time (low-value work):
  - Time in gates (waiting for gate evaluation)
  - Waiting (blocked on dependencies, approvals)
  - Rework (fixing gate rejections, addressing review comments)
  - Fixing CI (pipeline failures, flaky tests)

Data sources:
  - VSM tracker timestamps (stage transitions)
  - Gate timestamps (gate entry/exit times)

Target: >60% creative time / total time
Alert: Happy Time drops below 40% for 7-day rolling window

DynamoDB SK pattern: happy_time#{task_id}#{date}

Ref: docs/design/fde-core-brain-development.md Section 7.5
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Thresholds
HAPPY_TIME_TARGET = 0.60  # Target: >60% creative time
HAPPY_TIME_ALERT_THRESHOLD = 0.40  # Alert if below 40%
ALERT_WINDOW_DAYS = 7


class TimeCategory(Enum):
    """Categories of time spent during task execution."""

    # Creative (high-value)
    IMPLEMENTATION = "implementation"
    ARCHITECTURE = "architecture"
    CODE_REVIEW = "code_review"

    # Toil (low-value)
    GATES = "gates"
    WAITING = "waiting"
    REWORK = "rework"
    FIXING_CI = "fixing_ci"


# Classification of categories
_CREATIVE_CATEGORIES = {
    TimeCategory.IMPLEMENTATION,
    TimeCategory.ARCHITECTURE,
    TimeCategory.CODE_REVIEW,
}

_TOIL_CATEGORIES = {
    TimeCategory.GATES,
    TimeCategory.WAITING,
    TimeCategory.REWORK,
    TimeCategory.FIXING_CI,
}


@dataclass
class TimeEntry:
    """A single time entry for a task."""

    task_id: str
    category: TimeCategory
    duration_seconds: float
    timestamp: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    @property
    def is_creative(self) -> bool:
        """Whether this entry counts as creative time."""
        return self.category in _CREATIVE_CATEGORIES

    @property
    def is_toil(self) -> bool:
        """Whether this entry counts as toil time."""
        return self.category in _TOIL_CATEGORIES


@dataclass
class HappyTimeSnapshot:
    """Happy Time metric snapshot for a time window."""

    project_id: str
    window_days: int
    creative_time_seconds: float = 0.0
    toil_time_seconds: float = 0.0
    total_time_seconds: float = 0.0
    happy_time_ratio: float = 0.0
    meets_target: bool = False
    is_alert: bool = False
    category_breakdown: dict[str, float] = field(default_factory=dict)
    task_count: int = 0
    computed_at: str = ""

    def __post_init__(self) -> None:
        if not self.computed_at:
            self.computed_at = datetime.now(timezone.utc).isoformat()
        self.total_time_seconds = self.creative_time_seconds + self.toil_time_seconds
        if self.total_time_seconds > 0:
            self.happy_time_ratio = self.creative_time_seconds / self.total_time_seconds
        self.meets_target = self.happy_time_ratio >= HAPPY_TIME_TARGET
        self.is_alert = self.happy_time_ratio < HAPPY_TIME_ALERT_THRESHOLD

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "project_id": self.project_id,
            "window_days": self.window_days,
            "creative_time_seconds": round(self.creative_time_seconds, 1),
            "toil_time_seconds": round(self.toil_time_seconds, 1),
            "total_time_seconds": round(self.total_time_seconds, 1),
            "happy_time_ratio": round(self.happy_time_ratio, 4),
            "happy_time_percent": round(self.happy_time_ratio * 100, 1),
            "meets_target": self.meets_target,
            "is_alert": self.is_alert,
            "category_breakdown": self.category_breakdown,
            "task_count": self.task_count,
            "computed_at": self.computed_at,
        }


class HappyTimeMetric:
    """
    Tracks and computes the Happy Time ratio (creative vs toil).

    The Happy Time metric measures developer experience by tracking
    how much time is spent on high-value creative work vs low-value toil.

    Usage:
        ht = HappyTimeMetric(project_id="my-repo", metrics_table="metrics")
        ht.record_time("task-123", TimeCategory.IMPLEMENTATION, duration_seconds=3600)
        ht.record_time("task-123", TimeCategory.GATES, duration_seconds=600)
        snapshot = ht.get_snapshot(window_days=7)
        # snapshot.happy_time_ratio -> 0.857
    """

    def __init__(
        self,
        project_id: str,
        metrics_table: str | None = None,
    ):
        self._project_id = project_id
        self._metrics_table = metrics_table or os.environ.get("METRICS_TABLE", "")
        self._dynamodb = boto3.resource("dynamodb")

    def record_time(
        self,
        task_id: str,
        category: TimeCategory,
        duration_seconds: float,
        metadata: dict[str, Any] | None = None,
    ) -> TimeEntry:
        """
        Record a time entry for a task.

        Args:
            task_id: The task this time is associated with.
            category: The time category (creative or toil).
            duration_seconds: Duration in seconds.
            metadata: Optional additional context.

        Returns:
            The created TimeEntry.
        """
        entry = TimeEntry(
            task_id=task_id,
            category=category,
            duration_seconds=duration_seconds,
            metadata=metadata or {},
        )

        self._persist_entry(entry)
        logger.debug(
            "Recorded %s time: task=%s category=%s duration=%.0fs",
            "creative" if entry.is_creative else "toil",
            task_id,
            category.value,
            duration_seconds,
        )
        return entry

    def record_from_vsm_stages(
        self, task_id: str, stage_durations: dict[str, float]
    ) -> list[TimeEntry]:
        """
        Record time entries derived from VSM stage durations.

        Maps VSM stages to Happy Time categories:
          - implementation -> IMPLEMENTATION
          - review -> CODE_REVIEW
          - spec -> ARCHITECTURE
          - intake, pr_created, merge, deploy -> WAITING

        Args:
            task_id: The task these durations belong to.
            stage_durations: Dict of "from_to" stage keys to seconds.

        Returns:
            List of created TimeEntries.
        """
        stage_to_category: dict[str, TimeCategory] = {
            "spec_to_intake": TimeCategory.ARCHITECTURE,
            "intake_to_implementation": TimeCategory.WAITING,
            "implementation_to_review": TimeCategory.IMPLEMENTATION,
            "review_to_pr_created": TimeCategory.CODE_REVIEW,
            "pr_created_to_merge": TimeCategory.WAITING,
            "merge_to_deploy": TimeCategory.WAITING,
            "idea_to_spec": TimeCategory.ARCHITECTURE,
        }

        entries: list[TimeEntry] = []
        for stage_key, duration in stage_durations.items():
            category = stage_to_category.get(stage_key, TimeCategory.WAITING)
            entry = self.record_time(task_id, category, duration)
            entries.append(entry)

        return entries

    def record_gate_time(
        self, task_id: str, gate_name: str, duration_seconds: float
    ) -> TimeEntry:
        """
        Record time spent in a gate (classified as toil).

        Args:
            task_id: The task that went through the gate.
            gate_name: Name of the gate.
            duration_seconds: Time spent in the gate.

        Returns:
            The created TimeEntry.
        """
        return self.record_time(
            task_id,
            TimeCategory.GATES,
            duration_seconds,
            metadata={"gate_name": gate_name},
        )

    def record_rework_time(
        self, task_id: str, reason: str, duration_seconds: float
    ) -> TimeEntry:
        """
        Record rework time (classified as toil).

        Args:
            task_id: The task requiring rework.
            reason: Why rework was needed.
            duration_seconds: Time spent on rework.

        Returns:
            The created TimeEntry.
        """
        return self.record_time(
            task_id,
            TimeCategory.REWORK,
            duration_seconds,
            metadata={"reason": reason},
        )

    def get_snapshot(self, window_days: int = 7) -> HappyTimeSnapshot:
        """
        Compute Happy Time snapshot for a rolling window.

        Aggregates all time entries within the window and computes
        the creative vs toil ratio.

        Args:
            window_days: Number of days to look back.

        Returns:
            HappyTimeSnapshot with ratio and alert status.
        """
        entries = self._load_entries(window_days)

        creative_time = 0.0
        toil_time = 0.0
        category_totals: dict[str, float] = {}
        task_ids: set[str] = set()

        for entry_data in entries:
            category_str = entry_data.get("category", "")
            duration = entry_data.get("duration_seconds", 0.0)
            task_id = entry_data.get("task_id", "")

            try:
                category = TimeCategory(category_str)
            except ValueError:
                continue

            task_ids.add(task_id)
            category_totals[category_str] = category_totals.get(category_str, 0.0) + duration

            if category in _CREATIVE_CATEGORIES:
                creative_time += duration
            elif category in _TOIL_CATEGORIES:
                toil_time += duration

        snapshot = HappyTimeSnapshot(
            project_id=self._project_id,
            window_days=window_days,
            creative_time_seconds=creative_time,
            toil_time_seconds=toil_time,
            category_breakdown=category_totals,
            task_count=len(task_ids),
        )

        if snapshot.is_alert:
            logger.warning(
                "HAPPY TIME ALERT: project=%s ratio=%.1f%% (threshold=%.0f%%) "
                "over %d-day window. Developer toil is too high.",
                self._project_id,
                snapshot.happy_time_ratio * 100,
                HAPPY_TIME_ALERT_THRESHOLD * 100,
                window_days,
            )

        self._persist_snapshot(snapshot)
        return snapshot

    def get_task_breakdown(self, task_id: str) -> dict[str, Any]:
        """
        Get Happy Time breakdown for a single task.

        Args:
            task_id: The task to analyze.

        Returns:
            Dict with creative/toil breakdown for the task.
        """
        if not self._metrics_table:
            return {"task_id": task_id, "creative_seconds": 0, "toil_seconds": 0}

        table = self._dynamodb.Table(self._metrics_table)
        prefix = f"happy_time#{task_id}#"

        try:
            response = table.query(
                KeyConditionExpression=(
                    "project_id = :pid AND begins_with(metric_key, :prefix)"
                ),
                ExpressionAttributeValues={
                    ":pid": self._project_id,
                    ":prefix": prefix,
                },
            )

            creative = 0.0
            toil = 0.0
            for item in response.get("Items", []):
                data = json.loads(item.get("data", "{}"))
                category_str = data.get("category", "")
                duration = data.get("duration_seconds", 0.0)
                try:
                    category = TimeCategory(category_str)
                    if category in _CREATIVE_CATEGORIES:
                        creative += duration
                    elif category in _TOIL_CATEGORIES:
                        toil += duration
                except ValueError:
                    continue

            total = creative + toil
            return {
                "task_id": task_id,
                "creative_seconds": round(creative, 1),
                "toil_seconds": round(toil, 1),
                "total_seconds": round(total, 1),
                "happy_time_ratio": round(creative / total, 4) if total > 0 else 0.0,
            }

        except ClientError as e:
            logger.warning("Failed to get task breakdown for %s: %s", task_id, str(e))
            return {"task_id": task_id, "creative_seconds": 0, "toil_seconds": 0}

    def check_alert(self) -> bool:
        """
        Check if Happy Time is below alert threshold for the default window.

        Returns:
            True if an alert condition exists.
        """
        snapshot = self.get_snapshot(window_days=ALERT_WINDOW_DAYS)
        return snapshot.is_alert

    def _persist_entry(self, entry: TimeEntry) -> None:
        """Persist a time entry to DynamoDB."""
        if not self._metrics_table:
            return

        table = self._dynamodb.Table(self._metrics_table)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        try:
            table.put_item(
                Item={
                    "project_id": self._project_id,
                    "metric_key": f"happy_time#{entry.task_id}#{date_str}#{entry.category.value}",
                    "metric_type": "happy_time",
                    "task_id": entry.task_id,
                    "recorded_at": entry.timestamp,
                    "data": json.dumps(
                        {
                            "task_id": entry.task_id,
                            "category": entry.category.value,
                            "duration_seconds": entry.duration_seconds,
                            "is_creative": entry.is_creative,
                            "timestamp": entry.timestamp,
                            "metadata": entry.metadata,
                        }
                    ),
                }
            )
        except ClientError as e:
            logger.warning("Failed to persist happy time entry: %s", str(e))

    def _persist_snapshot(self, snapshot: HappyTimeSnapshot) -> None:
        """Persist a computed snapshot to DynamoDB."""
        if not self._metrics_table:
            return

        table = self._dynamodb.Table(self._metrics_table)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        try:
            table.put_item(
                Item={
                    "project_id": self._project_id,
                    "metric_key": f"happy_time_snapshot#{date_str}",
                    "metric_type": "happy_time_snapshot",
                    "recorded_at": snapshot.computed_at,
                    "data": json.dumps(snapshot.to_dict()),
                }
            )
        except ClientError as e:
            logger.warning("Failed to persist happy time snapshot: %s", str(e))

    def _load_entries(self, window_days: int) -> list[dict[str, Any]]:
        """Load time entries within a rolling window from DynamoDB."""
        if not self._metrics_table:
            return []

        table = self._dynamodb.Table(self._metrics_table)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()

        try:
            response = table.query(
                KeyConditionExpression=(
                    "project_id = :pid AND begins_with(metric_key, :prefix)"
                ),
                FilterExpression="recorded_at >= :cutoff",
                ExpressionAttributeValues={
                    ":pid": self._project_id,
                    ":prefix": "happy_time#",
                    ":cutoff": cutoff,
                },
            )

            results: list[dict[str, Any]] = []
            for item in response.get("Items", []):
                # Skip snapshot records
                if item.get("metric_type") == "happy_time_snapshot":
                    continue
                data = json.loads(item.get("data", "{}"))
                results.append(data)
            return results

        except ClientError as e:
            logger.warning("Failed to load happy time entries: %s", str(e))
            return []
