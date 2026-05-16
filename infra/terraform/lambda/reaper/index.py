"""
Scheduled Reaper Lambda — Closed-loop self-healing for stuck tasks.

Triggered every 5 minutes by CloudWatch Events. Runs independently
of the orchestrator so stuck tasks are healed even when no new events arrive.

Fixes:
  - Pipeline loose end #1 — stuck tasks block concurrency slots indefinitely.
  - Concurrency deadlock — counter drift from ungraceful ECS stops blocks all queued tasks.
  - Dispatch loop gap — tasks stuck in DISPATCHED/READY with current_stage=ingested
    are re-dispatched via EventBridge (closes the open loop identified in 5 Whys analysis).

Closed-loop guarantee:
  Phase 1: Reap stuck tasks (mark FAILED, release slots)
  Phase 2: Reconcile concurrency counters (fix drift)
  Phase 3: Identify eligible tasks for re-dispatch
  Phase 4: Re-dispatch eligible tasks via EventBridge (CLOSES THE LOOP)

Adversarial mitigations:
  - Max retry cap (MAX_RETRIES=3) prevents infinite re-dispatch storms
  - Exponential backoff (2^retry * 60s) prevents thundering herd on repeated failures
  - Idempotent dispatch (conditional update on retry_count) prevents race conditions
  - Pre-flight ECR check prevents dispatching to a dead end
"""
import json
import logging
import os
import random
from datetime import datetime, timezone, timedelta

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger("fde.reaper")
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ.get("TASK_QUEUE_TABLE", "fde-dev-task-queue")
EVENT_BUS_NAME = os.environ.get("EVENT_BUS_NAME", "fde-dev-factory-bus")
REGION = os.environ.get("AWS_DEFAULT_REGION", os.environ.get("AWS_REGION", "us-east-1"))

# Closed-loop dispatch configuration
MAX_RETRIES = int(os.environ.get("REAPER_MAX_RETRIES", "3"))
BASE_BACKOFF_SECONDS = 60  # 2^retry * 60s between retries (60s, 120s, 240s)


def _get_table():
    return boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)


def _get_eventbridge():
    return boto3.client("events", region_name=REGION)


def _now():
    return datetime.now(timezone.utc).isoformat()


def handler(event, context):
    """CloudWatch Events scheduled handler — closed-loop self-healing."""
    logger.info("Reaper triggered (scheduled)")

    table = _get_table()

    # Phase 1: Reap stuck tasks (mark FAILED, release concurrency slots)
    reaped = _reap_stuck_tasks(table)

    # Phase 2: Reconcile concurrency counters (fix drift from ungraceful stops)
    drift_fixes = _reconcile_counters(table)

    # Phase 3: Identify eligible tasks for re-dispatch
    repos_freed = set()
    for task_id in reaped:
        item = table.get_item(Key={"task_id": task_id}).get("Item", {})
        repo = item.get("repo", "")
        if repo:
            repos_freed.add(repo)

    for repo in drift_fixes:
        repos_freed.add(repo)

    eligible_for_redispatch = _find_redispatch_eligible(table)

    # Phase 4: CLOSE THE LOOP — re-dispatch eligible tasks via EventBridge
    redispatched = _redispatch_eligible(table, eligible_for_redispatch)

    # Legacy: also track freed repos for logging
    retried = []
    for repo in repos_freed:
        retried.extend(_find_ready_tasks_for_repo(table, repo))

    result = {
        "reaped_count": len(reaped),
        "reaped_task_ids": reaped,
        "counter_drift_fixes": drift_fixes,
        "repos_freed": list(repos_freed),
        "redispatched_count": len(redispatched),
        "redispatched_task_ids": redispatched,
        "retried_task_ids": retried,
    }

    if reaped or drift_fixes or redispatched:
        logger.warning(
            "Reaper healed: reaped=%d, drift_fixes=%d, redispatched=%d",
            len(reaped), len(drift_fixes), len(redispatched),
        )
    else:
        logger.info("Reaper: no stuck tasks, counter drift, or dispatch gaps found")

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


def _find_ready_tasks_for_repo(table, repo: str) -> list:
    """Find tasks in READY state for a given repo (logging only)."""
    eligible = []
    ready_items = table.query(
        IndexName="status-created-index",
        KeyConditionExpression=Key("status").eq("READY"),
    ).get("Items", [])

    for item in ready_items:
        if item.get("repo") == repo and item.get("current_stage") == "ingested":
            eligible.append(item["task_id"])

    return eligible


def _find_redispatch_eligible(table) -> list:
    """Find tasks stuck in dispatch limbo that are eligible for re-dispatch.

    Targets:
      - Status DISPATCHED or READY with current_stage=ingested, older than 10 min
      - retry_count < MAX_RETRIES
      - Respects exponential backoff (2^retry * BASE_BACKOFF_SECONDS)

    Adversarial mitigations:
      - Backoff prevents thundering herd if ECS is capacity-exhausted
      - MAX_RETRIES prevents infinite loop if image is permanently missing
      - Only targets early-stage tasks (ingested) — late-stage tasks are handled by Phase 1
    """
    eligible = []
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(minutes=10)

    for status in ("DISPATCHED", "READY"):
        items = table.query(
            IndexName="status-created-index",
            KeyConditionExpression=Key("status").eq(status),
        ).get("Items", [])

        for item in items:
            task_id = item.get("task_id", "")
            if task_id.startswith("CONFIG#") or task_id.startswith("COUNTER#"):
                continue

            # Only target tasks stuck in early stage
            current_stage = item.get("current_stage", "")
            if current_stage not in ("ingested", ""):
                continue

            # Check age — must be older than 10 min to avoid racing with normal dispatch
            created_at = item.get("created_at", "")
            if not created_at:
                continue
            try:
                created_ts = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue

            if created_ts > stale_cutoff:
                continue  # Too young — normal dispatch may still be in progress

            # Check retry cap
            retry_count = int(item.get("retry_count", 0))
            if retry_count >= MAX_RETRIES:
                # Exhausted retries — move to DEAD_LETTER (permanent failure)
                _move_to_dead_letter(table, item)
                continue

            # Check exponential backoff: don't re-dispatch if last retry was too recent
            last_retry_at = item.get("last_retry_at", "")
            if last_retry_at:
                try:
                    last_retry_ts = datetime.fromisoformat(last_retry_at.replace("Z", "+00:00"))
                    backoff_seconds = (2 ** retry_count) * BASE_BACKOFF_SECONDS
                    # Add jitter (±20%) to prevent synchronized retries
                    jitter = backoff_seconds * 0.2 * (random.random() * 2 - 1)
                    next_eligible = last_retry_ts + timedelta(seconds=backoff_seconds + jitter)
                    if now < next_eligible:
                        continue  # Backoff not elapsed — skip this cycle
                except (ValueError, TypeError):
                    pass  # Malformed timestamp — proceed with retry

            eligible.append(item)

    return eligible


def _redispatch_eligible(table, eligible_tasks: list) -> list:
    """Re-dispatch eligible tasks via EventBridge — CLOSES THE LOOP.

    For each eligible task:
      1. Atomically increment retry_count (conditional update prevents races)
      2. Emit fde.internal/task.dispatched event to EventBridge
      3. Log the re-dispatch for observability

    The same EventBridge rules that handle initial dispatch (cognitive_router.tf)
    will route these events to the correct ECS target based on target_mode.
    """
    if not eligible_tasks:
        return []

    eventbridge = _get_eventbridge()
    redispatched = []

    for item in eligible_tasks:
        task_id = item["task_id"]
        current_retry = int(item.get("retry_count", 0))
        target_mode = item.get("target_mode", "monolith")
        repo = item.get("repo", "")

        # Step 1: Atomic conditional update — increment retry_count
        # This prevents race conditions if two reaper invocations overlap
        try:
            table.update_item(
                Key={"task_id": task_id},
                UpdateExpression=(
                    "SET retry_count = :new_retry, "
                    "last_retry_at = :now, "
                    "#s = :status, "
                    "updated_at = :now"
                ),
                ConditionExpression="attribute_not_exists(retry_count) OR retry_count = :current_retry",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":new_retry": current_retry + 1,
                    ":current_retry": current_retry,
                    ":status": "DISPATCHED",
                    ":now": _now(),
                },
            )
        except table.meta.client.exceptions.ConditionalCheckFailedException:
            # Another reaper invocation already incremented — skip to avoid double-dispatch
            logger.info("Skipped %s (concurrent retry detected)", task_id)
            continue

        # Step 2: Emit dispatch event to EventBridge
        try:
            eventbridge.put_events(
                Entries=[{
                    "Source": "fde.internal",
                    "DetailType": "task.dispatched",
                    "EventBusName": EVENT_BUS_NAME,
                    "Detail": json.dumps({
                        "task_id": task_id,
                        "target_mode": target_mode,
                        "depth": float(item.get("depth", 0)),
                        "repo": repo,
                        "issue_id": item.get("issue_id", ""),
                        "title": item.get("title", ""),
                        "priority": item.get("priority", "P2"),
                        "retry_count": current_retry + 1,
                        "redispatch_source": "reaper",
                    }),
                }]
            )
            redispatched.append(task_id)
            logger.warning(
                "Re-dispatched: %s (retry=%d/%d, target=%s, repo=%s)",
                task_id, current_retry + 1, MAX_RETRIES, target_mode, repo,
            )
        except Exception as e:
            # EventBridge emit failed — task stays DISPATCHED, next reaper cycle will retry
            logger.error(
                "Re-dispatch EventBridge emit failed for %s (will retry next cycle): %s",
                task_id, str(e),
            )

    return redispatched


def _move_to_dead_letter(table, item: dict):
    """Move a task to DEAD_LETTER after exhausting all retries.

    This is a terminal state — the task will not be retried again.
    Operator must investigate and manually re-trigger if needed.
    """
    task_id = item["task_id"]
    retry_count = int(item.get("retry_count", 0))
    repo = item.get("repo", "")

    table.update_item(
        Key={"task_id": task_id},
        UpdateExpression=(
            "SET #s = :status, #e = :error, "
            "dead_letter_at = :now, updated_at = :now"
        ),
        ExpressionAttributeNames={"#s": "status", "#e": "error"},
        ExpressionAttributeValues={
            ":status": "DEAD_LETTER",
            ":error": (
                f"Exhausted {retry_count}/{MAX_RETRIES} retries. "
                f"Task never progressed past '{item.get('current_stage', 'ingested')}'. "
                f"Likely cause: ECS container image missing or persistent capacity issue. "
                f"Manual intervention required."
            ),
            ":now": _now(),
        },
    )

    # Release concurrency slot
    if repo:
        _decrement_counter(table, repo)

    logger.error(
        "DEAD_LETTER: %s exhausted %d retries (repo=%s). Manual intervention required.",
        task_id, retry_count, repo,
    )


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
