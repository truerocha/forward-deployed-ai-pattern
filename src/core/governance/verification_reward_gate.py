"""
Verification Reward Gate — Deterministic Tool-Use Rewards for ICRL.

Implements the ICRL principle of verifiable tool-use rewards: before PR creation,
the agent runs deterministic verification tools (linter, type-checker, test suite)
on its own output. Tool outputs serve as unambiguous reward signals (Pass/Fail).

The gate operates as an inner loop within a single execution:
  1. Agent writes code
  2. Gate runs verification tools (linter -> type-checker -> tests)
  3. If any fail: agent reads error, refines (max 3 inner iterations)
  4. Only when all pass (or max iterations reached): proceed to PR creation

Verification levels (graceful degradation):
  - Level 3 (full): linter + type-checker + test suite
  - Level 2 (standard): linter + type-checker
  - Level 1 (minimal): linter only
  - Level 0 (bypass): no verification available (logged as reduced confidence)

Research grounding:
  - ICRL verifiable rewards: compiler/runtime logs as clean reward signals
  - Self-Improving Agent (arXiv:2504.15228): autonomous self-editing from feedback
  - DORA 2025: shift-left verification reduces downstream rework

Ref: docs/adr/ADR-027-review-feedback-loop.md (V2: ICRL Enhancement)
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger("fde.governance.verification_gate")

_MAX_INNER_ITERATIONS = 3
_VERIFICATION_TIMEOUT_SECONDS = 120
_MAX_ERROR_CHARS = 2000


class VerificationLevel(Enum):
    """Available verification depth based on project tooling."""

    FULL = "full"
    STANDARD = "standard"
    MINIMAL = "minimal"
    BYPASS = "bypass"


class VerificationStatus(Enum):
    """Result status of a verification step."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass
class VerificationStep:
    """Result of a single verification tool execution."""

    tool_name: str
    status: VerificationStatus
    exit_code: int = 0
    output: str = ""
    error_summary: str = ""
    duration_seconds: float = 0.0
    files_checked: int = 0

    @property
    def passed(self) -> bool:
        return self.status == VerificationStatus.PASSED


@dataclass
class VerificationResult:
    """Complete result of a verification gate execution."""

    level: VerificationLevel
    iteration: int
    steps: list[VerificationStep] = field(default_factory=list)
    all_passed: bool = False
    total_duration_seconds: float = 0.0
    timestamp: str = ""
    files_verified: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        self.all_passed = all(
            s.passed or s.status == VerificationStatus.SKIPPED for s in self.steps
        )
        self.total_duration_seconds = sum(s.duration_seconds for s in self.steps)

    @property
    def failed_steps(self) -> list[VerificationStep]:
        return [s for s in self.steps if s.status == VerificationStatus.FAILED]

    def get_error_feedback(self) -> str:
        """Format failed step outputs as feedback for the agent's inner loop."""
        if not self.failed_steps:
            return ""
        parts = [f"VERIFICATION FAILED (iteration {self.iteration}/{_MAX_INNER_ITERATIONS}):"]
        for step in self.failed_steps:
            parts.append(f"\n[{step.tool_name}] EXIT {step.exit_code}:")
            parts.append(step.error_summary[:500] or step.output[:500])
        return "\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "iteration": self.iteration,
            "all_passed": self.all_passed,
            "total_duration_seconds": round(self.total_duration_seconds, 2),
            "steps": [
                {
                    "tool": s.tool_name,
                    "status": s.status.value,
                    "exit_code": s.exit_code,
                    "duration_seconds": round(s.duration_seconds, 2),
                }
                for s in self.steps
            ],
            "timestamp": self.timestamp,
        }


@dataclass
class GateOutcome:
    """Final outcome of the verification reward gate (across all iterations)."""

    passed: bool
    iterations_used: int
    max_iterations: int
    verification_level: VerificationLevel
    total_duration_seconds: float
    results: list[VerificationResult] = field(default_factory=list)
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "iterations_used": self.iterations_used,
            "max_iterations": self.max_iterations,
            "verification_level": self.verification_level.value,
            "total_duration_seconds": round(self.total_duration_seconds, 2),
            "confidence": round(self.confidence, 3),
        }


class VerificationRewardGate:
    """
    Deterministic verification gate providing reward signals for ICRL.

    Runs available verification tools on agent output before PR creation.
    Provides binary reward signals (pass/fail) for inner-loop refinement.

    Usage:
        gate = VerificationRewardGate(repo_path="/path/to/repo")
        outcome = gate.run_gate(changed_files=["src/auth.py"])
        if outcome.passed:
            # Proceed to PR creation
            ...
        else:
            # PR created with reduced confidence annotation
            ...
    """

    def __init__(
        self,
        repo_path: str = "",
        timeout_seconds: int = _VERIFICATION_TIMEOUT_SECONDS,
        max_iterations: int = _MAX_INNER_ITERATIONS,
    ):
        self._repo_path = repo_path or os.environ.get("REPO_PATH", ".")
        self._timeout = timeout_seconds
        self._max_iterations = max_iterations

    def detect_verification_level(self) -> VerificationLevel:
        """Detect available verification tools in the repository."""
        has_linter = self._detect_tool(["ruff", "flake8", "eslint", "pylint"])
        has_typechecker = self._detect_tool(["mypy", "pyright", "tsc"])
        has_tests = self._detect_test_runner()

        if has_linter and has_typechecker and has_tests:
            return VerificationLevel.FULL
        elif has_linter and has_typechecker:
            return VerificationLevel.STANDARD
        elif has_linter:
            return VerificationLevel.MINIMAL
        else:
            return VerificationLevel.BYPASS

    def verify(
        self,
        changed_files: list[str],
        level: VerificationLevel | None = None,
        iteration: int = 1,
    ) -> VerificationResult:
        """Run a single verification pass on changed files."""
        if level is None:
            level = self.detect_verification_level()

        if level == VerificationLevel.BYPASS:
            return VerificationResult(
                level=level, iteration=iteration, steps=[], files_verified=changed_files,
            )

        steps: list[VerificationStep] = []

        if level in (VerificationLevel.FULL, VerificationLevel.STANDARD, VerificationLevel.MINIMAL):
            steps.append(self._run_linter(changed_files))

        if level in (VerificationLevel.FULL, VerificationLevel.STANDARD):
            steps.append(self._run_type_checker(changed_files))

        if level == VerificationLevel.FULL:
            steps.append(self._run_tests(changed_files))

        return VerificationResult(
            level=level, iteration=iteration, steps=steps, files_verified=changed_files,
        )

    def run_gate(
        self,
        changed_files: list[str],
        level: VerificationLevel | None = None,
    ) -> GateOutcome:
        """Run the full verification gate with inner-loop iterations."""
        if level is None:
            level = self.detect_verification_level()

        if level == VerificationLevel.BYPASS:
            logger.warning("Verification gate BYPASS — no tools available.")
            return GateOutcome(
                passed=True, iterations_used=0, max_iterations=self._max_iterations,
                verification_level=level, total_duration_seconds=0.0, confidence=0.3,
            )

        results: list[VerificationResult] = []
        total_duration = 0.0

        for iteration in range(1, self._max_iterations + 1):
            result = self.verify(changed_files, level, iteration)
            results.append(result)
            total_duration += result.total_duration_seconds

            if result.all_passed:
                confidence = 1.0 - (iteration - 1) * 0.15
                return GateOutcome(
                    passed=True, iterations_used=iteration,
                    max_iterations=self._max_iterations,
                    verification_level=level, total_duration_seconds=total_duration,
                    results=results, confidence=max(0.5, confidence),
                )

            logger.info(
                "Verification iteration %d/%d FAILED: %s",
                iteration, self._max_iterations,
                [s.tool_name for s in result.failed_steps],
            )

        return GateOutcome(
            passed=False, iterations_used=self._max_iterations,
            max_iterations=self._max_iterations,
            verification_level=level, total_duration_seconds=total_duration,
            results=results, confidence=0.2,
        )

    def _run_linter(self, files: list[str]) -> VerificationStep:
        linter = self._find_available_tool(["ruff check", "flake8", "pylint"])
        if not linter:
            return VerificationStep(tool_name="linter", status=VerificationStatus.SKIPPED)
        python_files = [f for f in files if f.endswith(".py")]
        if not python_files:
            return VerificationStep(tool_name="linter", status=VerificationStatus.SKIPPED)
        return self._execute_tool("linter", f"{linter} {' '.join(python_files)}")

    def _run_type_checker(self, files: list[str]) -> VerificationStep:
        checker = self._find_available_tool(["mypy", "pyright"])
        if not checker:
            return VerificationStep(tool_name="type-checker", status=VerificationStatus.SKIPPED)
        python_files = [f for f in files if f.endswith(".py")]
        if not python_files:
            return VerificationStep(tool_name="type-checker", status=VerificationStatus.SKIPPED)
        return self._execute_tool("type-checker", f"{checker} {' '.join(python_files)}")

    def _run_tests(self, files: list[str]) -> VerificationStep:
        runner = self._find_available_tool(["pytest", "python -m pytest"])
        if not runner:
            return VerificationStep(tool_name="tests", status=VerificationStatus.SKIPPED)
        return self._execute_tool("tests", f"{runner} --tb=short -q")

    def _execute_tool(self, tool_name: str, command: str) -> VerificationStep:
        start = time.time()
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=self._timeout, cwd=self._repo_path,
            )
            duration = time.time() - start
            if result.returncode == 0:
                return VerificationStep(
                    tool_name=tool_name, status=VerificationStatus.PASSED,
                    exit_code=0, output=result.stdout[:_MAX_ERROR_CHARS],
                    duration_seconds=duration,
                )
            else:
                return VerificationStep(
                    tool_name=tool_name, status=VerificationStatus.FAILED,
                    exit_code=result.returncode,
                    output=result.stdout[:_MAX_ERROR_CHARS],
                    error_summary=(result.stderr or result.stdout)[:_MAX_ERROR_CHARS],
                    duration_seconds=duration,
                )
        except subprocess.TimeoutExpired:
            return VerificationStep(
                tool_name=tool_name, status=VerificationStatus.TIMEOUT,
                exit_code=-1, error_summary=f"Timeout after {self._timeout}s",
                duration_seconds=self._timeout,
            )
        except Exception as e:
            return VerificationStep(
                tool_name=tool_name, status=VerificationStatus.ERROR,
                exit_code=-1, error_summary=str(e)[:_MAX_ERROR_CHARS],
                duration_seconds=time.time() - start,
            )

    def _detect_tool(self, candidates: list[str]) -> bool:
        for tool in candidates:
            try:
                result = subprocess.run(
                    f"which {tool}", shell=True, capture_output=True, timeout=5,
                )
                if result.returncode == 0:
                    return True
            except (subprocess.TimeoutExpired, Exception):
                continue
        return False

    def _detect_test_runner(self) -> bool:
        has_pytest = self._detect_tool(["pytest"])
        if has_pytest:
            tests_dir = os.path.join(self._repo_path, "tests")
            return os.path.isdir(tests_dir)
        return False

    def _find_available_tool(self, candidates: list[str]) -> str:
        for tool in candidates:
            tool_name = tool.split()[0]
            try:
                result = subprocess.run(
                    f"which {tool_name}", shell=True, capture_output=True, timeout=5,
                )
                if result.returncode == 0:
                    return tool
            except (subprocess.TimeoutExpired, Exception):
                continue
        return ""
