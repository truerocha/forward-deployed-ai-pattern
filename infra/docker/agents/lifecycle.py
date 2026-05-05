"""
Agent Lifecycle Manager — Tracks agent instances from creation to decommission.

Lifecycle: CREATED → INITIALIZING → RUNNING → COMPLETED | FAILED → DECOMMISSIONED

DynamoDB schema:
  PK: agent_instance_id (S), GSI: status-created-index (status S, created_at S)
"""

import logging
import os
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger("fde.lifecycle")

_TABLE_NAME = os.environ.get("AGENT_LIFECYCLE_TABLE", "fde-dev-agent-lifecycle")
_REGION = os.environ.get("AWS_REGION", "us-east-1")


def _get_table():
    return boto3.resource("dynamodb", region_name=_REGION).Table(_TABLE_NAME)


def _now():
    return datetime.now(timezone.utc).isoformat()


def create_instance(agent_name: str, task_id: str, model_id: str,
                    prompt_version: int = 0, prompt_hash: str = "") -> str:
    instance_id = f"AGENT-{uuid.uuid4().hex[:8]}"
    now = _now()
    _get_table().put_item(Item={
        "agent_instance_id": instance_id, "agent_name": agent_name,
        "task_id": task_id, "model_id": model_id,
        "prompt_version": prompt_version, "prompt_hash": prompt_hash,
        "status": "CREATED", "created_at": now, "started_at": "",
        "completed_at": "", "decommissioned_at": "",
        "execution_time_ms": 0, "result_summary": "", "error": "", "updated_at": now,
    })
    logger.info("Agent created: %s (%s for %s)", instance_id, agent_name, task_id)
    return instance_id


def mark_initializing(instance_id: str) -> None:
    _get_table().update_item(
        Key={"agent_instance_id": instance_id},
        UpdateExpression="SET #s = :status, updated_at = :now",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": "INITIALIZING", ":now": _now()},
    )
    logger.info("Agent %s → INITIALIZING", instance_id)


def mark_running(instance_id: str) -> None:
    _get_table().update_item(
        Key={"agent_instance_id": instance_id},
        UpdateExpression="SET #s = :status, started_at = :now, updated_at = :now",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": "RUNNING", ":now": _now()},
    )
    logger.info("Agent %s → RUNNING", instance_id)


def mark_completed(instance_id: str, result_summary: str, execution_time_ms: int) -> None:
    _get_table().update_item(
        Key={"agent_instance_id": instance_id},
        UpdateExpression="SET #s = :status, completed_at = :now, result_summary = :result, "
                         "execution_time_ms = :time, updated_at = :now",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": "COMPLETED", ":now": _now(),
            ":result": result_summary[:500], ":time": execution_time_ms,
        },
    )
    logger.info("Agent %s → COMPLETED (%dms)", instance_id, execution_time_ms)


def mark_failed(instance_id: str, error: str, execution_time_ms: int) -> None:
    _get_table().update_item(
        Key={"agent_instance_id": instance_id},
        UpdateExpression="SET #s = :status, completed_at = :now, #e = :error, "
                         "execution_time_ms = :time, updated_at = :now",
        ExpressionAttributeNames={"#s": "status", "#e": "error"},
        ExpressionAttributeValues={
            ":status": "FAILED", ":now": _now(),
            ":error": error[:500], ":time": execution_time_ms,
        },
    )
    logger.info("Agent %s → FAILED (%dms)", instance_id, execution_time_ms)


def decommission(instance_id: str) -> None:
    _get_table().update_item(
        Key={"agent_instance_id": instance_id},
        UpdateExpression="SET #s = :status, decommissioned_at = :now, updated_at = :now",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": "DECOMMISSIONED", ":now": _now()},
    )
    logger.info("Agent %s → DECOMMISSIONED", instance_id)


def get_instance(instance_id: str) -> dict | None:
    return _get_table().get_item(Key={"agent_instance_id": instance_id}).get("Item")


def list_instances(status: str | None = None) -> list[dict]:
    table = _get_table()
    if status:
        return table.query(IndexName="status-created-index",
                           KeyConditionExpression=Key("status").eq(status)).get("Items", [])
    return table.scan().get("Items", [])


def get_active_count() -> int:
    table = _get_table()
    init = table.query(IndexName="status-created-index",
                       KeyConditionExpression=Key("status").eq("INITIALIZING"),
                       Select="COUNT").get("Count", 0)
    running = table.query(IndexName="status-created-index",
                          KeyConditionExpression=Key("status").eq("RUNNING"),
                          Select="COUNT").get("Count", 0)
    return init + running
