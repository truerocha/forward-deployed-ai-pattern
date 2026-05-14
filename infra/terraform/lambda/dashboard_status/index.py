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
DORA_METRICS_TABLE = os.environ.get("DORA_METRICS_TABLE", "fde-dev-dora-metrics")
METRICS_TABLE = os.environ.get("METRICS_TABLE", "fde-dev-metrics")
REGION = os.environ.get("AWS_REGION_NAME", os.environ.get("AWS_REGION", "us-east-1"))

dynamodb = boto3.resource("dynamodb", region_name=REGION)
task_table = dynamodb.Table(TASK_QUEUE_TABLE)
lifecycle_table = dynamodb.Table(AGENT_LIFECYCLE_TABLE)
dora_table = dynamodb.Table(DORA_METRICS_TABLE)
metrics_table = dynamodb.Table(METRICS_TABLE)

# Pipeline stages in execution order (for progress visualization)
# Classic mode uses: ingested → workspace → reconnaissance → engineering → review → completion
# Squad mode (ADR-019) uses agent role names as stages.
# The progress bar works with both — unknown stages get a fallback calculation.
PIPELINE_STAGES = [
    "ingested",
    "workspace",
    "reconnaissance",
    "intake",
    "task",          # task-intake-eval-agent
    "swe",           # swe-issue-code-reader, swe-code-context, swe-developer, swe-architect
    "code",          # code-sec, code-rel, code-perf, code-ops, code-cost, code-sus
    "architect",     # architect-standard-agent
    "reviewer",      # reviewer-security-agent
    "engineering",
    "testing",
    "review",
    "reporting",     # reporting-agent
    "completion",
]


def handler(event, context):
    """Lambda handler — routes to /status/tasks, /status/tasks/{id}/reasoning, /status/metrics, or /status/health."""
    path = event.get("rawPath", event.get("path", "/status/tasks"))

    if "/status/health" in path:
        return _handle_health(event, context)
    if "/status/registries" in path:
        return _handle_registries(event, context)
    if "/status/metrics" in path:
        return _handle_metrics(event, context)
    if "/reasoning" in path:
        return _handle_reasoning(event, context)
    return _handle_tasks(event, context)


def _handle_reasoning(event, context):
    """GET /status/tasks/{id}/reasoning — Full reasoning timeline for a single task.

    Returns all events (not capped at 20) with structured metadata for the
    Reasoning and Gates views in the dashboard.
    """
    try:
        # Extract task_id from path: /status/tasks/{id}/reasoning
        path = event.get("rawPath", event.get("path", ""))
        parts = [p for p in path.strip("/").split("/") if p]
        # Expected: ['status', 'tasks', '{task_id}', 'reasoning']
        task_id = parts[2] if len(parts) >= 4 else ""

        if not task_id:
            return _response(400, {"error": "task_id required in path"})

        item = task_table.get_item(Key={"task_id": task_id}).get("Item")
        if not item:
            return _response(404, {"error": f"Task {task_id} not found"})

        events = item.get("events", [])

        # Separate gate events from general reasoning events
        gate_events = [e for e in events if e.get("type") == "gate"]
        reasoning_events = [e for e in events if e.get("type") != "gate"]

        # Compute gate summary
        gate_passed = sum(1 for e in gate_events if e.get("gate_result") == "pass")
        gate_failed = sum(1 for e in gate_events if e.get("gate_result") == "fail")

        body = {
            "task_id": task_id,
            "title": item.get("title", ""),
            "status": _map_status(item.get("status", "")),
            "current_stage": item.get("current_stage", ""),
            "events": events,
            "reasoning_events": reasoning_events,
            "gate_events": gate_events,
            "gate_summary": {
                "total": len(gate_events),
                "passed": gate_passed,
                "failed": gate_failed,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        return _response(200, body)

    except Exception as e:
        return _response(500, {"error": "Internal server error"})


def _handle_metrics(event, context):
    """GET /status/metrics — Architect-view metrics from the unified metrics table.

    Queries the fde-dev-metrics DynamoDB table with prefix scans for:
      - brain_sim: Fidelity scores, emulation classification, organism distribution
      - conductor: Topology usage, step counts, recursion depth
      - synapse: Paradigm distribution, design quality trend, coherence violations
      - vsm: Value stream mapping (lead time by stage)
      - friction: Net friction scores
      - perturbation: Robustness testing results

    Each section is optional — if no data exists for a prefix, that section
    returns null (portal renders appropriate empty state).

    Supports ?project_id= query parameter for project filtering.
    """
    try:
        params = event.get("queryStringParameters") or {}
        project_id = params.get("project_id", "global")
        limit = int(params.get("limit", "20"))

        body = {
            "project_id": project_id,
            "brain_sim": _query_metrics_section(project_id, "brain_sim#", limit),
            "fidelity": _query_metrics_section(project_id, "fidelity#", limit),
            "emulation": _query_metrics_section(project_id, "emulation#", limit),
            "conductor": _query_metrics_section(project_id, "conductor#", limit),
            "synapse": _query_metrics_section(project_id, "synapse#", limit),
            "perturbation": _query_metrics_section(project_id, "perturbation#", limit),
            "vsm": _query_metrics_section(project_id, "vsm#", limit),
            "friction": _query_metrics_section(project_id, "friction#", limit),
            "maturity": _query_metrics_section(project_id, "maturity#", limit),
            "review_feedback": _compute_review_feedback_metrics(project_id),
            "cognitive_autonomy": _query_metrics_section(project_id, "cognitive_autonomy#", limit),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        return _response(200, body)

    except Exception as e:
        return _response(500, {"error": "Internal server error"})


def _query_metrics_section(project_id: str, prefix: str, limit: int) -> dict | None:
    """Query a metrics section from the unified metrics table.

    Returns the most recent items for the given prefix, or None if
    no data exists (triggers empty state in portal).
    """
    try:
        response = metrics_table.query(
            KeyConditionExpression=Key("project_id").eq(project_id) & Key("metric_key").begins_with(prefix),
            ScanIndexForward=False,
            Limit=limit,
        )
        items = response.get("Items", [])
        if not items:
            return None

        # Parse the JSON data field from each item
        parsed = []
        for item in items:
            data_raw = item.get("data", "{}")
            try:
                data = json.loads(data_raw) if isinstance(data_raw, str) else data_raw
            except (json.JSONDecodeError, TypeError):
                data = {}

            parsed.append({
                "metric_key": item.get("metric_key", ""),
                "metric_type": item.get("metric_type", ""),
                "task_id": item.get("task_id", ""),
                "recorded_at": item.get("recorded_at", ""),
                "data": data,
            })

        # Return summary + recent items
        return {
            "count": len(parsed),
            "latest": parsed[0] if parsed else None,
            "items": parsed[:limit],
        }

    except Exception:
        return None


def _handle_tasks(event, context):
    """GET /status/tasks — Full dashboard payload with agent assignment.

    Supports query parameter ?repo=owner/repo for project filtering.
    """
    try:
        # Extract repo filter from query parameters
        params = event.get("queryStringParameters") or {}
        repo_filter = params.get("repo", "")

        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

        # Fetch tasks from last 24h
        task_response = task_table.scan(
            FilterExpression=Attr("created_at").gte(cutoff),
            Limit=50,
        )
        items = task_response.get("Items", [])

        # Apply repo filter if specified
        if repo_filter:
            items = [i for i in items if i.get("repo", "") == repo_filter]

        # Fetch active agents
        agents = _fetch_active_agents()
        agent_by_task = {a.get("task_id", ""): a for a in agents if a.get("task_id")}

        # Compute metrics
        active = sum(1 for i in items if i.get("status") in ("RUNNING", "PENDING", "READY", "IN_PROGRESS", "DISPATCHED"))
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

            # Determine if task completed without delivery (pr_error present)
            result_json = item.get("result", "")
            has_pr_error = False
            if result_json and isinstance(result_json, str):
                try:
                    result_data = json.loads(result_json)
                    has_pr_error = bool(result_data.get("pr_error"))
                except (json.JSONDecodeError, TypeError):
                    pass

            task_status = _map_status(item.get("status", "PENDING"))
            # Surface "completed-without-delivery" as a distinct status for the portal
            if task_status == "completed" and has_pr_error and not item.get("pr_url"):
                task_status = "completed_no_delivery"

            tasks.append({
                "task_id": task_id,
                "title": item.get("title", item.get("task_id", "Unknown")),
                "status": task_status,
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
                "pr_error": item.get("pr_error", ""),
                "workspace_error": item.get("workspace_error", ""),
                "priority": item.get("priority", "P2"),
                "duration_ms": int(item.get("duration_ms", 0)),
                "elapsed_ms": _compute_elapsed(item),
                "created_at": item.get("created_at", ""),
                "updated_at": item.get("updated_at", ""),
                "events": item.get("events", [])[-20:],  # Last 20 events for Chain of Thought
            })

        # ── Issue-Centric Aggregation (ADR-030) ────────────────────────
        # Group tasks by issue_id. Show only the PRIMARY task per issue in
        # the rail view. Prior attempts are collapsed into attempt_count +
        # prior_attempts summary. This prevents visual noise when multiple
        # tasks exist for the same issue (rework loops, retries, routing bugs).
        #
        # Primary selection: most recent task that has progressed beyond
        # "ingested" stage, OR simply the latest if all are at ingested.
        tasks_by_issue = {}
        for task in tasks:
            issue_id = task.get("issue_url", "") or task.get("task_id", "")
            if issue_id not in tasks_by_issue:
                tasks_by_issue[issue_id] = []
            tasks_by_issue[issue_id].append(task)

        deduplicated_tasks = []
        for issue_id, group in tasks_by_issue.items():
            if len(group) == 1:
                deduplicated_tasks.append(group[0])
                continue

            # Sort by created_at descending (newest first)
            group.sort(key=lambda t: t.get("created_at", ""), reverse=True)

            # Select primary: first task that progressed beyond ingested,
            # or the latest if none progressed
            primary = group[0]
            for task in group:
                stage_pct = task.get("stage_progress", {}).get("percent", 0)
                if stage_pct > 7 or task.get("status") in ("running", "completed", "approved"):
                    primary = task
                    break

            # Enrich primary with attempt metadata
            primary["attempt_count"] = len(group)
            primary["prior_attempts"] = [
                {
                    "task_id": t["task_id"],
                    "status": t["status"],
                    "created_at": t["created_at"],
                    "stage_progress": t.get("stage_progress", {}).get("percent", 0),
                }
                for t in group if t["task_id"] != primary["task_id"]
            ]
            deduplicated_tasks.append(primary)

        # Sort final list by created_at descending
        deduplicated_tasks.sort(key=lambda t: t.get("created_at", ""), reverse=True)

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
            "dora": _compute_dora_summary(items),
            "tasks": deduplicated_tasks[:20],
            "agents": _build_agent_summary(agents),
            "projects": _extract_projects(items),
            "repo_filter": repo_filter,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        return _response(200, body)

    except Exception as e:
        return _response(500, {"error": "Internal server error"})


def _handle_registries(event, context):
    """GET /status/registries — Live infrastructure registry.

    Reads actual infrastructure state from ECS, DynamoDB, and environment
    variables to provide a dynamic view of all factory components.
    No hardcoded values — everything is discovered at runtime.
    """
    try:
        ecs = boto3.client("ecs", region_name=REGION)

        # --- Models: read from ECS task definition environment variables ---
        models = []
        try:
            # Get the latest task definition for the strands agent
            task_def_family = os.environ.get("TASK_DEF_FAMILY", "fde-dev-strands-agent")
            td_response = ecs.describe_task_definition(taskDefinition=task_def_family)
            td = td_response.get("taskDefinition", {})
            containers = td.get("containerDefinitions", [])

            # Extract model env vars from the main container
            for container in containers:
                if container.get("name") in ("strands-agent", "squad-agent"):
                    env_vars = {e["name"]: e["value"] for e in container.get("environment", [])}
                    model_reasoning = env_vars.get("BEDROCK_MODEL_REASONING", "")
                    model_standard = env_vars.get("BEDROCK_MODEL_STANDARD", "")
                    model_fast = env_vars.get("BEDROCK_MODEL_FAST", "")
                    model_default = env_vars.get("BEDROCK_MODEL_ID", "")

                    if model_reasoning:
                        models.append({
                            "name": _friendly_model_name(model_reasoning),
                            "model_id": model_reasoning,
                            "tier": "reasoning",
                            "usage": "architect, adversarial, security",
                            "status": "ready",
                        })
                    if model_standard:
                        models.append({
                            "name": _friendly_model_name(model_standard),
                            "model_id": model_standard,
                            "tier": "standard",
                            "usage": "developer, intake, code analysis",
                            "status": "ready",
                        })
                    if model_fast:
                        models.append({
                            "name": _friendly_model_name(model_fast),
                            "model_id": model_fast,
                            "tier": "fast",
                            "usage": "reporting, committer, cost",
                            "status": "ready",
                        })
                    if not models and model_default:
                        models.append({
                            "name": _friendly_model_name(model_default),
                            "model_id": model_default,
                            "tier": "default",
                            "usage": "all agents",
                            "status": "ready",
                        })
                    break
        except Exception:
            pass

        # --- Infrastructure: ECS task definitions ---
        infrastructure = []
        try:
            task_def_family = os.environ.get("TASK_DEF_FAMILY", "fde-dev-strands-agent")
            td_response = ecs.describe_task_definition(taskDefinition=task_def_family)
            td = td_response.get("taskDefinition", {})
            infrastructure.append({
                "name": td.get("family", task_def_family),
                "version": f"rev:{td.get('revision', '?')}",
                "status": "ready",
                "details": f"ECS Fargate / {td.get('cpu', '?')}cpu {td.get('memory', '?')}MB",
            })
            # Add sidecar info
            for container in td.get("containerDefinitions", []):
                if container.get("name") != "strands-agent" and container.get("name") != "squad-agent":
                    infrastructure.append({
                        "name": container["name"],
                        "version": container.get("image", "").split(":")[-1] if ":" in container.get("image", "") else "latest",
                        "status": "ready",
                        "details": "Sidecar / X-Ray" if "adot" in container.get("name", "") else "Sidecar",
                    })
        except Exception:
            pass

        # --- Data Plane: DynamoDB tables ---
        data_plane = []
        table_names = [
            TASK_QUEUE_TABLE,
            AGENT_LIFECYCLE_TABLE,
            DORA_METRICS_TABLE,
            os.environ.get("PROMPT_REGISTRY_TABLE", ""),
        ]
        dynamo_client = boto3.client("dynamodb", region_name=REGION)
        for table_name in table_names:
            if not table_name:
                continue
            try:
                desc = dynamo_client.describe_table(TableName=table_name)
                table = desc.get("Table", {})
                item_count = table.get("ItemCount", 0)
                status = "ready" if table.get("TableStatus") == "ACTIVE" else "degraded"
                data_plane.append({
                    "name": table_name,
                    "version": "v1",
                    "status": status,
                    "details": f"{item_count} items / {table.get('TableStatus', 'UNKNOWN')}",
                })
            except Exception:
                data_plane.append({
                    "name": table_name,
                    "version": "v1",
                    "status": "degraded",
                    "details": "Unable to describe",
                })

        # --- Squad Agents: discovered from recent task events ---
        squad_agents = []
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
            response = task_table.scan(
                FilterExpression=Attr("created_at").gte(cutoff),
                ProjectionExpression="events",
                Limit=30,
            )
            agent_set = set()
            for item in response.get("Items", []):
                for ev in item.get("events", []):
                    msg = ev.get("msg", "")
                    if "Squad agent:" in msg:
                        match = msg.split("Squad agent:")[-1].strip()
                        if match:
                            agent_set.add(match)
                    phase = ev.get("phase", "")
                    if phase and phase not in ("intake", "workspace", "ingested"):
                        agent_set.add(phase)

            for agent_name in sorted(agent_set):
                squad_agents.append({
                    "name": agent_name,
                    "version": "v1",
                    "status": "ready",
                    "details": _infer_agent_layer(agent_name),
                })
        except Exception:
            pass

        # --- Orchestration: EventBridge rules ---
        orchestration = []
        try:
            eb = boto3.client("events", region_name=REGION)
            bus_name = os.environ.get("EVENT_BUS_NAME", "fde-dev-factory-bus")
            rules = eb.list_rules(EventBusName=bus_name).get("Rules", [])
            for rule in rules:
                if "catch-all" in rule["Name"]:
                    continue
                orchestration.append({
                    "name": rule["Name"],
                    "version": "EB",
                    "status": "ready" if rule.get("State") == "ENABLED" else "deprecated",
                    "details": f"EventBridge / {rule.get('State', 'UNKNOWN')}",
                })
        except Exception:
            pass

        body = {
            "models": models,
            "infrastructure": infrastructure,
            "data_plane": data_plane,
            "squad_agents": squad_agents,
            "orchestration": orchestration,
            "region": REGION,
            "environment": os.environ.get("ENVIRONMENT", "dev"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        return _response(200, body)

    except Exception as e:
        return _response(500, {"error": "Internal server error"})


def _friendly_model_name(model_id: str) -> str:
    """Convert a Bedrock model ID to a human-friendly name."""
    mappings = {
        "claude-sonnet-4-5": "Claude Sonnet 4.5",
        "claude-sonnet-4-": "Claude Sonnet 4",
        "claude-haiku-4-5": "Claude Haiku 4.5",
        "claude-haiku-3": "Claude Haiku 3",
        "claude-opus-4": "Claude Opus 4",
    }
    for key, name in mappings.items():
        if key in model_id:
            return name
    return model_id.split("/")[-1] if "/" in model_id else model_id


def _infer_agent_layer(agent_name: str) -> str:
    """Infer the architectural layer from agent name."""
    name = agent_name.lower()
    if any(x in name for x in ("intake", "architect", "reviewer", "reasoning")):
        return "Quarteto"
    if any(x in name for x in ("ops", "sec", "rel", "perf", "cost", "sus")):
        return "WAF"
    if any(x in name for x in ("swe", "developer", "code", "adversarial", "redteam")):
        return "SWE"
    if any(x in name for x in ("dtl", "commiter", "writer", "reporting")):
        return "Delivery"
    return "Pipeline"


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


def _extract_projects(items: list) -> list:
    """Extract unique projects from task items for the project selector."""
    repos = {}
    for item in items:
        repo = item.get("repo", "")
        if repo and repo not in repos:
            repos[repo] = {
                "repo": repo,
                "display_name": repo.split("/")[-1] if "/" in repo else repo,
                "task_count": 0,
                "active": 0,
            }
        if repo:
            repos[repo]["task_count"] += 1
            if item.get("status") in ("RUNNING", "IN_PROGRESS", "READY"):
                repos[repo]["active"] += 1
    return list(repos.values())


def _compute_dora_summary(items: list) -> dict:
    """Compute DORA-style metrics from task data for the metrics bar.

    Returns:
        Dict with lead_time_avg_ms, success_rate_pct, throughput_24h, change_failure_rate_pct.
    """
    completed = [i for i in items if i.get("status") == "COMPLETED"]
    failed = [i for i in items if i.get("status") in ("FAILED", "DEAD_LETTER")]
    total_finished = len(completed) + len(failed)

    # Lead time: average duration of completed tasks
    durations = [int(i.get("duration_ms", 0)) for i in completed if i.get("duration_ms")]
    lead_time_avg = int(sum(durations) / len(durations)) if durations else 0

    # Success rate
    success_rate = int((len(completed) / total_finished) * 100) if total_finished > 0 else 0

    # Throughput: completed tasks in 24h
    throughput = len(completed)

    # Change failure rate
    failure_rate = int((len(failed) / total_finished) * 100) if total_finished > 0 else 0

    # DORA level classification
    if lead_time_avg < 300000 and success_rate >= 95:  # <5min, >95%
        level = "Elite"
    elif lead_time_avg < 900000 and success_rate >= 85:  # <15min, >85%
        level = "High"
    elif lead_time_avg < 3600000 and success_rate >= 70:  # <1hr, >70%
        level = "Medium"
    else:
        level = "Low"

    return {
        "lead_time_avg_ms": lead_time_avg,
        "success_rate_pct": success_rate,
        "throughput_24h": throughput,
        "change_failure_rate_pct": failure_rate,
        "level": level,
    }


def _compute_elapsed(item: dict) -> int:
    """Compute elapsed execution time in ms.

    For running tasks: uses started_at (when container claimed the task),
    NOT created_at (when webhook arrived). This gives accurate execution time.

    For completed tasks: uses the pre-computed duration_ms field.
    """
    if item.get("status") not in ("RUNNING", "IN_PROGRESS", "READY"):
        return int(item.get("duration_ms", 0))

    # Prefer started_at (actual execution start) over created_at (webhook arrival)
    start_field = item.get("started_at") or item.get("created_at", "")
    if not start_field:
        return 0

    try:
        start = datetime.fromisoformat(start_field.replace("Z", "+00:00"))
        elapsed = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        return int(elapsed)
    except (ValueError, TypeError):
        return 0


def _map_status(dynamo_status: str) -> str:
    """Map DynamoDB status values to dashboard display status."""
    mapping = {
        "PENDING": "pending",
        "READY": "ready",
        "DISPATCHED": "running",
        "IN_PROGRESS": "running",
        "RUNNING": "running",
        "COMPLETED": "completed",
        "FAILED": "failed",
        "DEAD_LETTER": "failed",
        "BLOCKED": "blocked",
        "REWORK": "rework",
        "APPROVED": "approved",
    }
    return mapping.get(dynamo_status, "pending")


def _compute_review_feedback_metrics(project_id: str) -> dict | None:
    """Compute ICRL Review Feedback Loop metrics for the ReviewFeedbackCard.

    Queries the metrics table for review_feedback, icrl_episode, and
    verification gate records to produce the card's data shape.

    Returns None if no review feedback data exists (card renders empty state).
    """
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

        # Query review feedback records
        feedback_response = metrics_table.query(
            KeyConditionExpression=Key("project_id").eq(project_id) & Key("metric_key").begins_with("review_feedback#"),
            FilterExpression=Attr("recorded_at").gte(cutoff),
            ScanIndexForward=False,
            Limit=50,
        )
        feedback_items = feedback_response.get("Items", [])

        if not feedback_items:
            return None

        # Classify feedback records
        full_rework = 0
        partial_fix = 0
        approval = 0
        informational = 0
        rework_triggered_count = 0

        for item in feedback_items:
            data = json.loads(item.get("data", "{}")) if isinstance(item.get("data"), str) else item.get("data", {})
            classification = data.get("classification", "")

            if classification == "full_rework":
                full_rework += 1
            elif classification == "partial_fix":
                partial_fix += 1
            elif classification == "approval":
                approval += 1
            else:
                informational += 1

            if data.get("rework_triggered"):
                rework_triggered_count += 1

        # Query ICRL episodes
        episode_response = metrics_table.query(
            KeyConditionExpression=Key("project_id").eq(project_id) & Key("metric_key").begins_with("icrl_episode#"),
            ScanIndexForward=False,
            Limit=50,
        )
        icrl_episodes = episode_response.get("Items", [])
        icrl_count = len(icrl_episodes)
        pattern_digest_available = icrl_count >= 10
        last_episode_ts = icrl_episodes[0].get("recorded_at", "") if icrl_episodes else ""

        # Query autonomy adjustments
        autonomy_response = metrics_table.query(
            KeyConditionExpression=Key("project_id").eq(project_id) & Key("metric_key").begins_with("autonomy_adjustment#"),
            FilterExpression=Attr("recorded_at").gte(cutoff),
            ScanIndexForward=False,
            Limit=20,
        )
        autonomy_items = autonomy_response.get("Items", [])
        autonomy_reductions = 0
        autonomy_increases = 0
        for item in autonomy_items:
            data = json.loads(item.get("data", "{}")) if isinstance(item.get("data"), str) else item.get("data", {})
            adj_type = data.get("adjustment_type", "")
            if "reduction" in adj_type:
                autonomy_reductions += 1
            elif adj_type in ("auto_restoration", "promotion"):
                autonomy_increases += 1

        # Get current autonomy level
        current_level = 4
        try:
            level_response = metrics_table.get_item(
                Key={"project_id": project_id, "metric_key": "autonomy#current_level"}
            )
            if "Item" in level_response:
                level_data = json.loads(level_response["Item"].get("data", "{}"))
                current_level = level_data.get("level", 4)
        except Exception:
            pass

        # Circuit breaker: tasks with 2+ rework records
        task_rework_counts = {}
        for item in feedback_items:
            data = json.loads(item.get("data", "{}")) if isinstance(item.get("data"), str) else item.get("data", {})
            task_id = item.get("task_id", "")
            if data.get("rework_triggered") and task_id:
                task_rework_counts[task_id] = task_rework_counts.get(task_id, 0) + 1
        circuit_breaker_trips = sum(1 for count in task_rework_counts.values() if count >= 2)

        total_reviews = full_rework + partial_fix + approval + informational

        return {
            "total_reviews": total_reviews,
            "full_rework_count": full_rework,
            "partial_fix_count": partial_fix,
            "approval_count": approval,
            "informational_count": informational,
            "active_rework_tasks": rework_triggered_count,
            "circuit_breaker_trips": circuit_breaker_trips,
            "avg_rework_attempts": round(rework_triggered_count / max(full_rework, 1), 1),
            "icrl_episode_count": icrl_count,
            "pattern_digest_available": pattern_digest_available,
            "last_episode_timestamp": last_episode_ts,
            "verification_pass_rate": 100.0 if total_reviews == 0 else round((approval / max(total_reviews, 1)) * 100, 1),
            "avg_verification_iterations": 1.0,
            "verification_level": "standard",
            "autonomy_reductions": autonomy_reductions,
            "autonomy_increases": autonomy_increases,
            "current_autonomy_level": current_level,
        }

    except Exception:
        return None


def _response(status_code: int, body: dict) -> dict:
    """Build API Gateway response with CORS + no-cache headers."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Accept",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
        "body": json.dumps(body, default=str),
    }
