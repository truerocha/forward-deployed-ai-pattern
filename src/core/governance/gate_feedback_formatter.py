"""
Gate Feedback Formatter — Clear, Actionable Gate Rejection Messages.

DORA O19 (P0): The #1 correlated platform capability is "clear feedback on tasks."
Gates must not just reject — they must explain WHY and WHAT to fix.
"Adversarial gate rejected" is insufficient.

This module transforms raw gate rejection output into structured feedback:
  - reason: What specifically failed
  - violated_rule: Which governance rule was violated
  - suggestion: Actionable next step to resolve
  - reference_artifact: Link to relevant documentation
  - severity: critical | high | medium | low

Every gate in the factory uses this formatter to produce consistent,
human-readable, actionable feedback.

Ref: docs/design/fde-core-brain-development.md Section 8.1
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class FeedbackSeverity(Enum):
    """Severity of a gate rejection."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class GateType(Enum):
    """Types of gates in the factory."""

    DOR = "dor"
    ADVERSARIAL = "adversarial"
    DOD = "dod"
    PIPELINE = "pipeline"
    TEST_IMMUTABILITY = "test_immutability"
    CIRCUIT_BREAKER = "circuit_breaker"


@dataclass
class GateFeedback:
    """Structured feedback from a gate rejection."""

    gate_name: str
    gate_type: GateType
    status: str  # "passed" | "rejected" | "warning"
    reason: str
    violated_rule: str
    suggestion: str
    reference_artifact: str
    severity: FeedbackSeverity
    task_id: str = ""
    timestamp: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON output."""
        return {
            "gate_name": self.gate_name,
            "gate_type": self.gate_type.value,
            "status": self.status,
            "reason": self.reason,
            "violated_rule": self.violated_rule,
            "suggestion": self.suggestion,
            "reference_artifact": self.reference_artifact,
            "severity": self.severity.value,
            "task_id": self.task_id,
            "timestamp": self.timestamp,
            "context": self.context,
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    def to_human_readable(self) -> str:
        """Format as human-readable message for portal/chat display."""
        icon = {
            FeedbackSeverity.CRITICAL: "🚨",
            FeedbackSeverity.HIGH: "❌",
            FeedbackSeverity.MEDIUM: "⚠️",
            FeedbackSeverity.LOW: "ℹ️",
        }.get(self.severity, "❓")

        lines = [
            f"{icon} **{self.gate_name}** — {self.status.upper()}",
            f"",
            f"**What failed:** {self.reason}",
            f"**Rule violated:** {self.violated_rule}",
            f"**What to do:** {self.suggestion}",
            f"**Reference:** {self.reference_artifact}",
        ]
        return "\n".join(lines)


_GATE_REFERENCES: dict[GateType, str] = {
    GateType.DOR: "docs/design/forward-deployed-ai-engineers.md#phase-2",
    GateType.ADVERSARIAL: "docs/design/forward-deployed-ai-engineers.md#phase-3a",
    GateType.DOD: "docs/design/forward-deployed-ai-engineers.md#dod-gate",
    GateType.PIPELINE: "docs/design/forward-deployed-ai-engineers.md#phase-3b",
    GateType.TEST_IMMUTABILITY: "docs/testing/fixture-governance.md",
    GateType.CIRCUIT_BREAKER: "docs/adr/ADR-004-circuit-breaker-error-classification.md",
}


class GateFeedbackFormatter:
    """
    Formats gate outputs into structured, actionable feedback.

    Usage:
        formatter = GateFeedbackFormatter()
        feedback = formatter.format_rejection(
            gate_name="fde-adversarial-gate",
            gate_type=GateType.ADVERSARIAL,
            reason="Function lacks error handling for network failures",
            violated_rule="All external calls must have try/except with specific exception types",
            suggestion="Add try/except around the boto3 call with ClientError handling",
            severity=FeedbackSeverity.HIGH,
            task_id="task-123",
        )
    """

    def format_rejection(
        self,
        gate_name: str,
        gate_type: GateType,
        reason: str,
        violated_rule: str,
        suggestion: str,
        severity: FeedbackSeverity,
        task_id: str = "",
        reference_artifact: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> GateFeedback:
        """Format a gate rejection into structured feedback."""
        ref = reference_artifact or _GATE_REFERENCES.get(gate_type, "docs/")
        feedback = GateFeedback(
            gate_name=gate_name,
            gate_type=gate_type,
            status="rejected",
            reason=reason,
            violated_rule=violated_rule,
            suggestion=suggestion,
            reference_artifact=ref,
            severity=severity,
            task_id=task_id,
            context=context or {},
        )
        logger.info("Gate rejection: gate=%s severity=%s reason=%s", gate_name, severity.value, reason[:100])
        return feedback

    def format_pass(
        self, gate_name: str, gate_type: GateType, task_id: str = "", context: dict[str, Any] | None = None,
    ) -> GateFeedback:
        """Format a gate pass (for consistent output schema)."""
        return GateFeedback(
            gate_name=gate_name, gate_type=gate_type, status="passed",
            reason="All checks passed", violated_rule="", suggestion="",
            reference_artifact="", severity=FeedbackSeverity.LOW,
            task_id=task_id, context=context or {},
        )

    def format_warning(
        self, gate_name: str, gate_type: GateType, reason: str, suggestion: str,
        task_id: str = "", context: dict[str, Any] | None = None,
    ) -> GateFeedback:
        """Format a gate warning (non-blocking but noteworthy)."""
        ref = _GATE_REFERENCES.get(gate_type, "docs/")
        return GateFeedback(
            gate_name=gate_name, gate_type=gate_type, status="warning",
            reason=reason, violated_rule="", suggestion=suggestion,
            reference_artifact=ref, severity=FeedbackSeverity.MEDIUM,
            task_id=task_id, context=context or {},
        )

    def format_from_raw_output(
        self, gate_name: str, gate_type: GateType, raw_output: str, task_id: str = "",
    ) -> GateFeedback:
        """
        Parse raw gate output (from hook execution) into structured feedback.

        Attempts JSON parsing first, falls back to wrapping raw text.
        """
        try:
            data = json.loads(raw_output)
            if isinstance(data, dict):
                status = data.get("status", "rejected")
                return GateFeedback(
                    gate_name=gate_name, gate_type=gate_type, status=status,
                    reason=data.get("reason", raw_output[:200]),
                    violated_rule=data.get("violated_rule", ""),
                    suggestion=data.get("suggestion", ""),
                    reference_artifact=data.get("reference_artifact", _GATE_REFERENCES.get(gate_type, "")),
                    severity=FeedbackSeverity(data.get("severity", "high")),
                    task_id=task_id, context=data.get("context", {}),
                )
        except (json.JSONDecodeError, ValueError):
            pass

        is_pass = any(kw in raw_output.lower() for kw in ["passed", "approved", "accepted", "lgtm"])
        if is_pass:
            return self.format_pass(gate_name, gate_type, task_id)

        return GateFeedback(
            gate_name=gate_name, gate_type=gate_type, status="rejected",
            reason=raw_output[:500],
            violated_rule="Unable to parse specific rule from gate output",
            suggestion="Review the gate output above and address the identified issues",
            reference_artifact=_GATE_REFERENCES.get(gate_type, "docs/"),
            severity=FeedbackSeverity.HIGH, task_id=task_id,
        )
