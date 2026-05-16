"""
Webhook Ingest Lambda — Cognitive Router for the Autonomous Code Factory.

Enhanced from simple DynamoDB writer to intelligent dispatch router that:
  1. Ingests ALM webhooks (GitHub, GitLab, Asana) → DynamoDB task_queue
  2. Computes capability depth from issue metadata + metrics (with fallback)
  3. Emits fde.internal/task.dispatched event with target_mode decision
  4. Monolith ECS target (always-on) provides self-healing fallback

Architecture (dual-path, zero single point of failure):
  EventBridge rule fires on issue.labeled
    ├─ Target 1: This Lambda (intelligent routing, ~200ms)
    │   ├─ Writes task_queue (status: DISPATCHED, target_mode: monolith|distributed)
    │   ├─ Computes depth from: issue body (deps, blocks) + metrics (100ms timeout)
    │   ├─ Emits: fde.internal/task.dispatched {target_mode, depth, task_id}
    │   └─ If dispatch fails → task stays READY (monolith fallback handles it)
    │
    └─ Target 2: ECS monolith (ALWAYS starts, 30s cold start)
        ├─ Checks task_queue: if status=DISPATCHED → exit (Lambda handled it)
        └─ If status=READY → Lambda failed → run as fallback

Properties:
  - No single point of failure (dual-path)
  - Intelligent routing for complex tasks (depth ≥ 0.5 → distributed)
  - Self-healing (Lambda failure → monolith fallback via READY status)
  - Graceful degradation (metrics unavailable → metadata-only depth)
  - No static execution_mode variable (cognitive signals decide per-task)

Well-Architected alignment:
  OPS 6: Telemetry — every task tracked from ingestion with depth decision
  REL 2: Workload architecture — decoupled write from execution
  REL 9: Fault isolation — dual-path prevents single point of failure
  COST 7: Right-sizing — simple tasks stay on monolith, complex get squad
"""

import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone

import boto3
from botocore.config import Config

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ─── Configuration ───────────────────────────────────────────────

AWS_REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_REGION_NAME", "us-east-1"))

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
eventbridge = boto3.client("events", region_name=AWS_REGION)

# DynamoDB client with short timeout for metrics reads (Risk 2 mitigation)
_METRICS_CLIENT_CONFIG = Config(
    connect_timeout=0.1,  # 100ms connect timeout
    read_timeout=0.1,     # 100ms read timeout
    retries={"max_attempts": 0},  # No retries — fallback to metadata-only
)
dynamodb_fast = boto3.resource("dynamodb", region_name=AWS_REGION, config=_METRICS_CLIENT_CONFIG)

TASK_QUEUE_TABLE = os.environ.get("TASK_QUEUE_TABLE", "fde-dev-task-queue")
AGENT_LIFECYCLE_TABLE = os.environ.get("AGENT_LIFECYCLE_TABLE", "fde-dev-agent-lifecycle")
METRICS_TABLE = os.environ.get("METRICS_TABLE", "")
EVENT_BUS_NAME = os.environ.get("EVENT_BUS_NAME", "fde-dev-factory-bus")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")

# Depth threshold: tasks at or above this depth route to distributed
DEPTH_THRESHOLD_DISTRIBUTED = float(os.environ.get("DEPTH_THRESHOLD", "0.5"))

# Feature flag: disable cognitive routing (falls back to READY status, monolith handles)
COGNITIVE_ROUTING_ENABLED = os.environ.get("COGNITIVE_ROUTING_ENABLED", "true").lower() == "true"
ECR_REPOSITORY = os.environ.get("ECR_REPOSITORY", "")
ORCHESTRATOR_IMAGE_TAG = os.environ.get("ORCHESTRATOR_IMAGE_TAG", "orchestrator-latest")


# ─── Handler ─────────────────────────────────────────────────────

def handler(event, context):
    """Process EventBridge events: ingest task, compute depth, emit dispatch event.

    EventBridge delivers the event in standard envelope format:
    {
        "source": "fde.github.webhook",
        "detail-type": "issue.labeled",
        "detail": { ...raw webhook payload... }
    }
    """
    start_time = time.time()
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

    # ─── Cognitive Routing: compute depth and decide target mode ──
    if COGNITIVE_ROUTING_ENABLED:
        depth_result = _compute_depth(task, detail)
        target_mode = "distributed" if depth_result["depth"] >= DEPTH_THRESHOLD_DISTRIBUTED else "monolith"

        # Enrich task record with routing decision
        task["target_mode"] = target_mode
        task["depth"] = str(round(depth_result["depth"], 3))
        task["depth_signals"] = json.dumps(depth_result["signals"])
        task["status"] = "DISPATCHED"
    else:
        target_mode = "monolith"
        task["target_mode"] = target_mode
        task["depth"] = "0.0"
        task["depth_signals"] = "{}"
        # status stays READY — monolith picks it up directly

    # ─── ERP Wave 1: Classify spec complexity (textual, ~5ms) ────
    complexity_result = _classify_spec_complexity(task.get("spec_content", ""))
    task["complexity"] = complexity_result["complexity"]
    task["complexity_indicators"] = json.dumps(complexity_result["matched_indicators"])

    # Write task to DynamoDB
    table.put_item(Item=task)

    # Create a provisional agent lifecycle record (CREATED state)
    _create_agent_record(task)

    # ─── Emit dispatch event (non-blocking) ──────────────────────
    if COGNITIVE_ROUTING_ENABLED and task["status"] == "DISPATCHED":
        # Pre-flight: validate dispatch readiness before emitting event
        block_reason = _validate_dispatch_readiness(target_mode)
        if block_reason:
            if block_reason in ("orchestrator_not_ready", "config_read_failed"):
                # Downgrade to monolith — emit dispatch event immediately.
                # The dispatch_distributed EventBridge rule accepts both target_modes
                # and starts strands-agent ECS task. No 10-min reaper wait needed.
                target_mode = "monolith"
                task["target_mode"] = "monolith"
                task["status"] = "DISPATCHED"
                table.update_item(
                    Key={"task_id": task["task_id"]},
                    UpdateExpression="SET target_mode = :tm, #s = :s, updated_at = :t",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={
                        ":tm": "monolith",
                        ":s": "DISPATCHED",
                        ":t": datetime.now(timezone.utc).isoformat(),
                    },
                )
                # Emit dispatch event so ECS starts immediately (closed-loop)
                _emit_dispatch_event(task, depth_result, target_mode)
                logger.info("Downgraded to monolith (dispatched immediately): %s", task["task_id"])
            else:
                # Hard block — infrastructure issue (missing image, etc.)
                table.update_item(
                    Key={"task_id": task["task_id"]},
                    UpdateExpression="SET #s = :s, #e = :e, updated_at = :t",
                    ExpressionAttributeNames={"#s": "status", "#e": "error"},
                    ExpressionAttributeValues={
                        ":s": "BLOCKED",
                        ":e": f"dispatch_preflight_failed: {block_reason}",
                        ":t": datetime.now(timezone.utc).isoformat(),
                    },
                )
                task["status"] = "BLOCKED"
                logger.warning("Task BLOCKED (dispatch pre-flight failed): %s — %s",
                               task["task_id"], block_reason)
        else:
            _emit_dispatch_event(task, depth_result, target_mode)

    elapsed_ms = int((time.time() - start_time) * 1000)
    logger.info(
        "Task ingested: task_id=%s, title=%s, source=%s, depth=%.3f, target=%s, complexity=%s, elapsed=%dms",
        task["task_id"], task["title"], task["source"],
        depth_result["depth"] if COGNITIVE_ROUTING_ENABLED else 0.0,
        target_mode, task.get("complexity", "simple"), elapsed_ms,
    )

    return {
        "statusCode": 200,
        "body": json.dumps({
            "task_id": task["task_id"],
            "status": task["status"],
            "target_mode": target_mode,
            "depth": depth_result["depth"] if COGNITIVE_ROUTING_ENABLED else 0.0,
            "complexity": task.get("complexity", "simple"),
            "elapsed_ms": elapsed_ms,
        }),
    }


# ─── Depth Computation (Risk 2 + Risk 3 mitigation) ─────────────

def _compute_depth(task: dict, detail: dict) -> dict:
    """Compute capability depth from issue metadata + metrics.

    Strategy (Risk 2 — B):
      1. Extract metadata signals from issue body (always available, ~0ms)
      2. Attempt DynamoDB metrics read with 100ms timeout
      3. If metrics unavailable, use metadata-only computation

    Strategy (Risk 3 — B):
      The webhook payload already contains issue.body with full text.
      Parse dependency count, blocking count, and labels directly.

    Returns:
        dict with 'depth' (float 0.0-1.0) and 'signals' (dict of contributing factors)
    """
    signals = {}

    # ─── Phase 1: Metadata signals (always available) ────────────
    body = task.get("spec_content", "")
    labels = _extract_all_labels(detail)

    dependency_count = _count_dependencies(body)
    blocking_count = _count_blocking(body)
    level_label = _extract_level_label(labels)
    order_label = _extract_order_label(labels)

    signals["dependency_count"] = dependency_count
    signals["blocking_count"] = blocking_count
    signals["level_label"] = level_label
    signals["order_label"] = order_label

    # ─── Phase 2: Metrics signals (100ms timeout, fallback) ──────
    metrics_signals = _fetch_metrics_signals(task.get("repo", ""))
    signals.update(metrics_signals)

    # ─── Phase 3: Compute depth ──────────────────────────────────
    depth = _calculate_depth(
        dependency_count=dependency_count,
        blocking_count=blocking_count,
        level_label=level_label,
        order_label=order_label,
        cfr_history=metrics_signals.get("cfr_history", 0.0),
        icrl_failure_count=metrics_signals.get("icrl_failure_count", 0),
    )

    signals["metrics_available"] = metrics_signals.get("metrics_available", False)
    return {"depth": depth, "signals": signals}


def _calculate_depth(
    dependency_count: int = 0,
    blocking_count: int = 0,
    level_label: int = 0,
    order_label: int = 0,
    cfr_history: float = 0.0,
    icrl_failure_count: int = 0,
) -> float:
    """Map cognitive signals to a continuous depth value (0.0-1.0).

    Mirrors the logic in cognitive_autonomy.compute_capability_depth() but
    operates on the subset of signals available at webhook time.

    Key principle: failures INCREASE depth (harder task needs more capability).
    """
    depth = 0.0

    # Level label (factory/level:L1-L5) is the strongest pre-computed signal
    if level_label >= 5:
        depth = max(depth, 0.85)
    elif level_label >= 4:
        depth = max(depth, 0.7)
    elif level_label >= 3:
        depth = max(depth, 0.5)
    elif level_label >= 2:
        depth = max(depth, 0.3)

    # Integration complexity raises floor
    if dependency_count >= 6:
        depth = max(depth, 0.7)
    elif dependency_count >= 4:
        depth = max(depth, 0.6)
    elif dependency_count >= 2:
        depth = max(depth, 0.4)

    # Critical path raises floor
    if blocking_count >= 3:
        depth = max(depth, 0.7)
    elif blocking_count >= 1:
        depth = max(depth, 0.4)

    # High order number suggests later in dependency chain (more context needed)
    if order_label >= 8:
        depth = max(depth, 0.5)

    # Past failures INCREASE capability (recovery, not punishment)
    if icrl_failure_count >= 3:
        depth = max(depth, 0.8)
    elif icrl_failure_count >= 1:
        depth = max(depth, 0.5)

    # High CFR raises capability floor
    if cfr_history > 0.30:
        depth = max(depth, 0.8)
    elif cfr_history > 0.15:
        depth = max(depth, 0.6)

    return max(0.0, min(1.0, depth))


def _count_dependencies(body: str) -> int:
    """Count dependency references in issue body.

    Patterns recognized:
      - "depends on #123" or "depends on org/repo#123"
      - "- [ ] #123" (task list with issue refs)
      - "blocked by #123"
      - YAML front-matter: "depends_on: [TASK-xxx, TASK-yyy]"
    """
    if not body:
        return 0

    patterns = [
        r"depends\s+on\s+[#\w/]+",
        r"blocked\s+by\s+[#\w/]+",
        r"-\s*\[[ x]\]\s*#\d+",
        r"depends_on:\s*\[([^\]]+)\]",
    ]

    count = 0
    for pattern in patterns:
        matches = re.findall(pattern, body, re.IGNORECASE)
        count += len(matches)

    return count


def _count_blocking(body: str) -> int:
    """Count how many other tasks this issue blocks.

    Patterns recognized:
      - "blocks #123"
      - "blocking: [TASK-xxx, TASK-yyy]"
    """
    if not body:
        return 0

    patterns = [
        r"blocks\s+[#\w/]+",
        r"blocking:\s*\[([^\]]+)\]",
    ]

    count = 0
    for pattern in patterns:
        matches = re.findall(pattern, body, re.IGNORECASE)
        count += len(matches)

    return count


def _extract_level_label(labels: list[str]) -> int:
    """Extract factory level from labels (factory/level:L1 → 1)."""
    for label in labels:
        match = re.match(r"factory/level:L(\d+)", label)
        if match:
            return int(match.group(1))
    return 0


def _extract_order_label(labels: list[str]) -> int:
    """Extract factory order from labels (factory/order:08 → 8)."""
    for label in labels:
        match = re.match(r"factory/order:(\d+)", label)
        if match:
            return int(match.group(1))
    return 0


def _extract_all_labels(detail: dict) -> list[str]:
    """Extract all label names from the webhook payload (platform-agnostic)."""
    labels = []

    # GitHub: detail.issue.labels[].name
    issue = detail.get("issue", {})
    for label in issue.get("labels", []):
        name = label.get("name", "") if isinstance(label, dict) else str(label)
        if name:
            labels.append(name)

    # GitLab: detail.object_attributes.labels[].title
    attrs = detail.get("object_attributes", {})
    for label in attrs.get("labels", []):
        title = label.get("title", "") if isinstance(label, dict) else str(label)
        if title:
            labels.append(title)

    return labels


def _fetch_metrics_signals(repo: str) -> dict:
    """Fetch CFR and ICRL metrics from DynamoDB with 100ms timeout.

    If the read fails or times out, returns empty signals (graceful degradation).
    The depth computation will use metadata-only in that case.
    """
    if not METRICS_TABLE or not repo:
        return {"metrics_available": False, "cfr_history": 0.0, "icrl_failure_count": 0}

    try:
        table = dynamodb_fast.Table(METRICS_TABLE)

        # Query recent CFR metrics for this project
        response = table.query(
            KeyConditionExpression="project_id = :pid AND begins_with(metric_key, :prefix)",
            ExpressionAttributeValues={
                ":pid": repo,
                ":prefix": "trust#cfr#",
            },
            ScanIndexForward=False,  # Most recent first
            Limit=1,
        )

        cfr_history = 0.0
        items = response.get("Items", [])
        if items:
            data = json.loads(items[0].get("data", "{}"))
            cfr_history = float(data.get("cfr_value", data.get("value", 0.0)))

        # Query ICRL failure episodes
        response_icrl = table.query(
            KeyConditionExpression="project_id = :pid AND begins_with(metric_key, :prefix)",
            ExpressionAttributeValues={
                ":pid": repo,
                ":prefix": "autonomy_adjustment#",
            },
            ScanIndexForward=False,
            Limit=5,
        )

        icrl_failure_count = len(response_icrl.get("Items", []))

        return {
            "metrics_available": True,
            "cfr_history": cfr_history,
            "icrl_failure_count": icrl_failure_count,
        }

    except Exception as e:
        # Graceful degradation: metrics unavailable → metadata-only depth
        logger.warning("Metrics fetch failed (using metadata-only depth): %s", str(e))
        return {"metrics_available": False, "cfr_history": 0.0, "icrl_failure_count": 0}


# ─── Dispatch Event Emission ─────────────────────────────────────

def _validate_dispatch_readiness(target_mode: str) -> str | None:
    """Pre-flight validation before dispatching to ECS.

    Reads runtime routing config from DynamoDB (CONFIG#dispatch_routing).
    This allows the orchestrator to self-register when ready, and the reaper
    to deregister it on failure — no Terraform deploy needed to change routing.

    Behavior:
    - If target_mode=monolith: always ready (no validation needed)
    - If target_mode=distributed: check CONFIG#dispatch_routing.orchestrator_ready
      - If true: validate ECR image exists, proceed with distributed
      - If false (default): return block reason → caller downgrades to monolith

    Returns None if ready, or a human-readable block reason string.
    """
    if target_mode != "distributed":
        return None  # Monolith mode doesn't need validation

    # Check DynamoDB runtime config for orchestrator readiness
    try:
        table = dynamodb.Table(TASK_QUEUE_TABLE)
        config = table.get_item(Key={"task_id": "CONFIG#dispatch_routing"}).get("Item", {})
        orchestrator_ready = config.get("orchestrator_ready", False)

        if not orchestrator_ready:
            return "orchestrator_not_ready"  # Caller will downgrade to monolith
    except Exception as e:
        # DynamoDB read failed — safe default: orchestrator not ready
        logger.warning("Dispatch config read failed (defaulting to monolith): %s", str(e))
        return "config_read_failed"

    # Orchestrator is registered as ready — validate ECR image exists
    if not ECR_REPOSITORY:
        return "ECR_REPOSITORY env var not configured — cannot validate image"

    try:
        ecr = boto3.client("ecr", region_name=AWS_REGION)
        ecr.describe_images(
            repositoryName=ECR_REPOSITORY,
            imageIds=[{"imageTag": ORCHESTRATOR_IMAGE_TAG}],
        )
        return None  # Image exists + orchestrator registered → ready
    except ecr.exceptions.ImageNotFoundException:
        return f"ECR image '{ECR_REPOSITORY}:{ORCHESTRATOR_IMAGE_TAG}' not found — push image before dispatching"
    except Exception as e:
        # Don't block on transient ECR API errors — let dispatch proceed
        logger.warning("ECR pre-flight check failed (non-blocking): %s", str(e))
        return None


def _emit_dispatch_event(task: dict, depth_result: dict, target_mode: str) -> None:
    """Emit fde.internal/task.dispatched event to EventBridge.

    Two separate EventBridge rules (filtered by target_mode) will start
    the correct ECS task definition:
      - target_mode=monolith → strands-agent task def
      - target_mode=distributed → orchestrator task def

    Non-blocking: if PutEvents fails, the task stays DISPATCHED in DynamoDB.
    The monolith fallback (always-on Target 2) will detect DISPATCHED status
    and exit cleanly. If this Lambda fails entirely, task stays READY and
    monolith runs as fallback.
    """
    try:
        # Sanitize all fields before emission — prevents InputTransformer JSON
        # breakage from user-generated content (titles with quotes, newlines, etc.)
        # See ADR-036 for root cause analysis and decision record.
        from shared.eventbridge_sanitizer import sanitize_dispatch_detail

        raw_detail = {
            "task_id": task["task_id"],
            "target_mode": target_mode,
            "depth": depth_result["depth"],
            "repo": task.get("repo", ""),
            "issue_id": task.get("issue_id", ""),
            "title": task.get("title", ""),
            "priority": task.get("priority", "P2"),
            "signals": depth_result["signals"],
        }
        sanitized_detail = sanitize_dispatch_detail(raw_detail)

        response = eventbridge.put_events(
            Entries=[{
                "Source": "fde.internal",
                "DetailType": "task.dispatched",
                "EventBusName": EVENT_BUS_NAME,
                "Detail": json.dumps(sanitized_detail),
            }]
        )
        # Validate response — put_events returns 200 even when entries fail
        failed_count = response.get("FailedEntryCount", 0)
        if failed_count > 0:
            entry_error = response.get("Entries", [{}])[0]
            logger.error(
                "EventBridge PutEvents FAILED (entry rejected): task_id=%s error=%s code=%s",
                task["task_id"],
                entry_error.get("ErrorMessage", "unknown"),
                entry_error.get("ErrorCode", "unknown"),
            )
        else:
            logger.info("Dispatch event emitted: task_id=%s target_mode=%s depth=%.3f",
                        task["task_id"], target_mode, depth_result["depth"])
    except Exception as e:
        # Non-blocking: monolith fallback will handle if this fails
        logger.error("Failed to emit dispatch event (monolith fallback active): %s", str(e))


# ─── ALM Ingest Functions (unchanged) ────────────────────────────

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
    labels = [lbl.get("title", "") for lbl in attrs.get("labels", [])]

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


# ─── Helper Functions ────────────────────────────────────────────

def _create_agent_record(task: dict) -> None:
    """Create a provisional agent lifecycle record for dashboard visibility.

    Agent name is derived from the task context:
    - target_mode: distributed → 'orchestrator', monolith → 'monolith-agent'
    - depth >= 0.7 → 'deep-orchestrator' (full squad)
    - depth >= 0.4 → 'standard-orchestrator' (partial squad)
    - depth < 0.4 → 'fast-agent' (single agent, no squad)

    The name is provisional — the actual ECS container may override it
    once the Conductor assigns specific roles. But this gives the portal
    a meaningful label from the moment the task is ingested.
    """
    try:
        lifecycle_table = dynamodb.Table(AGENT_LIFECYCLE_TABLE)
        now = datetime.now(timezone.utc).isoformat()
        instance_id = f"AGENT-{uuid.uuid4().hex[:8]}"

        # Derive agent role from task context
        target_mode = task.get("target_mode", "monolith")
        depth = float(task.get("depth", 0.5))

        if target_mode == "distributed":
            if depth >= 0.7:
                agent_name = "deep-orchestrator"
            elif depth >= 0.4:
                agent_name = "standard-orchestrator"
            else:
                agent_name = "fast-orchestrator"
        else:
            if depth >= 0.7:
                agent_name = "deep-agent"
            elif depth >= 0.4:
                agent_name = "standard-agent"
            else:
                agent_name = "fast-agent"

        lifecycle_table.put_item(Item={
            "agent_instance_id": instance_id,
            "agent_name": agent_name,
            "task_id": task["task_id"],
            "task_title": task.get("title", "")[:100],
            "model_id": "pending-assignment",
            "target_mode": target_mode,
            "depth": str(depth),
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

    Scans READY, IN_PROGRESS, RUNNING, DISPATCHED, and recently-FAILED tasks.
    If found in an active state, returns the existing record to prevent duplicates.
    If found in FAILED state within the cooldown window, also blocks (prevents
    retry storms when the same issue keeps failing).

    Stale task TTL: If a task has been in a non-terminal state for >30 minutes
    without an updated_at change, it's considered stale and won't block new tasks.

    Failed task cooldown: If a task FAILED less than 15 minutes ago for the same
    issue, block new task creation (prevents retry storm from repeated webhooks).
    After 15 minutes, allow retry (user may have fixed the issue content).
    """
    if not issue_id:
        return None

    FAILED_COOLDOWN_MINUTES = 15

    try:
        # Check active tasks (non-terminal states)
        response = table.scan(
            FilterExpression="issue_id = :iid AND #s IN (:s1, :s2, :s3, :s4)",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":iid": issue_id,
                ":s1": "READY",
                ":s2": "IN_PROGRESS",
                ":s3": "RUNNING",
                ":s4": "DISPATCHED",
            },
            Limit=5,
        )
        items = response.get("Items", [])

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

        # Check recently-FAILED tasks (cooldown prevents retry storm)
        failed_response = table.scan(
            FilterExpression="issue_id = :iid AND #s = :failed",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":iid": issue_id,
                ":failed": "FAILED",
            },
            Limit=5,
        )
        failed_items = failed_response.get("Items", [])

        for item in failed_items:
            updated_at_str = item.get("updated_at", item.get("created_at", ""))
            if updated_at_str:
                try:
                    updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
                    age_minutes = (now - updated_at).total_seconds() / 60
                    if age_minutes < FAILED_COOLDOWN_MINUTES:
                        logger.info(
                            "Task %s for issue %s FAILED %.0f min ago (cooldown=%d min) — blocking retry storm",
                            item.get("task_id"), issue_id, age_minutes, FAILED_COOLDOWN_MINUTES,
                        )
                        return item  # Block — too soon to retry
                except (ValueError, TypeError):
                    pass

        return None
    except Exception as e:
        logger.warning("Deduplication check failed (proceeding with insert): %s", e)
        return None


# ─── ERP Wave 1: Spec Complexity Classification ─────────────────

# Indicators that suggest the task requires multi-step execution
_EXECUTION_INDICATORS = {
    "bash_commands": r"```bash\s*\n",
    "pytest_execution": r"pytest\s+\S+",
    "artifact_generation": r"git\s+add\s+\S+",
    "sequential_gates": r"\*\*Gate\*\*\s*:",
    "multi_part": r"###\s+Part\s+[A-Z]",
    "script_execution": r"python3?\s+scripts/",
    "dependency_chain": r"[A-Z]\d+.*\u2192.*[A-Z]\d+|then\s+[A-Z]\d+",
    "step_numbering": r"####\s+[A-Z]\d+[\.\s:]",
    "validation_markers": r"\*\*(?:Validation|Verify|Assert)\*\*\s*:",
    "file_generation": r"(?:generate|create|write)\s+(?:artifacts?|files?)/",
}

_EXECUTION_THRESHOLD = 3


def _classify_spec_complexity(spec_content: str) -> dict:
    """Classify spec complexity based on textual indicators (~5ms).

    Runs at Lambda time to enrich the task record with complexity metadata.
    The ECS entrypoint uses this field to decide whether to use the
    step-by-step executor (complexity=execution) or the standard pipeline.

    Classification:
      - "simple": No execution indicators (standard code gen)
      - "standard": Some structure but not multi-step execution
      - "execution": Multi-step with scripts, gates, sequential deps

    Returns:
        dict with 'complexity' and 'matched_indicators' fields.
    """
    if not spec_content:
        return {"complexity": "simple", "matched_indicators": []}

    matched = []
    for name, pattern in _EXECUTION_INDICATORS.items():
        if re.search(pattern, spec_content, re.IGNORECASE):
            matched.append(name)

    if len(matched) >= _EXECUTION_THRESHOLD:
        complexity = "execution"
    elif len(matched) >= 1:
        complexity = "standard"
    else:
        complexity = "simple"

    logger.info(
        "ERP classification: complexity=%s indicators=%d matched=%s",
        complexity, len(matched), matched,
    )

    return {"complexity": complexity, "matched_indicators": matched}
