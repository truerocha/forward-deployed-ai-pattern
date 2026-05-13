"""
FDE Agent Tools — Real tool implementations for Strands agents.

Each tool is a @tool-decorated function that the Strands agent can call.
Tools are grouped by category and registered with specific agents.

Security: ALM tokens (GitHub, GitLab, Asana) are NEVER stored in environment
variables. They are fetched from Secrets Manager at the moment of use inside
each tool function, used for the HTTP request, and immediately discarded.
This prevents the LLM from observing token values in its context window.
See ADR-014 for the full rationale.
"""

import json
import logging
import os
import subprocess
import time
from datetime import datetime, timezone

import boto3
import requests
from strands import tool

logger = logging.getLogger("fde.tools")

_s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))
_FACTORY_BUCKET = os.environ.get("FACTORY_BUCKET", "")

# ─── Secret Isolation: Fetch-Use-Discard Pattern (ADR-014) ──────
# Tokens are fetched from Secrets Manager at invocation time, cached
# for 5 minutes to avoid repeated API calls within a pipeline run,
# and NEVER exposed as env vars or returned to the agent.

_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_TOKEN_CACHE_TTL = 300  # 5 minutes


def _fetch_alm_token(token_name: str) -> str:
    """Fetch an ALM token from Secrets Manager with short-lived cache.

    Security contract:
    - Token value is NEVER logged
    - Token value is NEVER returned to the agent's message history
    - Token is cached in-process for 5 minutes to reduce API calls
    - Falls back to env var ONLY for local development (no Secrets Manager)

    Args:
        token_name: Key within the secret JSON (e.g., "GITHUB_TOKEN").

    Returns:
        The token value, or empty string if unavailable.
    """
    now = time.time()

    # Check cache (TTL-based)
    if token_name in _TOKEN_CACHE:
        cached_value, cached_at = _TOKEN_CACHE[token_name]
        if now - cached_at < _TOKEN_CACHE_TTL:
            return cached_value

    # Try Secrets Manager first
    env = os.environ.get("ENVIRONMENT", "dev")
    secret_id = os.environ.get("ALM_SECRET_ID", f"fde-{env}/alm-tokens")

    try:
        sm = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        response = sm.get_secret_value(SecretId=secret_id)
        secret_data = json.loads(response["SecretString"])
        token = secret_data.get(token_name, "")
        if token:
            _TOKEN_CACHE[token_name] = (token, now)
            logger.debug("Token %s fetched from Secrets Manager", token_name)
            return token
    except Exception as e:
        # Secrets Manager unavailable — fall back to env var (local dev only)
        logger.warning(
            "Secrets Manager unavailable for %s (falling back to env var): %s",
            token_name, type(e).__name__,
        )

    # Fallback: env var (local development mode only)
    fallback = os.environ.get(token_name, "")
    if fallback:
        _TOKEN_CACHE[token_name] = (fallback, now)
        logger.debug("Token %s loaded from env var (local dev fallback)", token_name)
    return fallback


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
    token = _fetch_alm_token("GITHUB_TOKEN")
    if not token:
        return "SKIPPED: GITHUB_TOKEN not available (check Secrets Manager)"
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
    token = _fetch_alm_token("GITLAB_TOKEN")
    if not token:
        return "SKIPPED: GITLAB_TOKEN not available (check Secrets Manager)"
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
    token = _fetch_alm_token("ASANA_ACCESS_TOKEN")
    if not token:
        return "SKIPPED: ASANA_ACCESS_TOKEN not available (check Secrets Manager)"
    resp = requests.post(
        f"https://app.asana.com/api/1.0/tasks/{task_gid}/stories",
        headers={"Authorization": f"Bearer {token}"},
        json={"data": {"text": comment}},
        timeout=30,
    )
    return f"Comment added to Asana task {task_gid}" if resp.status_code in (200, 201) else f"Failed: HTTP {resp.status_code}"


@tool
def run_shell_command(command: str, working_dir: str = "") -> str:
    """Execute a shell command in the workspace.

    Args:
        command: Shell command to execute.
        working_dir: Working directory. Defaults to AGENT_WORKSPACE env var
                     (set by workspace_setup.py) or /tmp/workspace.

    Returns:
        Command output (last 2000 chars).
    """
    if not working_dir:
        working_dir = os.environ.get("AGENT_WORKSPACE", "/tmp/workspace")

    # ── OS-level destructive commands ──
    blocked = ["rm -rf /", "mkfs", "dd if=", ":(){"]
    for b in blocked:
        if b in command:
            return f"BLOCKED: dangerous pattern '{b}'"

    # ── Git safety: FDE delivery rules enforcement ──
    # Agent ALWAYS works on feature branches (never main/master).
    # Agent NEVER merges, force pushes, or deletes branches.
    _git_blocked = [
        ("git push origin main", "push_to_main"),
        ("git push origin master", "push_to_master"),
        ("git push -u origin main", "push_to_main"),
        ("git push -u origin master", "push_to_master"),
        ("git merge main", "merge_main"),
        ("git merge master", "merge_master"),
        ("git checkout main", "checkout_main"),
        ("git checkout master", "checkout_master"),
        ("git switch main", "switch_main"),
        ("git switch master", "switch_master"),
        ("git branch -D", "branch_delete_force"),
        ("git branch -d main", "branch_delete_main"),
        ("git branch -d master", "branch_delete_master"),
        ("git push --force", "force_push"),
        ("git push -f", "force_push"),
        ("git reset --hard origin/main", "hard_reset_main"),
        ("git reset --hard origin/master", "hard_reset_master"),
    ]
    cmd_lower = command.lower()
    for pattern, reason in _git_blocked:
        if pattern.lower() in cmd_lower:
            return f"BLOCKED: FDE delivery rule violation — '{reason}'. Agent must work on feature branches only."

    # ── Artifact Hygiene: Block bulk staging and forbidden commit patterns ──
    # See: docs/internal/agent-artifact-hygiene.md
    _hygiene_blocked = [
        ("git add .", "bulk_stage_dot"),
        ("git add -a", "bulk_stage_all_flag"),
        ("git add --all", "bulk_stage_all"),
        ("git add *", "bulk_stage_glob"),
        ("git commit -a", "commit_auto_stage"),
        ("git commit --all", "commit_auto_stage"),
    ]
    for pattern, reason in _hygiene_blocked:
        if pattern.lower() in cmd_lower:
            return (
                f"BLOCKED: Artifact hygiene violation — '{reason}'. "
                "You MUST stage files explicitly: git add path/to/file1 path/to/file2. "
                "Never use 'git add .', 'git add -A', 'git add *', or 'git commit -a'. "
                "See: docs/internal/agent-artifact-hygiene.md"
            )

    # ── Artifact Hygiene: Block staging of internal working files ──
    if "git add" in cmd_lower:
        import re as _re
        _blocked_file_patterns = [
            r"(?:^|\s)[\w/]*_ANALYSIS[\w]*\.md",
            r"(?:^|\s)[\w/]*_REPORT[\w]*\.md",
            r"(?:^|\s)[\w/]*_SUMMARY[\w]*\.md",
            r"(?:^|\s)[\w/]*_BRIEF[\w]*\.md",
            r"(?:^|\s)[\w/]*_COMPLETE[\w]*\.md",
            r"(?:^|\s)PHASE\d+_[\w]*\.md",
            r"(?:^|\s)HANDOFF[\w]*\.md",
            r"(?:^|\s)[\w/]*_CHECKLIST[\w]*\.md",
            r"(?:^|\s)README_GH[\w]*\.md",
            r"(?:^|\s)REFERENCE_[\w]*\.md",
            r"(?:^|\s)CODE_SNIPPETS[\w]*\.md",
            r"(?:^|\s)task_analysis[\w]*\.md",
            r"(?:^|\s)handoff_summary[\w]*\.md",
            r"(?:^|\s)reconnaissance[\w]*\.md",
            r"(?:^|\s)CODE_QUALITY[\w]*\.md",
            r"(?:^|\s)REL_REVIEW[\w]*\.md",
            r"(?:^|\s)IMPLEMENTATION_[\w]*\.md",
            # WAF pillar agent review artifacts (GH-{N}-{PILLAR}-*-review.md)
            r"(?:^|\s)[\w/]*GH-\d+[\w-]*review[\w-]*\.md",
            r"(?:^|\s)[\w/]*GL-\d+[\w-]*review[\w-]*\.md",
            r"(?:^|\s)[\w/]*ASANA-\d+[\w-]*review[\w-]*\.md",
            # Generic review artifacts from pillar agents
            r"(?:^|\s)[\w/]*-(?:reliability|security|operational|performance|cost|sustainability)-review[\w-]*\.md",
        ]
        for pat in _blocked_file_patterns:
            match = _re.search(pat, command, _re.IGNORECASE)
            if match:
                blocked_file = match.group().strip()
                return (
                    f"BLOCKED: Artifact hygiene violation — staging internal file '{blocked_file}'. "
                    "Internal working files (analysis, handoff, reports) must NOT be committed. "
                    "Move them to /tmp/agent-artifacts-{{task-id}}/ before staging. "
                    "See: docs/internal/agent-artifact-hygiene.md"
                )

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


@tool
def create_github_pull_request(
    owner: str, repo: str, title: str, body: str,
    head_branch: str, base_branch: str = "main",
) -> str:
    """Create a pull request on GitHub with structured body.

    Enforces FDE delivery rules:
    - head_branch must NOT be main/master
    - base_branch defaults to main
    - Agent NEVER merges — human approves

    Args:
        owner: Repository owner.
        repo: Repository name.
        title: PR title (concise, under 70 chars).
        body: PR body (summary, spec ref, validation results).
        head_branch: Feature branch with changes.
        base_branch: Target branch (default: main).

    Returns:
        Status message with PR URL.
    """
    # Enforce: head must be a feature branch
    if head_branch in ("main", "master"):
        return "BLOCKED: FDE rule — head_branch cannot be main/master. Use a feature branch."

    token = _fetch_alm_token("GITHUB_TOKEN")
    if not token:
        return "SKIPPED: GITHUB_TOKEN not available (check Secrets Manager)"

    resp = requests.post(
        f"https://api.github.com/repos/{owner}/{repo}/pulls",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        json={
            "title": title,
            "body": body,
            "head": head_branch,
            "base": base_branch,
            "draft": False,
        },
        timeout=30,
    )

    if resp.status_code == 201:
        pr_data = resp.json()
        return f"PR created: {pr_data['html_url']} (#{pr_data['number']})"
    return f"Failed to create PR: HTTP {resp.status_code} — {resp.text[:200]}"


@tool
def create_gitlab_merge_request(
    project_id: int, title: str, description: str,
    source_branch: str, target_branch: str = "main",
) -> str:
    """Create a merge request on GitLab with structured description.

    Enforces FDE delivery rules:
    - source_branch must NOT be main/master
    - target_branch defaults to main
    - Agent NEVER merges — human approves

    Args:
        project_id: GitLab project ID.
        title: MR title (concise, under 70 chars).
        description: MR description (summary, spec ref, validation results).
        source_branch: Feature branch with changes.
        target_branch: Target branch (default: main).

    Returns:
        Status message with MR URL.
    """
    # Enforce: source must be a feature branch
    if source_branch in ("main", "master"):
        return "BLOCKED: FDE rule — source_branch cannot be main/master. Use a feature branch."

    token = _fetch_alm_token("GITLAB_TOKEN")
    if not token:
        return "SKIPPED: GITLAB_TOKEN not available (check Secrets Manager)"

    gitlab_url = os.environ.get("GITLAB_URL", "https://gitlab.com")
    resp = requests.post(
        f"{gitlab_url}/api/v4/projects/{project_id}/merge_requests",
        headers={"PRIVATE-TOKEN": token},
        json={
            "title": title,
            "description": description,
            "source_branch": source_branch,
            "target_branch": target_branch,
            "remove_source_branch": True,
        },
        timeout=30,
    )

    if resp.status_code == 201:
        mr_data = resp.json()
        return f"MR created: {mr_data['web_url']} (!{mr_data['iid']})"
    return f"Failed to create MR: HTTP {resp.status_code} — {resp.text[:200]}"


@tool
def query_code_kb(query: str, search_type: str = "semantic") -> str:
    """Search the Code Knowledge Base for modules, functions, or concepts.

    Resolves the linguistic impedance mismatch between business language
    and code symbols. Agents should call this BEFORE reading files to
    understand which modules are relevant to their task.

    Search types:
      - "semantic": Natural language search over module descriptions (default)
      - "function": Find a specific function by name across all modules
      - "callers": Find all modules that call a given function
      - "callees": Find all functions called by a given function
      - "module": Get complete knowledge about a specific module path

    Args:
        query: The search query. For "semantic", use natural language
               (e.g., "authentication handling"). For "function", use the
               function name (e.g., "invoke_agent" or "CostTracker.record").
               For "module", use the relative file path.
        search_type: One of "semantic", "function", "callers", "callees", "module".

    Returns:
        JSON string with search results including module paths, descriptions,
        relevance scores, and function lists. Returns empty results (not error)
        if the Knowledge Base has not been indexed yet.
    """
    from src.core.knowledge.query_api import QueryAPI

    project_id = os.environ.get("PROJECT_ID", "")
    if not project_id:
        return json.dumps({"results": [], "message": "PROJECT_ID not set — Code KB unavailable"})

    try:
        api = QueryAPI(project_id=project_id)

        if search_type == "module":
            knowledge = api.query_module(query)
            if not knowledge:
                return json.dumps({"results": [], "query": query, "search_type": search_type})
            return json.dumps({
                "results": [{
                    "module_path": knowledge.module_path,
                    "description": knowledge.description,
                    "functions": knowledge.functions[:20],
                    "classes": knowledge.classes[:10],
                    "calls_to": knowledge.calls_to[:15],
                    "called_by": knowledge.called_by[:10],
                    "line_count": knowledge.line_count,
                }],
                "query": query,
                "search_type": search_type,
            }, indent=2)

        elif search_type == "function":
            results = api.query_function(query)
            return json.dumps({
                "results": [
                    {
                        "module_path": r.module_path,
                        "relevance_score": r.relevance_score,
                        "description": r.description[:200],
                        "functions": r.functions[:10],
                    }
                    for r in results[:10]
                ],
                "query": query,
                "search_type": search_type,
            }, indent=2)

        elif search_type == "callers":
            results = api.get_callers(query)
            return json.dumps({
                "results": [
                    {
                        "module_path": r.module_path,
                        "relevance_score": r.relevance_score,
                        "description": r.description[:200],
                    }
                    for r in results[:10]
                ],
                "query": query,
                "search_type": search_type,
            }, indent=2)

        elif search_type == "callees":
            results = api.get_callees(query)
            return json.dumps({
                "results": [
                    {
                        "module_path": r.module_path,
                        "relevance_score": r.relevance_score,
                        "description": r.description[:200],
                        "metadata": r.metadata,
                    }
                    for r in results[:10]
                ],
                "query": query,
                "search_type": search_type,
            }, indent=2)

        else:  # semantic (default)
            results = api.search_by_description(query, top_k=10)
            return json.dumps({
                "results": [
                    {
                        "module_path": r.module_path,
                        "relevance_score": r.relevance_score,
                        "description": r.description[:200],
                        "match_type": r.match_type,
                    }
                    for r in results[:10]
                ],
                "query": query,
                "search_type": search_type,
            }, indent=2)

    except Exception as e:
        logger.warning("query_code_kb failed: %s", e)
        return json.dumps({"results": [], "error": str(e), "query": query})


@tool
def read_factory_metrics(task_id: str) -> str:
    """Read DORA metrics for a specific task (read-only observability).

    Gives the agent awareness of its own performance history for a task.
    Returns structured metrics including lead time, outcome, and stage durations.

    Args:
        task_id: The task identifier to query metrics for.

    Returns:
        JSON string with the task's metrics, or an error message.
    """
    from .dora_metrics import DORACollector

    try:
        collector = DORACollector(factory_bucket=_FACTORY_BUCKET)
        metrics = collector.get_task_metrics(task_id)
        return json.dumps({"task_id": task_id, "metrics": metrics, "count": len(metrics)}, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "task_id": task_id})


@tool
def read_factory_health(window_days: int = 30) -> str:
    """Read the latest Factory Health Report (read-only observability).

    Returns the DORA metrics summary including:
    - DORA level classification (Elite/High/Medium/Low)
    - Lead time, deployment frequency, change failure rate, MTTR
    - Domain-segmented acceptance rates
    - Factory-specific metrics (constraint extraction rate, gate pass rate)

    Args:
        window_days: Number of days to include in the report (default 30).

    Returns:
        JSON string with the factory health report.
    """
    from .dora_metrics import DORACollector

    try:
        collector = DORACollector(factory_bucket=_FACTORY_BUCKET)
        report = collector.generate_factory_report(window_days=window_days)
        return json.dumps(report, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "window_days": window_days})


RECON_TOOLS = [read_spec, run_shell_command, query_code_kb]
ENGINEERING_TOOLS = [read_spec, write_artifact, run_shell_command, query_code_kb, update_github_issue, update_gitlab_issue, update_asana_task, create_github_pull_request, create_gitlab_merge_request]
REPORTING_TOOLS = [write_artifact, update_github_issue, update_gitlab_issue, update_asana_task, read_factory_metrics, read_factory_health]
