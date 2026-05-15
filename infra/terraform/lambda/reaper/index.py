"""
Scheduled Reaper Lambda — Self-healing for stuck tasks and counter drift.

Triggered every 5 minutes by CloudWatch Events. Runs independently
of the orchestrator so stuck tasks are healed even when no new events arrive.

Fixes:
  - Pipeline loose end #1 — stuck tasks block concurrency slots indefinitely.
  - Concurrency deadlock — counter drift from ungraceful ECS stops blocks all queued tasks.
"""
import json
import logging
import os
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger("fde.reaper")
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ.get("TASK_QUEUE_TABLE", "fde-dev-task-queue")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")


def _get_table():
    return boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)


def _now():
    return datetime.now(timezone.utc).isoformat()


def handler(event, context):
    """CloudWatch Events scheduled handler."""
    logger.info("Reaper triggered (scheduled)")

    table = _get_table()

    # Phase 1: Reap stuck tasks
    reaped = _reap_stuck_tasks(table)

    # Phase 2: Reconcile concurrency counters
    drift_fixes = _reconcile_counters(table)

    # Phase 3: Unblock queued tasks
    repos_freed = set()
    for task_id in reaped:
        item = table.get_item(Key={"task_id": task_id}).get("Item", {})
        repo = item.get("repo", "")
        if repo:
            repos_freed.add(repo)

    for repo in drift_fixes:
        repos_freed.add(repo)

    retried = []
    for repo in repos_freed:
        eligible = _retry_queued_tasks(table, repo)
        retried.extend(eligible)

    result = {
        "reaped_count": len(reaped),
        "reaped_task_ids": reaped,
        "counter_drift_fixes": drift_fixes,
        "repos_freed": list(repos_freed),
        "retried_task_ids": retried,
    }

    if reaped or drift_fixes:
        logger.warning("Reaper healed: reaped=%d, drift_fixes=%d, retried=%d",
                       len(reaped), len(drift_fixes), len(retried))
    else:
        logger.info("Reaper: no stuck tasks or counter drift found")

    return result


def _reap_stuck_tasks(table) -> list:
    """Detect and heal tasks stuck in non-terminal states."""
    reaped = []
    now = datetime.now(timezone.utc)

    early_stages = {"ingested", "workspace", "reconnaissance", "intake"}
    early_threshold_minutes = 10
    late_threshold_minutes = 60

    for status in ("IN_PROGRESS", "RUNNING", "READY"):
        items = table.query(
            IndexName="status-created-index",
            KeyConditionExpression=Key("status").eq(status),
        ).get("Items", [])

        for item in items:
            task_id = item.get("task_id", "")
            if task_id.startswith("CONFIG#") or task_id.startswith("COUNTER#"):
                continue

            updated_at = item.get("updated_at", "")
            if not updated_at:
                continue
            try:
                updated_ts = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue

            age_minutes = (now - updated_ts).total_seconds() / 60
            current_stage = item.get("current_stage", "unknown")
            is_early = current_stage in early_stages
            threshold = early_threshold_minutes if is_early else late_threshold_minutes

            if age_minutes < threshold:
                continue

            repo = item.get("repo", "")
            error_msg = (
                f"Self-healed: stuck in '{current_stage}' for {int(age_minutes)}min "
                f"(threshold: {threshold}min). "
                f"{'Auto-retry eligible.' if is_early else 'Permanent failure.'}"
            )

            table.update_item(
                Key={"task_id": task_id},
                UpdateExpression="SET #s = :status, #e = :error, updated_at = :now",
                ExpressionAttributeNames={"#s": "status", "#e": "error"},
                ExpressionAttributeValues={
                    ":status": "FAILED",
                    ":error": error_msg,
                    ":now": _now(),
                },
            )

            if repo:
                _decrement_counter(table, repo)

            reaped.append(task_id)
            logger.warning("Reaped: %s (stage=%s, age=%.0fmin)", task_id, current_stage, age_minutes)

    return reaped


def _reconcile_counters(table) -> dict:
    """Fix counter drift from ungraceful ECS stops."""
    fixes = {}

    response = table.scan(
        FilterExpression="begins_with(task_id, :prefix)",
        ExpressionAttributeValues={":prefix": "COUNTER#"},
    )

    for item in response.get("Items", []):
        task_id_key = item.get("task_id", "")
        repo = task_id_key.replace("COUNTER#", "")
        counter_value = int(item.get("active_count", 0))

        if counter_value <= 0:
            continue

        actual_active = 0
        for status in ("IN_PROGRESS", "RUNNING"):
            items = table.query(
                IndexName="status-created-index",
                KeyConditionExpression=Key("status").eq(status),
            ).get("Items", [])
            actual_active += sum(1 for t in items if t.get("repo") == repo)

        if counter_value > actual_active:
            logger.warning(
                "Counter drift: repo=%s counter=%d actual=%d -> correcting",
                repo, counter_value, actual_active,
            )
            table.update_item(
                Key={"task_id": f"COUNTER#{repo}"},
                UpdateExpression="SET active_count = :actual, updated_at = :now",
                ExpressionAttributeValues={":actual": actual_active, ":now": _now()},
            )
            fixes[repo] = {"counter_was": counter_value, "corrected_to": actual_active}

    return fixes


def _retry_queued_tasks(table, repo: str) -> list:
    """Find tasks blocked by concurrency that can now proceed."""
    eligible = []
    ready_items = table.query(
        IndexName="status-created-index",
        KeyConditionExpression=Key("status").eq("READY"),
    ).get("Items", [])

    for item in ready_items:
        if item.get("repo") == repo and item.get("current_stage") == "ingested":
            eligible.append(item["task_id"])
            logger.info("Unblocked: %s (repo=%s)", item["task_id"], repo)

    return eligible


def _decrement_counter(table, repo: str):
    """Atomically decrement counter, clamped to 0."""
    try:
        table.update_item(
            Key={"task_id": f"COUNTER#{repo}"},
            UpdateExpression="ADD active_count :dec SET updated_at = :now",
            ConditionExpression="active_count > :zero",
            ExpressionAttributeValues={":dec": -1, ":now": _now(), ":zero": 0},
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        pass
