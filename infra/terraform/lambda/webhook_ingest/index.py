"""
Webhook Ingest Lambda — Bridges ALM webhooks to the Task Queue (DynamoDB).

This is the missing piece between "webhook arrives on EventBridge" and
"task appears in the dashboard." Without this Lambda, events land on the
EventBridge bus and trigger ECS directly, but the task_queue table never
gets populated — so the dashboard shows nothing.

Flow:
  API Gateway → EventBridge → [this Lambda] → DynamoDB task_queue
                            → [ECS RunTask]  → agent executes

The ECS target and this Lambda both fire from the same EventBridge rule.
This Lambda writes the task record; the ECS container executes it.

Well-Architected alignment:
  OPS 6: Telemetry — every task is tracked from ingestion
  REL 2: Workload architecture — decoupled write from execution
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))

TASK_QUEUE_TABLE = os.environ.get("TASK_QUEUE_TABLE", "fde-dev-task-queue")
AGENT_LIFECYCLE_TABLE = os.environ.get("AGENT_LIFECYCLE_TABLE", "fde-dev-agent-lifecycle")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")


def handler(event, context):
    """Process EventBridge events and write task records to DynamoDB.

    EventBridge delivers the event in standard envelope format:
    {
        "source": "fde.github.webhook",
        "detail-type": "issue.labeled",
        "detail": { ...raw webhook payload... }
    }
    """
    logger.info("Webhook ingest invoked: source=%s, detail-type=%s",
                event.get("source", "unknown"), event.get("detail-type", "unknown"))

    source = event.get("source", "")
    detail = event.get("detail", {})

    if "fde.github" in source:
        task = _ingest_github(detail)
    elif "fde.gitlab" in source:
        task = _ingest_gitlab(detail)
    elif "fde.asana" in source:
        task = _ingest_asana(detail)
    else:
        logger.warning("Unknown source: %s — skipping", source)
        return {"statusCode": 200, "body": "skipped"}

    if not task:
        logger.info("Event did not produce a task (filtered out)")
        return {"statusCode": 200, "body": "filtered"}

    # Write to task_queue table (idempotent — skip if issue_id already exists)
    table = dynamodb.Table(TASK_QUEUE_TABLE)

    # Deduplicate: check if a task for this issue already exists
    existing = _find_existing_task(table, task.get("issue_id", ""))
    if existing:
        logger.info("Task already exists for issue %s (task_id=%s) — skipping duplicate",
                    task.get("issue_id"), existing.get("task_id"))
        return {
            "statusCode": 200,
            "body": json.dumps({"task_id": existing["task_id"], "status": "duplicate_skipped"}),
        }

    table.put_item(Item=task)

    # Create a provisional agent lifecycle record (CREATED state)
    _create_agent_record(task)

    logger.info("Task ingested: task_id=%s, title=%s, source=%s",
                task["task_id"], task["title"], task["source"])

    return {
        "statusCode": 200,
        "body": json.dumps({"task_id": task["task_id"], "status": task["status"]}),
    }


def _ingest_github(detail: dict) -> dict | None:
    """Extract task from GitHub issues.labeled webhook payload."""
    action = detail.get("action", "")
    label_name = detail.get("label", {}).get("name", "")

    # Only process factory-ready labeled events
    if action != "labeled" or label_name != "factory-ready":
        return None

    issue = detail.get("issue", {})
    repo = detail.get("repository", {}).get("full_name", "")
    issue_number = issue.get("number", 0)
    title = issue.get("title", f"GitHub #{issue_number}")
    body = issue.get("body", "")

    now = datetime.now(timezone.utc).isoformat()
    task_id = f"TASK-{uuid.uuid4().hex[:8]}"

    return {
        "task_id": task_id,
        "title": title,
        "spec_content": body,
        "spec_path": "",
        "source": "github",
        "repo": repo,
        "issue_id": f"{repo}#{issue_number}",
        "issue_url": f"https://github.com/{repo}/issues/{issue_number}",
        "status": "READY",
        "priority": _extract_priority(issue.get("labels", [])),
        "depends_on": [],
        "assigned_agent": "",
        "current_stage": "ingested",
        "result": "",
        "error": "",
        "duration_ms": 0,
        "created_at": now,
        "updated_at": now,
    }


def _ingest_gitlab(detail: dict) -> dict | None:
    """Extract task from GitLab issue webhook payload."""
    action = detail.get("action", "")
    if action != "update":
        return None

    # GitLab sends labels in object_attributes.labels
    attrs = detail.get("object_attributes", {})
    labels = [l.get("title", "") for l in attrs.get("labels", [])]

    if "factory-ready" not in labels:
        return None

    project = detail.get("project", {})
    repo = project.get("path_with_namespace", "")
    issue_id = attrs.get("iid", 0)
    title = attrs.get("title", f"GitLab !{issue_id}")
    body = attrs.get("description", "")

    now = datetime.now(timezone.utc).isoformat()
    task_id = f"TASK-{uuid.uuid4().hex[:8]}"

    return {
        "task_id": task_id,
        "title": title,
        "spec_content": body,
        "spec_path": "",
        "source": "gitlab",
        "repo": repo,
        "issue_id": f"{repo}#{issue_id}",
        "issue_url": attrs.get("url", ""),
        "status": "READY",
        "priority": "P2",
        "depends_on": [],
        "assigned_agent": "",
        "current_stage": "ingested",
        "result": "",
        "error": "",
        "duration_ms": 0,
        "created_at": now,
        "updated_at": now,
    }


def _ingest_asana(detail: dict) -> dict | None:
    """Extract task from Asana task.moved webhook payload."""
    # Asana webhooks have events[].resource structure
    events = detail.get("events", [detail])

    for ev in events:
        resource = ev.get("resource", ev)
        task_name = resource.get("name", "Asana Task")
        task_gid = resource.get("gid", "")

        now = datetime.now(timezone.utc).isoformat()
        task_id = f"TASK-{uuid.uuid4().hex[:8]}"

        return {
            "task_id": task_id,
            "title": task_name,
            "spec_content": resource.get("notes", ""),
            "spec_path": "",
            "source": "asana",
            "repo": "",
            "issue_id": task_gid,
            "issue_url": f"https://app.asana.com/0/0/{task_gid}" if task_gid else "",
            "status": "READY",
            "priority": "P2",
            "depends_on": [],
            "assigned_agent": "",
            "current_stage": "ingested",
            "result": "",
            "error": "",
            "duration_ms": 0,
            "created_at": now,
            "updated_at": now,
        }

    return None


def _create_agent_record(task: dict) -> None:
    """Create a provisional agent lifecycle record for dashboard visibility."""
    try:
        lifecycle_table = dynamodb.Table(AGENT_LIFECYCLE_TABLE)
        now = datetime.now(timezone.utc).isoformat()
        instance_id = f"AGENT-{uuid.uuid4().hex[:8]}"

        lifecycle_table.put_item(Item={
            "agent_instance_id": instance_id,
            "agent_name": "fde-pipeline",
            "task_id": task["task_id"],
            "model_id": "pending-assignment",
            "prompt_version": 0,
            "prompt_hash": "",
            "status": "CREATED",
            "created_at": now,
            "started_at": "",
            "completed_at": "",
            "decommissioned_at": "",
            "execution_time_ms": 0,
            "result_summary": "",
            "error": "",
            "updated_at": now,
        })

        # Update task with assigned agent
        task_table = dynamodb.Table(TASK_QUEUE_TABLE)
        task_table.update_item(
            Key={"task_id": task["task_id"]},
            UpdateExpression="SET assigned_agent = :agent",
            ExpressionAttributeValues={":agent": instance_id},
        )

        logger.info("Agent record created: %s for task %s", instance_id, task["task_id"])
    except Exception as e:
        # Non-blocking — task is already in the queue
        logger.warning("Failed to create agent lifecycle record: %s", e)


def _extract_priority(labels: list) -> str:
    """Extract priority from GitHub labels (P0, P1, P2, P3)."""
    for label in labels:
        name = label.get("name", "") if isinstance(label, dict) else str(label)
        if name in ("P0", "P1", "P2", "P3"):
            return name
    return "P2"


def _find_existing_task(table, issue_id: str) -> dict | None:
    """Check if a task already exists for this issue_id (deduplication).

    Scans READY and IN_PROGRESS tasks. If found, returns the existing record
    to prevent duplicate entries from webhook retries or duplicate events.

    Stale task TTL: If a task has been in a non-terminal state for >30 minutes
    without an updated_at change, it's considered stale and won't block new tasks.
    This prevents permanently stuck tasks from blocking retries (COE: 5-Whys).
    """
    if not issue_id:
        return None

    try:
        # Scan is acceptable here — table is small (< 50 active tasks)
        response = table.scan(
            FilterExpression="issue_id = :iid AND #s IN (:s1, :s2, :s3)",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":iid": issue_id,
                ":s1": "READY",
                ":s2": "IN_PROGRESS",
                ":s3": "RUNNING",
            },
            Limit=5,
        )
        items = response.get("Items", [])
        if not items:
            return None

        # Check staleness: if task hasn't been updated in 30+ minutes, allow override
        now = datetime.now(timezone.utc)
        stale_threshold_minutes = 30

        for item in items:
            updated_at_str = item.get("updated_at", item.get("created_at", ""))
            if updated_at_str:
                try:
                    updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
                    age_minutes = (now - updated_at).total_seconds() / 60
                    if age_minutes > stale_threshold_minutes:
                        logger.info(
                            "Task %s for issue %s is stale (%.0f min without update) — allowing new task",
                            item.get("task_id"), issue_id, age_minutes,
                        )
                        continue  # Skip stale task, check next
                except (ValueError, TypeError):
                    pass
            # Non-stale active task found — block duplicate
            return item

        return None
    except Exception as e:
        logger.warning("Deduplication check failed (proceeding with insert): %s", e)
        return None
