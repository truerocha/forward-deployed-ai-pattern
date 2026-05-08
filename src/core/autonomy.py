"""
Autonomy Module — L2/L3 gating for Human-in-the-Loop (HITL).

Extends the factory autonomy model (ADR-013) with HITL-specific gating
logic. Defines which tools are available at each autonomy level and how
timeout behavior varies across levels.

Activity 4.04 — Autonomy Level HITL Integration

Five levels (Feng et al., 2025):
  L1 Operator:     Human drives everything — HITL always active
  L2 Collaborator: Human checkpoint at every phase — HITL active, abort on timeout
  L3 Consultant:   Human checkpoint after recon — HITL active, infer on timeout
  L4 Approver:     Human approves final PR only — HITL not available
  L5 Observer:     Fully autonomous — HITL not available

Integration points:
  - human_input_tool: uses can_use_hitl() and get_timeout_behavior()
  - orchestrator: uses get_available_tools() to configure agent toolsets
  - anti_instability_loop: queries current level for escalation decisions
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger("fde.autonomy")


# ─── Autonomy Level Enum ────────────────────────────────────────


class AutonomyLevel(Enum):
    """Autonomy levels for FDE agents (Feng et al., 2025)."""

    L1 = "L1"  # Operator — human drives everything
    L2 = "L2"  # Collaborator — human checkpoint at every phase
    L3 = "L3"  # Consultant — human checkpoint after reconnaissance
    L4 = "L4"  # Approver — human approves final PR only
    L5 = "L5"  # Observer — fully autonomous

    @property
    def name_label(self) -> str:
        """Human-readable label for this level."""
        return _LEVEL_METADATA[self]["name"]

    @property
    def description(self) -> str:
        """Description of this autonomy level."""
        return _LEVEL_METADATA[self]["description"]


_LEVEL_METADATA: dict[AutonomyLevel, dict[str, str]] = {
    AutonomyLevel.L1: {
        "name": "Operator",
        "description": "Human drives everything; agent assists only when asked",
    },
    AutonomyLevel.L2: {
        "name": "Collaborator",
        "description": "Human checkpoint at every phase; abort on HITL timeout",
    },
    AutonomyLevel.L3: {
        "name": "Consultant",
        "description": "Human checkpoint after reconnaissance; infer on HITL timeout",
    },
    AutonomyLevel.L4: {
        "name": "Approver",
        "description": "Human approves final PR only; no HITL interruptions",
    },
    AutonomyLevel.L5: {
        "name": "Observer",
        "description": "Fully autonomous; human monitors metrics only",
    },
}


# ─── HITL Gating ────────────────────────────────────────────────

# Levels where HITL tool is available
_HITL_ENABLED_LEVELS = {AutonomyLevel.L1, AutonomyLevel.L2, AutonomyLevel.L3}

# Timeout behavior per level
_TIMEOUT_BEHAVIOR: dict[AutonomyLevel, str] = {
    AutonomyLevel.L1: "abort",
    AutonomyLevel.L2: "abort",
    AutonomyLevel.L3: "infer",
    AutonomyLevel.L4: "skip",
    AutonomyLevel.L5: "skip",
}


def can_use_hitl(level: str | AutonomyLevel) -> bool:
    """Check if the human-in-the-loop tool is available at this level.

    Args:
        level: Autonomy level as string ("L1"-"L5") or AutonomyLevel enum.

    Returns:
        True for L1/L2/L3, False for L4/L5.
    """
    parsed = _parse_level(level)
    return parsed in _HITL_ENABLED_LEVELS


def get_timeout_behavior(level: str | AutonomyLevel) -> str:
    """Get the timeout behavior for a given autonomy level.

    Args:
        level: Autonomy level as string ("L1"-"L5") or AutonomyLevel enum.

    Returns:
        "abort" — agent must stop and wait for human (L1/L2)
        "infer" — agent proceeds with best inference, flags for review (L3)
        "skip"  — HITL not used, no timeout applies (L4/L5)
    """
    parsed = _parse_level(level)
    return _TIMEOUT_BEHAVIOR.get(parsed, "skip")


# ─── Tool Availability per Level ────────────────────────────────

# Base tools available at all levels
_BASE_TOOLS = [
    "read_spec",
    "write_artifact",
    "run_shell_command",
    "read_factory_metrics",
    "read_factory_health",
]

# Tools that require human interaction
_HITL_TOOLS = [
    "human_input",
]

# Tools for code delivery (PR/MR creation)
_DELIVERY_TOOLS = [
    "create_github_pull_request",
    "create_gitlab_merge_request",
    "update_github_issue",
    "update_gitlab_issue",
    "update_asana_task",
]

# Tools available per level (cumulative)
_LEVEL_TOOLS: dict[AutonomyLevel, list[str]] = {
    AutonomyLevel.L1: _BASE_TOOLS + _HITL_TOOLS,
    AutonomyLevel.L2: _BASE_TOOLS + _HITL_TOOLS + _DELIVERY_TOOLS,
    AutonomyLevel.L3: _BASE_TOOLS + _HITL_TOOLS + _DELIVERY_TOOLS,
    AutonomyLevel.L4: _BASE_TOOLS + _DELIVERY_TOOLS,
    AutonomyLevel.L5: _BASE_TOOLS + _DELIVERY_TOOLS,
}


def get_available_tools(level: str | AutonomyLevel) -> list[str]:
    """Get the list of tool names available at a given autonomy level.

    Args:
        level: Autonomy level as string ("L1"-"L5") or AutonomyLevel enum.

    Returns:
        List of tool name strings available at this level.
    """
    parsed = _parse_level(level)
    return list(_LEVEL_TOOLS.get(parsed, _BASE_TOOLS))


# ─── Level Resolution ───────────────────────────────────────────


@dataclass
class AutonomyState:
    """Current autonomy state for a project/task.

    Tracks the active level and provides methods for HITL integration
    and anti-instability loop queries.
    """

    level: AutonomyLevel
    project_id: str = ""
    task_id: str = ""
    escalation_count: int = 0
    _max_escalations: int = field(default=3, init=False)

    @property
    def can_hitl(self) -> bool:
        """Whether HITL is available at current level."""
        return can_use_hitl(self.level)

    @property
    def timeout_behavior(self) -> str:
        """Timeout behavior at current level."""
        return get_timeout_behavior(self.level)

    @property
    def available_tools(self) -> list[str]:
        """Tools available at current level."""
        return get_available_tools(self.level)

    def escalate(self) -> AutonomyLevel:
        """Escalate to a more supervised level (lower number = more human).

        Used by anti_instability_loop when agent is stuck or failing.
        Returns the new level after escalation.
        """
        self.escalation_count += 1

        if self.escalation_count > self._max_escalations:
            logger.warning(
                "Max escalations reached for %s — holding at L1", self.task_id
            )
            self.level = AutonomyLevel.L1
            return self.level

        level_order = [
            AutonomyLevel.L5,
            AutonomyLevel.L4,
            AutonomyLevel.L3,
            AutonomyLevel.L2,
            AutonomyLevel.L1,
        ]
        current_idx = level_order.index(self.level)
        new_idx = min(current_idx + 1, len(level_order) - 1)
        self.level = level_order[new_idx]

        logger.info(
            "Autonomy escalated to %s for task %s (escalation #%d)",
            self.level.value, self.task_id, self.escalation_count,
        )
        return self.level

    def de_escalate(self) -> AutonomyLevel:
        """De-escalate to a more autonomous level (higher number = less human).

        Used when agent demonstrates consistent success.
        Returns the new level after de-escalation.
        """
        level_order = [
            AutonomyLevel.L1,
            AutonomyLevel.L2,
            AutonomyLevel.L3,
            AutonomyLevel.L4,
            AutonomyLevel.L5,
        ]
        current_idx = level_order.index(self.level)
        new_idx = min(current_idx + 1, len(level_order) - 1)
        self.level = level_order[new_idx]

        logger.info(
            "Autonomy de-escalated to %s for task %s",
            self.level.value, self.task_id,
        )
        return self.level

    def to_dict(self) -> dict[str, Any]:
        """Serialize state for persistence or event emission."""
        return {
            "level": self.level.value,
            "level_name": self.level.name_label,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "can_hitl": self.can_hitl,
            "timeout_behavior": self.timeout_behavior,
            "escalation_count": self.escalation_count,
            "available_tools": self.available_tools,
        }


# ─── Helpers ────────────────────────────────────────────────────


def _parse_level(level: str | AutonomyLevel) -> AutonomyLevel:
    """Parse a level string or enum into AutonomyLevel."""
    if isinstance(level, AutonomyLevel):
        return level
    try:
        return AutonomyLevel(level)
    except ValueError:
        logger.warning("Unknown autonomy level '%s' — defaulting to L4", level)
        return AutonomyLevel.L4
