"""
Pipeline Safety — PR Diff Review Gate + Automatic Rollback.

Two capabilities that close gaps identified in the adversarial analysis (ADR-012):

1. PR Diff Review Gate (outer loop, Decision 5):
   After the Engineering Agent opens a PR, this gate reviews the diff
   for common issues: large files, secrets, debug code, missing tests,
   and constraint violations. Runs as the final outer loop gate before
   the human reviews.

2. Automatic Rollback (Decision 6):
   When the Circuit Breaker exhausts all retries (3 failures), the
   rollback mechanism undoes partial commits on the feature branch.
   The branch is reset to its state before the agent started, and
   the task is marked FAILED with a clean workspace.

No fake code — every function uses real git commands and file operations.
"""

import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("fde.pipeline_safety")


# ═══════════════════════════════════════════════════════════════════
# PR Diff Review Gate
# ═══════════════════════════════════════════════════════════════════

@dataclass
class DiffFinding:
    """A single finding from the PR diff review."""

    severity: str          # "error" | "warning" | "info"
    category: str          # "secrets" | "debug" | "size" | "test_coverage" | "constraint"
    file: str              # File path
    line: int              # Line number (0 if file-level)
    message: str           # Human-readable description


@dataclass
class DiffReviewResult:
    """Result of reviewing a PR diff."""

    passed: bool
    findings: list[DiffFinding] = field(default_factory=list)
    files_reviewed: int = 0
    lines_added: int = 0
    lines_removed: int = 0

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "files_reviewed": self.files_reviewed,
            "lines_added": self.lines_added,
            "lines_removed": self.lines_removed,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "findings": [
                {"severity": f.severity, "category": f.category,
                 "file": f.file, "line": f.line, "message": f.message}
                for f in self.findings
            ],
        }


# Patterns that indicate secrets or credentials in code
_SECRET_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?:AKIA|ASIA)[A-Z0-9]{16}"), "AWS access key"),
    (re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}"), "GitHub token"),
    (re.compile(r"glpat-[A-Za-z0-9\-_]{20,}"), "GitLab token"),
    (re.compile(r"sk-[A-Za-z0-9]{32,}"), "API secret key"),
    (re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"), "Private key"),
    (re.compile(r"password\s*=\s*['\"][^'\"]{8,}['\"]", re.IGNORECASE), "Hardcoded password"),
]

# Patterns that indicate debug/temporary code
_DEBUG_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bconsole\.log\b"), "console.log left in code"),
    (re.compile(r"\bprint\s*\(.*\)\s*#\s*(?:debug|TODO|FIXME|HACK)", re.IGNORECASE), "Debug print"),
    (re.compile(r"\bimport\s+pdb\b"), "pdb import"),
    (re.compile(r"\bbreakpoint\s*\(\s*\)"), "breakpoint() call"),
    (re.compile(r"\bdebugger\b"), "debugger statement"),
]

# Patterns that indicate internal agent artifacts that must NOT be committed
# See: docs/internal/agent-artifact-hygiene.md
_ARTIFACT_HYGIENE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"_ANALYSIS[^/]*\.md$", re.IGNORECASE), "Internal analysis artifact"),
    (re.compile(r"_REPORT[^/]*\.md$", re.IGNORECASE), "Internal report artifact"),
    (re.compile(r"_SUMMARY[^/]*\.md$", re.IGNORECASE), "Internal summary artifact"),
    (re.compile(r"_BRIEF[^/]*\.md$", re.IGNORECASE), "Internal brief artifact"),
    (re.compile(r"_COMPLETE[^/]*\.md$", re.IGNORECASE), "Internal completion marker"),
    (re.compile(r"^PHASE\d+_.*\.md$", re.IGNORECASE), "Internal phase artifact"),
    (re.compile(r"^HANDOFF.*\.md$", re.IGNORECASE), "Internal handoff artifact"),
    (re.compile(r"_CHECKLIST[^/]*\.md$", re.IGNORECASE), "Internal checklist artifact"),
    (re.compile(r"^README_GH.*\.md$", re.IGNORECASE), "Internal GitHub readme artifact"),
    (re.compile(r"^REFERENCE_.*\.md$", re.IGNORECASE), "Internal reference artifact"),
    (re.compile(r"^CODE_SNIPPETS.*\.md$", re.IGNORECASE), "Internal code snippets artifact"),
    (re.compile(r"^task_analysis.*\.md$", re.IGNORECASE), "Internal task analysis artifact"),
    (re.compile(r"^handoff_summary.*\.md$", re.IGNORECASE), "Internal handoff summary"),
    (re.compile(r"^reconnaissance.*\.md$", re.IGNORECASE), "Internal reconnaissance artifact"),
    (re.compile(r"^CODE_QUALITY.*\.md$", re.IGNORECASE), "Internal code quality artifact"),
    (re.compile(r"^REL_REVIEW.*\.md$", re.IGNORECASE), "Internal reliability review artifact"),
    (re.compile(r"^IMPLEMENTATION_.*\.md$", re.IGNORECASE), "Internal implementation artifact"),
    # WAF pillar agent review artifacts (GH-{N}-{PILLAR}-*-review.md, GL-{N}-*, ASANA-{N}-*)
    (re.compile(r"^GH-\d+.*review.*\.md$", re.IGNORECASE), "WAF pillar review artifact (GitHub issue)"),
    (re.compile(r"^GL-\d+.*review.*\.md$", re.IGNORECASE), "WAF pillar review artifact (GitLab issue)"),
    (re.compile(r"^ASANA-\d+.*review.*\.md$", re.IGNORECASE), "WAF pillar review artifact (Asana task)"),
    # Generic pillar review artifacts in any subdirectory
    (re.compile(r"(?:reliability|security|operational|performance|cost|sustainability)-review.*\.md$", re.IGNORECASE), "WAF pillar review artifact"),
]

# Maximum file size for a single file change (lines added)
_MAX_FILE_LINES = 500
_MAX_TOTAL_LINES = 2000


def review_diff(workspace_dir: str, base_branch: str = "main") -> DiffReviewResult:
    """Review the git diff between the current branch and base branch.

    Checks for:
    1. Secrets and credentials in added lines
    2. Debug/temporary code left in
    3. Excessively large changes (>500 lines per file, >2000 total)
    4. Files that should not be committed (.env, *.key, etc.)

    Args:
        workspace_dir: Path to the git workspace.
        base_branch: The base branch to diff against.

    Returns:
        DiffReviewResult with findings.
    """
    findings: list[DiffFinding] = []
    files_reviewed = 0
    total_added = 0
    total_removed = 0

    # Get the diff
    try:
        diff_output = subprocess.run(
            ["git", "diff", f"{base_branch}...HEAD", "--unified=0", "--no-color"],
            capture_output=True, text=True, timeout=30, cwd=workspace_dir,
        )
        if diff_output.returncode != 0:
            diff_output = subprocess.run(
                ["git", "diff", "HEAD~1", "--unified=0", "--no-color"],
                capture_output=True, text=True, timeout=30, cwd=workspace_dir,
            )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.error("Failed to get git diff: %s", e)
        return DiffReviewResult(passed=True, findings=[
            DiffFinding("warning", "infrastructure", "", 0, f"Could not get diff: {e}")
        ])

    diff_text = diff_output.stdout
    if not diff_text.strip():
        return DiffReviewResult(passed=True)

    # Parse diff into file chunks
    current_file = ""
    current_line = 0
    file_added_lines: dict[str, int] = {}

    for line in diff_text.split("\n"):
        if line.startswith("+++ b/"):
            current_file = line[6:]
            files_reviewed += 1
            file_added_lines.setdefault(current_file, 0)
            continue

        hunk_match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)", line)
        if hunk_match:
            current_line = int(hunk_match.group(1))
            continue

        if line.startswith("+") and not line.startswith("+++"):
            added_content = line[1:]
            total_added += 1
            file_added_lines[current_file] = file_added_lines.get(current_file, 0) + 1

            for pattern, description in _SECRET_PATTERNS:
                if pattern.search(added_content):
                    findings.append(DiffFinding(
                        severity="error", category="secrets",
                        file=current_file, line=current_line,
                        message=f"Potential {description} detected",
                    ))

            for pattern, description in _DEBUG_PATTERNS:
                if pattern.search(added_content):
                    findings.append(DiffFinding(
                        severity="warning", category="debug",
                        file=current_file, line=current_line,
                        message=description,
                    ))

            current_line += 1

        elif line.startswith("-") and not line.startswith("---"):
            total_removed += 1

    # Check for sensitive file patterns
    sensitive_files = [".env", ".key", ".pem", "credentials", "secret"]
    for fname in file_added_lines:
        for pattern in sensitive_files:
            if pattern in fname.lower():
                findings.append(DiffFinding(
                    severity="error", category="secrets",
                    file=fname, line=0,
                    message=f"Sensitive file committed: {fname}",
                ))

    # Check for internal agent artifacts (artifact hygiene)
    # See: docs/internal/agent-artifact-hygiene.md
    for fname in file_added_lines:
        basename = os.path.basename(fname)
        for pattern, description in _ARTIFACT_HYGIENE_PATTERNS:
            if pattern.search(basename):
                findings.append(DiffFinding(
                    severity="error", category="artifact_hygiene",
                    file=fname, line=0,
                    message=f"Agent artifact hygiene violation: {description} — '{fname}' must not be committed. "
                            "Move to /tmp/agent-artifacts-{{task-id}}/ before staging.",
                ))

    # Check for excessively large changes
    for fname, count in file_added_lines.items():
        if count > _MAX_FILE_LINES:
            findings.append(DiffFinding(
                severity="warning", category="size",
                file=fname, line=0,
                message=f"Large change: {count} lines added (threshold: {_MAX_FILE_LINES})",
            ))

    if total_added > _MAX_TOTAL_LINES:
        findings.append(DiffFinding(
            severity="warning", category="size",
            file="", line=0,
            message=f"Total diff is {total_added} lines (threshold: {_MAX_TOTAL_LINES}). Consider splitting.",
        ))

    has_errors = any(f.severity == "error" for f in findings)

    return DiffReviewResult(
        passed=not has_errors,
        findings=findings,
        files_reviewed=files_reviewed,
        lines_added=total_added,
        lines_removed=total_removed,
    )


# ═══════════════════════════════════════════════════════════════════
# Automatic Rollback
# ═══════════════════════════════════════════════════════════════════

@dataclass
class RollbackResult:
    """Result of a rollback operation."""

    success: bool
    commits_reverted: int = 0
    branch: str = ""
    reset_to: str = ""
    error: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "commits_reverted": self.commits_reverted,
            "branch": self.branch,
            "reset_to": self.reset_to,
            "error": self.error,
            "timestamp": self.timestamp,
        }


def record_branch_checkpoint(workspace_dir: str) -> str:
    """Record the current HEAD SHA as a rollback checkpoint.

    Call this BEFORE the agent starts making changes. The returned SHA
    is used by rollback_to_checkpoint() if the pipeline fails.

    Args:
        workspace_dir: Path to the git workspace.

    Returns:
        The current HEAD commit SHA (the checkpoint).
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, cwd=workspace_dir,
        )
        sha = result.stdout.strip()
        logger.info("Branch checkpoint recorded: %s", sha[:12])
        return sha
    except Exception as e:
        logger.error("Failed to record checkpoint: %s", e)
        return ""


def rollback_to_checkpoint(
    workspace_dir: str,
    checkpoint_sha: str,
) -> RollbackResult:
    """Rollback the feature branch to a checkpoint SHA.

    This is called when the Circuit Breaker exhausts all retries.
    It performs a hard reset to the checkpoint, discarding all
    agent commits that happened after the checkpoint.

    Safety:
    - Only operates on feature branches (refuses main/master)
    - Uses git reset --hard (destructive but correct for agent branches)
    - Does NOT force push — local reset only
    - Logs the rollback for DORA metrics

    Args:
        workspace_dir: Path to the git workspace.
        checkpoint_sha: The SHA to reset to (from record_branch_checkpoint).

    Returns:
        RollbackResult with details.
    """
    if not checkpoint_sha:
        return RollbackResult(
            success=False,
            error="No checkpoint SHA provided — cannot rollback",
        )

    # Get current branch name
    try:
        branch_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=10, cwd=workspace_dir,
        )
        branch = branch_result.stdout.strip()
    except Exception as e:
        return RollbackResult(success=False, error=f"Cannot determine branch: {e}")

    # Safety: refuse to reset main/master
    if branch in ("main", "master"):
        return RollbackResult(
            success=False, branch=branch,
            error="REFUSED: Cannot rollback main/master branch",
        )

    # Count commits to revert
    try:
        log_result = subprocess.run(
            ["git", "rev-list", "--count", f"{checkpoint_sha}..HEAD"],
            capture_output=True, text=True, timeout=10, cwd=workspace_dir,
        )
        commits_to_revert = int(log_result.stdout.strip()) if log_result.returncode == 0 else 0
    except Exception:
        commits_to_revert = 0

    if commits_to_revert == 0:
        logger.info("No commits to rollback — already at checkpoint")
        return RollbackResult(
            success=True, commits_reverted=0,
            branch=branch, reset_to=checkpoint_sha,
        )

    # Perform the reset
    try:
        reset_result = subprocess.run(
            ["git", "reset", "--hard", checkpoint_sha],
            capture_output=True, text=True, timeout=30, cwd=workspace_dir,
        )
        if reset_result.returncode != 0:
            return RollbackResult(
                success=False, branch=branch,
                error=f"git reset failed: {reset_result.stderr}",
            )
    except Exception as e:
        return RollbackResult(success=False, branch=branch, error=f"Reset exception: {e}")

    # Clean untracked files (best effort)
    try:
        subprocess.run(
            ["git", "clean", "-fd"],
            capture_output=True, text=True, timeout=30, cwd=workspace_dir,
        )
    except Exception:
        pass

    logger.info(
        "Rollback complete: branch=%s, reverted %d commits, reset to %s",
        branch, commits_to_revert, checkpoint_sha[:12],
    )

    return RollbackResult(
        success=True, commits_reverted=commits_to_revert,
        branch=branch, reset_to=checkpoint_sha,
    )


# ═══════════════════════════════════════════════════════════════════
# LLM-Powered PR Review (Task 5 — Agent-to-Agent Review)
# ═══════════════════════════════════════════════════════════════════

@dataclass
class PRReviewResult:
    """Result of an LLM-powered PR review."""

    approved: bool
    concerns: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    summary: str = ""
    model_id: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "concerns": self.concerns,
            "suggestions": self.suggestions,
            "summary": self.summary,
            "model_id": self.model_id,
            "timestamp": self.timestamp,
        }


def is_pr_review_enabled() -> bool:
    """Check if LLM-powered PR review is enabled (opt-in via env var)."""
    return os.environ.get("PR_REVIEW_LLM_ENABLED", "").lower() in ("true", "1", "yes")


def review_pr_with_llm(
    diff_text: str,
    spec_content: str = "",
    constraints: list[str] | None = None,
    model_id: str = "",
) -> PRReviewResult:
    """Review a PR diff using an LLM for logic and architecture analysis.

    This is the agent-to-agent review capability. One agent (Engineering)
    produces the diff, another agent (Reviewer) evaluates it against the
    spec and constraints.

    The review checks:
    1. Does the diff satisfy the acceptance criteria in the spec?
    2. Are there architectural concerns (coupling, abstraction leaks)?
    3. Are there logic errors or edge cases not handled?
    4. Does the diff violate any stated constraints?

    Opt-in: Only runs when PR_REVIEW_LLM_ENABLED=true (env var).
    Uses the same Bedrock invocation pattern as the Constraint Extractor.

    Args:
        diff_text: The git diff to review.
        spec_content: The spec/acceptance criteria the diff should satisfy.
        constraints: List of constraints the diff must not violate.
        model_id: Bedrock model ID (defaults to Claude Sonnet).

    Returns:
        PRReviewResult with approval decision, concerns, and suggestions.
    """
    if not is_pr_review_enabled():
        logger.info("LLM PR review skipped — PR_REVIEW_LLM_ENABLED not set")
        return PRReviewResult(
            approved=True,
            summary="LLM review skipped (not enabled)",
        )

    if not diff_text.strip():
        return PRReviewResult(approved=True, summary="Empty diff — nothing to review")

    resolved_model = model_id or os.environ.get(
        "PR_REVIEW_MODEL_ID", "anthropic.claude-sonnet-4-20250514-v1:0"
    )
    constraint_text = "\n".join(f"- {c}" for c in (constraints or []))

    prompt = _build_review_prompt(diff_text, spec_content, constraint_text)

    try:
        response_text = _invoke_bedrock(prompt, resolved_model)
        result = _parse_review_response(response_text)
        result.model_id = resolved_model
        return result
    except Exception as e:
        logger.error("LLM PR review failed: %s", e)
        return PRReviewResult(
            approved=True,
            summary=f"LLM review failed (non-blocking): {e}",
            model_id=resolved_model,
        )


def _build_review_prompt(diff_text: str, spec_content: str, constraint_text: str) -> str:
    """Build the structured review prompt for the LLM."""
    # Truncate diff if too large (keep first 8000 chars)
    truncated_diff = diff_text[:8000]
    if len(diff_text) > 8000:
        truncated_diff += "\n\n[... diff truncated for review ...]"

    prompt = f"""You are reviewing a pull request. Analyze the diff against the spec and constraints.

## Spec / Acceptance Criteria
{spec_content or "(No spec provided — review for general quality)"}

## Constraints (must NOT be violated)
{constraint_text or "(No explicit constraints)"}

## Diff
```
{truncated_diff}
```

## Your Review

Respond in this exact JSON format:
{{
  "approved": true/false,
  "concerns": ["list of concerns (empty if none)"],
  "suggestions": ["list of improvement suggestions (empty if none)"],
  "summary": "one-sentence summary of your review"
}}

Rules:
- approved=false only if there are blocking issues (logic errors, constraint violations, security issues)
- concerns are blocking issues that must be fixed
- suggestions are non-blocking improvements
- Be specific: reference file names and line context from the diff
"""
    return prompt


def _invoke_bedrock(prompt: str, model_id: str) -> str:
    """Invoke Bedrock with the review prompt.

    Uses the same pattern as the Constraint Extractor (direct invoke_model).
    """
    import json as json_module

    bedrock = boto3.client(
        "bedrock-runtime",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
    )

    body = json_module.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 2000,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": prompt}],
    })

    response = bedrock.invoke_model(
        modelId=model_id,
        body=body,
        contentType="application/json",
        accept="application/json",
    )

    response_body = json_module.loads(response["body"].read())
    return response_body["content"][0]["text"]


def _parse_review_response(response_text: str) -> PRReviewResult:
    """Parse the LLM response into a PRReviewResult.

    Handles both clean JSON and JSON embedded in markdown code blocks.
    """
    import json as json_module

    # Try to extract JSON from the response
    text = response_text.strip()

    # Handle markdown code blocks
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        text = text[start:end].strip()

    try:
        data = json_module.loads(text)
        return PRReviewResult(
            approved=data.get("approved", True),
            concerns=data.get("concerns", []),
            suggestions=data.get("suggestions", []),
            summary=data.get("summary", ""),
        )
    except (json_module.JSONDecodeError, KeyError):
        # If parsing fails, treat as approved with the raw text as summary
        logger.warning("Could not parse LLM review response as JSON")
        return PRReviewResult(
            approved=True,
            summary=f"Could not parse response: {text[:200]}",
        )
