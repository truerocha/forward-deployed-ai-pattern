"""
Scheduled Reaper Lambda — Self-healing for stuck tasks.

Triggered every 5 minutes by CloudWatch Events. Runs independently
of the orchestrator so stuck tasks are healed even when no new events arrive.

Fixes: Pipeline loose end #1 — stuck tasks block concurrency slots indefinitely.
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

    reaped = task_queue.reap_stuck_tasks(max_age_minutes=60)

    result = {
        "reaped_count": len(reaped),
        "reaped_task_ids": reaped,
    }

    if reaped:
        logger.warning("Reaper healed %d stuck tasks: %s", len(reaped), reaped)

        # Check for queued tasks that can now proceed
        repos_freed = set()
        for task_id in reaped:
            task = task_queue.get_task(task_id)
            if task and task.get("repo"):
                repos_freed.add(task["repo"])

        retried = []
        for repo in repos_freed:
            eligible = task_queue.retry_queued_tasks(repo)
            retried.extend(eligible)

        result["repos_freed"] = list(repos_freed)
        result["retried_task_ids"] = retried
    else:
        logger.info("Reaper: no stuck tasks found")

    return result
