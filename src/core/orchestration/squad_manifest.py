"""
Squad Manifest — Canonical Schema Definition.

The Squad Manifest is the complete specification for a distributed task execution.
It defines what agents to run, in what order, with what context, and at what
autonomy level.

This is the canonical schema definition. The SquadManifest in
distributed_orchestrator.py is a simplified operational version; this module
provides the full schema with validation, serialization, and the learning_mode
field for fidelity agent reasoning explanations.

Fields:
  - task_id: Unique identifier for the task
  - project_id: Which project this task belongs to
  - organism_level: Complexity classification (O1-O5)
  - user_value_statement: Why this task matters to a user
  - autonomy_level: How much human oversight (L1-L5)
  - stages: Ordered dict of stage_number -> list of agent specs
  - knowledge_context: Relevant context from knowledge base
  - learning_mode: When True, fidelity agent explains reasoning at each step

DynamoDB SK pattern: manifest#{task_id}

Ref: docs/design/fde-core-brain-development.md Section 3.1
     docs/adr/ADR-019-agentic-squad-architecture.md
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class OrganismLevel(Enum):
    """Task complexity classification (organism ladder)."""

    O1 = "O1"  # Single-file change
    O2 = "O2"  # Multi-file, single module
    O3 = "O3"  # Cross-module change
    O4 = "O4"  # Architectural change
    O5 = "O5"  # System-wide transformation


class ModelTier(Enum):
    """LLM model tier for agent execution."""

    FAST = "fast"          # Quick responses, simple tasks
    REASONING = "reasoning"  # Complex logic, multi-step
    DEEP = "deep"          # Architecture, design decisions


@dataclass
class AgentStageSpec:
    """Specification for a single agent within a stage."""

    role: str
    model_tier: ModelTier
    stage: int
    permissions: list[str] = field(default_factory=list)
    timeout_seconds: int = 600
    retry_max: int = 3
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "role": self.role,
            "model_tier": self.model_tier.value,
            "stage": self.stage,
            "permissions": self.permissions,
            "timeout_seconds": self.timeout_seconds,
            "retry_max": self.retry_max,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentStageSpec:
        """Deserialize from dictionary."""
        return cls(
            role=data.get("role", ""),
            model_tier=ModelTier(data.get("model_tier", "fast")),
            stage=data.get("stage", 0),
            permissions=data.get("permissions", []),
            timeout_seconds=data.get("timeout_seconds", 600),
            retry_max=data.get("retry_max", 3),
            description=data.get("description", ""),
        )


@dataclass
class SquadManifest:
    """
    Canonical Squad Manifest schema.

    Defines the full squad composition, execution parameters, and context
    for a distributed task execution.

    Usage:
        manifest = SquadManifest(
            task_id="task-abc-123",
            project_id="my-service",
            organism_level=OrganismLevel.O3,
            user_value_statement="As a user, I need X so that Y",
            autonomy_level=4,
            stages={
                1: [AgentStageSpec(role="planner", model_tier=ModelTier.REASONING, stage=1)],
                2: [AgentStageSpec(role="implementer", model_tier=ModelTier.FAST, stage=2),
                    AgentStageSpec(role="tester", model_tier=ModelTier.FAST, stage=2)],
                3: [AgentStageSpec(role="reviewer", model_tier=ModelTier.REASONING, stage=3)],
            },
            learning_mode=True,
        )
        errors = validate_manifest(manifest)
        json_str = manifest.to_json()
    """

    task_id: str
    project_id: str
    organism_level: OrganismLevel
    user_value_statement: str
    autonomy_level: int  # L1-L5
    stages: dict[int, list[AgentStageSpec]] = field(default_factory=dict)
    knowledge_context: dict[str, Any] = field(default_factory=dict)
    learning_mode: bool = False
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def total_agents(self) -> int:
        """Total number of agents across all stages."""
        return sum(len(agents) for agents in self.stages.values())

    def stage_count(self) -> int:
        """Number of stages in the manifest."""
        return len(self.stages)

    def get_agents_for_stage(self, stage: int) -> list[AgentStageSpec]:
        """Get all agent specs for a given stage number."""
        return self.stages.get(stage, [])

    def get_all_roles(self) -> list[str]:
        """Get a flat list of all agent roles in execution order."""
        roles: list[str] = []
        for stage_num in sorted(self.stages.keys()):
            for agent in self.stages[stage_num]:
                roles.append(agent.role)
        return roles

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "task_id": self.task_id,
            "project_id": self.project_id,
            "organism_level": self.organism_level.value,
            "user_value_statement": self.user_value_statement,
            "autonomy_level": self.autonomy_level,
            "stages": {
                str(stage_num): [agent.to_dict() for agent in agents]
                for stage_num, agents in self.stages.items()
            },
            "knowledge_context": self.knowledge_context,
            "learning_mode": self.learning_mode,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SquadManifest:
        """Deserialize from dictionary."""
        stages: dict[int, list[AgentStageSpec]] = {}
        raw_stages = data.get("stages", {})
        for stage_key, agents_data in raw_stages.items():
            stage_num = int(stage_key)
            stages[stage_num] = [
                AgentStageSpec.from_dict(agent_data) for agent_data in agents_data
            ]

        return cls(
            task_id=data.get("task_id", ""),
            project_id=data.get("project_id", ""),
            organism_level=OrganismLevel(data.get("organism_level", "O1")),
            user_value_statement=data.get("user_value_statement", ""),
            autonomy_level=data.get("autonomy_level", 1),
            stages=stages,
            knowledge_context=data.get("knowledge_context", {}),
            learning_mode=data.get("learning_mode", False),
            created_at=data.get("created_at", ""),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_json(cls, json_str: str) -> SquadManifest:
        """Deserialize from JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)


def validate_manifest(manifest: SquadManifest) -> list[str]:
    """
    Validate a SquadManifest for completeness and consistency.

    Checks:
      - Required fields are non-empty
      - Autonomy level is in valid range (1-5)
      - At least one stage with at least one agent
      - Stage numbers are sequential starting from 1
      - Agent stage numbers match their containing stage
      - User value statement is substantive (>20 chars)
      - Organism level is consistent with stage count

    Args:
        manifest: The SquadManifest to validate.

    Returns:
        List of error messages. Empty list means valid.
    """
    errors: list[str] = []

    # Required fields
    if not manifest.task_id:
        errors.append("task_id is required")
    if not manifest.project_id:
        errors.append("project_id is required")
    if not manifest.user_value_statement:
        errors.append("user_value_statement is required")

    # User value statement quality
    if manifest.user_value_statement and len(manifest.user_value_statement) < 20:
        errors.append(
            "user_value_statement is too short (min 20 chars). "
            "Should describe who benefits and why."
        )

    # Autonomy level range
    if not 1 <= manifest.autonomy_level <= 5:
        errors.append(
            f"autonomy_level must be 1-5, got {manifest.autonomy_level}"
        )

    # Stages validation
    if not manifest.stages:
        errors.append("At least one stage with agents is required")
    else:
        # Check stage numbering
        stage_numbers = sorted(manifest.stages.keys())
        expected = list(range(1, len(stage_numbers) + 1))
        if stage_numbers != expected:
            errors.append(
                f"Stage numbers must be sequential starting from 1. "
                f"Got: {stage_numbers}, expected: {expected}"
            )

        # Check each stage has agents
        for stage_num, agents in manifest.stages.items():
            if not agents:
                errors.append(f"Stage {stage_num} has no agents")

            # Check agent stage numbers match
            for agent in agents:
                if agent.stage != stage_num:
                    errors.append(
                        f"Agent '{agent.role}' has stage={agent.stage} "
                        f"but is in stage {stage_num}"
                    )

                # Check agent role is non-empty
                if not agent.role:
                    errors.append(f"Agent in stage {stage_num} has empty role")

                # Check timeout is positive
                if agent.timeout_seconds <= 0:
                    errors.append(
                        f"Agent '{agent.role}' has invalid timeout: "
                        f"{agent.timeout_seconds}"
                    )

    # Organism level consistency hints
    if manifest.organism_level == OrganismLevel.O1 and manifest.stage_count() > 2:
        errors.append(
            "O1 (single-file) tasks typically need at most 2 stages. "
            "Consider if organism_level should be higher."
        )

    # Learning mode validation
    if manifest.learning_mode and manifest.autonomy_level >= 5:
        # Learning mode at L5 is unusual but not invalid — just log
        logger.info(
            "learning_mode=True at L5 for task %s. "
            "Fidelity agent will explain reasoning despite full autonomy.",
            manifest.task_id,
        )

    return errors


def create_minimal_manifest(
    task_id: str,
    project_id: str,
    user_value_statement: str,
    autonomy_level: int = 1,
    organism_level: OrganismLevel = OrganismLevel.O1,
    learning_mode: bool = False,
) -> SquadManifest:
    """
    Create a minimal valid manifest with default single-stage configuration.

    Useful for simple tasks that need a basic planner + implementer setup.

    Args:
        task_id: Unique task identifier.
        project_id: Project this task belongs to.
        user_value_statement: Why this task matters.
        autonomy_level: L1-L5 autonomy level.
        organism_level: O1-O5 complexity level.
        learning_mode: Whether fidelity agent explains reasoning.

    Returns:
        A valid SquadManifest with default agents.
    """
    return SquadManifest(
        task_id=task_id,
        project_id=project_id,
        organism_level=organism_level,
        user_value_statement=user_value_statement,
        autonomy_level=autonomy_level,
        stages={
            1: [
                AgentStageSpec(
                    role="planner",
                    model_tier=ModelTier.REASONING,
                    stage=1,
                    permissions=["read"],
                    description="Plans the implementation approach",
                ),
            ],
            2: [
                AgentStageSpec(
                    role="implementer",
                    model_tier=ModelTier.FAST,
                    stage=2,
                    permissions=["read", "write"],
                    description="Implements the planned changes",
                ),
                AgentStageSpec(
                    role="tester",
                    model_tier=ModelTier.FAST,
                    stage=2,
                    permissions=["read", "write"],
                    description="Writes and runs tests",
                ),
            ],
            3: [
                AgentStageSpec(
                    role="reviewer",
                    model_tier=ModelTier.REASONING,
                    stage=3,
                    permissions=["read"],
                    description="Reviews implementation for quality",
                ),
            ],
        },
        learning_mode=learning_mode,
    )
