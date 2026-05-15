"""
Scheduled Reaper Lambda — Self-healing for stuck tasks.

Triggered every 5 minutes by CloudWatch Events. Runs independently
of the orchestrator so stuck tasks are healed even when no new events arrive.

Fixes:
  - Pipeline loose end #1 — stuck tasks block concurrency slots indefinitely.
  - Concurrency deadlock — counter drift from ungraceful ECS stops blocks all queued tasks.
  - Death spiral detection — tasks stuck at ingested stage due to under-resourcing.
"""
import json
import logging
import os

logger = logging.getLogger("fde.reaper")
logger.setLevel(logging.INFO)


def handler(event, context):
    """CloudWatch Events scheduled handler."""
    # Import here to allow Lambda cold start optimization
    from . import task_queue

    logger.info("Reaper triggered (scheduled)")

    # Phase 1: Reap stuck tasks (existing behavior)
    reaped = task_queue.reap_stuck_tasks(max_age_minutes=60)

    result = {
        "reaped_count": len(reaped),
        "reaped_task_ids": reaped,
    }

    if reaped:
        logger.warning("Reaper healed %d stuck tasks: %s", len(reaped), reaped)

    # Phase 2: Reconcile concurrency counters (fixes counter drift from ungraceful stops)
    drift_fixes = _reconcile_counters(task_queue)
    result["counter_drift_fixes"] = drift_fixes

    # Phase 3: Unblock queued tasks after any healing
    repos_freed = set()
    for task_id in reaped:
        task = task_queue.get_task(task_id)
        if task and task.get("repo"):
            repos_freed.add(task["repo"])

    # Also include repos where counters were corrected
    for repo in drift_fixes:
        repos_freed.add(repo)

    retried = []
    for repo in repos_freed:
        eligible = task_queue.retry_queued_tasks(repo)
        retried.extend(eligible)

    result["repos_freed"] = list(repos_freed)
    result["retried_task_ids"] = retried

    if not reaped and not drift_fixes:
        logger.info("Reaper: no stuck tasks or counter drift found")

    return result


def _reconcile_counters(task_queue) -> dict:
    """Reconcile atomic counters against actual IN_PROGRESS/RUNNING tasks.

    Detects counter drift caused by:
    - ECS tasks stopped externally (SIGKILL, spot interruption, manual stop)
    - Container crashes before decrement_active_counter runs
    - Network partitions during graceful shutdown

    For each repo, compares:
      counter_value (what DynamoDB thinks is active)
      actual_active (tasks actually in IN_PROGRESS/RUNNING status)

    If counter > actual: resets counter to actual (releases phantom slots).
    This unblocks queued tasks that were waiting for a slot that will never free.

    Returns:
        Dict of {repo: {"counter_was": N, "actual_active": M, "corrected_to": M}}
    """
    import boto3
    from boto3.dynamodb.conditions import Key

    table_name = os.environ.get("TASK_QUEUE_TABLE", "fde-dev-task-queue")
    region = os.environ.get("AWS_REGION", "us-east-1")
    table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    fixes = {}

    # Scan for all COUNTER# items
    response = table.scan(
        FilterExpression="begins_with(task_id, :prefix)",
        ExpressionAttributeValues={":prefix": "COUNTER#"},
    )

    for item in response.get("Items", []):
        task_id_key = item.get("task_id", "")
        repo = task_id_key.replace("COUNTER#", "")
        counter_value = int(item.get("active_count", 0))

        if counter_value <= 0:
            continue  # No drift possible if counter is already 0

        # Count actual active tasks for this repo
        actual_active = 0
        for status in ("IN_PROGRESS", "RUNNING"):
            items = table.query(
                IndexName="status-created-index",
                KeyConditionExpression=Key("status").eq(status),
            ).get("Items", [])
            actual_active += sum(1 for t in items if t.get("repo") == repo)

        # Detect drift: counter says N active, but only M actually are
        if counter_value > actual_active:
            logger.warning(
                "Counter drift detected: repo=%s counter=%d actual=%d — correcting to %d",
                repo, counter_value, actual_active, actual_active,
            )

            # Reset counter to actual value
            table.update_item(
                Key={"task_id": f"COUNTER#{repo}"},
                UpdateExpression="SET active_count = :actual, updated_at = :now",
                ExpressionAttributeValues={
                    ":actual": actual_active,
                    ":now": task_queue._now(),
                },
            )

            fixes[repo] = {
                "counter_was": counter_value,
                "actual_active": actual_active,
                "corrected_to": actual_active,
            }

    if fixes:
        logger.warning("Counter reconciliation fixed %d repos: %s", len(fixes), list(fixes.keys()))

    return fixes
