"""
Failure Mode Taxonomy — Classifies WHY tasks fail (ADR-013, Decision 2).

The Circuit Breaker already classifies CODE vs ENVIRONMENT. This module
adds second-level classification within CODE failures using detectable
signals from the execution context.

Source: "SWE-Bench Pro" (Deng et al., Sep 2025) — failure mode clustering
Source: "SWE-AGI" (Zhang et al., Feb 2026) — spec-intensive degradation

Taxonomy:
  FM-01 SPEC_AMBIGUITY:      Spec is ambiguous, agent cannot determine intent
  FM-02 CONSTRAINT_CONFLICT:  Extracted constraints conflict with each other
  FM-03 TOOL_FAILURE:         External tool (git, npm, docker) failed
  FM-04 MODEL_HALLUCINATION:  Agent produced code that doesn't match spec
  FM-05 COMPLEXITY_EXCEEDED:  Task exceeds agent capability
  FM-06 TEST_REGRESSION:      New code breaks existing tests
  FM-07 DEPENDENCY_MISSING:   Required dependency not available
  FM-08 TIMEOUT:              Execution exceeded time limit
  FM-09 AUTH_FAILURE:         ALM token expired or insufficient permissions
  FM-99 UNKNOWN:              Unclassified failure (catch-all for post-mortem)

Classification uses heuristic rules on the execution context dict.
After 100 tasks, the taxonomy should be reviewed against real data.
"""

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger("fde.failure_modes")


@dataclass
class FailureModeResult:
    """Result of classifying a failure mode."""

    code: str                            # "FM-01" through "FM-99"
    category: str                        # Human-readable category name
    recovery_action: str                 # What the system should do next
    raw_context: dict = field(default_factory=dict)
    confidence: float = 1.0              # How confident the classification is (0-1)

    def to_metric_dimensions(self) -> dict:
        """Convert to dimensions dict for DORA metrics recording."""
        return {
            "failure_mode": self.code,
            "failure_category": self.category,
            "recovery_action": self.recovery_action,
            "classification_confidence": self.confidence,
        }

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "category": self.category,
            "recovery_action": self.recovery_action,
            "confidence": self.confidence,
        }


# ─── Environment Error Patterns (from Circuit Breaker) ──────────

_ENVIRONMENT_PATTERNS: list[re.Pattern] = [
    re.compile(r"ECONNREFUSED", re.IGNORECASE),
    re.compile(r"EADDRINUSE", re.IGNORECASE),
    re.compile(r"permission denied", re.IGNORECASE),
    re.compile(r"EACCES", re.IGNORECASE),
    re.compile(r"ENOMEM", re.IGNORECASE),
    re.compile(r"disk full", re.IGNORECASE),
    re.compile(r"command not found", re.IGNORECASE),
    re.compile(r"docker.*(not running|daemon)", re.IGNORECASE),
    re.compile(r"port.*in use", re.IGNORECASE),
    re.compile(r"credential.*expired", re.IGNORECASE),
    re.compile(r"network.*(error|timeout|unreachable)", re.IGNORECASE),
    re.compile(r"package.*not found", re.IGNORECASE),
]

_AUTH_PATTERNS: list[re.Pattern] = [
    re.compile(r"401\s*Unauthorized", re.IGNORECASE),
    re.compile(r"403\s*Forbidden", re.IGNORECASE),
    re.compile(r"token.*expired", re.IGNORECASE),
    re.compile(r"authentication.*failed", re.IGNORECASE),
    re.compile(r"insufficient.*permissions?", re.IGNORECASE),
    re.compile(r"Bad credentials", re.IGNORECASE),
]


# ─── Classification Logic ───────────────────────────────────────

def classify_failure(context: dict) -> FailureModeResult:
    """Classify a task failure into a failure mode using execution context signals.

    The classifier applies rules in priority order. The first matching rule wins.
    If no rule matches, FM-99 (UNKNOWN) is returned with the full context preserved.

    Args:
        context: Execution context dict with keys like:
            - error_message (str): The error text
            - exit_code (int): Process exit code
            - stage (str): Which pipeline stage failed
            - dor_warnings (list): DoR Gate warnings
            - dor_failures (list): DoR Gate failures
            - command_output (str): Shell command output
            - tests_before (dict): Test results before changes
            - tests_after (dict): Test results after changes
            - files_modified (int): Number of files changed
            - execution_time_ms (int): How long execution took
            - max_execution_time_ms (int): Time limit

    Returns:
        FailureModeResult with code, category, and recovery action.
    """
    error_msg = context.get("error_message", "")
    command_output = context.get("command_output", "")
    combined_text = f"{error_msg} {command_output}"

    # ── Priority 1: Auth failures (FM-09) ───────────────────────
    if _matches_any(_AUTH_PATTERNS, combined_text):
        return FailureModeResult(
            code="FM-09",
            category="AUTH_FAILURE",
            recovery_action="report_environment_error",
            raw_context=context,
            confidence=0.95,
        )

    # ── Priority 2: Constraint conflicts (FM-02) ────────────────
    dor_failures = context.get("dor_failures", [])
    if dor_failures:
        return FailureModeResult(
            code="FM-02",
            category="CONSTRAINT_CONFLICT",
            recovery_action="request_human_resolution",
            raw_context=context,
            confidence=0.9,
        )

    # ── Priority 3: Spec ambiguity (FM-01) ──────────────────────
    dor_warnings = context.get("dor_warnings", [])
    if len(dor_warnings) >= 3:
        return FailureModeResult(
            code="FM-01",
            category="SPEC_AMBIGUITY",
            recovery_action="request_clarification",
            raw_context=context,
            confidence=0.8,
        )

    # ── Priority 4: Test regression (FM-06) ─────────────────────
    tests_before = context.get("tests_before", {})
    tests_after = context.get("tests_after", {})
    if tests_before and tests_after:
        failed_before = tests_before.get("failed", 0)
        failed_after = tests_after.get("failed", 0)
        if failed_after > failed_before:
            return FailureModeResult(
                code="FM-06",
                category="TEST_REGRESSION",
                recovery_action="rollback_and_retry",
                raw_context=context,
                confidence=0.95,
            )

    # ── Priority 5: Tool/environment failure (FM-03) ────────────
    if _matches_any(_ENVIRONMENT_PATTERNS, combined_text):
        return FailureModeResult(
            code="FM-03",
            category="TOOL_FAILURE",
            recovery_action="retry_with_backoff",
            raw_context=context,
            confidence=0.85,
        )

    # ── Priority 6: Complexity exceeded (FM-05) ─────────────────
    files_modified = context.get("files_modified", 0)
    execution_time_ms = context.get("execution_time_ms", 0)
    max_time = context.get("max_execution_time_ms", 300000)

    if files_modified >= 15 and execution_time_ms >= max_time:
        return FailureModeResult(
            code="FM-05",
            category="COMPLEXITY_EXCEEDED",
            recovery_action="decompose_into_subtasks",
            raw_context=context,
            confidence=0.8,
        )

    # ── Priority 7: Timeout without complexity (FM-08) ──────────
    if execution_time_ms >= max_time or "TIMEOUT" in error_msg.upper():
        return FailureModeResult(
            code="FM-08",
            category="TIMEOUT",
            recovery_action="rollback_and_report",
            raw_context=context,
            confidence=0.85,
        )

    # ── Priority 8: Dependency missing (FM-07) ──────────────────
    dep_patterns = [
        re.compile(r"ModuleNotFoundError", re.IGNORECASE),
        re.compile(r"ImportError", re.IGNORECASE),
        re.compile(r"Cannot find module", re.IGNORECASE),
        re.compile(r"No such file or directory", re.IGNORECASE),
    ]
    if _matches_any(dep_patterns, combined_text):
        return FailureModeResult(
            code="FM-07",
            category="DEPENDENCY_MISSING",
            recovery_action="report_and_block",
            raw_context=context,
            confidence=0.7,
        )

    # ── Catch-all: Unknown (FM-99) ──────────────────────────────
    logger.warning("Failure mode unclassified — FM-99. Context: %s", error_msg[:200])
    return FailureModeResult(
        code="FM-99",
        category="UNKNOWN",
        recovery_action="log_and_report",
        raw_context=context,
        confidence=0.0,
    )


def _matches_any(patterns: list[re.Pattern], text: str) -> bool:
    """Check if any pattern matches the text."""
    return any(p.search(text) for p in patterns)
