"""
Scope Boundaries — Enforces what the Code Factory can and cannot do (ADR-013, Decision 4).

This is the factory's "autonomy certificate" — a programmatic definition of
its operational limits. The DoR Gate consumes this module to reject tasks
that are out of scope BEFORE the pipeline starts.

Source: "Levels of Autonomy for AI Agents" (Feng et al., 2025) — autonomy certificates
Source: "WhatsCode" (Mao et al., 2025) — organizational factors

Scope rules:
  IN-SCOPE:  Tasks with acceptance criteria, tech_stack, and no forbidden actions
  OUT-OF-SCOPE: Production deploys, PR merges, tasks without halting conditions
  CONDITIONAL: Tasks with unsupported languages (accepted with low confidence)

Confidence levels:
  high:   tech_stack has tooling + 3+ acceptance criteria + constraints present
  medium: tech_stack has tooling + 1-2 acceptance criteria
  low:    tech_stack has no tooling OR single vague criterion
"""

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger("fde.scope_boundaries")


# ─── Supported tech stacks (have lint/test/build commands configured) ───

_SUPPORTED_STACKS: set[str] = {
    "python", "typescript", "javascript", "go", "rust", "java",
    "terraform", "docker", "react", "next.js", "fastapi", "flask",
    "django", "node.js", "aws", "postgresql", "mysql", "redis",
}


# ─── Forbidden action patterns ─────────────────────────────────

_FORBIDDEN_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bdeploy\b.*\bto\s+production\b", re.IGNORECASE), "production_deploy_forbidden"),
    (re.compile(r"\bproduction\s+deploy", re.IGNORECASE), "production_deploy_forbidden"),
    (re.compile(r"\bmerge\s+(the\s+)?PR\b", re.IGNORECASE), "merge_forbidden"),
    (re.compile(r"\bmerge\s+(the\s+)?MR\b", re.IGNORECASE), "merge_forbidden"),
    (re.compile(r"\bmerge\s+to\s+main\b", re.IGNORECASE), "merge_forbidden"),
    (re.compile(r"\bmerge\s+to\s+master\b", re.IGNORECASE), "merge_forbidden"),
    (re.compile(r"\bclose\s+(the\s+)?issue\b", re.IGNORECASE), "close_issue_forbidden"),
    (re.compile(r"\bdelete\s+(the\s+)?repo", re.IGNORECASE), "destructive_action_forbidden"),
    (re.compile(r"\bforce\s+push\b", re.IGNORECASE), "destructive_action_forbidden"),
    (re.compile(r"\brm\s+-rf\s+/", re.IGNORECASE), "destructive_action_forbidden"),
]


@dataclass
class ScopeCheckResult:
    """Result of checking whether a task is within the factory's scope."""

    in_scope: bool
    confidence_level: str = "medium"     # "high" | "medium" | "low"
    rejection_reason: str = ""           # Why it was rejected (empty if in_scope)
    details: str = ""                    # Human-readable explanation
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "in_scope": self.in_scope,
            "confidence_level": self.confidence_level,
            "rejection_reason": self.rejection_reason,
            "details": self.details,
            "warnings": self.warnings,
        }


def check_scope(data_contract: dict) -> ScopeCheckResult:
    """Check whether a task is within the Code Factory's operational scope.

    Applies rules in order:
    1. Hard rejections (forbidden actions, missing halting condition)
    2. Soft warnings (unsupported language, vague criteria)
    3. Confidence scoring based on available signals

    Args:
        data_contract: The canonical data contract dict.

    Returns:
        ScopeCheckResult with in_scope, confidence, and details.
    """
    warnings: list[str] = []

    # ── Hard rejection: no acceptance criteria (no halting condition) ──
    acceptance_criteria = data_contract.get("acceptance_criteria", [])
    if not acceptance_criteria:
        return ScopeCheckResult(
            in_scope=False,
            rejection_reason="no_halting_condition",
            details="Task has no acceptance_criteria — agent has no halting condition",
        )

    # ── Hard rejection: no tech_stack ──
    tech_stack = data_contract.get("tech_stack", [])
    if not tech_stack:
        return ScopeCheckResult(
            in_scope=False,
            rejection_reason="no_tech_stack",
            details="Task has no tech_stack — Agent Builder cannot provision a specialized agent",
        )

    # ── Hard rejection: forbidden actions in description/title/criteria ──
    searchable_text = " ".join([
        data_contract.get("title", ""),
        data_contract.get("description", ""),
        " ".join(acceptance_criteria),
    ])

    for pattern, reason in _FORBIDDEN_PATTERNS:
        if pattern.search(searchable_text):
            return ScopeCheckResult(
                in_scope=False,
                rejection_reason=reason,
                details=f"Task requests a forbidden action: {reason}",
            )

    # ── Soft warning: unsupported language ──
    stack_lower = {s.lower() for s in tech_stack}
    has_supported = any(
        supported in item
        for item in stack_lower
        for supported in _SUPPORTED_STACKS
    )
    if not has_supported:
        warnings.append("no_inner_loop_tooling")

    # ── Confidence scoring ──
    confidence_score = 0

    # Signal 1: tech_stack has tooling
    if has_supported:
        confidence_score += 1

    # Signal 2: acceptance criteria are specific (>= 3 items)
    if len(acceptance_criteria) >= 3:
        confidence_score += 1

    # Signal 3: constraints are present
    constraints = data_contract.get("constraints", "")
    if constraints and str(constraints).strip():
        confidence_score += 1

    # Signal 4: related_docs are present
    related_docs = data_contract.get("related_docs", [])
    if related_docs:
        confidence_score += 1

    # Map score to confidence level
    if confidence_score >= 2:
        confidence_level = "high"
    elif confidence_score >= 1:
        confidence_level = "medium"
    else:
        confidence_level = "low"

    logger.info(
        "Scope check: in_scope=True, confidence=%s (score=%d), warnings=%s",
        confidence_level, confidence_score, warnings,
    )

    return ScopeCheckResult(
        in_scope=True,
        confidence_level=confidence_level,
        warnings=warnings,
    )
