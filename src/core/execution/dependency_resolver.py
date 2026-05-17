"""
Dependency Resolver — Executes a ProvisioningPlan to install missing dependencies.

This module takes the plan produced by DependencyAwareness and executes it:
  - pip install --user (Python packages)
  - Binary downloads (terraform, go, etc.)
  - npm install (Node packages)
  - PATH augmentation (ensures installed binaries are discoverable)

Design decisions:
  - Non-root execution: all installs use --user or $HOME/.local/bin/
  - Budget-aware: stops if total time exceeds plan.total_budget_seconds
  - Best-effort: failures are recorded but don't block the pipeline
  - Idempotent: already-installed packages are no-ops (pip handles this)
  - Follows KG cascade pattern: resolve what you can, report what you can't
  - PATH is augmented ONCE at the start (not per-action)

Security:
  - Only installs from the project's own manifests (requirements.txt, package.json)
  - Binary downloads use pinned versions from TECH_STACK_PROVISIONS
  - No arbitrary package names from user input — all derived from known sources

Ref: ADR-038 Wave 4 (Dependency Provisioning Phase)
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from src.core.execution.dependency_awareness import InstallAction, ProvisioningPlan

logger = logging.getLogger(__name__)

# User-local binary directory (non-root install target)
LOCAL_BIN = os.path.expanduser("~/.local/bin")


# ═══════════════════════════════════════════════════════════════════
# Data Contracts
# ═══════════════════════════════════════════════════════════════════

@dataclass
class ActionResult:
    """Result of executing a single InstallAction."""

    name: str
    status: str          # "installed" | "already_available" | "failed" | "skipped" | "timeout"
    duration_ms: int = 0
    error: str = ""
    command: str = ""


@dataclass
class ResolutionResult:
    """Aggregate result of executing the full provisioning plan."""

    installed: list[str] = field(default_factory=list)
    already_available: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    action_results: list[ActionResult] = field(default_factory=list)
    duration_ms: int = 0
    path_additions: list[str] = field(default_factory=list)
    budget_exhausted: bool = False

    @property
    def total_resolved(self) -> int:
        return len(self.installed) + len(self.already_available)

    def summary(self) -> str:
        parts = []
        if self.installed:
            parts.append(f"installed={len(self.installed)}")
        if self.already_available:
            parts.append(f"already_available={len(self.already_available)}")
        if self.failed:
            parts.append(f"failed={len(self.failed)}")
        if self.budget_exhausted:
            parts.append("BUDGET_EXHAUSTED")
        return f"Resolution: {', '.join(parts)} ({self.duration_ms}ms)"


# ═══════════════════════════════════════════════════════════════════
# Core Logic
# ═══════════════════════════════════════════════════════════════════

def resolve_dependencies(
    plan: ProvisioningPlan,
    event_callback: Optional[Callable] = None,
    task_id: str = "",
) -> ResolutionResult:
    """Execute a provisioning plan to install missing dependencies.

    Runs each action in priority order. Stops if the total budget is exhausted.
    Already-available tools are detected via shutil.which() and skipped.

    Args:
        plan: The ProvisioningPlan from build_provisioning_plan().
        event_callback: Optional Callable(task_id, event_type, message, **metadata)
                       for observability events.
        task_id: Task ID for event emission.

    Returns:
        ResolutionResult with per-action details.
    """
    result = ResolutionResult()
    start_time = time.time()

    if not plan.has_actions():
        logger.info("No provisioning actions needed")
        return result

    # ── Step 0: Augment PATH ─────────────────────────────────────────
    # Ensure ~/.local/bin is in PATH so shutil.which() finds installed tools
    _augment_path(result)

    logger.info(
        "Dependency resolver starting: %d actions, budget=%ds",
        len(plan.actions), plan.total_budget_seconds,
    )

    if event_callback and task_id:
        event_callback(
            task_id, "system",
            f"🔧 Dependency provisioning: {plan.summary()}",
            phase="provisioning",
        )

    # ── Step 1: Execute actions in priority order ────────────────────
    for action in plan.actions:
        elapsed_ms = int((time.time() - start_time) * 1000)

        # Budget check
        if elapsed_ms >= plan.total_budget_seconds * 1000:
            result.budget_exhausted = True
            result.skipped.append(action.name)
            result.action_results.append(ActionResult(
                name=action.name, status="skipped",
                error="Budget exhausted",
            ))
            logger.warning("Budget exhausted — skipping %s", action.name)
            continue

        # Check if already available
        if _is_already_available(action):
            result.already_available.append(action.name)
            result.action_results.append(ActionResult(
                name=action.name, status="already_available",
            ))
            logger.debug("%s already available — skipping", action.name)
            continue

        # Execute the install action
        action_result = _execute_action(action)
        result.action_results.append(action_result)

        if action_result.status == "installed":
            result.installed.append(action.name)
            logger.info("Installed: %s (%dms)", action.name, action_result.duration_ms)
        else:
            result.failed.append(action.name)
            logger.warning(
                "Failed to install %s: %s", action.name, action_result.error[:200],
            )

    result.duration_ms = int((time.time() - start_time) * 1000)

    logger.info(
        "Dependency resolver complete: %s",
        result.summary(),
    )

    if event_callback and task_id:
        event_callback(
            task_id, "gate",
            f"🔧 {result.summary()}",
            phase="provisioning",
            gate_name="dependency_provisioning",
            gate_result="pass" if not result.failed else "warn",
            context=f"Installed: {result.installed}. Failed: {result.failed}. "
                    f"Already available: {result.already_available}.",
        )

    return result


def _augment_path(result: ResolutionResult) -> None:
    """Ensure ~/.local/bin and other user-install paths are in PATH."""
    current_path = os.environ.get("PATH", "")
    additions = []

    # Python user scripts
    if LOCAL_BIN not in current_path:
        additions.append(LOCAL_BIN)

    # Go binary path (if Go is installed to ~/.local)
    go_bin = os.path.expanduser("~/.local/go/bin")
    if go_bin not in current_path:
        additions.append(go_bin)

    # Rust/Cargo binary path
    cargo_bin = os.path.expanduser("~/.cargo/bin")
    if cargo_bin not in current_path:
        additions.append(cargo_bin)

    if additions:
        new_path = ":".join(additions) + ":" + current_path
        os.environ["PATH"] = new_path
        result.path_additions = additions
        logger.info("PATH augmented: +%s", additions)

    # Ensure the directory exists
    os.makedirs(LOCAL_BIN, exist_ok=True)


def _is_already_available(action: InstallAction) -> bool:
    """Check if the tool/package from this action is already available."""
    # For pip packages, check if the binary is in PATH
    binary_name = _action_to_binary_name(action)
    if binary_name:
        return shutil.which(binary_name) is not None

    # For manifest installs, we can't easily check — always run
    if action.source == "repo_manifest":
        return False

    return False


def _action_to_binary_name(action: InstallAction) -> str:
    """Map an InstallAction to the binary name it provides."""
    name_to_binary = {
        "pytest": "pytest",
        "ruff": "ruff",
        "pip-tools": "pip-compile",
        "black": "black",
        "mypy": "mypy",
        "terraform": "terraform",
        "go": "go",
        "cargo": "cargo",
        "typescript": "tsc",
        "httpx": "",  # Library, no binary
        "npm-check": "node",
    }
    return name_to_binary.get(action.name, "")


def _execute_action(action: InstallAction) -> ActionResult:
    """Execute a single install action via subprocess.

    Runs the command with shell=True in a subprocess with timeout.
    The command is from TECH_STACK_PROVISIONS (trusted, not user input).
    """
    start = time.time()

    try:
        # Expand $HOME in commands
        command = action.command.replace("$HOME", os.path.expanduser("~"))

        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=action.timeout_seconds,
            env={**os.environ},  # Inherit augmented PATH
        )

        duration_ms = int((time.time() - start) * 1000)

        if proc.returncode == 0:
            return ActionResult(
                name=action.name,
                status="installed",
                duration_ms=duration_ms,
                command=action.command,
            )
        else:
            return ActionResult(
                name=action.name,
                status="failed",
                duration_ms=duration_ms,
                error=proc.stderr[:500] or proc.stdout[:500] or f"Exit code {proc.returncode}",
                command=action.command,
            )

    except subprocess.TimeoutExpired:
        duration_ms = int((time.time() - start) * 1000)
        return ActionResult(
            name=action.name,
            status="timeout",
            duration_ms=duration_ms,
            error=f"Timed out after {action.timeout_seconds}s",
            command=action.command,
        )
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        return ActionResult(
            name=action.name,
            status="failed",
            duration_ms=duration_ms,
            error=str(e)[:500],
            command=action.command,
        )
