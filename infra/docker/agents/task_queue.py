"""
Task Queue — DynamoDB-backed with dependency resolution.

Statuses: PENDING → READY → IN_PROGRESS → COMPLETED | FAILED | BLOCKED
A task is READY when all depends_on tasks are COMPLETED.

DynamoDB schema:
  PK: task_id (S), GSI: status-created-index (status S, created_at S)
"""

import logging
import os
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger("fde.task_queue")

_TABLE_NAME = os.environ.get("TASK_QUEUE_TABLE", "fde-dev-task-queue")
_REGION = os.environ.get("AWS_REGION", "us-east-1")


def _get_table():
    return boto3.resource("dynamodb", region_name=_REGION).Table(_TABLE_NAME)


def _now():
    return datetime.now(timezone.utc).isoformat()


def enqueue_task(title: str, spec_content: str, source: str = "direct",
                 issue_id: str = "", spec_path: str = "", priority: str = "P2",
                 depends_on: list[str] | None = None) -> dict:
    table = _get_table()
    task_id = f"TASK-{uuid.uuid4().hex[:8]}"
    now = _now()
    status = "PENDING" if depends_on else "READY"
    item = {
        "task_id": task_id, "title": title, "spec_content": spec_content,
        "spec_path": spec_path, "source": source, "issue_id": issue_id,
        "status": status, "priority": priority, "depends_on": depends_on or [],
        "assigned_agent": "", "result": "", "error": "",
        "created_at": now, "updated_at": now,
    }
    table.put_item(Item=item)
    logger.info("Enqueued: %s (%s) status=%s deps=%s", task_id, title, status, depends_on or "none")
    return item


def get_task(task_id: str) -> dict | None:
    return _get_table().get_item(Key={"task_id": task_id}).get("Item")


def get_next_ready_task() -> dict | None:
    items = _get_table().query(
        IndexName="status-created-index",
        KeyConditionExpression=Key("status").eq("READY"), Limit=10,
    ).get("Items", [])
    if not items:
        return None
    priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    items.sort(key=lambda x: (priority_order.get(x.get("priority", "P2"), 2), x.get("created_at", "")))
    return items[0]


def claim_task(task_id: str, agent_name: str) -> bool:
    table = _get_table()
    try:
        table.update_item(
            Key={"task_id": task_id},
            UpdateExpression="SET #s = :new_status, assigned_agent = :agent, started_at = :now, updated_at = :now",
            ConditionExpression="#s = :ready",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":new_status": "IN_PROGRESS", ":agent": agent_name, ":ready": "READY", ":now": _now()},
        )
        logger.info("Task %s claimed by %s", task_id, agent_name)
        return True
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        logger.warning("Task %s already claimed", task_id)
        return False


def update_task_stage(task_id: str, stage: str, **kwargs) -> None:
    """Update the current_stage field for dashboard visibility.

    Called by the orchestrator at each pipeline milestone so the dashboard
    shows real-time stage progression.

    Also sets `started_at` (idempotent, first-write-wins) to ensure DORA
    lead time is measured from actual execution start, not webhook arrival.
    Uses if_not_exists so only the first call sets it — subsequent calls
    are no-ops for started_at while still updating the stage.

    Args:
        task_id: The task to update.
        stage: The new stage name (e.g., 'workspace', 'reconnaissance', 'engineering').
        **kwargs: Additional fields to update (e.g., pr_url, workspace_error).
    """
    table = _get_table()
    # started_at uses if_not_exists — idempotent, first-write-wins
    # This ensures DORA metrics use execution start, not webhook arrival
    update_expr = "SET current_stage = :stage, updated_at = :now, started_at = if_not_exists(started_at, :now)"
    expr_values = {":stage": stage, ":now": _now()}

    # Allow passing additional fields (pr_url, workspace_error, etc.)
    for key, value in kwargs.items():
        update_expr += f", {key} = :{key}"
        expr_values[f":{key}"] = value

    try:
        table.update_item(
            Key={"task_id": task_id},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_values,
        )
        logger.info("Task %s \u2192 stage: %s", task_id, stage)
    except Exception as e:
        # Non-blocking — don't fail the pipeline for a dashboard update
        logger.warning("Failed to update stage for %s: %s", task_id, e)


def append_task_event(task_id: str, event_type: str, message: str, **metadata) -> None:
    """Append a structured reasoning event to the task's events list.

    The dashboard reads these events and renders them in the Reasoning and
    Gates views so the PM can see what the agent decided and why.

    Events are capped at 50 per task to stay within DynamoDB item size limits.

    Args:
        task_id: The task to append the event to.
        event_type: Event category (e.g., 'agent', 'system', 'tool', 'gate', 'error').
        message: Human-readable event description (max 500 chars).
        **metadata: Optional structured fields for richer rendering:
            - phase: FDE phase (e.g., 'reconnaissance', 'intake', 'engineering')
            - gate_name: Gate identifier (e.g., 'dor', 'adversarial', 'dod', 'concurrency')
            - gate_result: 'pass' or 'fail'
            - criteria: What was evaluated (max 300 chars)
            - context: Accumulated context or rationale (max 500 chars)
            - autonomy_level: Computed autonomy level (e.g., 'L3', 'L5')
            - confidence: Confidence level (e.g., 'high', 'medium', 'low')
    """
    table = _get_table()
    event_entry = {
        "ts": _now(),
        "type": event_type,
        "msg": message[:500],
    }

    # Add optional structured metadata (only non-empty values)
    allowed_fields = ("phase", "gate_name", "gate_result", "criteria", "context",
                      "autonomy_level", "confidence")
    for field in allowed_fields:
        value = metadata.get(field)
        if value:
            max_len = 500 if field == "context" else 300
            event_entry[field] = str(value)[:max_len]

    try:
        table.update_item(
            Key={"task_id": task_id},
            UpdateExpression="SET events = list_append(if_not_exists(events, :empty), :evt), updated_at = :now",
            ExpressionAttributeValues={
                ":evt": [event_entry],
                ":empty": [],
                ":now": _now(),
            },
        )
    except Exception as e:
        # Non-blocking
        logger.debug("Failed to append event for %s: %s", task_id, e)


def find_task_by_issue(issue_id: str) -> dict | None:
    """Find a READY task by its issue_id field.

    Used by the orchestrator to correlate with the task created by the
    webhook_ingest Lambda. The issue_id format is 'owner/repo#number'.

    Args:
        issue_id: The issue identifier (e.g., 'org/repo#42').

    Returns:
        The task item if found, or None.
    """
    table = _get_table()
    # Query READY tasks and filter by issue_id
    ready_tasks = table.query(
        IndexName="status-created-index",
        KeyConditionExpression=Key("status").eq("READY"),
    ).get("Items", [])

    for task in ready_tasks:
        if task.get("issue_id") == issue_id:
            return task

    # Also check IN_PROGRESS (in case of restart/resume)
    in_progress = table.query(
        IndexName="status-created-index",
        KeyConditionExpression=Key("status").eq("IN_PROGRESS"),
    ).get("Items", [])

    for task in in_progress:
        if task.get("issue_id") == issue_id:
            return task

    return None


def count_active_tasks_for_repo(repo: str) -> int:
    """Count tasks currently IN_PROGRESS or RUNNING for a specific repo.

    Used by the concurrency guard to prevent too many parallel agents
    on the same repository (risk of merge conflicts).

    Uses ConsistentRead on the base table (not GSI) to avoid race conditions
    where two tasks pass the guard simultaneously due to eventual consistency.

    Args:
        repo: Full repo name (e.g., 'truerocha/cognitive-wafr').

    Returns:
        Number of active tasks for this repo.
    """
    table = _get_table()
    count = 0

    for status in ("IN_PROGRESS", "RUNNING"):
        items = table.query(
            IndexName="status-created-index",
            KeyConditionExpression=Key("status").eq(status),
        ).get("Items", [])
        count += sum(1 for item in items if item.get("repo") == repo)

    return count


def check_concurrency(repo: str, max_concurrent: int = 2) -> tuple[bool, int]:
    """Check if a new task can start for this repo without exceeding limits.

    Args:
        repo: Full repo name.
        max_concurrent: Maximum allowed concurrent tasks for this repo.
            Must be >= 1. Values <= 0 are treated as 1 (fail-safe).

    Returns:
        Tuple of (can_proceed: bool, current_count: int).
    """
    # Fail-safe: never allow max_concurrent <= 0 to permanently block a repo
    if max_concurrent <= 0:
        logger.warning(
            "Concurrency guard: max_concurrent=%d for repo=%s is invalid, using 1",
            max_concurrent, repo,
        )
        max_concurrent = 1

    current = count_active_tasks_for_repo(repo)
    can_proceed = current < max_concurrent
    if not can_proceed:
        logger.warning(
            "Concurrency guard: repo=%s has %d/%d active tasks — new task must wait",
            repo, current, max_concurrent,
        )
    return can_proceed, current


def reap_stuck_tasks(max_age_minutes: int = 60) -> list[str]:
    """Reap tasks stuck in IN_PROGRESS/RUNNING beyond the max age.

    ECS tasks can crash without updating DynamoDB. These orphaned records
    block the concurrency guard permanently. This function marks them as
    FAILED so slots are freed.

    Should be called periodically (e.g., by a CloudWatch Events rule or
    before each concurrency check).

    Args:
        max_age_minutes: Tasks older than this (since last update) are reaped.

    Returns:
        List of task_ids that were reaped.
    """
    table = _get_table()
    reaped = []
    cutoff = datetime.now(timezone.utc).timestamp() - (max_age_minutes * 60)

    for status in ("IN_PROGRESS", "RUNNING"):
        items = table.query(
            IndexName="status-created-index",
            KeyConditionExpression=Key("status").eq(status),
        ).get("Items", [])

        for item in items:
            updated_at = item.get("updated_at", "")
            if not updated_at:
                continue
            try:
                updated_ts = datetime.fromisoformat(updated_at.replace("Z", "+00:00")).timestamp()
            except (ValueError, TypeError):
                continue

            if updated_ts < cutoff:
                task_id = item["task_id"]
                table.update_item(
                    Key={"task_id": task_id},
                    UpdateExpression="SET #s = :status, #e = :error, updated_at = :now",
                    ExpressionAttributeNames={"#s": "status", "#e": "error"},
                    ExpressionAttributeValues={
                        ":status": "FAILED",
                        ":error": f"Reaped: stuck in {status} for >{max_age_minutes}min (container likely crashed)",
                        ":now": _now(),
                    },
                )
                reaped.append(task_id)
                logger.warning(
                    "Reaped stuck task %s (status=%s, last_update=%s)",
                    task_id, status, updated_at,
                )

    return reaped


def retry_queued_tasks(repo: str) -> list[str]:
    """Find tasks that were queued due to concurrency limits and are now eligible.

    Called after a task completes or is reaped, to unblock queued work.
    Tasks in 'ingested' stage with a concurrency gate failure event are
    candidates for retry.

    Args:
        repo: The repo that just freed a slot.

    Returns:
        List of task_ids that are now eligible for retry.
    """
    table = _get_table()
    eligible = []

    # Find READY tasks for this repo stuck at 'ingested' stage
    # (they hit the concurrency guard and were returned as 'queued')
    ready_items = table.query(
        IndexName="status-created-index",
        KeyConditionExpression=Key("status").eq("READY"),
    ).get("Items", [])

    for item in ready_items:
        if item.get("repo") == repo and item.get("current_stage") == "ingested":
            eligible.append(item["task_id"])
            logger.info("Task %s eligible for retry (repo=%s slot freed)", item["task_id"], repo)

    return eligible


def complete_task(task_id: str, result: str) -> dict:
    table = _get_table()

    # Calculate actual execution duration (started_at → now)
    task = get_task(task_id)
    started_at = task.get("started_at", "") if task else ""
    duration_ms = 0
    if started_at:
        try:
            from datetime import datetime, timezone
            start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            duration_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        except (ValueError, TypeError):
            pass

    table.update_item(
        Key={"task_id": task_id},
        UpdateExpression="SET #s = :status, #r = :result, duration_ms = :dur, updated_at = :now",
        ExpressionAttributeNames={"#s": "status", "#r": "result"},
        ExpressionAttributeValues={
            ":status": "COMPLETED",
            ":result": result,
            ":dur": duration_ms,
            ":now": _now(),
        },
    )
    logger.info("Task %s completed (duration: %dms / %.1f min)", task_id, duration_ms, duration_ms / 60000)

    # Resolve DAG dependencies (existing behavior)
    promoted = _resolve_dependencies(task_id)

    # Reap stuck tasks and retry queued tasks for this repo (COE-016 fix)
    task = get_task(task_id)
    repo = task.get("repo", "") if task else ""
    if repo:
        reaped = reap_stuck_tasks(max_age_minutes=60)
        if reaped:
            logger.info("Reaped %d stuck tasks during completion of %s", len(reaped), task_id)
        eligible = retry_queued_tasks(repo)
        if eligible:
            logger.info("Found %d queued tasks eligible for retry after %s completed", len(eligible), task_id)

    return {"task_id": task_id, "status": "COMPLETED", "promoted_tasks": promoted}


def fail_task(task_id: str, error: str) -> dict:
    table = _get_table()
    table.update_item(
        Key={"task_id": task_id},
        UpdateExpression="SET #s = :status, #e = :error, updated_at = :now",
        ExpressionAttributeNames={"#s": "status", "#e": "error"},
        ExpressionAttributeValues={":status": "FAILED", ":error": error, ":now": _now()},
    )
    logger.info("Task %s failed: %s", task_id, error[:100])
    blocked = _block_dependents(task_id)
    return {"task_id": task_id, "status": "FAILED", "blocked_tasks": blocked}


def _resolve_dependencies(completed_task_id: str) -> list[str]:
    table = _get_table()
    promoted = []
    pending = table.query(IndexName="status-created-index",
                          KeyConditionExpression=Key("status").eq("PENDING")).get("Items", [])
    for item in pending:
        deps = item.get("depends_on", [])
        if completed_task_id not in deps:
            continue
        all_done = all(
            (get_task(d) or {}).get("status") == "COMPLETED" for d in deps
        )
        if all_done:
            table.update_item(
                Key={"task_id": item["task_id"]},
                UpdateExpression="SET #s = :status, updated_at = :now",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":status": "READY", ":now": _now()},
            )
            promoted.append(item["task_id"])
            logger.info("Task %s promoted to READY", item["task_id"])
    return promoted


def _block_dependents(failed_task_id: str) -> list[str]:
    table = _get_table()
    blocked = []
    pending = table.query(IndexName="status-created-index",
                          KeyConditionExpression=Key("status").eq("PENDING")).get("Items", [])
    for item in pending:
        if failed_task_id in item.get("depends_on", []):
            table.update_item(
                Key={"task_id": item["task_id"]},
                UpdateExpression="SET #s = :status, #e = :error, updated_at = :now",
                ExpressionAttributeNames={"#s": "status", "#e": "error"},
                ExpressionAttributeValues={
                    ":status": "BLOCKED",
                    ":error": f"Blocked by failed dependency: {failed_task_id}",
                    ":now": _now(),
                },
            )
            blocked.append(item["task_id"])
            logger.info("Task %s blocked by %s", item["task_id"], failed_task_id)
    return blocked


def list_tasks(status: str | None = None) -> list[dict]:
    table = _get_table()
    if status:
        return table.query(IndexName="status-created-index",
                           KeyConditionExpression=Key("status").eq(status)).get("Items", [])
    return table.scan().get("Items", [])
