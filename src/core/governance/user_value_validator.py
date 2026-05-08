"""
User Value Validator — DORA C6 User-Centric Focus.

DORA 2025's most critical finding: "In the absence of user-centric focus,
AI adoption can have a NEGATIVE impact on team performance."

Scores completeness 0-100 based on user story format presence and quality.
Threshold: Score < 40 = reject (DoR gate blocks the task).

Ref: docs/design/fde-core-brain-development.md Section 5.2
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_REJECTION_THRESHOLD = 40
_WARNING_THRESHOLD = 60

_USER_ROLE_PATTERNS = [
    r"[Aa]s\s+(?:a|an)\s+(.+?)(?:,|\s+I\s)",
    r"[Uu]ser\s*(?:role|type|persona)?\s*:\s*(.+)",
    r"[Tt]arget\s+(?:user|audience)\s*:\s*(.+)",
]

_ACTION_PATTERNS = [
    r"I\s+want\s+(?:to\s+)?(.+?)(?:,|\s+so\s+that|\.|$)",
    r"[Ss]hould\s+(?:be\s+able\s+to\s+)?(.+?)(?:\.|,|$)",
    r"[Nn]eed(?:s)?\s+(?:to\s+)?(.+?)(?:\.|,|$)",
]

_VALUE_PATTERNS = [
    r"[Ss]o\s+that\s+(.+?)(?:\.|$)",
    r"[Ii]n\s+order\s+to\s+(.+?)(?:\.|$)",
    r"[Bb]enefit\s*:\s*(.+)",
    r"[Vv]alue\s*:\s*(.+)",
]

_INFRASTRUCTURE_KEYWORDS = [
    "terraform", "infrastructure", "ci/cd", "pipeline", "deployment",
    "monitoring", "alerting", "logging", "security group", "iam",
    "database migration", "schema change", "dependency update",
]


@dataclass
class ValidationResult:
    """Result of user value validation."""

    score: int
    status: str  # "pass" | "warning" | "reject"
    user_role: str | None = None
    action: str | None = None
    value: str | None = None
    is_infrastructure_task: bool = False
    feedback: list[str] = field(default_factory=list)
    deductions: list[str] = field(default_factory=list)

    @property
    def user_value_statement(self) -> str:
        """Reconstruct the user value statement from parsed components."""
        parts = []
        if self.user_role:
            parts.append(f"As a {self.user_role}")
        if self.action:
            parts.append(f"I want {self.action}")
        if self.value:
            parts.append(f"so that {self.value}")
        return ", ".join(parts) if parts else ""


class UserValueValidator:
    """
    Validates that specs contain identifiable user value.

    Usage:
        validator = UserValueValidator()
        result = validator.validate(spec_text="As a developer, I want...")
        if result.status == "reject":
            print(f"Rejected: score {result.score}/100")
    """

    def __init__(self, rejection_threshold: int = _REJECTION_THRESHOLD):
        self._rejection_threshold = rejection_threshold

    def validate(self, spec_text: str, acceptance_criteria: list[str] | None = None) -> ValidationResult:
        """Validate user value presence in a spec."""
        score = 0
        feedback, deductions = [], []

        is_infra = self._is_infrastructure_task(spec_text)
        if is_infra:
            feedback.append("Infrastructure task detected — user value requirement relaxed")
            score = 50

        user_role = self._extract_user_role(spec_text)
        if user_role:
            score += 25
            feedback.append(f"User role identified: '{user_role}'")
        else:
            deductions.append("No user role identified")

        action = self._extract_action(spec_text)
        if action:
            score += 25
            feedback.append(f"Action specified: '{action[:60]}'")
        else:
            deductions.append("No action specified")

        value = self._extract_value(spec_text)
        if value:
            score += 25
            feedback.append(f"Value articulated: '{value[:60]}'")
        else:
            deductions.append("No value articulated")

        if acceptance_criteria:
            user_benefit_count = self._count_user_benefit_criteria(acceptance_criteria)
            if user_benefit_count > 0:
                score += 15
                feedback.append(f"{user_benefit_count} criteria reference user benefit")
            else:
                deductions.append("Acceptance criteria are purely technical")
        else:
            deductions.append("No acceptance criteria provided")

        if self._has_non_technical_context(spec_text):
            score += 10
            feedback.append("Spec includes business/user perspective")
        elif not is_infra:
            deductions.append("Spec is purely technical")

        score = min(100, score)

        if score >= _WARNING_THRESHOLD:
            status = "pass"
        elif score >= self._rejection_threshold:
            status = "warning"
        else:
            status = "reject"

        return ValidationResult(
            score=score, status=status, user_role=user_role,
            action=action, value=value, is_infrastructure_task=is_infra,
            feedback=feedback, deductions=deductions,
        )

    def _extract_user_role(self, text: str) -> str | None:
        for pattern in _USER_ROLE_PATTERNS:
            match = re.search(pattern, text)
            if match:
                role = match.group(1).strip().rstrip(",.")
                if 2 < len(role) < 100:
                    return role
        return None

    def _extract_action(self, text: str) -> str | None:
        for pattern in _ACTION_PATTERNS:
            match = re.search(pattern, text)
            if match:
                action = match.group(1).strip().rstrip(",.")
                if len(action) > 5:
                    return action
        return None

    def _extract_value(self, text: str) -> str | None:
        for pattern in _VALUE_PATTERNS:
            match = re.search(pattern, text)
            if match:
                value = match.group(1).strip().rstrip(",.")
                if len(value) > 5:
                    return value
        return None

    def _is_infrastructure_task(self, text: str) -> bool:
        text_lower = text.lower()
        return sum(1 for kw in _INFRASTRUCTURE_KEYWORDS if kw in text_lower) >= 2

    def _count_user_benefit_criteria(self, criteria: list[str]) -> int:
        benefit_keywords = ["user", "customer", "developer", "team", "can", "able to", "experience", "faster", "easier", "reduces", "improves", "enables", "allows", "provides", "delivers"]
        return sum(1 for c in criteria if any(kw in c.lower() for kw in benefit_keywords))

    def _has_non_technical_context(self, text: str) -> bool:
        context_keywords = ["business", "stakeholder", "workflow", "process", "productivity", "efficiency", "satisfaction", "adoption", "onboarding", "experience", "journey", "outcome"]
        return sum(1 for kw in context_keywords if kw in text.lower()) >= 2
