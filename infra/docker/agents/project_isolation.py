"""
Project Isolation — Ensures each task runs in its own namespace with zero
cross-project interference. The Code Factory acts like a SaaS kernel where
each project gets an isolated execution context.

Isolation boundaries:
  - S3: Each task writes to s3://{bucket}/projects/{task_id}/...
  - DynamoDB: task_id is the partition key (already isolated)
  - ECS: Each EventBridge event spawns a new Fargate task (process isolation)
  - Agent Registry: Transient agents are scoped to task_id (memory isolation)
  - Working directory: /tmp/workspace/{task_id} (filesystem isolation)
  - Git: Each task gets its own branch (never touches main)

The ProjectContext is created once per task and threaded through the entire
pipeline. Every component that writes to S3, DynamoDB, or the filesystem
uses the ProjectContext to scope its operations.
"""

import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("fde.project_isolation")


@dataclass(frozen=True)
class ProjectContext:
    """Immutable execution context for a single task.

    Created once when the Orchestrator receives an event.
    Passed to every component to scope all I/O operations.
    Frozen to prevent accidental mutation across pipeline stages.
    """

    task_id: str
    source: str                          # github | asana | gitlab | direct
    repo: str                            # owner/repo
    branch: str                          # feature branch name
    s3_prefix: str                       # projects/{task_id}
    workspace_dir: str                   # /tmp/workspace/{task_id}
    issue_id: str                        # GH-123, ASANA-456, GL-789
    created_at: str                      # ISO 8601
    environment: str                     # dev | staging | prod
    correlation_id: str                  # Unique ID for tracing across services


def create_project_context(
    data_contract: dict,
    metadata: dict,
    environment: str = "",
) -> ProjectContext:
    """Create an isolated ProjectContext from the data contract.

    Args:
        data_contract: The canonical data contract from the Router.
        metadata: The routing metadata (source, issue_number, etc.).
        environment: The deployment environment (dev/staging/prod).

    Returns:
        A frozen ProjectContext scoped to this task.
    """
    env = environment or os.environ.get("ENVIRONMENT", "dev")
    source = data_contract.get("source", metadata.get("source", "direct"))
    task_id = data_contract.get("task_id", f"TASK-{uuid.uuid4().hex[:8]}")

    # Build issue ID from metadata
    issue_id = _resolve_issue_id(source, metadata)

    # Build branch name: fde/{task_id}/{sanitized_title}
    title = data_contract.get("title", "untitled")
    safe_title = _sanitize_branch_name(title)[:40]
    branch = f"fde/{task_id}/{safe_title}"

    # Build repo from metadata or data contract
    repo = data_contract.get("repo", metadata.get("repo", ""))

    ctx = ProjectContext(
        task_id=task_id,
        source=source,
        repo=repo,
        branch=branch,
        s3_prefix=f"projects/{task_id}",
        workspace_dir=f"/tmp/workspace/{task_id}",
        issue_id=issue_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        environment=env,
        correlation_id=f"COR-{uuid.uuid4().hex[:12]}",
    )

    logger.info(
        "ProjectContext created: task=%s source=%s branch=%s s3=%s workspace=%s cor=%s",
        ctx.task_id, ctx.source, ctx.branch, ctx.s3_prefix,
        ctx.workspace_dir, ctx.correlation_id,
    )

    return ctx


def scoped_s3_key(ctx: ProjectContext, *parts: str) -> str:
    """Build an S3 key scoped to this project's namespace.

    Args:
        ctx: The project context.
        *parts: Path segments (e.g., "results", "recon-result.md").

    Returns:
        Full S3 key like "projects/TASK-abc123/results/recon-result.md".
    """
    return "/".join([ctx.s3_prefix] + list(parts))


def scoped_workspace(ctx: ProjectContext) -> str:
    """Ensure the project workspace directory exists and return its path.

    Args:
        ctx: The project context.

    Returns:
        Absolute path to the isolated workspace directory.
    """
    os.makedirs(ctx.workspace_dir, exist_ok=True)
    return ctx.workspace_dir


def _resolve_issue_id(source: str, metadata: dict) -> str:
    """Resolve the platform-specific issue ID from routing metadata."""
    if source == "github":
        num = metadata.get("issue_number", "")
        return f"GH-{num}" if num else ""
    elif source == "gitlab":
        iid = metadata.get("issue_iid", "")
        return f"GL-{iid}" if iid else ""
    elif source == "asana":
        gid = metadata.get("task_gid", "")
        return f"ASANA-{gid}" if gid else ""
    return ""


def _sanitize_branch_name(name: str) -> str:
    """Sanitize a string for use in a git branch name."""
    safe = ""
    for ch in name.lower():
        if ch.isalnum() or ch == "-":
            safe += ch
        elif ch in (" ", "_", "/"):
            safe += "-"
    # Collapse multiple dashes
    while "--" in safe:
        safe = safe.replace("--", "-")
    return safe.strip("-")
