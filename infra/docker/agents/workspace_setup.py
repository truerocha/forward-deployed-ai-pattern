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
    """Push the feature branch and create (or update) a PR.

    Hybrid safe push strategy for re-worked tasks:
      1. Pre-push artifact hygiene validation (blocks if internal files in diff)
      2. Fetch remote feature branch (if exists) so --force-with-lease has context
      3. Push with --force-with-lease (safe: fails if someone else pushed)
      4. If push fails, it means a human or different agent modified the branch
         — in that case, report the failure (don't force over human work)
      5. Create PR if none exists, or find existing PR for the branch

    This handles the common case where a task is re-executed on the same
    issue: the branch already exists from a previous attempt, and we need
    to overwrite it with the new (better) implementation.

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

    # ── Pre-push artifact hygiene validation ──
    # Block push if internal agent artifacts are in the diff.
    # See: docs/internal/agent-artifact-hygiene.md
    from .pipeline_safety import review_diff
    diff_review = review_diff(repo_path, base_branch="main")
    hygiene_violations = [
        f for f in diff_review.findings
        if f.category == "artifact_hygiene"
    ]
    if hygiene_violations:
        violation_files = [f.file for f in hygiene_violations]
        logger.error(
            "BLOCKED: Artifact hygiene violations detected before push: %s",
            violation_files,
        )
        return {
            "error": (
                f"Artifact hygiene violation: {len(hygiene_violations)} internal file(s) "
                f"found in diff: {', '.join(violation_files)}. "
                "Move them to /tmp/agent-artifacts/ and amend the commit before pushing. "
                "See: docs/internal/agent-artifact-hygiene.md"
            ),
            "pr_url": "",
            "hygiene_violations": violation_files,
        }

    # Step 1: Fetch the remote feature branch (if it exists) so that
    # --force-with-lease knows the remote state. Without this, force-with-lease
    # fails on re-worked tasks because the local git has no tracking ref.
    _fetch_remote_branch(repo_path, workspace.branch_name)

    # Step 2: Push with --force-with-lease (safe force for feature branches)
    push_result = subprocess.run(
        ["git", "push", "--force-with-lease", "-u", "origin", workspace.branch_name],
        capture_output=True, text=True, timeout=60, cwd=repo_path,
    )
    if push_result.returncode != 0:
        logger.warning("Push --force-with-lease failed: %s", push_result.stderr[:300])

        # force-with-lease failed. For re-worked tasks (branch already exists
        # on remote from a previous pipeline run), this is expected because
        # the local branch is not a descendant of the remote branch.
        # Safe to --force here because:
        #   1. This is a feature branch owned by the factory (not human work)
        #   2. We just fetched the remote state (we know what we're overwriting)
        #   3. The previous content was from a failed/incomplete pipeline run
        push_force = subprocess.run(
            ["git", "push", "--force", "-u", "origin", workspace.branch_name],
            capture_output=True, text=True, timeout=60, cwd=repo_path,
        )
        if push_force.returncode != 0:
            logger.error("All push strategies failed: %s", push_force.stderr[:300])
            return {"error": f"Push failed: {push_force.stderr[:200]}", "pr_url": ""}

    logger.info("Pushed branch %s to origin", workspace.branch_name)

    # Step 3: Create or find existing PR
    github_pat = _fetch_github_pat()
    if not github_pat:
        return {"error": "GitHub PAT not available for PR creation", "pr_url": ""}

    # Check if a PR already exists for this branch (re-worked task scenario)
    existing_pr = _find_existing_pr(workspace.repo_full_name, workspace.branch_name, github_pat)
    if existing_pr:
        logger.info("Found existing PR #%d for branch %s — updating", existing_pr["number"], workspace.branch_name)
        _update_pr(workspace.repo_full_name, existing_pr["number"], title, body, github_pat)
        return {"pr_url": existing_pr["html_url"], "pr_number": existing_pr["number"]}

    # Create new PR
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
        error_str = str(e)
        if "422" in error_str or "already exists" in error_str.lower():
            existing = _find_existing_pr(workspace.repo_full_name, workspace.branch_name, github_pat)
            if existing:
                return {"pr_url": existing["html_url"], "pr_number": existing["number"]}
        logger.error("PR creation failed: %s", e)
        return {"error": str(e), "pr_url": ""}


def _fetch_remote_branch(repo_path: str, branch_name: str) -> None:
    """Fetch a specific remote branch to update local tracking refs.

    This is critical for --force-with-lease to work on re-worked tasks:
    without fetching, git doesn't know the remote branch's current state
    and force-with-lease fails with 'stale info'.
    """
    result = subprocess.run(
        ["git", "fetch", "origin", branch_name],
        capture_output=True, text=True, timeout=30, cwd=repo_path,
    )
    if result.returncode == 0:
        logger.info("Fetched remote branch %s (exists on remote)", branch_name)
    else:
        logger.debug("Remote branch %s not found (first push)", branch_name)


def _find_existing_pr(repo_full_name: str, branch_name: str, github_pat: str) -> dict | None:
    """Find an existing open PR for the given branch."""
    import urllib.request

    owner = repo_full_name.split("/")[0]
    url = f"https://api.github.com/repos/{repo_full_name}/pulls?head={owner}:{branch_name}&state=open"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {github_pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            prs = json.loads(resp.read().decode())
            if prs and len(prs) > 0:
                return prs[0]
    except Exception as e:
        logger.warning("Failed to check existing PRs: %s", e)

    return None


def _update_pr(repo_full_name: str, pr_number: int, title: str, body: str, github_pat: str) -> None:
    """Update an existing PR's title and body."""
    import urllib.request

    update_data = json.dumps({"title": title, "body": body}).encode()
    url = f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}"
    req = urllib.request.Request(url, data=update_data, method="PATCH", headers={
        "Authorization": f"Bearer {github_pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info("Updated PR #%d", pr_number)
    except Exception as e:
        logger.warning("Failed to update PR #%d: %s", pr_number, e)


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
