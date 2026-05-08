"""
Learning Curve Tracker — Instability Learning Curve Compression.

DORA O23 (P1): Instability has a LONGER learning curve than throughput
(took teams "another year"). Our governance layer compresses this by making
instability visible and preventable mechanically.

Metrics tracked:
  - days_to_stable: Days from first task to sustained CFR < 10%
  - stability_velocity: Rate of CFR improvement over time
  - benchmark_comparison: Factory-assisted vs industry average (DORA: "another year")

Target: Factory-assisted projects reach stability in <30 days.

DynamoDB SK pattern: learning#{project_id}#{metric}

Ref: docs/design/fde-core-brain-development.md Section 8.6
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_STABILITY_CFR_THRESHOLD = 10.0
_SUSTAINED_STABILITY_DAYS = 7
_INDUSTRY_BENCHMARK_DAYS = 365


@dataclass
class LearningCurveSnapshot:
    """Learning curve metrics for a project."""

    project_id: str
    first_task_date: str | None
    stability_reached_date: str | None
    days_to_stable: int | None
    current_cfr: float
    cfr_trend: list[float]
    stability_velocity: float
    is_stable: bool
    benchmark_comparison: float


class LearningCurveTracker:
    """
    Tracks how quickly projects reach stability with factory governance.

    Usage:
        tracker = LearningCurveTracker(project_id="my-repo")
        tracker.record_project_start()
        snapshot = tracker.get_snapshot()
    """

    def __init__(self, project_id: str = "", metrics_table: str | None = None):
        self._project_id = project_id or os.environ.get("PROJECT_ID", "global")
        self._metrics_table = metrics_table or os.environ.get("METRICS_TABLE", "")
        self._dynamodb = boto3.resource("dynamodb")

    def record_project_start(self) -> None:
        """Record when a project first starts using the factory."""
        self._record("project_start", {"started_at": datetime.now(timezone.utc).isoformat()})

    def record_stability_reached(self) -> None:
        """Record when a project first reaches sustained stability."""
        self._record("stability_reached", {"reached_at": datetime.now(timezone.utc).isoformat()})

    def get_snapshot(self) -> LearningCurveSnapshot:
        """Compute current learning curve metrics."""
        start_data = self._get_latest("project_start")
        first_task_date = start_data.get("started_at") if start_data else None

        stability_data = self._get_latest("stability_reached")
        stability_date = stability_data.get("reached_at") if stability_data else None

        days_to_stable = None
        if first_task_date and stability_date:
            try:
                start = datetime.fromisoformat(first_task_date)
                stable = datetime.fromisoformat(stability_date)
                days_to_stable = (stable - start).days
            except (ValueError, TypeError):
                pass

        cfr_trend = self._compute_cfr_trend(weeks=8)
        current_cfr = cfr_trend[-1] if cfr_trend else 0.0
        velocity = self._compute_velocity(cfr_trend)
        is_stable = current_cfr < _STABILITY_CFR_THRESHOLD

        if is_stable and not stability_date and first_task_date:
            self.record_stability_reached()
            stability_date = datetime.now(timezone.utc).isoformat()
            try:
                start = datetime.fromisoformat(first_task_date)
                days_to_stable = (datetime.now(timezone.utc) - start).days
            except (ValueError, TypeError):
                pass

        benchmark = (days_to_stable / _INDUSTRY_BENCHMARK_DAYS) if days_to_stable else None

        return LearningCurveSnapshot(
            project_id=self._project_id,
            first_task_date=first_task_date,
            stability_reached_date=stability_date,
            days_to_stable=days_to_stable,
            current_cfr=current_cfr,
            cfr_trend=cfr_trend,
            stability_velocity=velocity,
            is_stable=is_stable,
            benchmark_comparison=round(benchmark, 3) if benchmark else 0.0,
        )

    def _compute_cfr_trend(self, weeks: int = 8) -> list[float]:
        """Compute weekly CFR values for trend analysis."""
        if not self._metrics_table:
            return []
        table = self._dynamodb.Table(self._metrics_table)
        trend: list[float] = []

        for week_offset in range(weeks, 0, -1):
            week_start = datetime.now(timezone.utc) - timedelta(weeks=week_offset)
            week_end = week_start + timedelta(weeks=1)
            prefix = "dora#change_fail_rate#"
            try:
                response = table.query(
                    KeyConditionExpression="project_id = :pid AND begins_with(metric_key, :prefix)",
                    FilterExpression="recorded_at BETWEEN :start AND :end_val",
                    ExpressionAttributeValues={
                        ":pid": self._project_id, ":prefix": prefix,
                        ":start": week_start.isoformat(), ":end_val": week_end.isoformat(),
                    },
                )
                items = response.get("Items", [])
                if items:
                    failures = sum(
                        1 for item in items
                        if json.loads(item.get("data", "{}")).get("value", 0) == 1.0
                    )
                    trend.append(round((failures / len(items)) * 100, 1))
                else:
                    trend.append(0.0)
            except ClientError:
                trend.append(0.0)
        return trend

    def _compute_velocity(self, trend: list[float]) -> float:
        """Compute rate of CFR change (negative = improving)."""
        if len(trend) < 2:
            return 0.0
        n = len(trend)
        x_mean = (n - 1) / 2
        y_mean = sum(trend) / n
        numerator = sum((i - x_mean) * (trend[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        if denominator == 0:
            return 0.0
        return round(numerator / denominator, 3)

    def _record(self, event_type: str, data: dict[str, Any]) -> None:
        """Persist a learning curve event."""
        if not self._metrics_table:
            return
        table = self._dynamodb.Table(self._metrics_table)
        now = datetime.now(timezone.utc).isoformat()
        try:
            table.put_item(Item={
                "project_id": self._project_id,
                "metric_key": f"learning#{self._project_id}#{event_type}",
                "metric_type": "learning_curve", "task_id": "", "recorded_at": now,
                "data": json.dumps(data),
            })
        except ClientError as e:
            logger.warning("Failed to record learning curve event: %s", str(e))

    def _get_latest(self, event_type: str) -> dict[str, Any]:
        """Get the latest event of a given type."""
        if not self._metrics_table:
            return {}
        table = self._dynamodb.Table(self._metrics_table)
        try:
            response = table.get_item(Key={
                "project_id": self._project_id,
                "metric_key": f"learning#{self._project_id}#{event_type}",
            })
            if "Item" in response:
                return json.loads(response["Item"].get("data", "{}"))
            return {}
        except ClientError as e:
            logger.warning("Failed to get learning curve event: %s", str(e))
            return {}
