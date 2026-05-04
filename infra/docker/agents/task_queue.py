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
            UpdateExpression="SET #s = :new_status, assigned_agent = :agent, updated_at = :now",
            ConditionExpression="#s = :ready",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":new_status": "IN_PROGRESS", ":agent": agent_name, ":ready": "READY", ":now": _now()},
        )
        logger.info("Task %s claimed by %s", task_id, agent_name)
        return True
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        logger.warning("Task %s already claimed", task_id)
        return False


def complete_task(task_id: str, result: str) -> dict:
    table = _get_table()
    table.update_item(
        Key={"task_id": task_id},
        UpdateExpression="SET #s = :status, #r = :result, updated_at = :now",
        ExpressionAttributeNames={"#s": "status", "#r": "result"},
        ExpressionAttributeValues={":status": "COMPLETED", ":result": result, ":now": _now()},
    )
    logger.info("Task %s completed", task_id)
    promoted = _resolve_dependencies(task_id)
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
