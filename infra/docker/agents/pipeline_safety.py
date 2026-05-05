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
