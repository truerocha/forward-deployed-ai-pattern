"""
Net Friction Calculator — Upstream vs Downstream Friction Measurement.

DORA O14 (P1): "Friction doesn't vanish, it moves." Our gates add upstream
friction but should reduce downstream friction (fewer incidents, less rework).
We must measure NET friction across the full value stream.

Formula:
  net_friction = downstream_friction_saved - upstream_friction_cost

Where:
  upstream_friction = gate_time + rejection_rework_time
  downstream_friction = incidents + hotfixes + rework (counterfactual estimate)

A positive net_friction means gates are costing more than they save.
A negative net_friction means gates are providing net value.

Alert: Fires when net_friction > 0 for 14-day window (gates net-negative).

Ref: docs/design/fde-core-brain-development.md Section 8.2
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

_HOURS_PER_PREVENTED_INCIDENT = 4.0
_HOURS_PER_PREVENTED_REWORK = 2.0


@dataclass
class FrictionSnapshot:
    """Net friction measurement for a time window."""

    project_id: str
    window_days: int
    upstream_friction_hours: float
    downstream_friction_saved_hours: float
    net_friction_hours: float
    gate_time_hours: float
    rejection_rework_hours: float
    incidents_prevented: int
    rework_cycles_prevented: int
    roi_percent: float
    is_net_negative: bool


class NetFrictionCalculator:
    """
    Computes net friction across the value stream.

    Usage:
        calc = NetFrictionCalculator(project_id="my-repo")
        snapshot = calc.compute(window_days=14)
    """

    def __init__(self, project_id: str = "", metrics_table: str | None = None):
        self._project_id = project_id or os.environ.get("PROJECT_ID", "global")
        self._metrics_table = metrics_table or os.environ.get("METRICS_TABLE", "")
        self._dynamodb = boto3.resource("dynamodb")
        self._cloudwatch = boto3.client("cloudwatch")

    def compute(self, window_days: int = 14) -> FrictionSnapshot:
        """Compute net friction for the given time window."""
        gate_time = self._compute_gate_time(window_days)
        rejection_rework = self._compute_rejection_rework(window_days)
        upstream = gate_time + rejection_rework

        incidents_prevented = self._estimate_incidents_prevented(window_days)
        rework_prevented = self._estimate_rework_prevented(window_days)
        downstream_saved = (
            incidents_prevented * _HOURS_PER_PREVENTED_INCIDENT
            + rework_prevented * _HOURS_PER_PREVENTED_REWORK
        )

        net = upstream - downstream_saved
        roi = ((downstream_saved - upstream) / max(upstream, 0.01)) * 100

        snapshot = FrictionSnapshot(
            project_id=self._project_id, window_days=window_days,
            upstream_friction_hours=round(upstream, 2),
            downstream_friction_saved_hours=round(downstream_saved, 2),
            net_friction_hours=round(net, 2), gate_time_hours=round(gate_time, 2),
            rejection_rework_hours=round(rejection_rework, 2),
            incidents_prevented=incidents_prevented,
            rework_cycles_prevented=rework_prevented,
            roi_percent=round(roi, 1), is_net_negative=net > 0,
        )
        self._persist_snapshot(snapshot)
        if snapshot.is_net_negative:
            self._emit_net_negative_alert(snapshot)
        return snapshot

    def _compute_gate_time(self, window_days: int) -> float:
        """Compute total hours spent in gate execution."""
        records = self._query_metrics("cost", window_days)
        total_seconds = 0.0
        for data in records:
            if data.get("gate_name"):
                tokens = data.get("total_tokens", 0)
                total_seconds += tokens / 333.0
        return total_seconds / 3600.0

    def _compute_rejection_rework(self, window_days: int) -> float:
        """Estimate hours spent on rework from gate rejections."""
        records = self._query_metrics("gate_feedback", window_days)
        rejections = sum(1 for r in records if r.get("status") == "rejected")
        return (rejections * 15) / 60.0

    def _estimate_incidents_prevented(self, window_days: int) -> int:
        """Estimate incidents prevented by adversarial gate."""
        records = self._query_metrics("gate_feedback", window_days)
        adversarial_rejections = sum(
            1 for r in records
            if r.get("gate_type") == "adversarial" and r.get("status") == "rejected"
        )
        return int(adversarial_rejections * 0.3)

    def _estimate_rework_prevented(self, window_days: int) -> int:
        """Estimate rework cycles prevented by DoR gate."""
        records = self._query_metrics("gate_feedback", window_days)
        return sum(
            1 for r in records
            if r.get("gate_type") == "dor" and r.get("status") == "rejected"
        )

    def _query_metrics(self, metric_type: str, window_days: int) -> list[dict[str, Any]]:
        """Query metrics by type within window."""
        if not self._metrics_table:
            return []
        table = self._dynamodb.Table(self._metrics_table)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
        try:
            response = table.query(
                IndexName="metric-type-index",
                KeyConditionExpression="metric_type = :mt AND recorded_at >= :cutoff",
                ExpressionAttributeValues={":mt": metric_type, ":cutoff": cutoff},
                Limit=500,
            )
            return [json.loads(item.get("data", "{}")) for item in response.get("Items", [])]
        except ClientError as e:
            logger.warning("Failed to query metrics for friction calc: %s", str(e))
            return []

    def _persist_snapshot(self, snapshot: FrictionSnapshot) -> None:
        """Persist friction snapshot to metrics table."""
        if not self._metrics_table:
            return
        table = self._dynamodb.Table(self._metrics_table)
        now = datetime.now(timezone.utc).isoformat()
        try:
            table.put_item(Item={
                "project_id": self._project_id,
                "metric_key": f"friction#{self._project_id}#{now}",
                "metric_type": "friction", "task_id": "", "recorded_at": now,
                "data": json.dumps({
                    "window_days": snapshot.window_days,
                    "upstream_hours": snapshot.upstream_friction_hours,
                    "downstream_saved_hours": snapshot.downstream_friction_saved_hours,
                    "net_friction_hours": snapshot.net_friction_hours,
                    "roi_percent": snapshot.roi_percent,
                    "is_net_negative": snapshot.is_net_negative,
                }),
            })
        except ClientError as e:
            logger.warning("Failed to persist friction snapshot: %s", str(e))

    def _emit_net_negative_alert(self, snapshot: FrictionSnapshot) -> None:
        """Emit CloudWatch alarm when gates are net-negative."""
        logger.warning("Net friction POSITIVE: %.2f hours over %d days", snapshot.net_friction_hours, snapshot.window_days)
        try:
            self._cloudwatch.put_metric_data(
                Namespace="FDE/Factory",
                MetricData=[{"MetricName": "NetFrictionPositive", "Value": snapshot.net_friction_hours, "Unit": "None",
                             "Dimensions": [{"Name": "ProjectId", "Value": self._project_id}]}],
            )
        except ClientError as e:
            logger.warning("Failed to emit friction alert: %s", str(e))
