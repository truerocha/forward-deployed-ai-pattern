"""
Organism Ladder — Task Complexity Classification.

Classifies tasks into organism levels that determine squad composition:
  O1 (Reactive): Single agent, no memory, deterministic gates only
  O2 (Adaptive): Single agent + memory recall, basic context
  O3 (Cognitive): Multi-agent squad, shared context, adversarial review
  O4 (Reflective): Full squad + fidelity scoring + perturbation testing
  O5 (Autonomous): Self-optimizing squad + gate optimization + auto-scaling

DynamoDB table: fde-dev-organism
  PK: project_id (S)
  SK: organism_key (S)

Ref: docs/design/fde-brain-simulation-design.md
     docs/design/fde-core-brain-development.md Wave 2
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class OrganismLevel(IntEnum):
    O1_REACTIVE = 1
    O2_ADAPTIVE = 2
    O3_COGNITIVE = 3
    O4_REFLECTIVE = 4
    O5_AUTONOMOUS = 5


_SQUAD_COMPOSITION: dict[OrganismLevel, dict[str, Any]] = {
    OrganismLevel.O1_REACTIVE: {"agents": 1, "stages": 3, "model_tier": "fast", "features": ["deterministic_gates"]},
    OrganismLevel.O2_ADAPTIVE: {"agents": 1, "stages": 4, "model_tier": "reasoning", "features": ["deterministic_gates", "memory_recall"]},
    OrganismLevel.O3_COGNITIVE: {"agents": 3, "stages": 5, "model_tier": "reasoning", "features": ["deterministic_gates", "memory_recall", "adversarial_review", "shared_context"]},
    OrganismLevel.O4_REFLECTIVE: {"agents": 5, "stages": 6, "model_tier": "reasoning", "features": ["deterministic_gates", "memory_recall", "adversarial_review", "shared_context", "fidelity_scoring", "perturbation_testing"]},
    OrganismLevel.O5_AUTONOMOUS: {"agents": 6, "stages": 6, "model_tier": "deep", "features": ["deterministic_gates", "memory_recall", "adversarial_review", "shared_context", "fidelity_scoring", "perturbation_testing", "gate_optimization", "auto_scaling"]},
}


@dataclass
class TaskComplexitySignals:
    """Signals used to classify task complexity."""
    files_affected: int = 1
    cross_module_edges: int = 0
    knowledge_artifacts_involved: bool = False
    architecture_impact: bool = False
    security_sensitive: bool = False
    infrastructure_change: bool = False
    estimated_loc: int = 0
    has_user_facing_impact: bool = False


@dataclass
class ClassificationResult:
    """Result of organism classification for a task."""
    task_id: str
    project_id: str
    organism_level: OrganismLevel
    signals: TaskComplexitySignals
    squad_composition: dict[str, Any]
    reasoning: str
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class OrganismLadder:
    """
    Classifies tasks and manages organism level state per project.

    Usage:
        ladder = OrganismLadder(project_id="my-repo")
        signals = TaskComplexitySignals(files_affected=5, cross_module_edges=2)
        result = ladder.classify("task-123", signals)
    """

    def __init__(self, project_id: str = "", table_name: str | None = None):
        self._project_id = project_id or os.environ.get("PROJECT_ID", "global")
        self._table_name = table_name or os.environ.get("ORGANISM_TABLE", "")
        self._dynamodb = boto3.resource("dynamodb")

    def classify(self, task_id: str, signals: TaskComplexitySignals) -> ClassificationResult:
        """Classify a task into an organism level based on complexity signals."""
        score = self._compute_complexity_score(signals)
        level = self._score_to_level(score)
        composition = _SQUAD_COMPOSITION[level]

        reasoning_parts = []
        if signals.files_affected > 5:
            reasoning_parts.append(f"{signals.files_affected} files")
        if signals.cross_module_edges > 0:
            reasoning_parts.append(f"{signals.cross_module_edges} edges")
        if signals.knowledge_artifacts_involved:
            reasoning_parts.append("knowledge artifacts")
        if signals.architecture_impact:
            reasoning_parts.append("architecture impact")
        if signals.security_sensitive:
            reasoning_parts.append("security sensitive")

        reasoning = f"Score {score} -> {level.name}: " + (", ".join(reasoning_parts) if reasoning_parts else "standard task")

        result = ClassificationResult(
            task_id=task_id, project_id=self._project_id,
            organism_level=level, signals=signals,
            squad_composition=composition, reasoning=reasoning,
        )
        self._persist_classification(result)
        logger.info("Organism classification: task=%s level=%s score=%d", task_id, level.name, score)
        return result

    def get_squad_composition(self, level: OrganismLevel) -> dict[str, Any]:
        """Get the squad composition for a given organism level."""
        return _SQUAD_COMPOSITION.get(level, _SQUAD_COMPOSITION[OrganismLevel.O1_REACTIVE])

    def get_project_default_level(self) -> OrganismLevel:
        """Get the default organism level for this project."""
        if not self._table_name:
            return OrganismLevel.O3_COGNITIVE
        table = self._dynamodb.Table(self._table_name)
        try:
            response = table.get_item(Key={"project_id": self._project_id, "organism_key": "current_level"})
            if "Item" in response:
                data = json.loads(response["Item"].get("data", "{}"))
                return OrganismLevel(data.get("level", 3))
            return OrganismLevel.O3_COGNITIVE
        except (ClientError, ValueError):
            return OrganismLevel.O3_COGNITIVE

    def set_project_default_level(self, level: OrganismLevel, reason: str = "") -> None:
        """Set the default organism level for this project."""
        if not self._table_name:
            return
        table = self._dynamodb.Table(self._table_name)
        now = datetime.now(timezone.utc).isoformat()
        try:
            table.put_item(Item={"project_id": self._project_id, "organism_key": "current_level", "data": json.dumps({"level": int(level), "reason": reason, "updated_at": now})})
            table.put_item(Item={"project_id": self._project_id, "organism_key": f"history#{now}", "data": json.dumps({"level": int(level), "reason": reason})})
        except ClientError as e:
            logger.error("Failed to set organism level: %s", str(e))

    def _compute_complexity_score(self, signals: TaskComplexitySignals) -> int:
        score = 0
        if signals.files_affected <= 1:
            score += 0
        elif signals.files_affected <= 3:
            score += 1
        elif signals.files_affected <= 7:
            score += 2
        elif signals.files_affected <= 15:
            score += 3
        else:
            score += 4
        score += min(signals.cross_module_edges, 4)
        if signals.knowledge_artifacts_involved:
            score += 2
        if signals.architecture_impact:
            score += 3
        if signals.security_sensitive:
            score += 2
        if signals.infrastructure_change:
            score += 2
        if signals.estimated_loc > 500:
            score += 2
        elif signals.estimated_loc > 200:
            score += 1
        if signals.has_user_facing_impact:
            score += 1
        return score

    def _score_to_level(self, score: int) -> OrganismLevel:
        if score <= 2:
            return OrganismLevel.O1_REACTIVE
        elif score <= 5:
            return OrganismLevel.O2_ADAPTIVE
        elif score <= 9:
            return OrganismLevel.O3_COGNITIVE
        elif score <= 13:
            return OrganismLevel.O4_REFLECTIVE
        else:
            return OrganismLevel.O5_AUTONOMOUS

    def _persist_classification(self, result: ClassificationResult) -> None:
        if not self._table_name:
            return
        table = self._dynamodb.Table(self._table_name)
        try:
            table.put_item(Item={
                "project_id": self._project_id, "organism_key": f"classification#{result.task_id}",
                "data": json.dumps({"task_id": result.task_id, "organism_level": int(result.organism_level), "organism_name": result.organism_level.name, "score": self._compute_complexity_score(result.signals), "reasoning": result.reasoning, "timestamp": result.timestamp}),
            })
        except ClientError as e:
            logger.warning("Failed to persist organism classification: %s", str(e))
