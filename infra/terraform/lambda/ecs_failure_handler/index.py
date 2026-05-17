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

    # SQS event (DLQ reprocessing) — REL 11
    if "Records" in event:
        return _handle_dlq_reprocess(event)

    if source == "aws.ecs":
        return _handle_ecs_state_change(event)
    elif source == "aws.events" or event.get("detail-type") == "Scheduled Event":
        return _handle_stuck_detection(event)
    else:
        logger.info("Unknown event source: %s", source)
        return {"statusCode": 200, "body": "ignored"}


def _handle_dlq_reprocess(event):
    """Reprocess messages from the dispatch DLQ.

    DLQ messages contain the InputTransformer output that was meant for ECS RunTask.
    The body is the containerOverrides JSON with TASK_ID in the environment array.
    We extract the task_id and re-dispatch via _attempt_redispatch.

    Well-Architected: REL 11 — Design your workload to withstand component failures
    """
    records = event.get("Records", [])
    reprocessed = 0

    for record in records:
        try:
            body = json.loads(record.get("body", "{}"))
            # Extract TASK_ID from containerOverrides
            task_id = None
            for container in body.get("containerOverrides", []):
                for env in container.get("environment", []):
                    if env.get("name") == "TASK_ID" and env.get("value", "").startswith("TASK-"):
                        task_id = env["value"]
                        break

            if not task_id:
                logger.warning("DLQ message has no TASK_ID — skipping: %s", str(body)[:200])
                continue

            logger.info("DLQ reprocessing: task_id=%s", task_id)

            # Check if task is still in a retriable state
            task_item = task_table.get_item(Key={"task_id": task_id}).get("Item", {})
            status = task_item.get("status", "")

            if status in ("COMPLETED", "FAILED", "DEAD_LETTER"):
                logger.info("DLQ: task %s already in terminal state (%s) — skipping", task_id, status)
                continue

            # Re-dispatch using existing retry logic
            _attempt_redispatch(task_id, "DLQ reprocessing: EventBridge target invocation failed")
            reprocessed += 1

        except Exception as e:
            logger.error("DLQ reprocess error: %s", str(e)[:200])

    logger.info("DLQ reprocessing complete: %d/%d records", reprocessed, len(records))
    return {"statusCode": 200, "body": f"reprocessed {reprocessed}/{len(records)}"}


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

        # ── Retry for transient infrastructure failures (EFS mount timeout) ──
        # ECS Fargate has a known race condition where EFS mount attempts happen
        # before ENI has full L3 connectivity. This is transient — retry succeeds.
        # Max 3 retries with exponential backoff via re-dispatch.
        # Ref: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/resource-initialization-error.html
        if stop_code == "TaskFailedToStart":
            _attempt_redispatch(task_id, stopped_reason)
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
    """Periodic check for tasks stuck in early stages — self-heals them.

    Instead of just warning, this now actively heals stuck tasks:
    1. Marks them as FAILED with diagnostic reason
    2. Releases concurrency slot (decrement counter)
    3. Emits a visible event for the portal
    4. Sends alert to operator

    The self-healing reaper in the orchestrator handles auto-retry.
    This Lambda handles the case where NO orchestrator is running
    (because ECS failed to start — the reaper can't run if the container never started).
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=STUCK_THRESHOLD_MINUTES)).isoformat()
    stuck_count = 0
    healed_tasks = []

    for status in ("READY", "IN_PROGRESS"):
        items = task_table.query(
            IndexName="status-created-index",
            KeyConditionExpression=Key("status").eq(status),
        ).get("Items", [])

        for item in items:
            task_id = item.get("task_id", "")
            # Skip CONFIG# and COUNTER# items
            if task_id.startswith("CONFIG#") or task_id.startswith("COUNTER#"):
                continue

            current_stage = item.get("current_stage", "")
            # Only heal tasks stuck in early stages (ECS likely failed to start)
            if current_stage not in ("ingested", "workspace", ""):
                continue

            # Use created_at for staleness (not updated_at which gets refreshed by warnings)
            created_at = item.get("created_at", "")
            if not created_at or created_at > cutoff:
                continue

            # Check if already being warned repeatedly (prevent infinite warnings)
            # If task has been stuck for >10 min, heal it instead of warning again
            stuck_duration = _compute_stuck_minutes(created_at)
            if stuck_duration < STUCK_THRESHOLD_MINUTES:
                continue

            if stuck_duration >= 10:
                # HEAL: mark as failed and release slot
                error_msg = (
                    f"Self-healed by Lambda: stuck in '{current_stage}' for {stuck_duration}min. "
                    f"ECS container never started or crashed before updating DynamoDB."
                )
                try:
                    task_table.update_item(
                        Key={"task_id": task_id},
                        UpdateExpression="SET #s = :status, #e = :error, current_stage = :stage",
                        ExpressionAttributeNames={"#s": "status", "#e": "error"},
                        ExpressionAttributeValues={
                            ":status": "FAILED",
                            ":error": error_msg,
                            ":stage": "failed",
                        },
                    )
                    # Decrement atomic counter
                    repo = item.get("repo", "")
                    if repo:
                        task_table.update_item(
                            Key={"task_id": f"COUNTER#{repo}"},
                            UpdateExpression="ADD active_count :dec",
                            ExpressionAttributeValues={":dec": -1},
                        )
                    healed_tasks.append(task_id)
                    logger.info("Self-healed stuck task %s (stage=%s, age=%dmin)", task_id, current_stage, stuck_duration)
                except Exception as e:
                    logger.error("Failed to heal task %s: %s", task_id, e)
            else:
                # First detection (5-10 min): emit warning only (don't update updated_at)
                _append_event_no_timestamp_update(
                    task_id, "error",
                    f"⚠️ Task stuck in '{current_stage}' for {stuck_duration}min — ECS may have failed to start",
                )

            stuck_count += 1

    if healed_tasks:
        _send_alert(
            subject=f"[{ENVIRONMENT}] Self-healed {len(healed_tasks)} stuck task(s)",
            message=(
                f"Stuck Task Self-Healing\n\n"
                f"Healed {len(healed_tasks)} task(s) stuck in early stages for >{STUCK_THRESHOLD_MINUTES}min.\n"
                f"Tasks: {', '.join(healed_tasks)}\n"
                f"Action: Tasks marked FAILED, concurrency slots released.\n"
                f"Next orchestrator start will auto-retry eligible tasks.\n"
                f"Timestamp: {datetime.now(timezone.utc).isoformat()}\n"
            ),
        )
    elif stuck_count > 0:
        _send_alert(
            subject=f"[{ENVIRONMENT}] {stuck_count} stuck task(s) detected",
            message=(
                f"Stuck Task Detection\n\n"
                f"Found {stuck_count} task(s) stuck in early stages for >{STUCK_THRESHOLD_MINUTES}min.\n"
                f"Will self-heal at 10min threshold.\n"
                f"Timestamp: {datetime.now(timezone.utc).isoformat()}\n"
            ),
        )

    return {"statusCode": 200, "body": f"checked: {stuck_count} stuck, {len(healed_tasks)} healed"}


def _extract_task_id_from_overrides(detail):
    """Try to extract the task_id from ECS task environment overrides.

    Supports two formats:
      1. InputTransformer format (cognitive_router.tf dispatch rules):
         env: TASK_ID=TASK-xxx (direct, no parsing needed)
      2. Legacy format (original ALM rules):
         env: EVENTBRIDGE_EVENT={...} (requires JSON parsing + DynamoDB lookup)
    """
    overrides = detail.get("overrides", {})
    for container in overrides.get("containerOverrides", []):
        for env in container.get("environment", []):
            # Format 1: Direct TASK_ID from InputTransformer (dispatch_distributed rule)
            if env.get("name") == "TASK_ID" and env.get("value", "").startswith("TASK-"):
                return env["value"]

            # Format 2: Legacy EVENTBRIDGE_EVENT (original ALM rules)
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
    # Use specific stage for dispatch failures vs runtime failures (OPS 8)
    stage = "dispatch_failed" if stop_code == "TaskFailedToStart" else "execution_error"
    try:
        task_table.update_item(
            Key={"task_id": task_id},
            UpdateExpression="SET current_stage = :stage, updated_at = :now, ecs_error = :err",
            ExpressionAttributeValues={
                ":stage": stage,
                ":now": datetime.now(timezone.utc).isoformat(),
                ":err": f"{stop_code}: {safe_reason}",
            },
        )
        _append_event(task_id, "error", f"❌ ECS startup failed: {safe_reason}")
        logger.info("Updated task %s with ECS failure (stage=%s)", task_id, stage)
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
                ":evt": [{"ts": datetime.now(timezone.utc).isoformat(), "type": event_type, "msg": message[:500]}],
                ":empty": [],
                ":now": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as e:
        logger.warning("Failed to append event for %s: %s", task_id, e)


def _append_event_no_timestamp_update(task_id, event_type, message):
    """Append an event WITHOUT updating updated_at (prevents staleness clock reset)."""
    try:
        task_table.update_item(
            Key={"task_id": task_id},
            UpdateExpression="SET events = list_append(if_not_exists(events, :empty), :evt)",
            ExpressionAttributeValues={
                ":evt": [{"ts": datetime.now(timezone.utc).isoformat(), "type": event_type, "msg": message[:500]}],
                ":empty": [],
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


# ─── Retry for TaskFailedToStart (EFS mount race condition) ──────────

MAX_INFRA_RETRIES = 3
EVENT_BUS_NAME = os.environ.get("EVENT_BUS_NAME", "fde-dev-factory")
eventbridge = boto3.client("events", region_name=REGION)


def _attempt_redispatch(task_id: str, stopped_reason: str) -> None:
    """Re-dispatch a task that failed due to transient infrastructure errors.

    Only retries for TaskFailedToStart (EFS mount timeout, ENI race, etc.).
    Uses an atomic counter in DynamoDB to track retry attempts.
    Re-emits fde.internal/task.dispatched to trigger the dispatch_distributed rule.

    Well-Architected alignment:
      REL 10: Use fault isolation to protect your workload
      REL 11: Design your workload to withstand component failures
    """
    try:
        # Atomic increment of retry counter
        response = task_table.update_item(
            Key={"task_id": task_id},
            UpdateExpression="SET infra_retry_count = if_not_exists(infra_retry_count, :zero) + :one, "
                           "current_stage = :stage, #s = :status, updated_at = :now",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":zero": 0,
                ":one": 1,
                ":stage": "retrying",
                ":status": "DISPATCHED",
                ":now": datetime.now(timezone.utc).isoformat(),
            },
            ReturnValues="ALL_NEW",
        )

        retry_count = int(response["Attributes"].get("infra_retry_count", 1))
        task_item = response["Attributes"]

        if retry_count > MAX_INFRA_RETRIES:
            logger.warning(
                "Task %s exceeded max infra retries (%d/%d) — marking as FAILED",
                task_id, retry_count, MAX_INFRA_RETRIES,
            )
            task_table.update_item(
                Key={"task_id": task_id},
                UpdateExpression="SET #s = :status, current_stage = :stage, #e = :error",
                ExpressionAttributeNames={"#s": "status", "#e": "error"},
                ExpressionAttributeValues={
                    ":status": "FAILED",
                    ":stage": "failed",
                    ":error": f"Infrastructure failure after {MAX_INFRA_RETRIES} retries: {stopped_reason[:200]}",
                },
            )
            _append_event(
                task_id, "error",
                f"❌ Task failed permanently after {MAX_INFRA_RETRIES} infra retries: {stopped_reason[:100]}",
            )
            return

        # Re-dispatch via EventBridge (same event format as webhook_ingest)
        repo = task_item.get("repo", "")
        issue_id = task_item.get("issue_id", "")
        title = task_item.get("title", "")
        depth = task_item.get("depth", "0.5")

        eventbridge.put_events(
            Entries=[{
                "Source": "fde.internal",
                "DetailType": "task.dispatched",
                "EventBusName": EVENT_BUS_NAME,
                "Detail": json.dumps({
                    "task_id": task_id,
                    "target_mode": "distributed",
                    "depth": str(depth),
                    "repo": repo,
                    "issue_id": issue_id,
                    "title": title,
                    "priority": "normal",
                    "retry_attempt": retry_count,
                }),
            }]
        )

        _append_event(
            task_id, "system",
            f"♻️ Infra retry {retry_count}/{MAX_INFRA_RETRIES}: re-dispatched after TaskFailedToStart "
            f"({stopped_reason[:80]})",
        )

        logger.info(
            "Re-dispatched task %s (retry %d/%d) after TaskFailedToStart",
            task_id, retry_count, MAX_INFRA_RETRIES,
        )

    except Exception as e:
        logger.error("Failed to re-dispatch task %s: %s", task_id, str(e)[:200])
