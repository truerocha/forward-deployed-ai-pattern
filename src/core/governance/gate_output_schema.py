"""
Gate Output Schema — Unified Gate Response Format.

Defines the canonical output schema that ALL gates in the factory must produce:
  {gate_name, status, feedback, next_action}

This ensures consistent gate output regardless of which gate is executing,
enabling:
  - GateFeedbackFormatter to parse any gate output
  - Portal GateHistoryCard to render any gate result
  - Gate optimizer to track pass/fail rates uniformly
  - Automated retry logic to understand gate decisions

Schema versioning supports forward compatibility as gates evolve.

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

# Current schema version — increment on breaking changes
SCHEMA_VERSION = "1.0.0"

# Supported schema versions for backward compatibility
SUPPORTED_VERSIONS = {"1.0.0"}


class GateStatus(Enum):
    """Possible gate evaluation statuses."""

    PASSED = "passed"
    REJECTED = "rejected"
    WARNING = "warning"
    ERROR = "error"
    SKIPPED = "skipped"


class NextAction(Enum):
    """Recommended next action after gate evaluation."""

    PROCEED = "proceed"
    REVISE = "revise"
    ESCALATE = "escalate"
    RETRY = "retry"
    ABORT = "abort"
    HUMAN_REVIEW = "human_review"


@dataclass
class GateFeedbackDetail:
    """Detailed feedback from a gate evaluation."""

    reason: str
    violated_rule: str = ""
    suggestion: str = ""
    severity: str = "medium"  # critical | high | medium | low
    reference: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "reason": self.reason,
            "violated_rule": self.violated_rule,
            "suggestion": self.suggestion,
            "severity": self.severity,
            "reference": self.reference,
            "context": self.context,
        }


@dataclass
class GateOutput:
    """
    Unified gate output schema.

    Every gate in the factory MUST produce output conforming to this schema.
    This is the contract between gates and all downstream consumers
    (feedback formatter, portal, optimizer, retry logic).
    """

    gate_name: str
    status: GateStatus
    feedback: GateFeedbackDetail
    next_action: NextAction
    schema_version: str = SCHEMA_VERSION
    task_id: str = ""
    autonomy_level: int = 0
    duration_seconds: float = 0.0
    timestamp: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the canonical gate output dictionary."""
        return {
            "schema_version": self.schema_version,
            "gate_name": self.gate_name,
            "status": self.status.value,
            "feedback": self.feedback.to_dict(),
            "next_action": self.next_action.value,
            "task_id": self.task_id,
            "autonomy_level": self.autonomy_level,
            "duration_seconds": self.duration_seconds,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GateOutput:
        """Deserialize from a dictionary."""
        feedback_data = data.get("feedback", {})
        feedback = GateFeedbackDetail(
            reason=feedback_data.get("reason", ""),
            violated_rule=feedback_data.get("violated_rule", ""),
            suggestion=feedback_data.get("suggestion", ""),
            severity=feedback_data.get("severity", "medium"),
            reference=feedback_data.get("reference", ""),
            context=feedback_data.get("context", {}),
        )

        return cls(
            gate_name=data.get("gate_name", ""),
            status=GateStatus(data.get("status", "error")),
            feedback=feedback,
            next_action=NextAction(data.get("next_action", "abort")),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            task_id=data.get("task_id", ""),
            autonomy_level=data.get("autonomy_level", 0),
            duration_seconds=data.get("duration_seconds", 0.0),
            timestamp=data.get("timestamp", ""),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_json(cls, json_str: str) -> GateOutput:
        """Deserialize from a JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)


def validate_gate_output(output: dict[str, Any]) -> bool:
    """
    Validate that a gate output dictionary conforms to the schema.

    Checks:
      - Required fields are present
      - Status is a valid GateStatus value
      - Next action is a valid NextAction value
      - Schema version is supported
      - Feedback contains required 'reason' field

    Args:
        output: Dictionary to validate against the gate output schema.

    Returns:
        True if the output is valid, False otherwise.
    """
    errors = get_validation_errors(output)
    if errors:
        logger.debug("Gate output validation failed: %s", errors)
        return False
    return True


def get_validation_errors(output: dict[str, Any]) -> list[str]:
    """
    Get detailed validation errors for a gate output dictionary.

    Args:
        output: Dictionary to validate.

    Returns:
        List of error messages. Empty list means valid.
    """
    errors: list[str] = []

    if not isinstance(output, dict):
        return ["Output must be a dictionary"]

    # Required top-level fields
    required_fields = ["gate_name", "status", "feedback", "next_action"]
    for field_name in required_fields:
        if field_name not in output:
            errors.append(f"Missing required field: '{field_name}'")

    # Validate schema version if present
    version = output.get("schema_version", SCHEMA_VERSION)
    if version not in SUPPORTED_VERSIONS:
        errors.append(
            f"Unsupported schema version: '{version}'. "
            f"Supported: {sorted(SUPPORTED_VERSIONS)}"
        )

    # Validate status
    status = output.get("status")
    if status is not None:
        valid_statuses = {s.value for s in GateStatus}
        if status not in valid_statuses:
            errors.append(
                f"Invalid status: '{status}'. Valid: {sorted(valid_statuses)}"
            )

    # Validate next_action
    next_action = output.get("next_action")
    if next_action is not None:
        valid_actions = {a.value for a in NextAction}
        if next_action not in valid_actions:
            errors.append(
                f"Invalid next_action: '{next_action}'. Valid: {sorted(valid_actions)}"
            )

    # Validate feedback structure
    feedback = output.get("feedback")
    if feedback is not None:
        if not isinstance(feedback, dict):
            errors.append("'feedback' must be a dictionary")
        elif "reason" not in feedback:
            errors.append("'feedback' must contain a 'reason' field")

    # Validate gate_name is non-empty string
    gate_name = output.get("gate_name")
    if gate_name is not None and (not isinstance(gate_name, str) or not gate_name.strip()):
        errors.append("'gate_name' must be a non-empty string")

    return errors


def create_pass_output(
    gate_name: str,
    task_id: str = "",
    autonomy_level: int = 0,
    duration_seconds: float = 0.0,
    metadata: dict[str, Any] | None = None,
) -> GateOutput:
    """
    Create a standard gate PASS output.

    Convenience factory for the common case of a gate passing.

    Args:
        gate_name: Name of the gate that passed.
        task_id: Associated task ID.
        autonomy_level: Task autonomy level.
        duration_seconds: How long the gate evaluation took.
        metadata: Optional additional context.

    Returns:
        GateOutput with PASSED status and PROCEED next action.
    """
    return GateOutput(
        gate_name=gate_name,
        status=GateStatus.PASSED,
        feedback=GateFeedbackDetail(reason="All checks passed"),
        next_action=NextAction.PROCEED,
        task_id=task_id,
        autonomy_level=autonomy_level,
        duration_seconds=duration_seconds,
        metadata=metadata or {},
    )


def create_rejection_output(
    gate_name: str,
    reason: str,
    suggestion: str,
    violated_rule: str = "",
    severity: str = "high",
    task_id: str = "",
    autonomy_level: int = 0,
    duration_seconds: float = 0.0,
    next_action: NextAction = NextAction.REVISE,
    metadata: dict[str, Any] | None = None,
) -> GateOutput:
    """
    Create a standard gate REJECTION output.

    Convenience factory for the common case of a gate rejecting.

    Args:
        gate_name: Name of the gate that rejected.
        reason: Why the gate rejected.
        suggestion: What to do to fix it.
        violated_rule: Which rule was violated.
        severity: Severity level (critical/high/medium/low).
        task_id: Associated task ID.
        autonomy_level: Task autonomy level.
        duration_seconds: How long the gate evaluation took.
        next_action: Recommended next action (default: REVISE).
        metadata: Optional additional context.

    Returns:
        GateOutput with REJECTED status.
    """
    return GateOutput(
        gate_name=gate_name,
        status=GateStatus.REJECTED,
        feedback=GateFeedbackDetail(
            reason=reason,
            violated_rule=violated_rule,
            suggestion=suggestion,
            severity=severity,
        ),
        next_action=next_action,
        task_id=task_id,
        autonomy_level=autonomy_level,
        duration_seconds=duration_seconds,
        metadata=metadata or {},
    )


def is_compatible_version(version: str) -> bool:
    """
    Check if a schema version is compatible with the current implementation.

    Args:
        version: Schema version string to check.

    Returns:
        True if the version is supported.
    """
    return version in SUPPORTED_VERSIONS
