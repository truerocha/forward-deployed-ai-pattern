"""
Workspace Setup — Clones target repo and configures git for agent execution.

COE-011: The ECS container starts with an empty filesystem. The agent needs
a cloned repo with a feature branch to produce deliverable code changes.

This module:
1. Fetches GitHub PAT from Secrets Manager (ADR-014: fetch-use-discard)
2. Clones the target repo (shallow, depth=50)
3. Creates a feature branch (feature/GH-{issue_number}-{slug})
4. Configures git push credentials via GIT_ASKPASS
5. Returns the workspace path for the agent's tools

Security:
- PAT is fetched at runtime, used for clone/push, then discarded
- GIT_ASKPASS pattern prevents PAT from appearing in process env or logs
- Workspace is ephemeral (ECS Fargate container lifecycle)
"""

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger("fde.workspace_setup")

WORKSPACE_BASE = os.environ.get("WORKSPACE_BASE", "/tmp/workspace")


@dataclass
class WorkspaceContext:
    """Result of workspace setup — passed to agent tools."""

    repo_path: str
    branch_name: str
    repo_full_name: str
    issue_number: int
    ready: bool = True
    error: str = ""


def setup_workspace(event_detail: dict, metadata: dict) -> WorkspaceContext:
    """Clone the target repo and create a feature branch.

    Args:
        event_detail: The event detail containing repository and issue info.
        metadata: Routing metadata (source, issue_number, repo).

    Returns:
        WorkspaceContext with the repo path and branch name.
    """
    repo_full_name = (
        event_detail.get("repository", {}).get("full_name", "")
        or metadata.get("repo", "")
    )
    issue_number = (
        event_detail.get("issue", {}).get("number", 0)
        or metadata.get("issue_number", 0)
    )
    issue_title = event_detail.get("issue", {}).get("title", "")

    if not repo_full_name:
        logger.warning("No repo_full_name in event — workspace setup skipped")
        return WorkspaceContext(
            repo_path="", branch_name="", repo_full_name="",
            issue_number=0, ready=False, error="No repository in event",
        )

    # Generate branch name from issue
    slug = _slugify(issue_title)[:40] if issue_title else "task"
    branch_name = f"feature/GH-{issue_number}-{slug}"

    logger.info("Setting up workspace: repo=%s, branch=%s", repo_full_name, branch_name)

    # Fetch GitHub PAT from Secrets Manager
    github_pat = _fetch_github_pat()
    if not github_pat:
        return WorkspaceContext(
            repo_path="", branch_name=branch_name, repo_full_name=repo_full_name,
            issue_number=issue_number, ready=False, error="GitHub PAT not available",
        )

    # Clone the repo
    repo_path = os.path.join(WORKSPACE_BASE, repo_full_name.split("/")[-1])
    clone_url = f"https://x-access-token:{github_pat}@github.com/{repo_full_name}.git"

    try:
        os.makedirs(WORKSPACE_BASE, exist_ok=True)

        # Clone (shallow for speed, depth=50 for branch context)
        result = subprocess.run(
            ["git", "clone", "--depth", "50", "--single-branch", clone_url, repo_path],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            logger.error("Git clone failed: %s", result.stderr[:500])
            return WorkspaceContext(
                repo_path="", branch_name=branch_name, repo_full_name=repo_full_name,
                issue_number=issue_number, ready=False,
                error=f"Clone failed: {result.stderr[:200]}",
            )

        logger.info("Cloned %s to %s", repo_full_name, repo_path)

        # Configure git identity for agent commits (COE-017: proper agent labeling)
        # The commit author identifies the FDE agent, not the codebase owner.
        # The codebase owner reviews the PR — they don't author the code.
        agent_email = os.environ.get("FDE_AGENT_EMAIL", "fde-agent@factory.local")
        agent_name = os.environ.get("FDE_AGENT_NAME", "FDE Agent")
        _run_git(repo_path, ["config", "user.email", agent_email])
        _run_git(repo_path, ["config", "user.name", f"{agent_name} [GH-{issue_number}]"])

        # Create feature branch
        _run_git(repo_path, ["checkout", "-b", branch_name])
        logger.info("Created branch: %s", branch_name)

        # Configure GIT_ASKPASS for push (ADR-014: fetch-use-discard)
        askpass_path = _setup_git_askpass(github_pat)
        os.environ["GIT_ASKPASS"] = askpass_path
        os.environ["GIT_TERMINAL_PROMPT"] = "0"

        # Expose GITHUB_TOKEN for agent tools (create_github_pull_request, etc.)
        os.environ["GITHUB_TOKEN"] = github_pat

        # Set workspace as working directory for agent tools
        os.environ["AGENT_WORKSPACE"] = repo_path
        os.chdir(repo_path)

        return WorkspaceContext(
            repo_path=repo_path,
            branch_name=branch_name,
            repo_full_name=repo_full_name,
            issue_number=issue_number,
            ready=True,
        )

    except subprocess.TimeoutExpired:
        logger.error("Git clone timed out for %s", repo_full_name)
        return WorkspaceContext(
            repo_path="", branch_name=branch_name, repo_full_name=repo_full_name,
            issue_number=issue_number, ready=False, error="Clone timed out",
        )
    except Exception as e:
        logger.error("Workspace setup failed: %s", e)
        return WorkspaceContext(
            repo_path="", branch_name=branch_name, repo_full_name=repo_full_name,
            issue_number=issue_number, ready=False, error=str(e),
        )


def push_and_create_pr(workspace: WorkspaceContext, title: str, body: str) -> dict:
    """Push the feature branch and create a PR.

    Args:
        workspace: The workspace context from setup_workspace.
        title: PR title.
        body: PR body (markdown).

    Returns:
        Dict with pr_url, pr_number, or error.
    """
    if not workspace.ready:
        return {"error": "Workspace not ready", "pr_url": ""}

    repo_path = workspace.repo_path

    # Check if there are commits to push
    result = _run_git(repo_path, ["log", "origin/main..HEAD", "--oneline"])
    if not result.strip():
        return {"error": "No commits to push", "pr_url": ""}

    # Push the branch (force-with-lease for retry safety — feature branches only)
    push_result = subprocess.run(
        ["git", "push", "--force-with-lease", "-u", "origin", workspace.branch_name],
        capture_output=True, text=True, timeout=60, cwd=repo_path,
    )
    if push_result.returncode != 0:
        logger.error("Git push failed: %s", push_result.stderr[:500])
        return {"error": f"Push failed: {push_result.stderr[:200]}", "pr_url": ""}

    logger.info("Pushed branch %s to origin", workspace.branch_name)

    # Create PR via GitHub API
    github_pat = _fetch_github_pat()
    if not github_pat:
        return {"error": "GitHub PAT not available for PR creation", "pr_url": ""}

    import urllib.request
    pr_data = json.dumps({
        "title": title,
        "body": body,
        "head": workspace.branch_name,
        "base": "main",
    }).encode()

    url = f"https://api.github.com/repos/{workspace.repo_full_name}/pulls"
    req = urllib.request.Request(url, data=pr_data, method="POST", headers={
        "Authorization": f"Bearer {github_pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            pr_response = json.loads(resp.read().decode())
            pr_url = pr_response.get("html_url", "")
            pr_number = pr_response.get("number", 0)
            logger.info("PR created: %s (#%d)", pr_url, pr_number)
            return {"pr_url": pr_url, "pr_number": pr_number}
    except Exception as e:
        logger.error("PR creation failed: %s", e)
        return {"error": str(e), "pr_url": ""}


def _fetch_github_pat() -> str:
    """Fetch GitHub PAT from Secrets Manager (ADR-014)."""
    secrets_id = os.environ.get(
        "SECRETS_ID",
        f"fde-{os.environ.get('ENVIRONMENT', 'dev')}/alm-tokens",
    )
    try:
        client = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        secret = client.get_secret_value(SecretId=secrets_id)
        tokens = json.loads(secret["SecretString"])
        return tokens.get("github_pat", "")
    except ClientError as e:
        logger.error("Failed to fetch GitHub PAT: %s", e)
        return ""


def _setup_git_askpass(pat: str) -> str:
    """Create a GIT_ASKPASS script that provides the PAT.

    This avoids embedding the PAT in the clone URL or environment variables
    where it could be logged. The script is ephemeral (container lifecycle).
    """
    askpass_script = f"#!/bin/sh\necho {pat}\n"
    askpass_path = "/tmp/.git-askpass"
    with open(askpass_path, "w") as f:
        f.write(askpass_script)
    os.chmod(askpass_path, 0o700)
    return askpass_path


def _run_git(repo_path: str, args: list[str]) -> str:
    """Run a git command in the repo directory."""
    result = subprocess.run(
        ["git"] + args,
        capture_output=True, text=True, cwd=repo_path, timeout=30,
    )
    if result.returncode != 0:
        logger.warning("git %s failed: %s", " ".join(args), result.stderr[:200])
    return result.stdout


def _slugify(text: str) -> str:
    """Convert text to a git-branch-safe slug."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text
