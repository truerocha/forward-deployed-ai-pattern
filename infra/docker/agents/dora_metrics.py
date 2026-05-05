"""
DORA Metrics Collector — Measures and persists the four key DORA metrics
plus factory-specific metrics for continuous improvement.

DORA Metrics (per task):
  1. Lead Time for Changes: time from task InProgress → PR/MR opened
  2. Deployment Frequency: tasks completed per time window
  3. Change Failure Rate: tasks that failed / total tasks attempted
  4. Mean Time to Recovery (MTTR): time from failure → next successful completion

Factory Metrics (per task):
  5. Constraint Extraction Time: how long extraction took
  6. DoR Gate Pass Rate: % of tasks that pass DoR on first attempt
  7. Inner Loop Retry Rate: average retries per inner loop gate
  8. Agent Specialization Hit Rate: % of tasks that got a Registry prompt (vs fallback)
  9. Pipeline Stage Duration: time per stage (recon, engineering, reporting)

All metrics are written to DynamoDB (dora-metrics table) and S3 (for dashboards).
Each metric event is immutable — append-only for audit trail.

DynamoDB schema:
  PK: metric_id (S)  — "DORA-{uuid}"
  GSI: task-index (task_id S, recorded_at S)
  GSI: type-index (metric_type S, recorded_at S)
"""

import json
import logging
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger("fde.dora_metrics")

_TABLE_NAME = os.environ.get("DORA_METRICS_TABLE", "fde-dev-dora-metrics")
_REGION = os.environ.get("AWS_REGION", "us-east-1")


def _get_table():
    return boto3.resource("dynamodb", region_name=_REGION).Table(_TABLE_NAME)


class MetricType(str, Enum):
    # DORA core
    LEAD_TIME = "dora.lead_time"
    DEPLOYMENT_FREQUENCY = "dora.deployment_frequency"
    CHANGE_FAILURE_RATE = "dora.change_failure_rate"
    MTTR = "dora.mttr"
    # Factory-specific
    CONSTRAINT_EXTRACTION_TIME = "factory.constraint_extraction_time"
    DOR_GATE_RESULT = "factory.dor_gate_result"
    INNER_LOOP_RETRIES = "factory.inner_loop_retries"
    AGENT_SPECIALIZATION = "factory.agent_specialization"
    PIPELINE_STAGE_DURATION = "factory.pipeline_stage_duration"
    SDLC_REPORT = "factory.sdlc_report"
    TASK_OUTCOME = "factory.task_outcome"


@dataclass
class MetricEvent:
    """A single immutable metric event."""

    metric_type: str
    task_id: str
    value: float                         # The numeric metric value
    unit: str                            # ms, count, ratio, boolean
    dimensions: dict = field(default_factory=dict)  # Extra context
    recorded_at: str = ""
    metric_id: str = ""

    def __post_init__(self):
        if not self.recorded_at:
            self.recorded_at = datetime.now(timezone.utc).isoformat()
        if not self.metric_id:
            self.metric_id = f"DORA-{uuid.uuid4().hex[:8]}"


class DORACollector:
    """Collects and persists DORA metrics for the Code Factory.

    Usage:
        collector = DORACollector()
        collector.record_lead_time(task_id, start_time, end_time)
        collector.record_task_outcome(task_id, "completed", duration_ms)
        report = collector.get_task_metrics(task_id)
    """

    def __init__(self, factory_bucket: str = ""):
        self._factory_bucket = factory_bucket or os.environ.get("FACTORY_BUCKET", "")
        self._s3 = boto3.client("s3", region_name=_REGION) if self._factory_bucket else None

    # ─── DORA Core Metrics ──────────────────────────────────────

    def record_lead_time(
        self,
        task_id: str,
        started_at: str,
        pr_opened_at: str,
        source: str = "",
        tech_stack: list[str] | None = None,
    ) -> MetricEvent:
        """Record Lead Time for Changes: InProgress → PR opened.

        Args:
            task_id: The task identifier.
            started_at: ISO 8601 timestamp when task moved to InProgress.
            pr_opened_at: ISO 8601 timestamp when PR/MR was opened.
            source: ALM platform source.
            tech_stack: Technologies involved (for domain segmentation).

        Returns:
            The recorded MetricEvent.
        """
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(pr_opened_at)
        lead_time_ms = int((end - start).total_seconds() * 1000)

        event = MetricEvent(
            metric_type=MetricType.LEAD_TIME,
            task_id=task_id,
            value=lead_time_ms,
            unit="ms",
            dimensions={
                "source": source,
                "started_at": started_at,
                "pr_opened_at": pr_opened_at,
                "tech_stack": tech_stack or [],
            },
        )
        self._persist(event)
        logger.info("DORA lead_time: task=%s %dms", task_id, lead_time_ms)
        return event

    def record_task_outcome(
        self,
        task_id: str,
        outcome: str,
        duration_ms: int,
        source: str = "",
        failure_reason: str = "",
        tech_stack: list[str] | None = None,
    ) -> MetricEvent:
        """Record a task completion or failure for Change Failure Rate.

        Args:
            task_id: The task identifier.
            outcome: "completed" | "failed" | "blocked".
            duration_ms: Total pipeline execution time.
            source: ALM platform source.
            failure_reason: Why it failed (if applicable).
            tech_stack: Technologies involved (for domain segmentation).

        Returns:
            The recorded MetricEvent.
        """
        is_failure = 1.0 if outcome in ("failed", "blocked") else 0.0

        event = MetricEvent(
            metric_type=MetricType.TASK_OUTCOME,
            task_id=task_id,
            value=is_failure,
            unit="boolean",
            dimensions={
                "outcome": outcome,
                "duration_ms": duration_ms,
                "source": source,
                "failure_reason": failure_reason,
                "tech_stack": tech_stack or [],
            },
        )
        self._persist(event)
        logger.info("DORA task_outcome: task=%s outcome=%s %dms", task_id, outcome, duration_ms)
        return event

    def record_mttr(
        self,
        task_id: str,
        failed_at: str,
        recovered_at: str,
    ) -> MetricEvent:
        """Record Mean Time to Recovery: failure → next success.

        Args:
            task_id: The task identifier.
            failed_at: ISO 8601 timestamp of the failure.
            recovered_at: ISO 8601 timestamp of recovery.

        Returns:
            The recorded MetricEvent.
        """
        start = datetime.fromisoformat(failed_at)
        end = datetime.fromisoformat(recovered_at)
        mttr_ms = int((end - start).total_seconds() * 1000)

        event = MetricEvent(
            metric_type=MetricType.MTTR,
            task_id=task_id,
            value=mttr_ms,
            unit="ms",
            dimensions={"failed_at": failed_at, "recovered_at": recovered_at},
        )
        self._persist(event)
        logger.info("DORA mttr: task=%s %dms", task_id, mttr_ms)
        return event

    # ─── Factory Metrics ────────────────────────────────────────

    def record_constraint_extraction(
        self,
        task_id: str,
        duration_ms: int,
        constraints_count: int,
        ambiguous_count: int,
        used_llm: bool,
    ) -> MetricEvent:
        """Record constraint extraction performance."""
        event = MetricEvent(
            metric_type=MetricType.CONSTRAINT_EXTRACTION_TIME,
            task_id=task_id,
            value=duration_ms,
            unit="ms",
            dimensions={
                "constraints_count": constraints_count,
                "ambiguous_count": ambiguous_count,
                "used_llm": used_llm,
            },
        )
        self._persist(event)
        return event

    def record_dor_gate(
        self,
        task_id: str,
        passed: bool,
        failures_count: int,
        warnings_count: int,
    ) -> MetricEvent:
        """Record DoR Gate result."""
        event = MetricEvent(
            metric_type=MetricType.DOR_GATE_RESULT,
            task_id=task_id,
            value=1.0 if passed else 0.0,
            unit="boolean",
            dimensions={
                "failures_count": failures_count,
                "warnings_count": warnings_count,
            },
        )
        self._persist(event)
        return event

    def record_inner_loop(
        self,
        task_id: str,
        gate_name: str,
        attempts: int,
        passed: bool,
        duration_ms: int,
    ) -> MetricEvent:
        """Record inner loop gate execution."""
        event = MetricEvent(
            metric_type=MetricType.INNER_LOOP_RETRIES,
            task_id=task_id,
            value=attempts,
            unit="count",
            dimensions={
                "gate": gate_name,
                "passed": passed,
                "duration_ms": duration_ms,
            },
        )
        self._persist(event)
        return event

    def record_agent_specialization(
        self,
        task_id: str,
        used_registry_prompt: bool,
        prompt_name: str,
        prompt_version: int,
        tech_stack: list[str],
    ) -> MetricEvent:
        """Record whether the Agent Builder found a specialized prompt."""
        event = MetricEvent(
            metric_type=MetricType.AGENT_SPECIALIZATION,
            task_id=task_id,
            value=1.0 if used_registry_prompt else 0.0,
            unit="boolean",
            dimensions={
                "prompt_name": prompt_name,
                "prompt_version": prompt_version,
                "tech_stack": tech_stack,
            },
        )
        self._persist(event)
        return event

    def record_pipeline_stage(
        self,
        task_id: str,
        stage_name: str,
        duration_ms: int,
        status: str,
        tech_stack: list[str] | None = None,
    ) -> MetricEvent:
        """Record duration of a single pipeline stage."""
        event = MetricEvent(
            metric_type=MetricType.PIPELINE_STAGE_DURATION,
            task_id=task_id,
            value=duration_ms,
            unit="ms",
            dimensions={"stage": stage_name, "status": status, "tech_stack": tech_stack or []},
        )
        self._persist(event)
        return event

    def record_sdlc_report(
        self,
        task_id: str,
        sdlc_report_dict: dict,
    ) -> MetricEvent:
        """Record the full SDLC report as a metric event."""
        event = MetricEvent(
            metric_type=MetricType.SDLC_REPORT,
            task_id=task_id,
            value=1.0 if sdlc_report_dict.get("all_passed") else 0.0,
            unit="boolean",
            dimensions=sdlc_report_dict,
        )
        self._persist(event)
        return event

    # ─── Queries ────────────────────────────────────────────────

    def get_task_metrics(self, task_id: str) -> list[dict]:
        """Get all metrics for a specific task."""
        try:
            items = _get_table().query(
                IndexName="task-index",
                KeyConditionExpression=Key("task_id").eq(task_id),
            ).get("Items", [])
            return sorted(items, key=lambda x: x.get("recorded_at", ""))
        except Exception as e:
            logger.error("Failed to query metrics for task %s: %s", task_id, e)
            return []

    def get_metrics_by_type(
        self,
        metric_type: str,
        limit: int = 100,
    ) -> list[dict]:
        """Get recent metrics of a specific type (for dashboards)."""
        try:
            items = _get_table().query(
                IndexName="type-index",
                KeyConditionExpression=Key("metric_type").eq(metric_type),
                ScanIndexForward=False,
                Limit=limit,
            ).get("Items", [])
            return items
        except Exception as e:
            logger.error("Failed to query metrics type %s: %s", metric_type, e)
            return []

    def compute_acceptance_rate_by_domain(self, window_days: int = 30) -> dict:
        """Compute acceptance rate (success rate) segmented by tech_stack domain.

        Returns:
            Dict mapping domain name to {"rate": float, "samples": int, "status": str}.
            Domains with < 5 samples are marked "insufficient_data".
        """
        outcomes = self.get_metrics_by_type(MetricType.TASK_OUTCOME, limit=1000)
        cutoff = datetime.now(timezone.utc)

        # Aggregate by domain
        domain_stats: dict[str, dict[str, int]] = {}  # domain → {total, success}

        for item in outcomes:
            if not self._within_window(item.get("recorded_at", ""), cutoff, window_days):
                continue

            dimensions = item.get("dimensions", "")
            if isinstance(dimensions, str):
                try:
                    dimensions = json.loads(dimensions)
                except (json.JSONDecodeError, TypeError):
                    dimensions = {}

            tech_stack = dimensions.get("tech_stack", [])
            is_success = float(item.get("value", 1)) == 0.0

            for domain in tech_stack:
                domain_lower = domain.lower()
                if domain_lower not in domain_stats:
                    domain_stats[domain_lower] = {"total": 0, "success": 0}
                domain_stats[domain_lower]["total"] += 1
                if is_success:
                    domain_stats[domain_lower]["success"] += 1

        # Compute rates
        result: dict[str, dict] = {}
        for domain, stats in domain_stats.items():
            total = stats["total"]
            rate = round(stats["success"] / total, 2) if total > 0 else 0.0
            entry: dict = {"rate": rate, "samples": total}
            if total < 5:
                entry["status"] = "insufficient_data"
            result[domain] = entry

        return result

    def compute_change_failure_rate(self, window_days: int = 30) -> dict:
        """Compute Change Failure Rate over a time window.

        Returns:
            Dict with total_tasks, failed_tasks, failure_rate.
        """
        cutoff = datetime.now(timezone.utc)
        outcomes = self.get_metrics_by_type(MetricType.TASK_OUTCOME, limit=1000)

        total = 0
        failed = 0
        for item in outcomes:
            recorded = item.get("recorded_at", "")
            if recorded:
                try:
                    dt = datetime.fromisoformat(recorded)
                    if (cutoff - dt).days > window_days:
                        continue
                except ValueError:
                    continue
            total += 1
            if float(item.get("value", 0)) > 0:
                failed += 1

        rate = (failed / total * 100) if total > 0 else 0.0
        return {
            "window_days": window_days,
            "total_tasks": total,
            "failed_tasks": failed,
            "failure_rate_pct": round(rate, 2),
        }

    # ─── Persistence ────────────────────────────────────────────

    def generate_factory_report(self, window_days: int = 30) -> dict:
        """Generate a consumable Factory Health Report for dashboards.

        Computes all DORA metrics and factory metrics over a time window
        and returns a structured report suitable for S3 persistence,
        CloudWatch custom metrics, or Slack/email notifications.

        Args:
            window_days: Time window for metric computation.

        Returns:
            Dict with all computed metrics and health assessment.
        """
        cfr = self.compute_change_failure_rate(window_days)

        # Compute average lead time
        lead_times = self.get_metrics_by_type(MetricType.LEAD_TIME, limit=500)
        lead_time_values = [float(lt.get("value", 0)) for lt in lead_times]
        avg_lead_time_ms = (
            int(sum(lead_time_values) / len(lead_time_values))
            if lead_time_values else 0
        )

        # Compute deployment frequency (tasks completed in window)
        outcomes = self.get_metrics_by_type(MetricType.TASK_OUTCOME, limit=1000)
        cutoff = datetime.now(timezone.utc)
        completed_in_window = sum(
            1 for o in outcomes
            if float(o.get("value", 1)) == 0.0  # value 0 = success
            and self._within_window(o.get("recorded_at", ""), cutoff, window_days)
        )
        deploys_per_day = round(completed_in_window / max(window_days, 1), 2)

        # Compute DoR gate pass rate
        dor_results = self.get_metrics_by_type(MetricType.DOR_GATE_RESULT, limit=500)
        dor_passed = sum(1 for d in dor_results if float(d.get("value", 0)) == 1.0)
        dor_pass_rate = round(dor_passed / max(len(dor_results), 1) * 100, 2)

        # Compute agent specialization hit rate
        spec_results = self.get_metrics_by_type(MetricType.AGENT_SPECIALIZATION, limit=500)
        spec_hits = sum(1 for s in spec_results if float(s.get("value", 0)) == 1.0)
        spec_hit_rate = round(spec_hits / max(len(spec_results), 1) * 100, 2)

        # Compute average inner loop retries
        inner_results = self.get_metrics_by_type(MetricType.INNER_LOOP_RETRIES, limit=500)
        retry_values = [float(r.get("value", 1)) for r in inner_results]
        avg_retries = round(sum(retry_values) / max(len(retry_values), 1), 2)

        # DORA performance level classification
        # Elite: lead_time < 1h, deploys_per_day > 1, cfr < 5%, mttr < 1h
        # High:  lead_time < 1d, deploys_per_day > 0.14, cfr < 10%
        # Medium: lead_time < 7d, deploys_per_day > 0.03, cfr < 15%
        # Low:   everything else
        lead_time_hours = avg_lead_time_ms / 3_600_000
        if lead_time_hours < 1 and deploys_per_day > 1 and cfr["failure_rate_pct"] < 5:
            dora_level = "Elite"
        elif lead_time_hours < 24 and deploys_per_day > 0.14 and cfr["failure_rate_pct"] < 10:
            dora_level = "High"
        elif lead_time_hours < 168 and deploys_per_day > 0.03 and cfr["failure_rate_pct"] < 15:
            dora_level = "Medium"
        else:
            dora_level = "Low"

        report = {
            "report_type": "factory_health",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "window_days": window_days,
            "dora_level": dora_level,
            "dora_metrics": {
                "lead_time_avg_ms": avg_lead_time_ms,
                "lead_time_avg_human": self._humanize_ms(avg_lead_time_ms),
                "deployment_frequency": {
                    "completed_tasks": completed_in_window,
                    "deploys_per_day": deploys_per_day,
                },
                "change_failure_rate": cfr,
            },
            "factory_metrics": {
                "dor_gate_pass_rate_pct": dor_pass_rate,
                "agent_specialization_hit_rate_pct": spec_hit_rate,
                "avg_inner_loop_retries": avg_retries,
                "total_tasks_in_window": cfr["total_tasks"],
            },
            "domain_breakdown": self.compute_acceptance_rate_by_domain(window_days),
        }

        # Persist report to S3
        if self._s3 and self._factory_bucket:
            date_str = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            key = f"reports/factory-health/{date_str}.json"
            try:
                self._s3.put_object(
                    Bucket=self._factory_bucket,
                    Key=key,
                    Body=json.dumps(report, indent=2, default=str).encode("utf-8"),
                )
                report["s3_uri"] = f"s3://{self._factory_bucket}/{key}"
                logger.info("Factory health report written to s3://%s/%s", self._factory_bucket, key)
            except Exception as e:
                logger.error("Failed to write factory report to S3: %s", e)

        return report

    @staticmethod
    def _within_window(recorded_at: str, cutoff: datetime, window_days: int) -> bool:
        """Check if a timestamp is within the time window."""
        if not recorded_at:
            return False
        try:
            dt = datetime.fromisoformat(recorded_at)
            return (cutoff - dt).days <= window_days
        except ValueError:
            return False

    @staticmethod
    def _humanize_ms(ms: int) -> str:
        """Convert milliseconds to human-readable duration."""
        if ms < 1000:
            return f"{ms}ms"
        seconds = ms / 1000
        if seconds < 60:
            return f"{seconds:.1f}s"
        minutes = seconds / 60
        if minutes < 60:
            return f"{minutes:.1f}m"
        hours = minutes / 60
        if hours < 24:
            return f"{hours:.1f}h"
        days = hours / 24
        return f"{days:.1f}d"

    def _persist(self, event: MetricEvent) -> None:
        """Write a metric event to DynamoDB and optionally S3."""
        item = {
            "metric_id": event.metric_id,
            "metric_type": event.metric_type,
            "task_id": event.task_id,
            "value": str(event.value),  # DynamoDB doesn't support float directly
            "unit": event.unit,
            "dimensions": json.dumps(event.dimensions, default=str),
            "recorded_at": event.recorded_at,
        }

        try:
            _get_table().put_item(Item=item)
        except Exception as e:
            logger.error("Failed to persist metric %s: %s", event.metric_id, e)

        # Also write to S3 for long-term analytics
        if self._s3 and self._factory_bucket:
            date_prefix = event.recorded_at[:10].replace("-", "/")
            key = f"metrics/{date_prefix}/{event.metric_type}/{event.metric_id}.json"
            try:
                self._s3.put_object(
                    Bucket=self._factory_bucket,
                    Key=key,
                    Body=json.dumps(asdict(event), default=str).encode("utf-8"),
                )
            except Exception as e:
                logger.error("Failed to write metric to S3: %s", e)
