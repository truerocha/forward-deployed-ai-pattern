"""
Emulation Classifier — Distinguishing Simulation from Emulation.

Classifies each task execution as one of:
  - EMULATION: The agent replicated the causal reasoning process
  - SIMULATION: The agent produced correct output but via different reasoning
  - DEGRADED: The agent produced output that doesn't meet quality standards

Ref: docs/design/fde-brain-simulation-design.md
     docs/design/fde-core-brain-development.md Wave 2
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import boto3
from botocore.exceptions import ClientError

from src.core.brain_sim.fidelity_score import FidelityResult

logger = logging.getLogger(__name__)


class ExecutionClass(Enum):
    """Classification of a task execution's quality level."""

    EMULATION = "emulation"
    SIMULATION = "simulation"
    DEGRADED = "degraded"


_EMULATION_COMPOSITE_MIN = 0.85
_EMULATION_MIN_DIMENSIONS_HIGH = 4
_SIMULATION_COMPOSITE_MIN = 0.55
_DIMENSION_HIGH_THRESHOLD = 0.7

_EMULATION_REQUIRED_DIMENSIONS = {
    "governance_compliance": 0.8,
    "context_utilization": 0.6,
    "reasoning_quality": 0.6,
}


@dataclass
class ClassificationResult:
    """Result of classifying a task execution."""

    task_id: str
    project_id: str
    classification: ExecutionClass
    fidelity_score: float
    reasoning: str
    dimension_flags: dict[str, str]
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class EmulationRatio:
    """Emulation ratio over a window of tasks."""

    project_id: str
    window_size: int
    emulation_count: int
    simulation_count: int
    degraded_count: int
    emulation_ratio_percent: float
    trend: str  # "improving" | "stable" | "declining" | "insufficient_data"


class EmulationClassifier:
    """
    Classifies task executions and tracks emulation ratio.

    Usage:
        classifier = EmulationClassifier(project_id="my-repo")
        result = classifier.classify(fidelity_result)
        ratio = classifier.get_emulation_ratio(window_tasks=50)
    """

    def __init__(self, project_id: str = "", metrics_table: str | None = None):
        self._project_id = project_id or os.environ.get("PROJECT_ID", "global")
        self._metrics_table = metrics_table or os.environ.get("METRICS_TABLE", "")
        self._dynamodb = boto3.resource("dynamodb")

    def classify(self, fidelity_result: FidelityResult) -> ClassificationResult:
        """Classify a task execution based on its fidelity result."""
        composite = fidelity_result.composite_score
        dimensions = fidelity_result.dimensions
        dimension_flags: dict[str, str] = {}

        emulation_eligible = True
        reasoning_parts: list[str] = []

        if composite < _EMULATION_COMPOSITE_MIN:
            emulation_eligible = False
            reasoning_parts.append(f"Composite {composite:.3f} < {_EMULATION_COMPOSITE_MIN}")

        for dim_name, min_score in _EMULATION_REQUIRED_DIMENSIONS.items():
            dim = dimensions.get(dim_name)
            if dim and dim.score >= min_score:
                dimension_flags[dim_name] = "pass"
            else:
                emulation_eligible = False
                actual = dim.score if dim else 0.0
                dimension_flags[dim_name] = f"fail ({actual:.2f} < {min_score})"
                reasoning_parts.append(f"{dim_name}: {actual:.2f} < {min_score}")

        high_count = sum(1 for dim in dimensions.values() if dim.score >= _DIMENSION_HIGH_THRESHOLD)
        if high_count < _EMULATION_MIN_DIMENSIONS_HIGH:
            emulation_eligible = False
            reasoning_parts.append(f"Only {high_count}/{_EMULATION_MIN_DIMENSIONS_HIGH} dimensions >= {_DIMENSION_HIGH_THRESHOLD}")

        if emulation_eligible:
            classification = ExecutionClass.EMULATION
            reasoning = "All emulation criteria met: high composite, strong across all dimensions"
        elif composite >= _SIMULATION_COMPOSITE_MIN:
            classification = ExecutionClass.SIMULATION
            reasoning = "Simulation: " + "; ".join(reasoning_parts)
        else:
            classification = ExecutionClass.DEGRADED
            reasoning = "Degraded: " + "; ".join(reasoning_parts)

        result = ClassificationResult(
            task_id=fidelity_result.task_id, project_id=self._project_id,
            classification=classification, fidelity_score=composite,
            reasoning=reasoning, dimension_flags=dimension_flags,
        )
        self._persist_classification(result)
        logger.info("Classification: task=%s class=%s score=%.3f", result.task_id, classification.value, composite)
        return result

    def get_emulation_ratio(self, window_tasks: int = 50) -> EmulationRatio:
        """Compute emulation ratio over recent tasks."""
        classifications = self._load_recent_classifications(window_tasks)

        emulation_count = sum(1 for c in classifications if c == "emulation")
        simulation_count = sum(1 for c in classifications if c == "simulation")
        degraded_count = sum(1 for c in classifications if c == "degraded")
        total = len(classifications)

        ratio = (emulation_count / max(total, 1)) * 100

        if total >= 10:
            mid = total // 2
            first_half = sum(1 for c in classifications[:mid] if c == "emulation") / max(mid, 1)
            second_half = sum(1 for c in classifications[mid:] if c == "emulation") / max(total - mid, 1)
            if second_half > first_half + 0.05:
                trend = "improving"
            elif second_half < first_half - 0.05:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"

        return EmulationRatio(
            project_id=self._project_id, window_size=total,
            emulation_count=emulation_count, simulation_count=simulation_count,
            degraded_count=degraded_count, emulation_ratio_percent=round(ratio, 1), trend=trend,
        )

    def _persist_classification(self, result: ClassificationResult) -> None:
        """Persist classification to metrics table."""
        if not self._metrics_table:
            return
        table = self._dynamodb.Table(self._metrics_table)
        try:
            table.put_item(Item={
                "project_id": self._project_id,
                "metric_key": f"emulation#{result.task_id}#{result.timestamp}",
                "metric_type": "emulation_classification",
                "task_id": result.task_id, "recorded_at": result.timestamp,
                "data": json.dumps({
                    "classification": result.classification.value,
                    "fidelity_score": result.fidelity_score,
                    "reasoning": result.reasoning,
                    "dimension_flags": result.dimension_flags,
                }),
            })
        except ClientError as e:
            logger.warning("Failed to persist classification: %s", str(e))

    def _load_recent_classifications(self, limit: int) -> list[str]:
        """Load recent classification values from DynamoDB."""
        if not self._metrics_table:
            return []
        table = self._dynamodb.Table(self._metrics_table)
        try:
            response = table.query(
                KeyConditionExpression="project_id = :pid AND begins_with(metric_key, :prefix)",
                ExpressionAttributeValues={":pid": self._project_id, ":prefix": "emulation#"},
                ScanIndexForward=False, Limit=limit,
            )
            results = [json.loads(item.get("data", "{}")).get("classification", "degraded") for item in response.get("Items", [])]
            return list(reversed(results))
        except ClientError as e:
            logger.warning("Failed to load classifications: %s", str(e))
            return []
