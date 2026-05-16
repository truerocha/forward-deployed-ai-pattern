"""
Checkpoint Manager — Per-step persistence for resume-from-failure.

Provides atomic checkpoint writes to DynamoDB so that if a container dies
mid-execution, the next container can resume from the last successful step
instead of starting from scratch.

Checkpoint data model (stored in the task-queue DynamoDB table):
  - completed_steps: SS (String Set) — IDs of steps that passed their gate
  - current_step: S — ID of the step currently executing (or last attempted)
  - step_results: S (JSON) — detailed results per step (status, duration, output)
  - checkpoint_version: N — monotonically increasing version for conflict detection

Resume logic:
  1. On container start, read checkpoint for task_id
  2. If completed_steps is non-empty, skip those steps
  3. Start execution from the first step NOT in completed_steps
  4. If current_step is set but NOT in completed_steps, that step failed/timed out
     → retry it (idempotent commands assumed)

Design decisions:
  - Checkpoints are stored IN the task-queue item (not a separate table)
    → Single read to get task + checkpoint state
    → No cross-table consistency issues
  - completed_steps uses DynamoDB String Set (SS) for atomic ADD operations
  - step_results is a JSON string (not a Map) to avoid 400KB item size issues
    with deeply nested structures
  - checkpoint_version prevents stale writes from zombie containers

Ref: ADR-038 Wave 2 (Checkpoint per-step)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr

logger = logging.getLogger(__name__)

_TABLE_NAME = os.environ.get("TASK_QUEUE_TABLE", "fde-dev-task-queue")
_REGION = os.environ.get("AWS_REGION", "us-east-1")


def _get_table():
    return boto3.resource("dynamodb", region_name=_REGION).Table(_TABLE_NAME)


def _now():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CheckpointState:
    """Current checkpoint state for a task's execution steps."""

    task_id: str
    completed_steps: set[str] = field(default_factory=set)
    current_step: str = ""
    step_results: dict[str, Any] = field(default_factory=dict)
    checkpoint_version: int = 0
    last_updated: str = ""

    def is_step_completed(self, step_id: str) -> bool:
        """Check if a step has already been completed (gate passed)."""
        return step_id in self.completed_steps

    def get_resume_point(self, ordered_step_ids: list[str]) -> int:
        """Find the index of the first step that needs execution.

        Args:
            ordered_step_ids: List of step IDs in execution order.

        Returns:
            Index of the first non-completed step (0 if none completed).
        """
        for i, step_id in enumerate(ordered_step_ids):
            if step_id not in self.completed_steps:
                return i
        # All steps completed — nothing to resume
        return len(ordered_step_ids)

    def steps_remaining(self, ordered_step_ids: list[str]) -> list[str]:
        """Get list of step IDs that still need execution."""
        return [sid for sid in ordered_step_ids if sid not in self.completed_steps]


def load_checkpoint(task_id: str) -> CheckpointState:
    """Load checkpoint state from DynamoDB for a task.

    If no checkpoint exists (first execution), returns an empty state.
    This is the first call on container start for execution tasks.

    Args:
        task_id: The DynamoDB task_id.

    Returns:
        CheckpointState with completed steps and metadata.
    """
    table = _get_table()

    try:
        response = table.get_item(
            Key={"task_id": task_id},
            ProjectionExpression=(
                "completed_steps, current_step, step_results, "
                "checkpoint_version, updated_at"
            ),
        )
        item = response.get("Item", {})

        if not item:
            logger.info("No checkpoint found for task %s — starting fresh", task_id)
            return CheckpointState(task_id=task_id)

        # DynamoDB String Set → Python set
        completed_raw = item.get("completed_steps", set())
        if isinstance(completed_raw, set):
            completed = completed_raw
        elif isinstance(completed_raw, list):
            completed = set(completed_raw)
        else:
            completed = set()

        # Parse step_results JSON
        step_results_raw = item.get("step_results", "{}")
        try:
            step_results = json.loads(step_results_raw) if isinstance(step_results_raw, str) else {}
        except (json.JSONDecodeError, TypeError):
            step_results = {}

        state = CheckpointState(
            task_id=task_id,
            completed_steps=completed,
            current_step=item.get("current_step", ""),
            step_results=step_results,
            checkpoint_version=int(item.get("checkpoint_version", 0)),
            last_updated=item.get("updated_at", ""),
        )

        if completed:
            logger.info(
                "Checkpoint loaded for task %s: %d steps completed (%s), version=%d",
                task_id, len(completed), ", ".join(sorted(completed)),
                state.checkpoint_version,
            )
        else:
            logger.info("Checkpoint loaded for task %s: no steps completed yet", task_id)

        return state

    except Exception as e:
        logger.warning(
            "Failed to load checkpoint for task %s (starting fresh): %s",
            task_id, e,
        )
        return CheckpointState(task_id=task_id)


def save_step_checkpoint(
    task_id: str,
    step_id: str,
    step_result: dict[str, Any],
    checkpoint_version: int,
) -> int:
    """Atomically checkpoint a completed step.

    Uses DynamoDB ADD for the completed_steps set (atomic, no read-modify-write)
    and conditional write on checkpoint_version to prevent stale zombie writes.

    Args:
        task_id: The DynamoDB task_id.
        step_id: The step that just completed successfully.
        step_result: Result dict for this step (status, duration, output).
        checkpoint_version: Expected current version (optimistic locking).

    Returns:
        New checkpoint_version after the write.

    Raises:
        CheckpointConflictError: If another container wrote a newer checkpoint.
    """
    table = _get_table()
    new_version = checkpoint_version + 1

    try:
        # Merge step_result into existing step_results JSON
        # We read-then-write here, but the version check prevents conflicts
        existing = table.get_item(
            Key={"task_id": task_id},
            ProjectionExpression="step_results",
        ).get("Item", {})

        existing_results_raw = existing.get("step_results", "{}")
        try:
            existing_results = json.loads(existing_results_raw) if isinstance(existing_results_raw, str) else {}
        except (json.JSONDecodeError, TypeError):
            existing_results = {}

        existing_results[step_id] = step_result
        results_json = json.dumps(existing_results, default=str)

        # Atomic update with version check
        table.update_item(
            Key={"task_id": task_id},
            UpdateExpression=(
                "ADD completed_steps :step_set "
                "SET current_step = :current, "
                "step_results = :results, "
                "checkpoint_version = :new_ver, "
                "updated_at = :now"
            ),
            ConditionExpression=(
                Attr("checkpoint_version").not_exists()
                | Attr("checkpoint_version").eq(checkpoint_version)
            ),
            ExpressionAttributeValues={
                ":step_set": {step_id},
                ":current": step_id,
                ":results": results_json,
                ":new_ver": new_version,
                ":now": _now(),
            },
        )

        logger.info(
            "Checkpoint saved: task=%s step=%s version=%d→%d",
            task_id, step_id, checkpoint_version, new_version,
        )
        return new_version

    except table.meta.client.exceptions.ConditionalCheckFailedException:
        logger.error(
            "Checkpoint conflict: task=%s step=%s version=%d — another container wrote a newer checkpoint",
            task_id, step_id, checkpoint_version,
        )
        raise CheckpointConflictError(
            f"Checkpoint version conflict for task {task_id} at step {step_id}. "
            f"Expected version {checkpoint_version} but it was already updated."
        )
    except Exception as e:
        # Non-fatal: log but don't crash the executor
        # The step already executed successfully — worst case we re-run it on resume
        logger.warning(
            "Checkpoint write failed (non-fatal): task=%s step=%s error=%s",
            task_id, step_id, e,
        )
        return checkpoint_version  # Return same version (no increment)


def update_current_step(task_id: str, step_id: str) -> None:
    """Update the current_step field (lightweight, no version check).

    Called at the START of each step for dashboard visibility.
    This is a best-effort write — failure doesn't block execution.

    Args:
        task_id: The DynamoDB task_id.
        step_id: The step about to start executing.
    """
    table = _get_table()
    try:
        table.update_item(
            Key={"task_id": task_id},
            UpdateExpression="SET current_step = :step, updated_at = :now",
            ExpressionAttributeValues={":step": step_id, ":now": _now()},
        )
    except Exception as e:
        logger.debug("current_step update failed (non-blocking): %s", e)


class CheckpointConflictError(Exception):
    """Raised when a checkpoint write conflicts with another container's write."""

    pass
