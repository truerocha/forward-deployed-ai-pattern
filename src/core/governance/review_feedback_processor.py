"""
Review Feedback Processor — Closes the Human-Agent Learning Loop.

CRITICAL GAP (ADR-027): The factory operates open-loop with respect to human
PR reviews. When a reviewer submits "changes_requested" or comments with
re-work signals, the factory has no mechanism to detect, record, learn, or
re-execute. This module closes that gap.

Responsibilities:
  1. Classify PR review events (changes_requested vs informational)
  2. Record metrics across all metric systems (DORA, Trust, Verification, Happy Time)
  3. Update Risk Engine weights (Bayesian learning from false negatives)
  4. Emit re-work event for pipeline re-trigger (via EventBridge)
  5. Enforce circuit breaker (max 2 re-work attempts per task)

Integration points:
  - DORA Metrics: record_change_failure(is_failure=True)
  - Trust Metrics: record_pr_outcome(accepted=False)
  - Verification Metrics: record_review_completed(accepted=False)
  - Happy Time: record_rework_time()
  - Risk Engine: update_weights_from_outcome("failed")
  - Anti-Instability Loop: CFR increase triggers autonomy reduction
  - Conductor: refine_plan() with feedback context for re-execution

Research grounding:
  - c-CRAB (arXiv:2603.23448): Human reviews as ground truth for agent evaluation
  - HULA (arXiv:2411.12924): Iterative human feedback refinement
  - DORA 2025: Rework rate as fifth metric; AI shifts bottleneck to review
  - ThoughtWorks Radar 2026: Rework rate added to DORA framework

DynamoDB SK pattern: review_feedback#{task_id}#{review_id}

Ref: docs/adr/ADR-027-review-feedback-loop.md
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger("fde.governance.review_feedback")


# ─── Classification ─────────────────────────────────────────────


class ReviewClassification(Enum):
    """Classification of a PR review event."""

    FULL_REWORK = "full_rework"          # Major issues, redo the task
    PARTIAL_FIX = "partial_fix"          # Minor issues, targeted fixes needed
    INFORMATIONAL = "informational"      # Comment only, no action required
    APPROVAL = "approval"                # PR approved (positive signal)
    DISMISSED = "dismissed"              # Review dismissed (ignore)


# Keywords that signal re-work (case-insensitive)
_REWORK_KEYWORDS = [
    "re-work", "rework", "redo", "start over", "sent back",
    "fundamentally wrong", "wrong approach", "rewrite",
    "not acceptable", "reject", "major issues", "unsafe",
    "security concern", "breaks", "regression",
]

_PARTIAL_FIX_KEYWORDS = [
    "minor fix", "small change", "nit", "typo", "formatting",
    "please update", "consider changing", "suggestion",
    "could you", "would be better", "missing",
]

_APPROVAL_KEYWORDS = [
    "lgtm", "looks good", "approved", "ship it", "merge",
]


# ─── Data Structures ────────────────────────────────────────────


@dataclass
class ReviewFeedbackEvent:
    """Structured representation of a PR review feedback event."""

    review_id: str
    pr_number: int
    repo: str
    reviewer: str
    review_state: str          # "changes_requested" | "commented" | "approved" | "dismissed"
    review_body: str
    task_id: str = ""
    pr_url: str = ""
    files_commented: list[str] = field(default_factory=list)
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    @property
    def idempotency_key(self) -> str:
        """Unique key to prevent duplicate processing."""
        return f"{self.task_id}#{self.repo}#{self.pr_number}#{self.review_id}"


@dataclass
class ReviewFeedbackResult:
    """Result of processing a review feedback event."""

    classification: ReviewClassification
    metrics_recorded: list[str]
    risk_weights_updated: bool
    rework_triggered: bool
    rework_attempt: int
    circuit_breaker_tripped: bool
    feedback_summary: str
    event: ReviewFeedbackEvent


# ─── Circuit Breaker ─────────────────────────────────────────────

_MAX_REWORK_ATTEMPTS = 2
_REWORK_ESTIMATE_SECONDS = 1800  # 30 min estimated rework time per cycle


# ─── Processor ───────────────────────────────────────────────────


class ReviewFeedbackProcessor:
    """
    Processes PR review events and closes the human-agent learning loop.

    This is the central orchestrator for the review feedback mechanism.
    It classifies events, records metrics, updates weights, and triggers
    re-execution when appropriate.

    Usage:
        processor = ReviewFeedbackProcessor(project_id="my-repo")
        result = processor.process(event)
        if result.rework_triggered:
            # Pipeline will be re-triggered via EventBridge
            ...

    Circuit Breaker:
        After 2 re-work attempts for the same task, the processor stops
        re-triggering and escalates to Staff Engineer (autonomy L1).
    """

    def __init__(
        self,
        project_id: str = "",
        metrics_table: str | None = None,
        event_bus_name: str | None = None,
    ):
        self._project_id = project_id or os.environ.get("PROJECT_ID", "global")
        self._metrics_table = metrics_table or os.environ.get("METRICS_TABLE", "")
        self._event_bus = event_bus_name or os.environ.get(
            "EVENT_BUS_NAME", "fde-dev-factory-bus"
        )
        self._dynamodb = boto3.resource("dynamodb")
        self._eventbridge = boto3.client("events")
        self._cloudwatch = boto3.client("cloudwatch")

    def process(self, event: ReviewFeedbackEvent) -> ReviewFeedbackResult:
        """
        Process a PR review feedback event end-to-end.

        Steps:
          1. Check idempotency (skip if already processed)
          2. Classify the review (full_rework / partial_fix / informational / approval)
          3. Record metrics across all systems
          4. Update Risk Engine weights (for rejections)
          5. Check circuit breaker
          6. Emit re-work event if appropriate

        Args:
            event: The structured review feedback event.

        Returns:
            ReviewFeedbackResult with classification and actions taken.
        """
        # Step 1: Idempotency check
        if self._already_processed(event.idempotency_key):
            logger.info(
                "Review already processed (idempotent skip): %s",
                event.idempotency_key,
            )
            return ReviewFeedbackResult(
                classification=ReviewClassification.DISMISSED,
                metrics_recorded=[],
                risk_weights_updated=False,
                rework_triggered=False,
                rework_attempt=0,
                circuit_breaker_tripped=False,
                feedback_summary="Duplicate event — already processed",
                event=event,
            )

        # Step 2: Classify
        classification = self._classify(event)
        logger.info(
            "Review classified: pr=%s/#%d classification=%s reviewer=%s",
            event.repo, event.pr_number, classification.value, event.reviewer,
        )

        # Step 3: Record metrics (for rejections and partial fixes)
        metrics_recorded: list[str] = []
        if classification in (
            ReviewClassification.FULL_REWORK,
            ReviewClassification.PARTIAL_FIX,
        ):
            metrics_recorded = self._record_metrics(event, classification)

        # For approvals, record positive outcome
        if classification == ReviewClassification.APPROVAL:
            metrics_recorded = self._record_approval(event)

        # Step 4: Update Risk Engine weights (rejections only)
        risk_updated = False
        if classification == ReviewClassification.FULL_REWORK:
            risk_updated = self._update_risk_weights(event)

        # Step 5: Circuit breaker check
        rework_attempt = self._get_rework_count(event.task_id)
        circuit_breaker_tripped = rework_attempt >= _MAX_REWORK_ATTEMPTS

        # Step 6: Emit re-work event (if not circuit-broken)
        rework_triggered = False
        if classification == ReviewClassification.FULL_REWORK:
            if circuit_breaker_tripped:
                logger.warning(
                    "Circuit breaker TRIPPED for task %s (attempt %d >= max %d). "
                    "Escalating to Staff Engineer.",
                    event.task_id, rework_attempt, _MAX_REWORK_ATTEMPTS,
                )
                self._escalate_to_staff_engineer(event, rework_attempt)
            else:
                rework_triggered = self._emit_rework_event(event, rework_attempt + 1)

        # Persist processing record (for idempotency + audit)
        self._persist_processing_record(event, classification, rework_triggered)

        # Emit CloudWatch metrics
        self._emit_cloudwatch_metrics(classification, circuit_breaker_tripped)

        result = ReviewFeedbackResult(
            classification=classification,
            metrics_recorded=metrics_recorded,
            risk_weights_updated=risk_updated,
            rework_triggered=rework_triggered,
            rework_attempt=rework_attempt + (1 if rework_triggered else 0),
            circuit_breaker_tripped=circuit_breaker_tripped,
            feedback_summary=self._summarize_feedback(event),
            event=event,
        )

        logger.info(
            "Review feedback processed: task=%s classification=%s "
            "rework=%s attempt=%d circuit_breaker=%s metrics=%s",
            event.task_id, classification.value, rework_triggered,
            result.rework_attempt, circuit_breaker_tripped, metrics_recorded,
        )

        return result

    # ─── Classification ──────────────────────────────────────────

    def _classify(self, event: ReviewFeedbackEvent) -> ReviewClassification:
        """Classify the review event based on state and content analysis."""
        # GitHub review states map directly
        if event.review_state == "approved":
            return ReviewClassification.APPROVAL
        if event.review_state == "dismissed":
            return ReviewClassification.DISMISSED

        # For "changes_requested" — analyze body for severity
        if event.review_state == "changes_requested":
            return self._classify_by_content(event.review_body)

        # For "commented" — could be informational or a re-work signal
        if event.review_state == "commented":
            return self._classify_by_content(event.review_body)

        return ReviewClassification.INFORMATIONAL

    def _classify_by_content(self, body: str) -> ReviewClassification:
        """Classify review body text using keyword matching."""
        if not body:
            return ReviewClassification.INFORMATIONAL

        body_lower = body.lower()

        # Check for full rework signals
        rework_score = sum(
            1 for kw in _REWORK_KEYWORDS if kw in body_lower
        )
        if rework_score >= 2:
            return ReviewClassification.FULL_REWORK

        # Single strong rework keyword with "changes_requested" state
        if rework_score >= 1:
            return ReviewClassification.FULL_REWORK

        # Check for partial fix signals
        partial_score = sum(
            1 for kw in _PARTIAL_FIX_KEYWORDS if kw in body_lower
        )
        if partial_score >= 1:
            return ReviewClassification.PARTIAL_FIX

        # Check for approval signals in comments
        approval_score = sum(
            1 for kw in _APPROVAL_KEYWORDS if kw in body_lower
        )
        if approval_score >= 1:
            return ReviewClassification.APPROVAL

        return ReviewClassification.INFORMATIONAL

    # ─── Metrics Recording ───────────────────────────────────────

    def _record_metrics(
        self, event: ReviewFeedbackEvent, classification: ReviewClassification
    ) -> list[str]:
        """Record rejection metrics across all metric systems.

        This is the critical integration point that closes the gap:
        - DORA CFR goes up (PR rejection = change failure)
        - Trust score drops (PR not accepted)
        - Verification rejection rate increases
        - Happy Time rework toil increases
        """
        recorded: list[str] = []

        # DORA: Record as change failure
        self._record_metric_event(
            "dora_change_failure",
            event.task_id,
            {
                "metric": "change_fail_rate",
                "autonomy_level": self._get_task_autonomy_level(event.task_id),
                "value": 1.0,
                "unit": "boolean",
                "source": "human_review_rejection",
                "classification": classification.value,
                "metadata": {"is_failure": True, "reviewer": event.reviewer},
            },
        )
        recorded.append("dora_cfr")

        # Trust: Record PR outcome as rejected
        self._record_metric_event(
            "trust",
            event.task_id,
            {
                "event_type": "pr_outcome",
                "accepted": False,
                "reviewer": event.reviewer,
                "classification": classification.value,
            },
        )
        recorded.append("trust_pr_outcome")

        # Verification: Record review completed with rejection
        self._record_metric_event(
            "verification",
            event.task_id,
            {
                "event_type": "pr_rejected",
                "pr_identifier": f"{event.repo}#{event.pr_number}",
                "timestamp": event.timestamp,
                "metadata": {"accepted": False, "reviewer": event.reviewer},
            },
        )
        recorded.append("verification_rejected")

        # Happy Time: Record rework time (estimated)
        self._record_metric_event(
            "happy_time",
            event.task_id,
            {
                "task_id": event.task_id,
                "category": "rework",
                "duration_seconds": _REWORK_ESTIMATE_SECONDS,
                "is_creative": False,
                "timestamp": event.timestamp,
                "metadata": {
                    "reason": f"PR review rejection: {classification.value}",
                    "reviewer": event.reviewer,
                },
            },
        )
        recorded.append("happy_time_rework")

        return recorded

    def _record_approval(self, event: ReviewFeedbackEvent) -> list[str]:
        """Record positive PR outcome (approval)."""
        recorded: list[str] = []

        # Trust: Record PR accepted
        self._record_metric_event(
            "trust",
            event.task_id,
            {
                "event_type": "pr_outcome",
                "accepted": True,
                "reviewer": event.reviewer,
            },
        )
        recorded.append("trust_pr_accepted")

        # DORA: Record as successful change (not a failure)
        self._record_metric_event(
            "dora_change_failure",
            event.task_id,
            {
                "metric": "change_fail_rate",
                "autonomy_level": self._get_task_autonomy_level(event.task_id),
                "value": 0.0,
                "unit": "boolean",
                "source": "human_review_approval",
                "metadata": {"is_failure": False, "reviewer": event.reviewer},
            },
        )
        recorded.append("dora_cfr_success")

        return recorded

    # ─── Risk Engine Integration ─────────────────────────────────

    def _update_risk_weights(self, event: ReviewFeedbackEvent) -> bool:
        """Update Risk Engine weights for false negative (predicted success, actual failure).

        This implements the Bayesian learning loop:
        - The factory predicted the task would succeed (it created a PR)
        - The human rejected it (actual outcome = failure)
        - Therefore: update_weights_from_outcome("failed")

        The weight update is persisted via the risk engine's internal mechanism.
        """
        # Record the weight update signal in metrics table
        # The actual weight update happens when the Risk Engine reads this
        # during its next assessment (lazy evaluation pattern)
        self._record_metric_event(
            "risk_weight_update",
            event.task_id,
            {
                "actual_outcome": "failed",
                "source": "human_review_rejection",
                "reviewer": event.reviewer,
                "pr_number": event.pr_number,
                "repo": event.repo,
                "feedback_summary": self._summarize_feedback(event),
                "timestamp": event.timestamp,
            },
        )

        logger.info(
            "Risk weight update signal recorded: task=%s (false negative — "
            "predicted success, human rejected)",
            event.task_id,
        )
        return True

    # ─── Re-work Trigger ─────────────────────────────────────────

    def _emit_rework_event(self, event: ReviewFeedbackEvent, attempt: int) -> bool:
        """Emit EventBridge event to re-trigger the pipeline with feedback context.

        The event carries:
          - Original task_id (for context continuity)
          - Review feedback (what was wrong)
          - Files commented (where to focus)
          - Attempt number (for circuit breaker tracking)
          - Reviewer identity (for attribution)
        """
        detail = {
            "task_id": event.task_id,
            "repo": event.repo,
            "pr_number": event.pr_number,
            "review_feedback": event.review_body[:2000],  # Truncate for EventBridge limit
            "files_to_fix": event.files_commented,
            "rework_attempt": attempt,
            "reviewer": event.reviewer,
            "original_pr_url": event.pr_url,
            "constraint": (
                f"REWORK CONSTRAINT (attempt {attempt}/{_MAX_REWORK_ATTEMPTS}): "
                f"Previous PR was rejected by {event.reviewer}. "
                f"Feedback: {event.review_body[:500]}. "
                f"Files needing attention: {', '.join(event.files_commented[:10])}. "
                f"Do NOT repeat the same approach that was rejected."
            ),
        }

        try:
            self._eventbridge.put_events(
                Entries=[
                    {
                        "Source": "fde.internal",
                        "DetailType": "task.rework_requested",
                        "Detail": json.dumps(detail),
                        "EventBusName": self._event_bus,
                    }
                ]
            )
            logger.info(
                "Rework event emitted: task=%s attempt=%d bus=%s",
                event.task_id, attempt, self._event_bus,
            )
            return True
        except ClientError as e:
            logger.error("Failed to emit rework event: %s", str(e))
            return False

    # ─── Circuit Breaker ─────────────────────────────────────────

    def _get_rework_count(self, task_id: str) -> int:
        """Get the number of rework attempts for a task."""
        if not self._metrics_table or not task_id:
            return 0

        table = self._dynamodb.Table(self._metrics_table)
        prefix = f"review_feedback#{task_id}#"

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
            # Count records where rework was triggered
            count = 0
            for item in response.get("Items", []):
                data = json.loads(item.get("data", "{}"))
                if data.get("rework_triggered"):
                    count += 1
            return count
        except ClientError as e:
            logger.warning("Failed to get rework count: %s", str(e))
            return 0

    def _escalate_to_staff_engineer(
        self, event: ReviewFeedbackEvent, attempt: int
    ) -> None:
        """Escalate to Staff Engineer when circuit breaker trips.

        Emits a high-severity CloudWatch metric and records the escalation.
        The anti-instability loop will also detect the elevated CFR and
        reduce autonomy independently.
        """
        try:
            self._cloudwatch.put_metric_data(
                Namespace="FDE/Factory",
                MetricData=[
                    {
                        "MetricName": "ReworkCircuitBreakerTripped",
                        "Value": 1.0,
                        "Unit": "Count",
                        "Dimensions": [
                            {"Name": "ProjectId", "Value": self._project_id},
                            {"Name": "TaskId", "Value": event.task_id},
                        ],
                    }
                ],
            )
        except ClientError as e:
            logger.warning("Failed to emit circuit breaker metric: %s", str(e))

        logger.error(
            "CIRCUIT BREAKER: Task %s has failed %d rework attempts. "
            "Escalating to Staff Engineer. PR: %s/#%d",
            event.task_id, attempt, event.repo, event.pr_number,
        )

    # ─── Persistence ─────────────────────────────────────────────

    def _persist_processing_record(
        self,
        event: ReviewFeedbackEvent,
        classification: ReviewClassification,
        rework_triggered: bool,
    ) -> None:
        """Persist processing record for idempotency and audit trail."""
        if not self._metrics_table:
            return

        table = self._dynamodb.Table(self._metrics_table)
        try:
            table.put_item(
                Item={
                    "project_id": self._project_id,
                    "metric_key": f"review_feedback#{event.task_id}#{event.review_id}",
                    "metric_type": "review_feedback",
                    "task_id": event.task_id,
                    "recorded_at": event.timestamp,
                    "data": json.dumps({
                        "review_id": event.review_id,
                        "pr_number": event.pr_number,
                        "repo": event.repo,
                        "reviewer": event.reviewer,
                        "review_state": event.review_state,
                        "classification": classification.value,
                        "rework_triggered": rework_triggered,
                        "idempotency_key": event.idempotency_key,
                    }),
                }
            )
        except ClientError as e:
            logger.warning("Failed to persist review feedback record: %s", str(e))

    def _already_processed(self, idempotency_key: str) -> bool:
        """Check if this review event was already processed."""
        if not self._metrics_table:
            return False

        # Extract task_id and review_id from idempotency key
        parts = idempotency_key.split("#")
        if len(parts) < 4:
            return False

        task_id = parts[0]
        review_id = parts[3]

        table = self._dynamodb.Table(self._metrics_table)
        try:
            response = table.get_item(
                Key={
                    "project_id": self._project_id,
                    "metric_key": f"review_feedback#{task_id}#{review_id}",
                }
            )
            return "Item" in response
        except ClientError:
            return False

    def _record_metric_event(
        self, metric_type: str, task_id: str, data: dict[str, Any]
    ) -> None:
        """Record a metric event to DynamoDB."""
        if not self._metrics_table:
            return

        table = self._dynamodb.Table(self._metrics_table)
        now = datetime.now(timezone.utc).isoformat()

        try:
            table.put_item(
                Item={
                    "project_id": self._project_id,
                    "metric_key": f"{metric_type}#{task_id}#{now}",
                    "metric_type": metric_type,
                    "task_id": task_id,
                    "recorded_at": now,
                    "data": json.dumps(data),
                }
            )
        except ClientError as e:
            logger.warning(
                "Failed to record metric %s for task %s: %s",
                metric_type, task_id, str(e),
            )

    # ─── Helpers ─────────────────────────────────────────────────

    def _get_task_autonomy_level(self, task_id: str) -> int:
        """Get the autonomy level for a task (from task_queue or default)."""
        # Default to L4 (Approver) — the most common factory level
        if not self._metrics_table or not task_id:
            return 4

        table = self._dynamodb.Table(self._metrics_table)
        try:
            response = table.get_item(
                Key={
                    "project_id": self._project_id,
                    "metric_key": "autonomy#current_level",
                }
            )
            if "Item" in response:
                data = json.loads(response["Item"].get("data", "{}"))
                return data.get("level", 4)
        except ClientError:
            pass
        return 4

    def _summarize_feedback(self, event: ReviewFeedbackEvent) -> str:
        """Create a concise summary of the review feedback."""
        body = event.review_body or ""
        # Take first 200 chars as summary
        summary = body[:200].strip()
        if len(body) > 200:
            summary += "..."
        return summary or f"Review state: {event.review_state}"

    def _emit_cloudwatch_metrics(
        self, classification: ReviewClassification, circuit_breaker: bool
    ) -> None:
        """Emit CloudWatch metrics for observability."""
        try:
            metrics = [
                {
                    "MetricName": "ReviewFeedbackProcessed",
                    "Value": 1.0,
                    "Unit": "Count",
                    "Dimensions": [
                        {"Name": "ProjectId", "Value": self._project_id},
                        {"Name": "Classification", "Value": classification.value},
                    ],
                }
            ]

            if classification == ReviewClassification.FULL_REWORK:
                metrics.append({
                    "MetricName": "PRRejectedByHuman",
                    "Value": 1.0,
                    "Unit": "Count",
                    "Dimensions": [
                        {"Name": "ProjectId", "Value": self._project_id},
                    ],
                })

            self._cloudwatch.put_metric_data(
                Namespace="FDE/Factory",
                MetricData=metrics,
            )
        except ClientError as e:
            logger.warning("Failed to emit CloudWatch metrics: %s", str(e))


# ─── Factory Function ────────────────────────────────────────────


def create_review_feedback_event_from_github(
    webhook_payload: dict[str, Any],
    task_id: str = "",
) -> ReviewFeedbackEvent | None:
    """Create a ReviewFeedbackEvent from a GitHub webhook payload.

    Handles both pull_request_review and issue_comment event types.

    Args:
        webhook_payload: Raw GitHub webhook payload (from EventBridge detail).
        task_id: Task ID if known (looked up from task_queue if empty).

    Returns:
        ReviewFeedbackEvent or None if the event is not relevant.
    """
    # pull_request_review event
    review = webhook_payload.get("review", {})
    if review:
        pr = webhook_payload.get("pull_request", {})
        repo = webhook_payload.get("repository", {}).get("full_name", "")

        return ReviewFeedbackEvent(
            review_id=str(review.get("id", "")),
            pr_number=pr.get("number", 0),
            repo=repo,
            reviewer=review.get("user", {}).get("login", ""),
            review_state=review.get("state", ""),
            review_body=review.get("body", "") or "",
            task_id=task_id,
            pr_url=pr.get("html_url", ""),
        )

    # issue_comment on a PR (check if it's a re-work signal)
    comment = webhook_payload.get("comment", {})
    issue = webhook_payload.get("issue", {})
    if comment and issue.get("pull_request"):
        body = comment.get("body", "") or ""
        # Only process if it contains re-work keywords
        body_lower = body.lower()
        has_rework_signal = any(kw in body_lower for kw in _REWORK_KEYWORDS)
        if not has_rework_signal:
            return None

        repo = webhook_payload.get("repository", {}).get("full_name", "")
        return ReviewFeedbackEvent(
            review_id=str(comment.get("id", "")),
            pr_number=issue.get("number", 0),
            repo=repo,
            reviewer=comment.get("user", {}).get("login", ""),
            review_state="commented",
            review_body=body,
            task_id=task_id,
            pr_url=issue.get("pull_request", {}).get("html_url", ""),
        )

    return None
