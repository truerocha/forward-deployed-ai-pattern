"""
FDE Agent Tools — Real tool implementations for Strands agents.

Each tool is a @tool-decorated function that the Strands agent can call.
Tools are grouped by category and registered with specific agents.
"""

import json
import os
import subprocess
from datetime import datetime, timezone

import boto3
import requests
from strands import tool

_s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))
_FACTORY_BUCKET = os.environ.get("FACTORY_BUCKET", "")


@tool
def read_spec(spec_path: str) -> str:
    """Read a task specification from S3 or local path.

    Args:
        spec_path: S3 URI (s3://bucket/key) or local file path.

    Returns:
        The spec content as a string.
    """
    if spec_path.startswith("s3://"):
        parts = spec_path.replace("s3://", "").split("/", 1)
        response = _s3.get_object(Bucket=parts[0], Key=parts[1])
        return response["Body"].read().decode("utf-8")
    with open(spec_path) as f:
        return f.read()


@tool
def write_artifact(artifact_name: str, content: str) -> str:
    """Write a factory artifact (completion report, notes) to S3.

    Args:
        artifact_name: Name of the artifact (e.g., 'completion-report.md').
        content: The artifact content.

    Returns:
        The S3 URI where the artifact was written.
    """
    env = os.environ.get("ENVIRONMENT", "dev")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    key = f"artifacts/{env}/{timestamp}/{artifact_name}"
    _s3.put_object(Bucket=_FACTORY_BUCKET, Key=key, Body=content.encode("utf-8"))
    return f"s3://{_FACTORY_BUCKET}/{key}"


@tool
def update_github_issue(owner: str, repo: str, issue_number: int, comment: str) -> str:
    """Add a comment to a GitHub issue.

    Args:
        owner: Repository owner.
        repo: Repository name.
        issue_number: Issue number.
        comment: Comment text.

    Returns:
        Status message.
    """
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return "SKIPPED: GITHUB_TOKEN not configured"
    resp = requests.post(
        f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/comments",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        json={"body": comment},
        timeout=30,
    )
    return f"Comment added to {owner}/{repo}#{issue_number}" if resp.status_code == 201 else f"Failed: HTTP {resp.status_code}"


@tool
def update_gitlab_issue(project_id: int, issue_iid: int, comment: str) -> str:
    """Add a note to a GitLab issue.

    Args:
        project_id: GitLab project ID.
        issue_iid: Issue IID.
        comment: Note text.

    Returns:
        Status message.
    """
    token = os.environ.get("GITLAB_TOKEN", "")
    if not token:
        return "SKIPPED: GITLAB_TOKEN not configured"
    gitlab_url = os.environ.get("GITLAB_URL", "https://gitlab.com")
    resp = requests.post(
        f"{gitlab_url}/api/v4/projects/{project_id}/issues/{issue_iid}/notes",
        headers={"PRIVATE-TOKEN": token},
        json={"body": comment},
        timeout=30,
    )
    return f"Note added to project {project_id} issue !{issue_iid}" if resp.status_code == 201 else f"Failed: HTTP {resp.status_code}"


@tool
def update_asana_task(task_gid: str, comment: str) -> str:
    """Add a comment to an Asana task.

    Args:
        task_gid: Asana task GID.
        comment: Comment text.

    Returns:
        Status message.
    """
    token = os.environ.get("ASANA_ACCESS_TOKEN", "")
    if not token:
        return "SKIPPED: ASANA_ACCESS_TOKEN not configured"
    resp = requests.post(
        f"https://app.asana.com/api/1.0/tasks/{task_gid}/stories",
        headers={"Authorization": f"Bearer {token}"},
        json={"data": {"text": comment}},
        timeout=30,
    )
    return f"Comment added to Asana task {task_gid}" if resp.status_code in (200, 201) else f"Failed: HTTP {resp.status_code}"


@tool
def run_shell_command(command: str, working_dir: str = "/tmp/workspace") -> str:
    """Execute a shell command in the workspace.

    Args:
        command: Shell command to execute.
        working_dir: Working directory.

    Returns:
        Command output (last 2000 chars).
    """
    blocked = ["rm -rf /", "mkfs", "dd if=", ":(){"]
    for b in blocked:
        if b in command:
            return f"BLOCKED: dangerous pattern '{b}'"
    os.makedirs(working_dir, exist_ok=True)
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=300, cwd=working_dir,
        )
        output = result.stdout + result.stderr
        return output[-2000:] if len(output) > 2000 else output
    except subprocess.TimeoutExpired:
        return "TIMEOUT: exceeded 300s"
    except Exception as e:
        return f"ERROR: {e}"


RECON_TOOLS = [read_spec, run_shell_command]
ENGINEERING_TOOLS = [read_spec, write_artifact, run_shell_command, update_github_issue, update_gitlab_issue, update_asana_task]
REPORTING_TOOLS = [write_artifact, update_github_issue, update_gitlab_issue, update_asana_task]
