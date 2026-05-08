"""
Trust Metrics — Measuring Trust in Factory Outputs.

DORA O17 (P1): 30% report little or no trust in AI-generated code.
We must measure trust in factory outputs to detect erosion early.

Metrics tracked:
  - PR acceptance rate: Factory PRs merged vs rejected (target: >90%)
  - Gate override rate: How often humans override gate decisions (target: <5%)
  - Manual intervention rate: How often humans intervene mid-execution
  - Trust score composite: Weighted average of above metrics

DynamoDB SK pattern: trust#{metric}#{date}

Ref: docs/design/fde-core-brain-development.md Section 8.4
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

_WEIGHT_PR_ACCEPTANCE = 0.5
_WEIGHT_GATE_OVERRIDE = 0.3
_WEIGHT_MANUAL_INTERVENTION = 0.2


@dataclass
class TrustSnapshot:
    """Current trust metrics snapshot."""

    project_id: str
    window_days: int
    pr_acceptance_rate_percent: float
    gate_override_rate_percent: float
    manual_intervention_rate_percent: float
    trust_score_composite: float
    total_prs: int
    total_gate_decisions: int
    total_executions: int


class TrustMetrics:
    """
    Tracks trust indicators for factory outputs.

    Usage:
        trust = TrustMetrics(project_id="my-repo")
        trust.record_pr_outcome(task_id="t-123", accepted=True)
        trust.record_gate_override(task_id="t-456", gate_name="adversarial")
        snapshot = trust.get_snapshot(window_days=30)
    """

    def __init__(self, project_id: str = "", metrics_table: str | None = None):
        self._project_id = project_id or os.environ.get("PROJECT_ID", "global")
        self._metrics_table = metrics_table or os.environ.get("METRICS_TABLE", "")
        self._dynamodb = boto3.resource("dynamodb")

    def record_pr_outcome(self, task_id: str, accepted: bool) -> None:
        """Record whether a factory-generated PR was accepted or rejected."""
        self._record("pr_outcome", task_id, {"accepted": accepted})

    def record_gate_override(self, task_id: str, gate_name: str, reason: str = "") -> None:
        """Record when a human overrides a gate decision."""
        self._record("gate_override", task_id, {"gate_name": gate_name, "reason": reason})

    def record_manual_intervention(self, task_id: str, intervention_type: str) -> None:
        """Record when a human intervenes during execution."""
        self._record("manual_intervention", task_id, {"type": intervention_type})

    def record_gate_decision(self, task_id: str, gate_name: str, passed: bool) -> None:
        """Record a gate decision (for total gate decisions denominator)."""
        self._record("gate_decision", task_id, {"gate_name": gate_name, "passed": passed})

    def get_snapshot(self, window_days: int = 30) -> TrustSnapshot:
        """Compute trust metrics snapshot."""
        pr_outcomes = self._query("pr_outcome", window_days)
        total_prs = len(pr_outcomes)
        accepted_prs = sum(1 for r in pr_outcomes if r.get("accepted"))
        pr_rate = (accepted_prs / max(total_prs, 1)) * 100

        gate_overrides = self._query("gate_override", window_days)
        gate_decisions = self._query("gate_decision", window_days)
        total_decisions = len(gate_decisions)
        override_rate = (len(gate_overrides) / max(total_decisions, 1)) * 100

        interventions = self._query("manual_intervention", window_days)
        total_executions = max(total_decisions // 4, 1)
        intervention_rate = (len(interventions) / total_executions) * 100

        pr_component = min(pr_rate, 100) * _WEIGHT_PR_ACCEPTANCE
        override_component = max(0, 100 - override_rate * 10) * _WEIGHT_GATE_OVERRIDE
        intervention_component = max(0, 100 - intervention_rate * 5) * _WEIGHT_MANUAL_INTERVENTION
        composite = pr_component + override_component + intervention_component

        snapshot = TrustSnapshot(
            project_id=self._project_id, window_days=window_days,
            pr_acceptance_rate_percent=round(pr_rate, 1),
            gate_override_rate_percent=round(override_rate, 1),
            manual_intervention_rate_percent=round(intervention_rate, 1),
            trust_score_composite=round(composite, 1),
            total_prs=total_prs, total_gate_decisions=total_decisions,
            total_executions=total_executions,
        )
        self._persist_snapshot(snapshot)
        return snapshot

    def _record(self, event_type: str, task_id: str, data: dict[str, Any]) -> None:
        """Persist a trust event."""
        if not self._metrics_table:
            return
        table = self._dynamodb.Table(self._metrics_table)
        now = datetime.now(timezone.utc).isoformat()
        try:
            table.put_item(Item={
                "project_id": self._project_id,
                "metric_key": f"trust#{event_type}#{now}",
                "metric_type": "trust", "task_id": task_id, "recorded_at": now,
                "data": json.dumps({"event_type": event_type, **data}),
            })
        except ClientError as e:
            logger.warning("Failed to record trust event: %s", str(e))

    def _query(self, event_type: str, window_days: int) -> list[dict[str, Any]]:
        """Query trust events by type within window."""
        if not self._metrics_table:
            return []
        table = self._dynamodb.Table(self._metrics_table)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
        prefix = f"trust#{event_type}#"
        try:
            response = table.query(
                KeyConditionExpression="project_id = :pid AND begins_with(metric_key, :prefix)",
                FilterExpression="recorded_at >= :cutoff",
                ExpressionAttributeValues={":pid": self._project_id, ":prefix": prefix, ":cutoff": cutoff},
            )
            return [json.loads(item.get("data", "{}")) for item in response.get("Items", [])]
        except ClientError as e:
            logger.warning("Failed to query trust events: %s", str(e))
            return []

    def _persist_snapshot(self, snapshot: TrustSnapshot) -> None:
        """Persist trust snapshot."""
        if not self._metrics_table:
            return
        table = self._dynamodb.Table(self._metrics_table)
        now = datetime.now(timezone.utc).isoformat()
        try:
            table.put_item(Item={
                "project_id": self._project_id, "metric_key": f"trust#snapshot#{now}",
                "metric_type": "trust_snapshot", "task_id": "", "recorded_at": now,
                "data": json.dumps({
                    "pr_acceptance_rate": snapshot.pr_acceptance_rate_percent,
                    "gate_override_rate": snapshot.gate_override_rate_percent,
                    "intervention_rate": snapshot.manual_intervention_rate_percent,
                    "composite_score": snapshot.trust_score_composite,
                }),
            })
        except ClientError as e:
            logger.warning("Failed to persist trust snapshot: %s", str(e))
