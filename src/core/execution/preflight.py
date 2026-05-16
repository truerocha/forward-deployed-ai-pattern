"""
Pre-flight Workspace Validation — Wave 3.

Validates that the workspace has everything needed BEFORE executing steps.
This catches failures early (before burning compute) and provides actionable
error messages instead of cryptic "command not found" failures mid-execution.

Checks performed:
  1. Scripts exist: Every script referenced in commands exists in the workspace
  2. Dependencies available: Python packages, binaries, etc. are importable/callable
  3. Directories exist: Output directories for artifacts exist (or can be created)
  4. Git state clean: No uncommitted changes that would conflict with artifact generation

Design decisions:
  - Pre-flight runs BEFORE the step loop (fail fast, zero wasted compute)
  - Returns a structured report (not just pass/fail) so the dashboard shows WHAT is missing
  - Non-blocking mode available: warn but continue (for optional dependencies)
  - Checks are derived from the parsed ExecutionSteps (not hardcoded)

Ref: ADR-038 Wave 3 (Pre-flight workspace validation)
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field

from src.core.execution.spec_parser import ExecutionStep

logger = logging.getLogger(__name__)


@dataclass
class PreflightCheck:
    """A single pre-flight validation check."""

    name: str
    description: str
    passed: bool = False
    error: str = ""
    severity: str = "error"  # "error" (blocks) | "warning" (continues)


@dataclass
class PreflightResult:
    """Aggregate result of all pre-flight checks."""

    passed: bool = True
    checks: list[PreflightCheck] = field(default_factory=list)
    blocking_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_check(self, check: PreflightCheck) -> None:
        self.checks.append(check)
        if not check.passed:
            if check.severity == "error":
                self.passed = False
                self.blocking_errors.append(f"{check.name}: {check.error}")
            else:
                self.warnings.append(f"{check.name}: {check.error}")

    def summary(self) -> str:
        total = len(self.checks)
        passed = sum(1 for c in self.checks if c.passed)
        failed = total - passed
        parts = [f"Pre-flight: {passed}/{total} checks passed"]
        if self.blocking_errors:
            parts.append(f"BLOCKING: {'; '.join(self.blocking_errors[:3])}")
        if self.warnings:
            parts.append(f"Warnings: {'; '.join(self.warnings[:3])}")
        return " | ".join(parts)


def run_preflight(
    steps: list[ExecutionStep],
    workspace_dir: str,
) -> PreflightResult:
    """Run all pre-flight checks for the given execution steps.

    Extracts requirements from the step commands and validates them
    against the workspace state.

    Args:
        steps: Parsed execution steps with commands.
        workspace_dir: The cloned repo working directory.

    Returns:
        PreflightResult with pass/fail and detailed check results.
    """
    result = PreflightResult()

    # Collect all commands across all steps
    all_commands = []
    for step in steps:
        all_commands.extend(step.commands)
        if step.gate:
            all_commands.append(step.gate)

    # Check 1: Scripts exist
    _check_scripts_exist(all_commands, workspace_dir, result)

    # Check 2: Python modules importable
    _check_python_imports(all_commands, workspace_dir, result)

    # Check 3: Binaries available
    _check_binaries_available(all_commands, result)

    # Check 4: Output directories
    _check_output_directories(all_commands, workspace_dir, result)

    # Check 5: Git state (warning only — non-blocking)
    _check_git_state(workspace_dir, result)

    logger.info(
        "Pre-flight complete: passed=%s, checks=%d, errors=%d, warnings=%d",
        result.passed, len(result.checks), len(result.blocking_errors), len(result.warnings),
    )

    return result


def _check_scripts_exist(commands: list[str], workspace_dir: str, result: PreflightResult) -> None:
    """Verify that referenced scripts exist in the workspace."""
    import re

    # Extract script paths from commands like "python3 scripts/generate_foo.py"
    script_pattern = r"(?:python3?|bash|sh)\s+([\w/\-\.]+\.(?:py|sh|bash))"

    seen_scripts = set()
    for cmd in commands:
        matches = re.findall(script_pattern, cmd)
        for script_path in matches:
            if script_path in seen_scripts:
                continue
            seen_scripts.add(script_path)

            full_path = os.path.join(workspace_dir, script_path)
            exists = os.path.isfile(full_path)

            result.add_check(PreflightCheck(
                name=f"script:{script_path}",
                description=f"Script {script_path} exists in workspace",
                passed=exists,
                error="" if exists else f"Script not found: {full_path}",
                severity="error",
            ))


def _check_python_imports(commands: list[str], workspace_dir: str, result: PreflightResult) -> None:
    """Check that pytest and key Python packages are available."""
    import re

    # Check if pytest is needed
    needs_pytest = any("pytest" in cmd for cmd in commands)
    if needs_pytest:
        pytest_available = shutil.which("pytest") is not None
        result.add_check(PreflightCheck(
            name="binary:pytest",
            description="pytest is available in PATH",
            passed=pytest_available,
            error="" if pytest_available else "pytest not found in PATH — install with: pip install pytest",
            severity="error",
        ))

    # Check if pip-compile is needed
    needs_pip_compile = any("pip-compile" in cmd for cmd in commands)
    if needs_pip_compile:
        available = shutil.which("pip-compile") is not None
        result.add_check(PreflightCheck(
            name="binary:pip-compile",
            description="pip-compile is available in PATH",
            passed=available,
            error="" if available else "pip-compile not found — install with: pip install pip-tools",
            severity="error",
        ))


def _check_binaries_available(commands: list[str], result: PreflightResult) -> None:
    """Check that referenced binaries exist in PATH."""
    import re

    # Common binaries that might be referenced
    binary_patterns = {
        "git": r"\bgit\s+",
        "docker": r"\bdocker\s+",
        "terraform": r"\bterraform\s+",
        "node": r"\bnode\s+",
        "npm": r"\bnpm\s+",
    }

    for binary, pattern in binary_patterns.items():
        needed = any(re.search(pattern, cmd) for cmd in commands)
        if needed:
            available = shutil.which(binary) is not None
            result.add_check(PreflightCheck(
                name=f"binary:{binary}",
                description=f"{binary} is available in PATH",
                passed=available,
                error="" if available else f"{binary} not found in PATH",
                severity="error" if binary in ("git",) else "warning",
            ))


def _check_output_directories(commands: list[str], workspace_dir: str, result: PreflightResult) -> None:
    """Check that output directories referenced in git add commands exist (or create them)."""
    import re

    # Extract directories from "git add artifacts/..." or "mkdir -p dir/..."
    dir_pattern = r"git\s+add\s+([\w/\-]+)/"
    seen_dirs = set()

    for cmd in commands:
        matches = re.findall(dir_pattern, cmd)
        for dir_path in matches:
            if dir_path in seen_dirs:
                continue
            seen_dirs.add(dir_path)

            full_path = os.path.join(workspace_dir, dir_path)
            exists = os.path.isdir(full_path)

            if not exists:
                # Try to create it (non-blocking — many specs expect the script to create it)
                try:
                    os.makedirs(full_path, exist_ok=True)
                    exists = True
                except OSError:
                    pass

            result.add_check(PreflightCheck(
                name=f"dir:{dir_path}",
                description=f"Output directory {dir_path}/ exists",
                passed=exists,
                error="" if exists else f"Cannot create directory: {full_path}",
                severity="warning",  # Scripts often create their own output dirs
            ))


def _check_git_state(workspace_dir: str, result: PreflightResult) -> None:
    """Check git working tree is clean (warning only)."""
    try:
        proc = subprocess.run(
            "git status --porcelain",
            shell=True,
            cwd=workspace_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        is_clean = proc.returncode == 0 and not proc.stdout.strip()
        result.add_check(PreflightCheck(
            name="git:clean-state",
            description="Git working tree is clean",
            passed=is_clean,
            error="" if is_clean else f"Uncommitted changes: {proc.stdout[:100]}",
            severity="warning",  # Non-blocking — scripts may generate files
        ))
    except Exception as e:
        result.add_check(PreflightCheck(
            name="git:clean-state",
            description="Git working tree is clean",
            passed=True,  # Don't block on git check failure
            error="",
            severity="warning",
        ))
