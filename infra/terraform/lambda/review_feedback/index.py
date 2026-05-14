"""
Review Feedback Lambda — Processes PR review events from EventBridge.

This Lambda is triggered by EventBridge when a PR review event arrives
(changes_requested, commented with re-work signal, or approved).

Flow:
  GitHub PR Review → API Gateway → EventBridge → [this Lambda]
    → Classifies review
    → Records metrics (DORA CFR, Trust, Verification, Happy Time)
    → Updates Risk Engine weights (false negative learning)
    → Emits rework event (if full_rework + circuit breaker allows)

Architecture alignment:
  - Second target on the review feedback EventBridge rule
  - Parallel to webhook_ingest (which updates task_queue status)
  - Decoupled from ECS execution (Lambda for speed, ECS for re-execution)

Well-Architected:
  OPS 6: Every review event classified and tracked
  REL 2: Decoupled from execution path
  SEC 8: Review rejections treated as quality incidents
  COST 5: Lambda pay-per-invocation (~$0.50/month at expected volume)

Ref: docs/adr/ADR-027-review-feedback-loop.md
"""

import json
import logging
import os
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment
METRICS_TABLE = os.environ.get("METRICS_TABLE", "fde-dev-metrics")
TASK_QUEUE_TABLE = os.environ.get("TASK_QUEUE_TABLE", "fde-dev-task-queue")
EVENT_BUS_NAME = os.environ.get("EVENT_BUS_NAME", "fde-dev-factory-bus")
PROJECT_ID = os.environ.get("PROJECT_ID", "global")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")

dynamodb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
eventbridge = boto3.client("events", region_name=os.environ.get("AWS_REGION", "us-east-1"))
cloudwatch = boto3.client("cloudwatch", region_name=os.environ.get("AWS_REGION", "us-east-1"))

# Re-work signal keywords (case-insensitive)
REWORK_KEYWORDS = [
    "re-work", "rework", "redo", "start over", "sent back",
    "fundamentally wrong", "wrong approach", "rewrite",
    "not acceptable", "reject", "major issues", "unsafe",
    "security concern", "breaks", "regression",
]

MAX_REWORK_ATTEMPTS = 2
REWORK_ESTIMATE_SECONDS = 1800  # 30 min


def handler(event, context):
    """Process PR review events from EventBridge.

    EventBridge delivers:
    {
        "source": "fde.github.webhook",
        "detail-type": "pull_request_review.submitted" | "issue_comment.created",
        "detail": { ...GitHub webhook payload... }
    }
    """
    source = event.get("source", "")
    detail_type = event.get("detail-type", "")
    detail = event.get("detail", {})

    logger.info(
        "Review feedback Lambda invoked: source=%s detail-type=%s",
        source, detail_type,
    )

    # Only process GitHub review events
    if "fde.github" not in source:
        logger.info("Non-GitHub source — skipping: %s", source)
        return {"statusCode": 200, "body": "skipped"}

    # Extract review information
    review_event = _extract_review_event(detail_type, detail)
    if not review_event:
        logger.info("Event did not produce a review event (filtered)")
        return {"statusCode": 200, "body": "filtered"}

    # Resolve task_id from PR (lookup in task_queue)
    task_id = _resolve_task_id(review_event["repo"], review_event["pr_number"])
    review_event["task_id"] = task_id

    if not task_id:
        logger.warning(
            "Could not resolve task_id for PR %s/#%d — recording metrics without task correlation",
            review_event["repo"], review_event["pr_number"],
        )

    # Classify the review
    classification = _classify_review(review_event)
    logger.info(
        "Review classified: classification=%s pr=%s/#%d reviewer=%s",
        classification, review_event["repo"], review_event["pr_number"],
        review_event["reviewer"],
    )

    # Idempotency check
    idempotency_key = f"{task_id}#{review_event['repo']}#{review_event['pr_number']}#{review_event['review_id']}"
    if _already_processed(idempotency_key, task_id, review_event["review_id"]):
        logger.info("Already processed (idempotent skip): %s", idempotency_key)
        return {"statusCode": 200, "body": "duplicate_skipped"}

    # Process based on classification
    result = {"classification": classification, "actions": []}

    if classification in ("full_rework", "partial_fix"):
        _record_rejection_metrics(review_event, classification, task_id)
        result["actions"].append("metrics_recorded")

        # P0b (ADR-030): Store rejection as repo constraint for cognitive memory.
        # Next task on this repo will see this constraint at intake time.
        _store_repo_constraint(review_event, classification, task_id)
        result["actions"].append("repo_constraint_stored")

        # Update task_queue status to REWORK
        if task_id:
            _update_task_status(task_id, "REWORK", review_event)
            result["actions"].append("task_status_updated")

    if classification == "full_rework":
        # Record risk weight update signal
        _record_risk_weight_signal(review_event, task_id)
        result["actions"].append("risk_weight_signal")

        # Check circuit breaker and emit rework event
        rework_count = _get_rework_count(task_id)
        if rework_count < MAX_REWORK_ATTEMPTS:
            _emit_rework_event(review_event, task_id, rework_count + 1)
            result["actions"].append(f"rework_triggered_attempt_{rework_count + 1}")
        else:
            _emit_circuit_breaker_alert(task_id, review_event, rework_count)
            result["actions"].append("circuit_breaker_tripped")

    if classification == "approval":
        _record_approval_metrics(review_event, task_id)
        result["actions"].append("approval_recorded")

        if task_id:
            _update_task_status(task_id, "APPROVED", review_event)
            result["actions"].append("task_approved")

    # Persist processing record
    _persist_record(review_event, classification, task_id, result)

    logger.info("Review feedback processed: %s", json.dumps(result))
    return {"statusCode": 200, "body": json.dumps(result)}


# ─── Event Extraction ────────────────────────────────────────────


def _extract_review_event(detail_type: str, detail: dict) -> dict | None:
    """Extract structured review event from webhook payload."""

    if detail_type == "pull_request_review.submitted":
        review = detail.get("review", {})
        pr = detail.get("pull_request", {})
        repo = detail.get("repository", {}).get("full_name", "")

        state = review.get("state", "")
        # Only process changes_requested, commented, approved
        if state not in ("changes_requested", "commented", "approved", "dismissed"):
            return None

        return {
            "review_id": str(review.get("id", "")),
            "pr_number": pr.get("number", 0),
            "repo": repo,
            "reviewer": review.get("user", {}).get("login", ""),
            "review_state": state,
            "review_body": review.get("body", "") or "",
            "pr_url": pr.get("html_url", ""),
            "files_commented": [],
        }

    if detail_type == "issue_comment.created":
        comment = detail.get("comment", {})
        issue = detail.get("issue", {})

        # Only process comments on PRs (not regular issues)
        if not issue.get("pull_request"):
            return None

        body = comment.get("body", "") or ""
        # Only process if it contains re-work keywords
        body_lower = body.lower()
        has_signal = any(kw in body_lower for kw in REWORK_KEYWORDS)
        if not has_signal:
            return None

        repo = detail.get("repository", {}).get("full_name", "")
        return {
            "review_id": str(comment.get("id", "")),
            "pr_number": issue.get("number", 0),
            "repo": repo,
            "reviewer": comment.get("user", {}).get("login", ""),
            "review_state": "commented",
            "review_body": body,
            "pr_url": issue.get("pull_request", {}).get("html_url", ""),
            "files_commented": [],
        }

    return None


# ─── Classification ──────────────────────────────────────────────


def _classify_review(review_event: dict) -> str:
    """Classify review into: full_rework, partial_fix, informational, approval, dismissed."""
    state = review_event.get("review_state", "")

    if state == "approved":
        return "approval"
    if state == "dismissed":
        return "dismissed"

    body = (review_event.get("review_body", "") or "").lower()

    if state == "changes_requested":
        # changes_requested is always at least partial_fix
        rework_score = sum(1 for kw in REWORK_KEYWORDS if kw in body)
        if rework_score >= 1:
            return "full_rework"
        return "partial_fix"

    # For comments, check content
    rework_score = sum(1 for kw in REWORK_KEYWORDS if kw in body)
    if rework_score >= 2:
        return "full_rework"
    if rework_score >= 1:
        return "partial_fix"

    return "informational"


# ─── Task Resolution ─────────────────────────────────────────────


def _resolve_task_id(repo: str, pr_number: int) -> str:
    """Resolve task_id from task_queue by matching repo and PR number."""
    if not repo or not pr_number:
        return ""

    try:
        table = dynamodb.Table(TASK_QUEUE_TABLE)
        response = table.scan(
            FilterExpression="repo = :repo",
            ExpressionAttributeValues={":repo": repo},
            Limit=20,
        )

        for item in response.get("Items", []):
            result = item.get("result", "")
            if f"#{pr_number}" in result or f"/{pr_number}" in result:
                return item.get("task_id", "")
            issue_id = item.get("issue_id", "")
            if issue_id and repo in issue_id:
                return item.get("task_id", "")

        return ""
    except Exception as e:
        logger.warning("Failed to resolve task_id: %s", e)
        return ""


# ─── Metrics Recording ───────────────────────────────────────────


def _record_rejection_metrics(review_event: dict, classification: str, task_id: str) -> None:
    """Record rejection metrics across DORA, Trust, Verification, Happy Time."""
    table = dynamodb.Table(METRICS_TABLE)
    now = datetime.now(timezone.utc).isoformat()

    metrics = [
        # DORA CFR: PR rejection = change failure
        {
            "metric_key": f"dora_change_fail_rate#L4#{now}",
            "metric_type": "dora_change_fail_rate",
            "data": json.dumps({
                "metric": "change_fail_rate",
                "autonomy_level": 4,
                "value": 1.0,
                "unit": "boolean",
                "source": "human_review_rejection",
                "classification": classification,
                "metadata": {"is_failure": True, "reviewer": review_event["reviewer"]},
            }),
        },
        # Trust: PR rejected
        {
            "metric_key": f"trust#pr_outcome#{now}",
            "metric_type": "trust",
            "data": json.dumps({
                "event_type": "pr_outcome",
                "accepted": False,
                "reviewer": review_event["reviewer"],
                "classification": classification,
            }),
        },
        # Verification: Review completed with rejection
        {
            "metric_key": f"verification#pr_rejected#{now}",
            "metric_type": "verification",
            "data": json.dumps({
                "event_type": "pr_rejected",
                "pr_identifier": f"{review_event['repo']}#{review_event['pr_number']}",
                "timestamp": now,
                "metadata": {"accepted": False, "reviewer": review_event["reviewer"]},
            }),
        },
        # Happy Time: Rework toil
        {
            "metric_key": f"happy_time#{task_id}#{now}#rework",
            "metric_type": "happy_time",
            "data": json.dumps({
                "task_id": task_id,
                "category": "rework",
                "duration_seconds": REWORK_ESTIMATE_SECONDS,
                "is_creative": False,
                "timestamp": now,
                "metadata": {
                    "reason": f"PR review rejection: {classification}",
                    "reviewer": review_event["reviewer"],
                },
            }),
        },
    ]

    for metric in metrics:
        try:
            table.put_item(Item={
                "project_id": PROJECT_ID,
                "task_id": task_id,
                "recorded_at": now,
                **metric,
            })
        except Exception as e:
            logger.warning("Failed to record metric %s: %s", metric["metric_type"], e)


def _store_repo_constraint(review_event: dict, classification: str, task_id: str) -> None:
    """Store PR rejection as a structured repo constraint in the metrics table.

    P0b (ADR-030 Cognitive Memory): When a PR is rejected, the rejection
    feedback becomes a CONSTRAINT that is injected into all future tasks
    for the same repo. This prevents the factory from repeating the same
    mistake (e.g., submitting PRs without running generators first).

    Constraint schema:
      project_id: repo (e.g., "truerocha/cognitive-wafr")
      memory_key: "constraint#repo_prerequisite#{timestamp}"
      constraint_type: "repo_prerequisite" | "ci_gate" | "review_feedback"
      constraint_text: The actionable instruction for agents
      source_task: Which task triggered this constraint
      source_pr: Which PR was rejected
      reviewer: Who rejected it
      expires_when: Condition for automatic expiry (e.g., "issue #130 closed")
      active: True (set to False when resolved)

    The orchestrator reads these at intake time and injects them into the
    constraint pipeline alongside task-specific constraints.
    """
    table = dynamodb.Table(METRICS_TABLE)
    now = datetime.now(timezone.utc).isoformat()
    repo = review_event.get("repo", "")

    if not repo:
        return

    # Extract the actionable constraint from the review body
    review_body = review_event.get("body", "")
    constraint_text = _extract_constraint_from_review(review_body, classification)

    if not constraint_text:
        logger.info("No actionable constraint extracted from review — skipping storage")
        return

    try:
        table.put_item(Item={
            "project_id": repo,
            "metric_key": f"constraint#repo_prerequisite#{now}",
            "metric_type": "repo_constraint",
            "task_id": task_id or "unknown",
            "recorded_at": now,
            "data": json.dumps({
                "constraint_type": "repo_prerequisite",
                "constraint_text": constraint_text,
                "source_task": task_id,
                "source_pr": f"{repo}#{review_event.get('pr_number', '')}",
                "reviewer": review_event.get("reviewer", ""),
                "classification": classification,
                "active": True,
                "created_at": now,
            }),
        })
        logger.info(
            "Repo constraint stored: repo=%s type=repo_prerequisite source_pr=#%s",
            repo, review_event.get("pr_number", ""),
        )
    except Exception as e:
        logger.warning("Failed to store repo constraint: %s", e)


def _extract_constraint_from_review(review_body: str, classification: str) -> str:
    """Extract actionable constraint text from a PR review body.

    Looks for structured sections in the review:
      - "### What Is Missing" → becomes the constraint
      - "### Halting Condition" → becomes the acceptance criteria
      - Bullet points after "must" keywords

    Returns a concise constraint string for agent injection, or empty string
    if no actionable constraint can be extracted.
    """
    if not review_body:
        return ""

    lines = review_body.split("\n")
    constraint_parts = []
    in_missing_section = False
    in_halting_section = False

    for line in lines:
        stripped = line.strip()

        # Detect section headers
        if "what is missing" in stripped.lower() or "must add" in stripped.lower():
            in_missing_section = True
            in_halting_section = False
            continue
        elif "halting condition" in stripped.lower():
            in_halting_section = True
            in_missing_section = False
            continue
        elif stripped.startswith("### ") or stripped.startswith("## "):
            in_missing_section = False
            in_halting_section = False
            continue

        # Collect content from relevant sections
        if in_missing_section and stripped:
            constraint_parts.append(stripped)
        elif in_halting_section and stripped:
            constraint_parts.append(f"[HALT] {stripped}")

    if constraint_parts:
        return "\n".join(constraint_parts[:15])  # Cap at 15 lines

    # Fallback: extract lines with "must" or numbered requirements
    must_lines = [
        line.strip() for line in lines
        if any(kw in line.lower() for kw in ["must", "required", "need to", "should"])
        and len(line.strip()) > 10
    ]
    if must_lines:
        return "\n".join(must_lines[:10])

    return ""


def _record_approval_metrics(review_event: dict, task_id: str) -> None:
    """Record positive PR outcome metrics."""
    table = dynamodb.Table(METRICS_TABLE)
    now = datetime.now(timezone.utc).isoformat()

    metrics = [
        {
            "metric_key": f"trust#pr_outcome#{now}",
            "metric_type": "trust",
            "data": json.dumps({
                "event_type": "pr_outcome",
                "accepted": True,
                "reviewer": review_event["reviewer"],
            }),
        },
        {
            "metric_key": f"dora_change_fail_rate#L4#{now}",
            "metric_type": "dora_change_fail_rate",
            "data": json.dumps({
                "metric": "change_fail_rate",
                "autonomy_level": 4,
                "value": 0.0,
                "unit": "boolean",
                "source": "human_review_approval",
                "metadata": {"is_failure": False, "reviewer": review_event["reviewer"]},
            }),
        },
    ]

    for metric in metrics:
        try:
            table.put_item(Item={
                "project_id": PROJECT_ID,
                "task_id": task_id,
                "recorded_at": now,
                **metric,
            })
        except Exception as e:
            logger.warning("Failed to record approval metric: %s", e)


def _record_risk_weight_signal(review_event: dict, task_id: str) -> None:
    """Record signal for Risk Engine weight update (false negative)."""
    table = dynamodb.Table(METRICS_TABLE)
    now = datetime.now(timezone.utc).isoformat()

    try:
        table.put_item(Item={
            "project_id": PROJECT_ID,
            "metric_key": f"risk_weight_update#{task_id}#{now}",
            "metric_type": "risk_weight_update",
            "task_id": task_id,
            "recorded_at": now,
            "data": json.dumps({
                "actual_outcome": "failed",
                "source": "human_review_rejection",
                "reviewer": review_event["reviewer"],
                "pr_number": review_event["pr_number"],
                "repo": review_event["repo"],
                "feedback_summary": (review_event.get("review_body", "") or "")[:200],
            }),
        })
    except Exception as e:
        logger.warning("Failed to record risk weight signal: %s", e)


# ─── Task Queue Updates ──────────────────────────────────────────


def _update_task_status(task_id: str, status: str, review_event: dict) -> None:
    """Update task_queue status to REWORK or APPROVED."""
    try:
        table = dynamodb.Table(TASK_QUEUE_TABLE)
        now = datetime.now(timezone.utc).isoformat()

        table.update_item(
            Key={"task_id": task_id},
            UpdateExpression=(
                "SET #s = :status, updated_at = :now, "
                "current_stage = :stage, result = :result"
            ),
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":status": status,
                ":now": now,
                ":stage": "rework" if status == "REWORK" else "approved",
                ":result": (
                    f"Review by {review_event['reviewer']}: {status}. "
                    f"{(review_event.get('review_body', '') or '')[:100]}"
                ),
            },
        )
        logger.info("Task %s status updated to %s", task_id, status)
    except Exception as e:
        logger.warning("Failed to update task status: %s", e)


# ─── Rework Event Emission ───────────────────────────────────────


def _emit_rework_event(review_event: dict, task_id: str, attempt: int) -> None:
    """Emit EventBridge event to re-trigger pipeline with feedback context."""
    detail = {
        "task_id": task_id,
        "repo": review_event["repo"],
        "pr_number": review_event["pr_number"],
        "review_feedback": (review_event.get("review_body", "") or "")[:2000],
        "files_to_fix": review_event.get("files_commented", []),
        "rework_attempt": attempt,
        "reviewer": review_event["reviewer"],
        "original_pr_url": review_event.get("pr_url", ""),
        "constraint": (
            f"REWORK CONSTRAINT (attempt {attempt}/{MAX_REWORK_ATTEMPTS}): "
            f"Previous PR was rejected by {review_event['reviewer']}. "
            f"Feedback: {(review_event.get('review_body', '') or '')[:500]}. "
            f"Do NOT repeat the same approach that was rejected."
        ),
    }

    try:
        eventbridge.put_events(Entries=[{
            "Source": "fde.internal",
            "DetailType": "task.rework_requested",
            "Detail": json.dumps(detail),
            "EventBusName": EVENT_BUS_NAME,
        }])
        logger.info("Rework event emitted: task=%s attempt=%d", task_id, attempt)
    except Exception as e:
        logger.error("Failed to emit rework event: %s", e)


# ─── Circuit Breaker ─────────────────────────────────────────────


def _get_rework_count(task_id: str) -> int:
    """Get number of previous rework attempts for this task."""
    if not task_id:
        return 0

    try:
        table = dynamodb.Table(METRICS_TABLE)
        response = table.query(
            KeyConditionExpression=(
                "project_id = :pid AND begins_with(metric_key, :prefix)"
            ),
            ExpressionAttributeValues={
                ":pid": PROJECT_ID,
                ":prefix": f"review_feedback#{task_id}#",
            },
        )
        count = 0
        for item in response.get("Items", []):
            data = json.loads(item.get("data", "{}"))
            if data.get("rework_triggered"):
                count += 1
        return count
    except Exception as e:
        logger.warning("Failed to get rework count: %s", e)
        return 0


def _emit_circuit_breaker_alert(task_id: str, review_event: dict, count: int) -> None:
    """Emit CloudWatch alert when circuit breaker trips."""
    try:
        cloudwatch.put_metric_data(
            Namespace="FDE/Factory",
            MetricData=[{
                "MetricName": "ReworkCircuitBreakerTripped",
                "Value": 1.0,
                "Unit": "Count",
                "Dimensions": [
                    {"Name": "ProjectId", "Value": PROJECT_ID},
                    {"Name": "TaskId", "Value": task_id},
                ],
            }],
        )
    except Exception as e:
        logger.warning("Failed to emit circuit breaker alert: %s", e)

    logger.error(
        "CIRCUIT BREAKER: Task %s failed %d rework attempts. "
        "Escalating to Staff Engineer. PR: %s/#%d",
        task_id, count, review_event["repo"], review_event["pr_number"],
    )


# ─── Idempotency & Persistence ───────────────────────────────────


def _already_processed(idempotency_key: str, task_id: str, review_id: str) -> bool:
    """Check if this review was already processed."""
    if not task_id:
        return False

    try:
        table = dynamodb.Table(METRICS_TABLE)
        response = table.get_item(Key={
            "project_id": PROJECT_ID,
            "metric_key": f"review_feedback#{task_id}#{review_id}",
        })
        return "Item" in response
    except Exception:
        return False


def _persist_record(review_event: dict, classification: str, task_id: str, result: dict) -> None:
    """Persist processing record for audit and idempotency."""
    try:
        table = dynamodb.Table(METRICS_TABLE)
        now = datetime.now(timezone.utc).isoformat()

        rework_triggered = any("rework_triggered" in a for a in result.get("actions", []))

        table.put_item(Item={
            "project_id": PROJECT_ID,
            "metric_key": f"review_feedback#{task_id}#{review_event['review_id']}",
            "metric_type": "review_feedback",
            "task_id": task_id,
            "recorded_at": now,
            "data": json.dumps({
                "review_id": review_event["review_id"],
                "pr_number": review_event["pr_number"],
                "repo": review_event["repo"],
                "reviewer": review_event["reviewer"],
                "review_state": review_event["review_state"],
                "classification": classification,
                "rework_triggered": rework_triggered,
                "actions": result.get("actions", []),
            }),
        })
    except Exception as e:
        logger.warning("Failed to persist review feedback record: %s", e)
