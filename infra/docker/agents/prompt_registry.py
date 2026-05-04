"""
Prompt Registry — Versioned prompt storage in DynamoDB with hash integrity.

DynamoDB schema:
  PK: prompt_name (S), SK: version (N)
  Attributes: content, sha256_hash, context_tags, registered_by, registered_at, description, is_active
"""

import hashlib
import logging
import os
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger("fde.prompt_registry")

_TABLE_NAME = os.environ.get("PROMPT_REGISTRY_TABLE", "fde-dev-prompt-registry")
_REGION = os.environ.get("AWS_REGION", "us-east-1")


def _get_table():
    return boto3.resource("dynamodb", region_name=_REGION).Table(_TABLE_NAME)


def compute_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def register_prompt(prompt_name: str, content: str, description: str = "",
                    context_tags: list[str] | None = None, registered_by: str = "system") -> dict:
    table = _get_table()
    response = table.query(KeyConditionExpression=Key("prompt_name").eq(prompt_name),
                           ScanIndexForward=False, Limit=1)
    new_version = int(response["Items"][0]["version"]) + 1 if response["Items"] else 1
    sha256_hash = compute_hash(content)
    now = datetime.now(timezone.utc).isoformat()

    table.put_item(Item={
        "prompt_name": prompt_name, "version": new_version, "content": content,
        "sha256_hash": sha256_hash, "description": description,
        "context_tags": context_tags or [], "registered_by": registered_by,
        "registered_at": now, "is_active": True,
    })
    logger.info("Registered prompt: %s v%d (hash: %s...)", prompt_name, new_version, sha256_hash[:12])
    return {"prompt_name": prompt_name, "version": new_version, "sha256_hash": sha256_hash, "registered_at": now}


def get_prompt(prompt_name: str, version: int | None = None) -> dict | None:
    table = _get_table()
    if version is not None:
        item = table.get_item(Key={"prompt_name": prompt_name, "version": version}).get("Item")
    else:
        items = table.query(KeyConditionExpression=Key("prompt_name").eq(prompt_name),
                            ScanIndexForward=False, Limit=1).get("Items", [])
        item = items[0] if items else None

    if item is None:
        return None

    item["version"] = int(item["version"])
    item["integrity_valid"] = compute_hash(item["content"]) == item.get("sha256_hash", "")
    return item


def get_prompt_by_context(prompt_name: str, context_tags: list[str]) -> dict | None:
    table = _get_table()
    items = table.query(KeyConditionExpression=Key("prompt_name").eq(prompt_name),
                        ScanIndexForward=False).get("Items", [])
    if not items:
        return None

    for item in items:
        if any(tag in item.get("context_tags", []) for tag in context_tags):
            item["version"] = int(item["version"])
            item["integrity_valid"] = compute_hash(item["content"]) == item.get("sha256_hash", "")
            return item

    for item in items:
        if not item.get("context_tags"):
            item["version"] = int(item["version"])
            item["integrity_valid"] = compute_hash(item["content"]) == item.get("sha256_hash", "")
            return item

    item = items[0]
    item["version"] = int(item["version"])
    item["integrity_valid"] = compute_hash(item["content"]) == item.get("sha256_hash", "")
    return item


def list_prompts() -> list[dict]:
    items = _get_table().scan().get("Items", [])
    latest = {}
    for item in items:
        name, ver = item["prompt_name"], int(item["version"])
        if name not in latest or ver > latest[name]["version"]:
            item["version"] = ver
            latest[name] = item
    return sorted(latest.values(), key=lambda x: x["prompt_name"])


def deactivate_prompt(prompt_name: str, version: int) -> bool:
    try:
        _get_table().update_item(
            Key={"prompt_name": prompt_name, "version": version},
            UpdateExpression="SET is_active = :val",
            ExpressionAttributeValues={":val": False},
        )
        logger.info("Deactivated prompt: %s v%d", prompt_name, version)
        return True
    except Exception as e:
        logger.error("Failed to deactivate %s v%d: %s", prompt_name, version, e)
        return False
