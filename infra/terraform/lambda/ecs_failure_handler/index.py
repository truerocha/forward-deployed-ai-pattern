"""
ECS Failure Handler — Detects ECS task failures and updates DynamoDB + alerts.

Triggered by:
  1. EventBridge ECS Task State Change (STOPPED with error)
  2. CloudWatch Events scheduled rule (every 5 min) for stuck task detection

This closes the observability gap between "webhook received" and "agent starts":
  - If ECS task fails to start (CannotPullContainer, resource exhaustion, etc.)
  - If ECS task is stuck in PENDING for >5 minutes
  - If ECS task exits with non-zero code

Actions:
  - Updates DynamoDB task_queue with error status and reason
  - Emits task_event so the portal shows the failure
  - Publishes to SNS for operator notification

Well-Architected alignment:
  OPS 6: Telemetry for ECS task lifecycle failures
  OPS 8: Automated response to infrastructure failures
  REL 11: Fault detection and notification
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TASK_QUEUE_TABLE = os.environ.get("TASK_QUEUE_TABLE", "fde-dev-task-queue")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")
REGION = os.environ.get("AWS_REGION", "us-east-1")
STUCK_THRESHOLD_MINUTES = int(os.environ.get("STUCK_THRESHOLD_MINUTES", "5"))

dynamodb = boto3.resource("dynamodb", region_name=REGION)
task_table = dynamodb.Table(TASK_QUEUE_TABLE)
sns = boto3.client("sns", region_name=REGION)


def handler(event, context):
    """Route to appropriate handler based on event source."""
    source = event.get("source", "")

    if source == "aws.ecs":
        return _handle_ecs_state_change(event)
    elif source == "aws.events" or event.get("detail-type") == "Scheduled Event":
        return _handle_stuck_detection(event)
    else:
        logger.info("Unknown event source: %s", source)
        return {"statusCode": 200, "body": "ignored"}


def _handle_ecs_state_change(event):
    """Handle ECS Task State Change — detect failures."""
    detail = event.get("detail", {})
    last_status = detail.get("lastStatus", "")
    stopped_reason = detail.get("stoppedReason", "")
    stop_code = detail.get("stopCode", "")
    task_def_arn = detail.get("taskDefinitionArn", "")

    if last_status != "STOPPED":
        return {"statusCode": 200, "body": "not stopped"}

    # Check container exit codes — exit 0 is a successful completion, not a failure.
    # ECS reports "EssentialContainerExited" for ALL container exits (success or failure).
    # For batch/task workloads, exit 0 is the expected success signal.
    containers = detail.get("containers", [])
    exit_codes = [c.get("exitCode") for c in containers if c.get("exitCode") is not None]
    essential_exit_code = next(
        (c.get("exitCode") for c in containers if c.get("name") in ("strands-agent", "orchestrator")),
        None,
    )

    # Exit code 0 on the main container = successful task completion (not a failure)
    if essential_exit_code == 0:
        logger.info(
            "ECS task completed successfully (exit code 0): stopCode=%s taskDef=%s",
            stop_code, task_def_arn,
        )
        return {"statusCode": 200, "body": "successful_completion"}

    if not stopped_reason and stop_code != "TaskFailedToStart":
        return {"statusCode": 200, "body": "normal stop"}

    logger.warning(
        "ECS task failed: stopCode=%s reason=%s taskDef=%s",
        stop_code, stopped_reason[:200], task_def_arn,
    )

    task_id = _extract_task_id_from_overrides(detail)

    if task_id:
        _update_task_with_failure(task_id, stopped_reason, stop_code)
    else:
        _mark_stuck_tasks_as_failed(stopped_reason)

    _send_alert(
        subject=f"[{ENVIRONMENT}] ECS Task Failed: {stop_code}",
        message=(
            f"ECS Task Failed to Start\n\n"
            f"Stop Code: {stop_code}\n"
            f"Reason: {stopped_reason[:500]}\n"
            f"Task Definition: {task_def_arn}\n"
            f"Task ID (DynamoDB): {task_id or 'unknown'}\n"
            f"Timestamp: {datetime.now(timezone.utc).isoformat()}\n"
        ),
    )

    return {"statusCode": 200, "body": "failure handled"}


def _handle_stuck_detection(event):
    """Periodic check for tasks stuck in early stages."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=STUCK_THRESHOLD_MINUTES)).isoformat()
    stuck_count = 0

    for status in ("READY", "IN_PROGRESS"):
        items = task_table.query(
            IndexName="status-created-index",
            KeyConditionExpression=Key("status").eq(status),
        ).get("Items", [])

        for item in items:
            current_stage = item.get("current_stage", "")
            updated_at = item.get("updated_at", item.get("created_at", ""))

            if current_stage not in ("ingested", "workspace", ""):
                continue

            if updated_at and updated_at < cutoff:
                task_id = item["task_id"]
                stuck_duration = _compute_stuck_minutes(updated_at)

                logger.warning(
                    "Stuck task detected: %s (stage=%s, stuck=%dmin)",
                    task_id, current_stage, stuck_duration,
                )

                _append_event(
                    task_id, "error",
                    f"⚠️ Task stuck in '{current_stage}' for {stuck_duration}min — ECS may have failed to start",
                )
                stuck_count += 1

    if stuck_count > 0:
        _send_alert(
            subject=f"[{ENVIRONMENT}] {stuck_count} stuck task(s) detected",
            message=(
                f"Stuck Task Detection\n\n"
                f"Found {stuck_count} task(s) stuck in early stages for >{STUCK_THRESHOLD_MINUTES}min.\n"
                f"This usually means the ECS container failed to start.\n\n"
                f"Action: Check ECS task status and CloudWatch logs.\n"
                f"Timestamp: {datetime.now(timezone.utc).isoformat()}\n"
            ),
        )

    return {"statusCode": 200, "body": f"checked: {stuck_count} stuck"}


def _extract_task_id_from_overrides(detail):
    """Try to extract the task_id from ECS task environment overrides."""
    overrides = detail.get("overrides", {})
    for container in overrides.get("containerOverrides", []):
        for env in container.get("environment", []):
            if env.get("name") == "EVENTBRIDGE_EVENT":
                try:
                    event_data = json.loads(env.get("value", "{}"))
                    issue = event_data.get("detail", {}).get("issue", {})
                    repo = event_data.get("detail", {}).get("repository", {}).get("full_name", "")
                    issue_num = issue.get("number", 0)
                    if repo and issue_num:
                        issue_id = f"{repo}#{issue_num}"
                        items = task_table.query(
                            IndexName="status-created-index",
                            KeyConditionExpression=Key("status").eq("READY"),
                        ).get("Items", [])
                        for item in items:
                            if item.get("issue_id") == issue_id:
                                return item["task_id"]
                except (json.JSONDecodeError, KeyError):
                    pass
    return None


def _update_task_with_failure(task_id, reason, stop_code):
    """Update a DynamoDB task with the ECS failure information."""
    safe_reason = reason[:200] if reason else "Unknown ECS failure"
    try:
        task_table.update_item(
            Key={"task_id": task_id},
            UpdateExpression="SET current_stage = :stage, updated_at = :now, ecs_error = :err",
            ExpressionAttributeValues={
                ":stage": "failed",
                ":now": datetime.now(timezone.utc).isoformat(),
                ":err": f"{stop_code}: {safe_reason}",
            },
        )
        _append_event(task_id, "error", f"❌ ECS startup failed: {safe_reason}")
        logger.info("Updated task %s with ECS failure", task_id)
    except Exception as e:
        logger.error("Failed to update task %s: %s", task_id, e)


def _mark_stuck_tasks_as_failed(reason):
    """Mark any tasks stuck in 'ingested' as failed (best-effort correlation)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    items = task_table.query(
        IndexName="status-created-index",
        KeyConditionExpression=Key("status").eq("READY"),
    ).get("Items", [])

    for item in items:
        if item.get("current_stage") == "ingested" and item.get("updated_at", "") < cutoff:
            _update_task_with_failure(item["task_id"], reason, "TaskFailedToStart")
            break


def _append_event(task_id, event_type, message):
    """Append an event to the task's events list."""
    try:
        task_table.update_item(
            Key={"task_id": task_id},
            UpdateExpression="SET events = list_append(if_not_exists(events, :empty), :evt), updated_at = :now",
            ExpressionAttributeValues={
                ":evt": [{"ts": datetime.now(timezone.utc).isoformat(), "type": event_type, "msg": message[:200]}],
                ":empty": [],
                ":now": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as e:
        logger.warning("Failed to append event for %s: %s", task_id, e)


def _send_alert(subject, message):
    """Send alert via SNS (if configured)."""
    if not SNS_TOPIC_ARN:
        logger.info("SNS not configured — alert skipped: %s", subject)
        return
    try:
        sns.publish(TopicArn=SNS_TOPIC_ARN, Subject=subject[:100], Message=message)
        logger.info("Alert sent: %s", subject)
    except Exception as e:
        logger.error("Failed to send alert: %s", e)


def _compute_stuck_minutes(updated_at):
    """Compute how many minutes a task has been stuck."""
    try:
        updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        return int((datetime.now(timezone.utc) - updated).total_seconds() / 60)
    except (ValueError, TypeError):
        return 0
