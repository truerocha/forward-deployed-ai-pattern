"""
Gate Optimizer — Trust-Based Gate Fast Path.

Monitors gate-pass-rate per pattern category and manages trust status:
  - If a pattern passes adversarial gate >98% over 30 days -> "trusted pattern"
  - Trusted patterns at L5 skip adversarial gate (fast path)
  - Trust revocation: immediate on first failure
  - Re-trust requires 30 new clean passes after revocation

Also tracks time_in_gates metric to detect gate overhead:
  - Alert if gate time exceeds 20% of total task time

DynamoDB SK pattern: gate_trust#{pattern_category}

Ref: docs/design/fde-core-brain-development.md Section 8.2
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
TRUST_PASS_RATE_THRESHOLD = 0.98  # 98% pass rate required
TRUST_WINDOW_DAYS = 30
TRUST_MIN_SAMPLES = 20  # Minimum passes in window to qualify
RE_TRUST_CLEAN_PASSES_REQUIRED = 30
GATE_TIME_ALERT_THRESHOLD = 0.20  # Alert if >20% of task time in gates


class TrustStatus(Enum):
    """Trust status of a pattern category."""

    UNTRUSTED = "untrusted"
    TRUSTED = "trusted"
    REVOKED = "revoked"


@dataclass
class PatternTrustRecord:
    """Trust record for a pattern category."""

    pattern_category: str
    trust_status: TrustStatus = TrustStatus.UNTRUSTED
    total_passes: int = 0
    total_failures: int = 0
    consecutive_clean_passes: int = 0
    last_failure_at: str = ""
    trusted_at: str = ""
    revoked_at: str = ""
    last_evaluated_at: str = ""

    @property
    def pass_rate(self) -> float:
        """Compute pass rate as a fraction (0.0 - 1.0)."""
        total = self.total_passes + self.total_failures
        if total == 0:
            return 0.0
        return self.total_passes / total

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "pattern_category": self.pattern_category,
            "trust_status": self.trust_status.value,
            "total_passes": self.total_passes,
            "total_failures": self.total_failures,
            "consecutive_clean_passes": self.consecutive_clean_passes,
            "pass_rate": round(self.pass_rate, 4),
            "last_failure_at": self.last_failure_at,
            "trusted_at": self.trusted_at,
            "revoked_at": self.revoked_at,
            "last_evaluated_at": self.last_evaluated_at,
        }


@dataclass
class GateTimeMetric:
    """Time-in-gates metric for a task."""

    task_id: str
    total_task_time_seconds: float
    total_gate_time_seconds: float
    gate_time_ratio: float = 0.0
    is_alert: bool = False
    gate_breakdown: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.total_task_time_seconds > 0:
            self.gate_time_ratio = (
                self.total_gate_time_seconds / self.total_task_time_seconds
            )
        self.is_alert = self.gate_time_ratio > GATE_TIME_ALERT_THRESHOLD


class GateOptimizer:
    """
    Manages gate trust and fast-path optimization.

    Trust lifecycle:
      1. Pattern starts UNTRUSTED (all gates apply)
      2. After 30 days with >98% pass rate and >=20 samples -> TRUSTED
      3. Trusted patterns at L5 skip adversarial gate (fast path)
      4. On first failure -> REVOKED (immediate, all gates re-apply)
      5. After 30 consecutive clean passes -> eligible for TRUSTED again

    Usage:
        optimizer = GateOptimizer(project_id="my-repo", metrics_table="metrics")
        optimizer.record_gate_result("api-crud", passed=True)
        if optimizer.can_fast_path("api-crud", autonomy_level=5):
            # Skip adversarial gate
            ...
    """

    def __init__(
        self,
        project_id: str,
        metrics_table: str | None = None,
    ):
        self._project_id = project_id
        self._metrics_table = metrics_table or os.environ.get("METRICS_TABLE", "")
        self._dynamodb = boto3.resource("dynamodb")

    def record_gate_result(
        self, pattern_category: str, passed: bool, gate_name: str = "adversarial"
    ) -> PatternTrustRecord:
        """
        Record a gate pass/fail result for a pattern category.

        On failure: immediately revokes trust if currently trusted.
        On pass: increments counters and evaluates trust eligibility.

        Args:
            pattern_category: The pattern category (e.g., "api-crud", "data-pipeline").
            passed: Whether the gate was passed.
            gate_name: Which gate produced this result.

        Returns:
            Updated PatternTrustRecord.
        """
        record = self._load_trust_record(pattern_category)
        now = datetime.now(timezone.utc).isoformat()
        record.last_evaluated_at = now

        if passed:
            record.total_passes += 1
            record.consecutive_clean_passes += 1
            self._evaluate_trust_promotion(record)
        else:
            record.total_failures += 1
            record.consecutive_clean_passes = 0
            record.last_failure_at = now

            # Immediate trust revocation on failure
            if record.trust_status == TrustStatus.TRUSTED:
                record.trust_status = TrustStatus.REVOKED
                record.revoked_at = now
                logger.warning(
                    "Trust REVOKED for pattern '%s' in project %s (failure at gate '%s')",
                    pattern_category,
                    self._project_id,
                    gate_name,
                )

        self._persist_trust_record(record)
        return record

    def can_fast_path(self, pattern_category: str, autonomy_level: int) -> bool:
        """
        Check if a pattern can skip the adversarial gate (fast path).

        Fast path is only available when:
          - Pattern is TRUSTED
          - Autonomy level is L5

        Args:
            pattern_category: The pattern category to check.
            autonomy_level: Current task autonomy level (1-5).

        Returns:
            True if adversarial gate can be skipped.
        """
        if autonomy_level < 5:
            return False

        record = self._load_trust_record(pattern_category)
        can_skip = record.trust_status == TrustStatus.TRUSTED

        if can_skip:
            logger.info(
                "Fast path ENABLED for pattern '%s' at L%d",
                pattern_category,
                autonomy_level,
            )

        return can_skip

    def get_trust_status(self, pattern_category: str) -> PatternTrustRecord:
        """
        Get the current trust record for a pattern category.

        Args:
            pattern_category: The pattern to query.

        Returns:
            Current PatternTrustRecord.
        """
        return self._load_trust_record(pattern_category)

    def get_all_trusted_patterns(self) -> list[PatternTrustRecord]:
        """
        List all currently trusted pattern categories.

        Returns:
            List of PatternTrustRecords with TRUSTED status.
        """
        if not self._metrics_table:
            return []

        table = self._dynamodb.Table(self._metrics_table)
        try:
            response = table.query(
                KeyConditionExpression=(
                    "project_id = :pid AND begins_with(metric_key, :prefix)"
                ),
                ExpressionAttributeValues={
                    ":pid": self._project_id,
                    ":prefix": "gate_trust#",
                },
            )

            trusted: list[PatternTrustRecord] = []
            for item in response.get("Items", []):
                data = json.loads(item.get("data", "{}"))
                record = self._dict_to_record(data)
                if record.trust_status == TrustStatus.TRUSTED:
                    trusted.append(record)

            return trusted

        except ClientError as e:
            logger.warning("Failed to query trusted patterns: %s", str(e))
            return []

    def record_gate_time(
        self,
        task_id: str,
        total_task_time_seconds: float,
        gate_times: dict[str, float],
    ) -> GateTimeMetric:
        """
        Record time spent in gates for a task and check alert threshold.

        Args:
            task_id: The task being measured.
            total_task_time_seconds: Total elapsed time for the task.
            gate_times: Dict of gate_name -> seconds spent in that gate.

        Returns:
            GateTimeMetric with alert flag if threshold exceeded.
        """
        total_gate_time = sum(gate_times.values())

        metric = GateTimeMetric(
            task_id=task_id,
            total_task_time_seconds=total_task_time_seconds,
            total_gate_time_seconds=total_gate_time,
            gate_breakdown=gate_times,
        )

        if metric.is_alert:
            logger.warning(
                "GATE TIME ALERT: task=%s gate_ratio=%.1f%% (threshold=%.0f%%). "
                "Gates consuming too much task time.",
                task_id,
                metric.gate_time_ratio * 100,
                GATE_TIME_ALERT_THRESHOLD * 100,
            )

        self._persist_gate_time_metric(metric)
        return metric

    def get_gate_time_trend(self, window_days: int = 7) -> dict[str, Any]:
        """
        Get average gate time ratio over a window.

        Returns:
            Dict with average ratio, alert count, and trend direction.
        """
        if not self._metrics_table:
            return {"avg_ratio": 0.0, "alert_count": 0, "sample_size": 0}

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
                    ":prefix": "gate_time#",
                    ":cutoff": cutoff,
                },
            )

            items = response.get("Items", [])
            if not items:
                return {"avg_ratio": 0.0, "alert_count": 0, "sample_size": 0}

            ratios: list[float] = []
            alert_count = 0
            for item in items:
                data = json.loads(item.get("data", "{}"))
                ratio = data.get("gate_time_ratio", 0.0)
                ratios.append(ratio)
                if data.get("is_alert", False):
                    alert_count += 1

            avg_ratio = sum(ratios) / len(ratios) if ratios else 0.0
            return {
                "avg_ratio": round(avg_ratio, 4),
                "alert_count": alert_count,
                "sample_size": len(ratios),
            }

        except ClientError as e:
            logger.warning("Failed to query gate time trend: %s", str(e))
            return {"avg_ratio": 0.0, "alert_count": 0, "sample_size": 0}

    def _evaluate_trust_promotion(self, record: PatternTrustRecord) -> None:
        """Evaluate whether a pattern should be promoted to trusted."""
        now = datetime.now(timezone.utc).isoformat()

        if record.trust_status == TrustStatus.TRUSTED:
            return  # Already trusted

        if record.trust_status == TrustStatus.REVOKED:
            # Revoked patterns need 30 consecutive clean passes to re-trust
            if record.consecutive_clean_passes >= RE_TRUST_CLEAN_PASSES_REQUIRED:
                record.trust_status = TrustStatus.TRUSTED
                record.trusted_at = now
                logger.info(
                    "Trust RESTORED for pattern '%s' after %d clean passes",
                    record.pattern_category,
                    record.consecutive_clean_passes,
                )
        else:
            # Untrusted patterns need >98% pass rate with sufficient samples
            total = record.total_passes + record.total_failures
            if (
                total >= TRUST_MIN_SAMPLES
                and record.pass_rate >= TRUST_PASS_RATE_THRESHOLD
            ):
                record.trust_status = TrustStatus.TRUSTED
                record.trusted_at = now
                logger.info(
                    "Trust GRANTED for pattern '%s' (pass_rate=%.2f%%, samples=%d)",
                    record.pattern_category,
                    record.pass_rate * 100,
                    total,
                )

    def _load_trust_record(self, pattern_category: str) -> PatternTrustRecord:
        """Load trust record from DynamoDB or return a new one."""
        if not self._metrics_table:
            return PatternTrustRecord(pattern_category=pattern_category)

        table = self._dynamodb.Table(self._metrics_table)
        try:
            response = table.get_item(
                Key={
                    "project_id": self._project_id,
                    "metric_key": f"gate_trust#{pattern_category}",
                }
            )

            item = response.get("Item")
            if not item:
                return PatternTrustRecord(pattern_category=pattern_category)

            data = json.loads(item.get("data", "{}"))
            return self._dict_to_record(data)

        except ClientError as e:
            logger.warning("Failed to load trust record for '%s': %s", pattern_category, str(e))
            return PatternTrustRecord(pattern_category=pattern_category)

    def _persist_trust_record(self, record: PatternTrustRecord) -> None:
        """Persist trust record to DynamoDB."""
        if not self._metrics_table:
            return

        table = self._dynamodb.Table(self._metrics_table)
        now = datetime.now(timezone.utc).isoformat()

        try:
            table.put_item(
                Item={
                    "project_id": self._project_id,
                    "metric_key": f"gate_trust#{record.pattern_category}",
                    "metric_type": "gate_trust",
                    "recorded_at": now,
                    "data": json.dumps(record.to_dict()),
                }
            )
        except ClientError as e:
            logger.warning(
                "Failed to persist trust record for '%s': %s",
                record.pattern_category,
                str(e),
            )

    def _persist_gate_time_metric(self, metric: GateTimeMetric) -> None:
        """Persist gate time metric to DynamoDB."""
        if not self._metrics_table:
            return

        table = self._dynamodb.Table(self._metrics_table)
        now = datetime.now(timezone.utc).isoformat()

        try:
            table.put_item(
                Item={
                    "project_id": self._project_id,
                    "metric_key": f"gate_time#{metric.task_id}#{now}",
                    "metric_type": "gate_time",
                    "task_id": metric.task_id,
                    "recorded_at": now,
                    "data": json.dumps(
                        {
                            "task_id": metric.task_id,
                            "total_task_time_seconds": metric.total_task_time_seconds,
                            "total_gate_time_seconds": metric.total_gate_time_seconds,
                            "gate_time_ratio": metric.gate_time_ratio,
                            "is_alert": metric.is_alert,
                            "gate_breakdown": metric.gate_breakdown,
                        }
                    ),
                }
            )
        except ClientError as e:
            logger.warning("Failed to persist gate time metric: %s", str(e))

    def _dict_to_record(self, data: dict[str, Any]) -> PatternTrustRecord:
        """Convert a dictionary to a PatternTrustRecord."""
        return PatternTrustRecord(
            pattern_category=data.get("pattern_category", ""),
            trust_status=TrustStatus(data.get("trust_status", "untrusted")),
            total_passes=data.get("total_passes", 0),
            total_failures=data.get("total_failures", 0),
            consecutive_clean_passes=data.get("consecutive_clean_passes", 0),
            last_failure_at=data.get("last_failure_at", ""),
            trusted_at=data.get("trusted_at", ""),
            revoked_at=data.get("revoked_at", ""),
            last_evaluated_at=data.get("last_evaluated_at", ""),
        )
