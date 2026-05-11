"""
Conductor Metrics — CloudWatch Metrics Emission for Conductor Orchestration.

Emits structured metrics for observability of the Conductor pattern:
  - Plan generation events (topology, steps, tokens)
  - Recursive refinement triggers
  - Fallback usage (Conductor reasoning failures)
  - Confidence assessments

Metrics are emitted to CloudWatch under the namespace "FDE/Conductor"
and also persisted to DynamoDB metrics table for portal consumption.

Ref: ADR-020 (Conductor Orchestration Pattern)
Ref: docs/design/conductor-orchestration-pattern.md Section 5
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

CW_NAMESPACE = "FDE/Conductor"


@dataclass
class ConductorMetricEvent:
    """A single Conductor metric event."""

    metric_name: str
    value: float
    unit: str
    dimensions: dict[str, str]
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class ConductorMetrics:
    """
    Emits Conductor orchestration metrics to CloudWatch and DynamoDB.

    Usage:
        metrics = ConductorMetrics(project_id="my-service")
        metrics.record_plan_generated(
            task_id="task-123",
            topology="debate",
            steps=5,
            tokens_used=4200,
            organism_level="O4",
        )
    """

    def __init__(
        self,
        project_id: str | None = None,
        metrics_table: str | None = None,
        aws_region: str | None = None,
        emit_cloudwatch: bool = True,
    ):
        self._project_id = project_id or os.environ.get("PROJECT_ID", "global")
        self._metrics_table = metrics_table or os.environ.get("METRICS_TABLE", "")
        self._region = aws_region or os.environ.get("AWS_REGION", "us-east-1")
        self._emit_cw = emit_cloudwatch

        self._cloudwatch = boto3.client("cloudwatch", region_name=self._region)
        self._dynamodb = boto3.resource("dynamodb", region_name=self._region)

    def record_plan_generated(
        self,
        task_id: str,
        topology: str,
        steps: int,
        tokens_used: int,
        organism_level: str,
        agent_roles: list[str] | None = None,
    ) -> None:
        """Record a successful plan generation event."""
        dimensions = {
            "ProjectId": self._project_id,
            "OrganismLevel": organism_level,
            "Topology": topology,
        }

        events = [
            ConductorMetricEvent(
                metric_name="PlanGenerated",
                value=1.0,
                unit="Count",
                dimensions=dimensions,
            ),
            ConductorMetricEvent(
                metric_name="StepsPerPlan",
                value=float(steps),
                unit="Count",
                dimensions=dimensions,
            ),
            ConductorMetricEvent(
                metric_name="TokensUsed",
                value=float(tokens_used),
                unit="Count",
                dimensions=dimensions,
            ),
        ]

        self._emit_events(events)
        self._persist_to_dynamodb(
            task_id=task_id,
            metric_type="plan_generated",
            data={
                "topology": topology,
                "steps": steps,
                "tokens_used": tokens_used,
                "organism_level": organism_level,
                "agent_roles": agent_roles or [],
            },
        )

        logger.info(
            "Conductor metric: plan_generated task=%s topology=%s steps=%d tokens=%d",
            task_id, topology, steps, tokens_used,
        )

    def record_recursive_triggered(
        self,
        task_id: str,
        depth: int,
        confidence: float,
        reason: str = "",
    ) -> None:
        """Record a recursive refinement trigger."""
        dimensions = {
            "ProjectId": self._project_id,
            "RecursiveDepth": str(depth),
        }

        events = [
            ConductorMetricEvent(
                metric_name="RecursiveTriggered",
                value=1.0,
                unit="Count",
                dimensions=dimensions,
            ),
            ConductorMetricEvent(
                metric_name="ConfidenceAtRecursion",
                value=confidence,
                unit="None",
                dimensions=dimensions,
            ),
        ]

        self._emit_events(events)
        self._persist_to_dynamodb(
            task_id=task_id,
            metric_type="recursive_triggered",
            data={"depth": depth, "confidence": confidence, "reason": reason},
        )

        logger.info(
            "Conductor metric: recursive_triggered task=%s depth=%d confidence=%.2f",
            task_id, depth, confidence,
        )

    def record_fallback_used(
        self,
        task_id: str,
        reason: str,
        organism_level: str,
    ) -> None:
        """Record when the Conductor falls back to a static plan."""
        dimensions = {
            "ProjectId": self._project_id,
            "OrganismLevel": organism_level,
        }

        events = [
            ConductorMetricEvent(
                metric_name="FallbackUsed",
                value=1.0,
                unit="Count",
                dimensions=dimensions,
            ),
        ]

        self._emit_events(events)
        self._persist_to_dynamodb(
            task_id=task_id,
            metric_type="fallback_used",
            data={"reason": reason, "organism_level": organism_level},
        )

        logger.warning("Conductor metric: fallback_used task=%s reason=%s", task_id, reason)

    def record_plan_latency(
        self,
        task_id: str,
        latency_ms: float,
        organism_level: str,
    ) -> None:
        """Record plan generation latency."""
        dimensions = {
            "ProjectId": self._project_id,
            "OrganismLevel": organism_level,
        }

        events = [
            ConductorMetricEvent(
                metric_name="PlanLatencyMs",
                value=latency_ms,
                unit="Milliseconds",
                dimensions=dimensions,
            ),
        ]

        self._emit_events(events)

    # --- Private Methods ---

    def _emit_events(self, events: list[ConductorMetricEvent]) -> None:
        """Emit metric events to CloudWatch."""
        if not self._emit_cw:
            return

        metric_data = []
        for event in events:
            datum: dict[str, Any] = {
                "MetricName": event.metric_name,
                "Value": event.value,
                "Dimensions": [
                    {"Name": k, "Value": v}
                    for k, v in event.dimensions.items()
                ],
            }
            if event.unit != "None":
                datum["Unit"] = event.unit
            metric_data.append(datum)

        try:
            self._cloudwatch.put_metric_data(
                Namespace=CW_NAMESPACE,
                MetricData=metric_data,
            )
        except ClientError as e:
            logger.warning("Failed to emit CloudWatch metrics: %s", str(e))

    def _persist_to_dynamodb(
        self,
        task_id: str,
        metric_type: str,
        data: dict[str, Any],
    ) -> None:
        """Persist metric to DynamoDB for portal consumption."""
        if not self._metrics_table:
            return

        table = self._dynamodb.Table(self._metrics_table)
        now = datetime.now(timezone.utc).isoformat()

        try:
            table.put_item(
                Item={
                    "project_id": self._project_id,
                    "metric_key": f"conductor#{metric_type}#{now}",
                    "metric_type": f"conductor_{metric_type}",
                    "task_id": task_id,
                    "recorded_at": now,
                    "data": json.dumps(data),
                }
            )
        except ClientError as e:
            logger.warning("Failed to persist conductor metric: %s", str(e))
