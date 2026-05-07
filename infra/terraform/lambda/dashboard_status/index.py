"""
Dashboard Status API — Lambda handler for /status/tasks and /status/health endpoints.

Reads from DynamoDB task_queue AND agent_lifecycle tables to provide:
  - Task pipeline status with agent assignment
  - Agent-to-task mapping with visual progress stages
  - Capacity metrics (provisioned agents, active, idle)
  - Self-diagnosis health checks

Security: Returns only task metadata (title, status, stage, duration).
Never returns spec content, code, or internal error traces.
"""

import json
import os
from datetime import datetime, timezone, timedelta

import boto3
from boto3.dynamodb.conditions import Attr, Key

TASK_QUEUE_TABLE = os.environ.get("TASK_QUEUE_TABLE", "fde-dev-task-queue")
AGENT_LIFECYCLE_TABLE = os.environ.get("AGENT_LIFECYCLE_TABLE", "fde-dev-agent-lifecycle")
REGION = os.environ.get("AWS_REGION_NAME", os.environ.get("AWS_REGION", "us-east-1"))

dynamodb = boto3.resource("dynamodb", region_name=REGION)
task_table = dynamodb.Table(TASK_QUEUE_TABLE)
lifecycle_table = dynamodb.Table(AGENT_LIFECYCLE_TABLE)

# Pipeline stages in execution order (for progress visualization)
PIPELINE_STAGES = [
    "ingested",
    "workspace",
    "reconnaissance",
    "intake",
    "engineering",
    "testing",
    "review",
    "completion",
]


def handler(event, context):
    """Lambda handler — routes to /status/tasks or /status/health."""
    path = event.get("rawPath", event.get("path", "/status/tasks"))

    if "/status/health" in path:
        return _handle_health(event, context)
    return _handle_tasks(event, context)


def _handle_tasks(event, context):
    """GET /status/tasks — Full dashboard payload with agent assignment."""
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

        # Fetch tasks from last 24h
        task_response = task_table.scan(
            FilterExpression=Attr("created_at").gte(cutoff),
            Limit=50,
        )
        items = task_response.get("Items", [])

        # Fetch active agents
        agents = _fetch_active_agents()
        agent_by_task = {a.get("task_id", ""): a for a in agents if a.get("task_id")}

        # Compute metrics
        active = sum(1 for i in items if i.get("status") in ("RUNNING", "PENDING", "READY", "IN_PROGRESS"))
        completed = sum(1 for i in items if i.get("status") == "COMPLETED")
        failed = sum(1 for i in items if i.get("status") in ("FAILED", "DEAD_LETTER"))
        durations = [int(i.get("duration_ms", 0)) for i in items if i.get("duration_ms")]
        avg_duration = int(sum(durations) / len(durations)) if durations else 0

        # Agent capacity metrics
        total_agents = len(agents)
        active_agents = sum(1 for a in agents if a.get("status") in ("RUNNING", "INITIALIZING", "CREATED"))
        idle_agents = total_agents - active_agents

        # Build enriched task list with agent assignment
        tasks = []
        for item in sorted(items, key=lambda x: x.get("created_at", ""), reverse=True):
            task_id = item.get("task_id", "")
            agent = agent_by_task.get(task_id, {})
            current_stage = item.get("current_stage", "")
            stage_index = PIPELINE_STAGES.index(current_stage) if current_stage in PIPELINE_STAGES else -1

            tasks.append({
                "task_id": task_id,
                "title": item.get("title", item.get("task_id", "Unknown")),
                "status": _map_status(item.get("status", "PENDING")),
                "current_stage": current_stage,
                "stage_progress": {
                    "current": stage_index + 1,
                    "total": len(PIPELINE_STAGES),
                    "stages": PIPELINE_STAGES,
                    "percent": int(((stage_index + 1) / len(PIPELINE_STAGES)) * 100) if stage_index >= 0 else 0,
                },
                "agent": {
                    "instance_id": agent.get("agent_instance_id", item.get("assigned_agent", "")),
                    "name": agent.get("agent_name", ""),
                    "status": agent.get("status", ""),
                    "started_at": agent.get("started_at", ""),
                } if agent or item.get("assigned_agent") else None,
                "repo": item.get("repo", ""),
                "source": item.get("source", ""),
                "issue_url": item.get("issue_url", ""),
                "pr_url": item.get("pr_url", ""),
                "workspace_error": item.get("workspace_error", ""),
                "priority": item.get("priority", "P2"),
                "duration_ms": int(item.get("duration_ms", 0)),
                "elapsed_ms": _compute_elapsed(item),
                "created_at": item.get("created_at", ""),
                "updated_at": item.get("updated_at", ""),
                "events": item.get("events", [])[-20:],  # Last 20 events for Chain of Thought
            })

        body = {
            "metrics": {
                "active": active,
                "completed_24h": completed,
                "failed_24h": failed,
                "avg_duration_ms": avg_duration,
                "total_agents_provisioned": total_agents,
                "active_agents": active_agents,
                "idle_agents": idle_agents,
            },
            "tasks": tasks[:20],
            "agents": _build_agent_summary(agents),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        return _response(200, body)

    except Exception as e:
        return _response(500, {"error": "Internal server error"})


def _handle_health(event, context):
    """GET /status/health — Self-diagnosis endpoint.

    Checks:
      1. DynamoDB task_queue table accessible
      2. DynamoDB agent_lifecycle table accessible
      3. No stuck tasks (RUNNING > 30 min without update)
      4. No dead-letter accumulation
      5. Agent capacity not exhausted
    """
    checks = []
    overall = "healthy"

    # Check 1: Task queue table accessible
    try:
        task_table.scan(Limit=1)
        checks.append({"name": "task_queue_table", "status": "pass", "detail": "Accessible"})
    except Exception as e:
        checks.append({"name": "task_queue_table", "status": "fail", "detail": str(e)[:100]})
        overall = "degraded"

    # Check 2: Agent lifecycle table accessible
    try:
        lifecycle_table.scan(Limit=1)
        checks.append({"name": "agent_lifecycle_table", "status": "pass", "detail": "Accessible"})
    except Exception as e:
        checks.append({"name": "agent_lifecycle_table", "status": "fail", "detail": str(e)[:100]})
        overall = "degraded"

    # Check 3: Stuck tasks (RUNNING/IN_PROGRESS > 30 min without update)
    try:
        stuck_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        running_tasks = task_table.query(
            IndexName="status-created-index",
            KeyConditionExpression=Key("status").eq("RUNNING"),
        ).get("Items", [])

        in_progress = task_table.query(
            IndexName="status-created-index",
            KeyConditionExpression=Key("status").eq("IN_PROGRESS"),
        ).get("Items", [])

        stuck = [t for t in (running_tasks + in_progress)
                 if t.get("updated_at", "") < stuck_cutoff and t.get("updated_at", "")]

        if stuck:
            checks.append({
                "name": "stuck_tasks",
                "status": "warn",
                "detail": f"{len(stuck)} task(s) running >30min without update",
                "task_ids": [t["task_id"] for t in stuck[:5]],
            })
            overall = "degraded"
        else:
            checks.append({"name": "stuck_tasks", "status": "pass", "detail": "No stuck tasks"})
    except Exception as e:
        checks.append({"name": "stuck_tasks", "status": "fail", "detail": str(e)[:100]})

    # Check 4: Dead-letter accumulation
    try:
        dead_letters = task_table.query(
            IndexName="status-created-index",
            KeyConditionExpression=Key("status").eq("DEAD_LETTER"),
        ).get("Items", [])

        recent_dl = [t for t in dead_letters
                     if t.get("dead_letter_at", "") > (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()]

        if recent_dl:
            checks.append({
                "name": "dead_letters",
                "status": "warn",
                "detail": f"{len(recent_dl)} dead-letter task(s) in last hour",
                "task_ids": [t["task_id"] for t in recent_dl[:5]],
            })
            if len(recent_dl) >= 3:
                overall = "unhealthy"
            else:
                overall = "degraded"
        else:
            checks.append({"name": "dead_letters", "status": "pass", "detail": "No recent dead letters"})
    except Exception as e:
        checks.append({"name": "dead_letters", "status": "fail", "detail": str(e)[:100]})

    # Check 5: Agent capacity
    try:
        agents = _fetch_active_agents()
        running_agents = sum(1 for a in agents if a.get("status") in ("RUNNING", "INITIALIZING"))
        # Fargate soft limit is typically 10 concurrent tasks per cluster
        capacity_pct = int((running_agents / 10) * 100) if running_agents else 0

        if capacity_pct >= 90:
            checks.append({
                "name": "agent_capacity",
                "status": "warn",
                "detail": f"{running_agents}/10 agents active ({capacity_pct}% capacity)",
            })
            overall = "degraded"
        else:
            checks.append({
                "name": "agent_capacity",
                "status": "pass",
                "detail": f"{running_agents}/10 agents active ({capacity_pct}% capacity)",
            })
    except Exception as e:
        checks.append({"name": "agent_capacity", "status": "fail", "detail": str(e)[:100]})

    body = {
        "status": overall,
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": os.environ.get("ENVIRONMENT", "dev"),
    }

    status_code = 200 if overall == "healthy" else 503 if overall == "unhealthy" else 200
    return _response(status_code, body)


def _fetch_active_agents() -> list:
    """Fetch agents from lifecycle table (last 24h)."""
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        response = lifecycle_table.scan(
            FilterExpression=Attr("created_at").gte(cutoff),
            Limit=50,
        )
        return response.get("Items", [])
    except Exception:
        return []


def _build_agent_summary(agents: list) -> list:
    """Build agent summary for the dashboard sidebar."""
    summary = []
    for agent in sorted(agents, key=lambda x: x.get("created_at", ""), reverse=True)[:10]:
        summary.append({
            "instance_id": agent.get("agent_instance_id", ""),
            "name": agent.get("agent_name", ""),
            "task_id": agent.get("task_id", ""),
            "status": agent.get("status", ""),
            "started_at": agent.get("started_at", ""),
            "execution_time_ms": int(agent.get("execution_time_ms", 0)),
        })
    return summary


def _compute_elapsed(item: dict) -> int:
    """Compute elapsed time in ms for running tasks."""
    if item.get("status") not in ("RUNNING", "IN_PROGRESS", "READY"):
        return int(item.get("duration_ms", 0))

    created = item.get("created_at", "")
    if not created:
        return 0

    try:
        start = datetime.fromisoformat(created.replace("Z", "+00:00"))
        elapsed = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        return int(elapsed)
    except (ValueError, TypeError):
        return 0


def _map_status(dynamo_status: str) -> str:
    """Map DynamoDB status values to dashboard display status."""
    mapping = {
        "PENDING": "pending",
        "READY": "ready",
        "IN_PROGRESS": "running",
        "RUNNING": "running",
        "COMPLETED": "completed",
        "FAILED": "failed",
        "DEAD_LETTER": "failed",
        "BLOCKED": "blocked",
    }
    return mapping.get(dynamo_status, "pending")


def _response(status_code: int, body: dict) -> dict:
    """Build API Gateway response with CORS headers."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Accept",
        },
        "body": json.dumps(body, default=str),
    }
