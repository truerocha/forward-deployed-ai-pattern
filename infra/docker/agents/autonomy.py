"""
Autonomy Level — Computes and applies autonomy levels per task (ADR-013, Decision 1).

Five levels of autonomy based on "Levels of Autonomy for AI Agents" (Feng et al., 2025):
  L1 Operator:     Human drives everything (below factory threshold)
  L2 Collaborator: Human checkpoint at every phase
  L3 Consultant:   Human checkpoint after reconnaissance
  L4 Approver:     Human approves final PR only
  L5 Observer:     Fully autonomous, human monitors metrics

The autonomy level is computed from the data contract (type + level) with
optional human override. The Orchestrator uses it to adapt pipeline gates.

Two stable collaboration patterns from WhatsCode (Mao et al., 2025):
  - One-click rollout (60%): maps to L4-L5
  - Commandeer-revise (40%): maps to L2-L3
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("fde.autonomy")


@dataclass
class AutonomyResult:
    """Result of computing the autonomy level for a task."""

    level: str                           # "L1" through "L5"
    name: str                            # Human-readable name
    human_checkpoints: list[str] = field(default_factory=list)
    fast_path: bool = False

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "name": self.name,
            "human_checkpoints": self.human_checkpoints,
            "fast_path": self.fast_path,
        }


@dataclass
class PipelineGates:
    """Resolved pipeline gates based on autonomy level."""

    outer_gates: list[str] = field(default_factory=list)
    inner_gates: list[str] = field(default_factory=list)
    human_checkpoints: list[str] = field(default_factory=list)


# ─── Level Definitions ──────────────────────────────────────────

_LEVEL_DEFINITIONS: dict[str, dict] = {
    "L1": {
        "name": "Operator",
        "human_checkpoints": ["every_step"],
        "fast_path": False,
    },
    "L2": {
        "name": "Collaborator",
        "human_checkpoints": ["after_reconnaissance", "after_engineering", "pr_review"],
        "fast_path": False,
    },
    "L3": {
        "name": "Consultant",
        "human_checkpoints": ["after_reconnaissance", "pr_review"],
        "fast_path": False,
    },
    "L4": {
        "name": "Approver",
        "human_checkpoints": ["pr_review"],
        "fast_path": False,
    },
    "L5": {
        "name": "Observer",
        "human_checkpoints": [],
        "fast_path": True,
    },
}

# ─── Default Mapping: (type, level) → autonomy_level ────────────

_DEFAULT_AUTONOMY: dict[tuple[str, str], str] = {
    ("bugfix", "L2"): "L5",
    ("bugfix", "L3"): "L5",
    ("bugfix", "L4"): "L4",
    ("feature", "L2"): "L5",
    ("feature", "L3"): "L4",
    ("feature", "L4"): "L3",
    ("infrastructure", "L2"): "L5",
    ("infrastructure", "L3"): "L4",
    ("infrastructure", "L4"): "L3",
    ("documentation", "L2"): "L5",
    ("documentation", "L3"): "L5",
    ("documentation", "L4"): "L5",
}


def compute_autonomy_level(data_contract: dict) -> AutonomyResult:
    """Compute the autonomy level for a task from its data contract."""
    explicit = data_contract.get("autonomy_level", "")
    if explicit and explicit in _LEVEL_DEFINITIONS:
        level = explicit
    else:
        task_type = data_contract.get("type", "feature")
        eng_level = data_contract.get("level", "L3")
        level = _DEFAULT_AUTONOMY.get((task_type, eng_level), "L4")

    defn = _LEVEL_DEFINITIONS[level]
    return AutonomyResult(
        level=level,
        name=defn["name"],
        human_checkpoints=list(defn["human_checkpoints"]),
        fast_path=defn["fast_path"],
    )


_ALL_OUTER_GATES = ["dor_gate", "constraint_extraction", "adversarial_challenge", "ship_readiness"]
_ALL_INNER_GATES = ["lint", "typecheck", "unit_test", "build"]
_SKIP_OUTER_GATES: dict[str, list[str]] = {
    "L5": ["adversarial_challenge"],
    "L4": [],
    "L3": [],
    "L2": [],
    "L1": [],
}


def resolve_pipeline_gates(autonomy_level: str) -> PipelineGates:
    """Resolve which pipeline gates to run based on autonomy level."""
    if autonomy_level not in _LEVEL_DEFINITIONS:
        autonomy_level = "L4"

    skip_outer = _SKIP_OUTER_GATES.get(autonomy_level, [])
    outer_gates = [g for g in _ALL_OUTER_GATES if g not in skip_outer]
    inner_gates = list(_ALL_INNER_GATES)
    defn = _LEVEL_DEFINITIONS[autonomy_level]
    human_checkpoints = list(defn["human_checkpoints"])

    return PipelineGates(
        outer_gates=outer_gates,
        inner_gates=inner_gates,
        human_checkpoints=human_checkpoints,
    )
