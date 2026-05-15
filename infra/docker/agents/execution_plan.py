"""
Execution Plans with Progress Tracking — Enables resumable pipeline execution.

Allows L3/L4 tasks to resume from the interruption point instead of restarting
the entire pipeline from zero. For tasks that take 30+ minutes, this saves
compute and time.

The execution plan is a structured document that tracks:
  - milestones: ordered list of pipeline stages
  - current_milestone: index of the next milestone to execute
  - progress_log: append-only log of completed milestones with timestamps
  - decision_log: append-only log of decisions made during execution

Storage: filesystem-first (`.kiro/specs/{task_id}/execution_plan.json`).
For headless ECS execution, the same structure is written to S3 via
ProjectContext scoping.

Source: OpenAI PLANS.md Cookbook
Reference: docs/design/task-plan-fde.md (Task 1)
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("fde.execution_plan")


@dataclass
class Milestone:
    """A single pipeline milestone."""

    name: str                            # e.g., "constraint_extraction"
    description: str = ""                # Human-readable description
    status: str = "pending"              # pending | in_progress | completed | skipped
    started_at: str = ""                 # ISO 8601
    completed_at: str = ""               # ISO 8601
    output_summary: str = ""             # Brief summary of what was produced

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "output_summary": self.output_summary,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Milestone":
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            status=data.get("status", "pending"),
            started_at=data.get("started_at", ""),
            completed_at=data.get("completed_at", ""),
            output_summary=data.get("output_summary", ""),
        )


@dataclass
class ProgressEntry:
    """A single entry in the progress log."""

    milestone_name: str
    action: str                          # started | completed | skipped | failed
    timestamp: str = ""
    details: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "milestone_name": self.milestone_name,
            "action": self.action,
            "timestamp": self.timestamp,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProgressEntry":
        return cls(
            milestone_name=data.get("milestone_name", ""),
            action=data.get("action", ""),
            timestamp=data.get("timestamp", ""),
            details=data.get("details", ""),
        )


@dataclass
class DecisionEntry:
    """A single entry in the decision log."""

    decision: str                        # What was decided
    rationale: str = ""                  # Why
    timestamp: str = ""
    milestone_name: str = ""             # Which milestone this relates to

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "rationale": self.rationale,
            "timestamp": self.timestamp,
            "milestone_name": self.milestone_name,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DecisionEntry":
        return cls(
            decision=data.get("decision", ""),
            rationale=data.get("rationale", ""),
            timestamp=data.get("timestamp", ""),
            milestone_name=data.get("milestone_name", ""),
        )


@dataclass
class ExecutionPlan:
    """A resumable execution plan for a pipeline task.

    The plan tracks milestones, progress, and decisions. When the pipeline
    is interrupted and restarted, it reads the plan and resumes from the
    first non-completed milestone.
    """

    task_id: str
    milestones: list[Milestone] = field(default_factory=list)
    current_milestone: int = 0           # Index of next milestone to execute
    progress_log: list[ProgressEntry] = field(default_factory=list)
    decision_log: list[DecisionEntry] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    status: str = "active"               # active | completed | abandoned

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    @property
    def is_complete(self) -> bool:
        """True if all milestones are completed or skipped."""
        return all(
            m.status in ("completed", "skipped") for m in self.milestones
        )

    @property
    def completed_count(self) -> int:
        """Number of completed milestones."""
        return sum(1 for m in self.milestones if m.status == "completed")

    @property
    def total_count(self) -> int:
        """Total number of milestones."""
        return len(self.milestones)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "milestones": [m.to_dict() for m in self.milestones],
            "current_milestone": self.current_milestone,
            "progress_log": [p.to_dict() for p in self.progress_log],
            "decision_log": [d.to_dict() for d in self.decision_log],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ExecutionPlan":
        return cls(
            task_id=data.get("task_id", ""),
            milestones=[Milestone.from_dict(m) for m in data.get("milestones", [])],
            current_milestone=data.get("current_milestone", 0),
            progress_log=[ProgressEntry.from_dict(p) for p in data.get("progress_log", [])],
            decision_log=[DecisionEntry.from_dict(d) for d in data.get("decision_log", [])],
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            status=data.get("status", "active"),
        )


# ─── Plan Operations ────────────────────────────────────────────

def create_plan(
    task_id: str,
    milestone_names: list[str],
    descriptions: Optional[list[str]] = None,
) -> ExecutionPlan:
    """Create a new execution plan with the given milestones.

    Args:
        task_id: Unique identifier for the task.
        milestone_names: Ordered list of milestone names.
        descriptions: Optional descriptions for each milestone.

    Returns:
        A new ExecutionPlan ready for execution.
    """
    if descriptions and len(descriptions) != len(milestone_names):
        descriptions = None

    milestones = [
        Milestone(
            name=name,
            description=(descriptions[i] if descriptions else ""),
        )
        for i, name in enumerate(milestone_names)
    ]

    plan = ExecutionPlan(
        task_id=task_id,
        milestones=milestones,
        current_milestone=0,
    )

    logger.info(
        "Execution plan created: task=%s milestones=%d",
        task_id, len(milestones),
    )

    return plan


def start_milestone(plan: ExecutionPlan) -> ExecutionPlan:
    """Mark the current milestone as in_progress.

    Args:
        plan: The execution plan.

    Returns:
        Updated plan with current milestone marked as in_progress.
    """
    if plan.current_milestone >= len(plan.milestones):
        logger.warning("No more milestones to start (task=%s)", plan.task_id)
        return plan

    milestone = plan.milestones[plan.current_milestone]
    milestone.status = "in_progress"
    milestone.started_at = datetime.now(timezone.utc).isoformat()

    plan.progress_log.append(ProgressEntry(
        milestone_name=milestone.name,
        action="started",
    ))
    plan.updated_at = datetime.now(timezone.utc).isoformat()

    logger.info(
        "Milestone started: %s (%d/%d) task=%s",
        milestone.name, plan.current_milestone + 1, len(plan.milestones), plan.task_id,
    )

    return plan


def complete_milestone(plan: ExecutionPlan, output_summary: str = "") -> ExecutionPlan:
    """Mark the current milestone as completed and advance to the next.

    Args:
        plan: The execution plan.
        output_summary: Brief summary of what was produced.

    Returns:
        Updated plan with milestone completed and index advanced.
    """
    if plan.current_milestone >= len(plan.milestones):
        logger.warning("No more milestones to complete (task=%s)", plan.task_id)
        return plan

    milestone = plan.milestones[plan.current_milestone]
    milestone.status = "completed"
    milestone.completed_at = datetime.now(timezone.utc).isoformat()
    milestone.output_summary = output_summary

    plan.progress_log.append(ProgressEntry(
        milestone_name=milestone.name,
        action="completed",
        details=output_summary,
    ))

    plan.current_milestone += 1
    plan.updated_at = datetime.now(timezone.utc).isoformat()

    # Check if all milestones are done
    if plan.is_complete:
        plan.status = "completed"

    logger.info(
        "Milestone completed: %s (%d/%d) task=%s",
        milestone.name, plan.current_milestone, len(plan.milestones), plan.task_id,
    )

    return plan


def skip_milestone(plan: ExecutionPlan, reason: str = "") -> ExecutionPlan:
    """Skip the current milestone and advance to the next.

    Args:
        plan: The execution plan.
        reason: Why the milestone was skipped.

    Returns:
        Updated plan with milestone skipped and index advanced.
    """
    if plan.current_milestone >= len(plan.milestones):
        return plan

    milestone = plan.milestones[plan.current_milestone]
    milestone.status = "skipped"
    milestone.completed_at = datetime.now(timezone.utc).isoformat()

    plan.progress_log.append(ProgressEntry(
        milestone_name=milestone.name,
        action="skipped",
        details=reason,
    ))

    plan.current_milestone += 1
    plan.updated_at = datetime.now(timezone.utc).isoformat()

    if plan.is_complete:
        plan.status = "completed"

    return plan


def add_decision(plan: ExecutionPlan, decision: str, rationale: str = "") -> ExecutionPlan:
    """Record a decision in the plan's decision log.

    Args:
        plan: The execution plan.
        decision: What was decided.
        rationale: Why.

    Returns:
        Updated plan with decision recorded.
    """
    milestone_name = ""
    if plan.current_milestone < len(plan.milestones):
        milestone_name = plan.milestones[plan.current_milestone].name

    plan.decision_log.append(DecisionEntry(
        decision=decision,
        rationale=rationale,
        milestone_name=milestone_name,
    ))
    plan.updated_at = datetime.now(timezone.utc).isoformat()

    return plan


def resume_from_plan(plan: ExecutionPlan) -> int:
    """Determine the resume point from an existing plan.

    Finds the first milestone that is not completed or skipped.
    Updates current_milestone to that index.

    Args:
        plan: An existing execution plan (loaded from storage).

    Returns:
        The milestone index to resume from (0-based).
    """
    for i, milestone in enumerate(plan.milestones):
        if milestone.status not in ("completed", "skipped"):
            plan.current_milestone = i
            # If it was in_progress (interrupted), reset to pending
            if milestone.status == "in_progress":
                milestone.status = "pending"
                milestone.started_at = ""
                plan.progress_log.append(ProgressEntry(
                    milestone_name=milestone.name,
                    action="resumed",
                    details="Pipeline restarted — resuming from this milestone",
                ))
            plan.updated_at = datetime.now(timezone.utc).isoformat()
            logger.info(
                "Resuming from milestone %d/%d: %s (task=%s)",
                i + 1, len(plan.milestones), milestone.name, plan.task_id,
            )
            return i

    # All milestones complete — nothing to resume
    plan.status = "completed"
    return len(plan.milestones)


# ─── Persistence ─────────────────────────────────────────────────

def save_plan(plan: ExecutionPlan, base_dir: str) -> str:
    """Save the execution plan to the filesystem.

    Args:
        plan: The execution plan to save.
        base_dir: Base directory (e.g., workspace root or .kiro/specs/).

    Returns:
        Path to the saved plan file.
    """
    plan_dir = Path(base_dir) / plan.task_id
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_path = plan_dir / "execution_plan.json"

    plan_path.write_text(
        json.dumps(plan.to_dict(), indent=2, default=str),
        encoding="utf-8",
    )

    logger.info("Plan saved: %s", plan_path)
    return str(plan_path)


def load_plan(task_id: str, base_dir: str) -> Optional[ExecutionPlan]:
    """Load an execution plan from the filesystem.

    Args:
        task_id: The task identifier.
        base_dir: Base directory where plans are stored.

    Returns:
        The loaded ExecutionPlan, or None if not found or invalid.
    """
    plan_path = Path(base_dir) / task_id / "execution_plan.json"

    if not plan_path.exists():
        return None

    try:
        data = json.loads(plan_path.read_text(encoding="utf-8"))
        plan = ExecutionPlan.from_dict(data)
        logger.info("Plan loaded: task=%s milestones=%d current=%d",
                    plan.task_id, len(plan.milestones), plan.current_milestone)
        return plan
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error("Failed to load plan for task %s: %s", task_id, e)
        return None


def plan_exists(task_id: str, base_dir: str) -> bool:
    """Check if an execution plan exists for the given task.

    Args:
        task_id: The task identifier.
        base_dir: Base directory where plans are stored.

    Returns:
        True if a plan file exists.
    """
    plan_path = Path(base_dir) / task_id / "execution_plan.json"
    return plan_path.exists()


# ─── DynamoDB Persistence (cross-container resume) ───────────────


def save_plan_to_dynamodb(plan: ExecutionPlan, table_name: str = "") -> None:
    """Persist execution plan to DynamoDB for cross-container resume.

    Fixes: Pipeline loose end #3 — filesystem plans are lost when
    ECS containers die. DynamoDB persists across container restarts.

    The plan is stored as a JSON string in the task queue table
    using the task_id as the partition key and 'execution_plan' as
    a top-level attribute.
    """
    import boto3

    table_name = table_name or os.environ.get("TASK_QUEUE_TABLE", "fde-dev-task-queue")
    region = os.environ.get("AWS_REGION", "us-east-1")

    table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    try:
        table.update_item(
            Key={"task_id": plan.task_id},
            UpdateExpression="SET execution_plan = :plan, updated_at = :now",
            ExpressionAttributeValues={
                ":plan": json.dumps(plan.to_dict(), default=str),
                ":now": datetime.now(timezone.utc).isoformat(),
            },
        )
        logger.info("Plan persisted to DynamoDB: task=%s", plan.task_id)
    except Exception as e:
        logger.warning("Failed to persist plan to DynamoDB (non-blocking): %s", e)


def load_plan_from_dynamodb(task_id: str, table_name: str = "") -> Optional[ExecutionPlan]:
    """Load execution plan from DynamoDB (cross-container resume).

    Falls back to None if not found or invalid. The orchestrator
    should try DynamoDB first, then filesystem as fallback.
    """
    import boto3

    table_name = table_name or os.environ.get("TASK_QUEUE_TABLE", "fde-dev-task-queue")
    region = os.environ.get("AWS_REGION", "us-east-1")

    table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    try:
        result = table.get_item(Key={"task_id": task_id})
        item = result.get("Item", {})
        plan_json = item.get("execution_plan")

        if not plan_json:
            return None

        data = json.loads(plan_json)
        plan = ExecutionPlan.from_dict(data)
        logger.info(
            "Plan loaded from DynamoDB: task=%s milestones=%d current=%d",
            plan.task_id, len(plan.milestones), plan.current_milestone,
        )
        return plan
    except Exception as e:
        logger.warning("Failed to load plan from DynamoDB for %s: %s", task_id, e)
        return None
