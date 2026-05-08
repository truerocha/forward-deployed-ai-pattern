"""
Brain Simulation Metrics — Aggregated Brain Sim Observability.

Consolidates metrics from fidelity scoring, emulation classification,
organism ladder, and context hierarchy into a unified view for the
portal BrainSimCard.

Ref: docs/design/fde-core-brain-development.md Wave 2
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

from src.core.brain_sim.context_hierarchy import ContextHierarchy, ContextLevel
from src.core.brain_sim.emulation_classifier import EmulationClassifier, EmulationRatio
from src.core.brain_sim.fidelity_score import FidelityScorer
from src.core.brain_sim.organism_ladder import OrganismLadder, OrganismLevel

logger = logging.getLogger(__name__)

_MEMORY_WALL_STALE_RATIO = 0.4
_MEMORY_WALL_TOTAL_ITEMS = 200


@dataclass
class BrainSimSnapshot:
    """Complete brain simulation metrics snapshot for portal display."""

    project_id: str
    timestamp: str
    fidelity_trend: list[float] = field(default_factory=list)
    fidelity_current: float = 0.0
    fidelity_meets_target: bool = False
    emulation_ratio: EmulationRatio | None = None
    organism_default_level: int = 3
    organism_distribution: dict[str, int] = field(default_factory=dict)
    context_total_items: int = 0
    context_stale_items: int = 0
    context_coverage_percent: float = 0.0
    memory_wall_detected: bool = False
    memory_wall_reason: str = ""


class BrainSimMetrics:
    """
    Aggregates brain simulation metrics for dashboard consumption.

    Usage:
        bsm = BrainSimMetrics(project_id="my-repo")
        snapshot = bsm.get_snapshot()
    """

    def __init__(self, project_id: str = "", metrics_table: str | None = None):
        self._project_id = project_id or os.environ.get("PROJECT_ID", "global")
        self._metrics_table = metrics_table or os.environ.get("METRICS_TABLE", "")
        self._fidelity = FidelityScorer(project_id=self._project_id, metrics_table=self._metrics_table)
        self._classifier = EmulationClassifier(project_id=self._project_id, metrics_table=self._metrics_table)
        self._organism = OrganismLadder(project_id=self._project_id)
        self._context = ContextHierarchy(project_id=self._project_id)

    def get_snapshot(self) -> BrainSimSnapshot:
        """Compute complete brain simulation metrics snapshot."""
        now = datetime.now(timezone.utc).isoformat()

        fidelity_trend = self._fidelity.get_trend(window_tasks=20)
        fidelity_current = fidelity_trend[-1] if fidelity_trend else 0.0

        emulation_ratio = self._classifier.get_emulation_ratio(window_tasks=50)
        organism_default = self._organism.get_project_default_level()
        organism_distribution = self._get_organism_distribution()
        context_health = self._assess_context_health()
        memory_wall, wall_reason = self._detect_memory_wall(context_health)

        snapshot = BrainSimSnapshot(
            project_id=self._project_id, timestamp=now,
            fidelity_trend=fidelity_trend, fidelity_current=fidelity_current,
            fidelity_meets_target=fidelity_current >= 0.7,
            emulation_ratio=emulation_ratio,
            organism_default_level=int(organism_default),
            organism_distribution=organism_distribution,
            context_total_items=context_health.get("total", 0),
            context_stale_items=context_health.get("stale", 0),
            context_coverage_percent=context_health.get("coverage", 0.0),
            memory_wall_detected=memory_wall, memory_wall_reason=wall_reason,
        )
        self._persist_snapshot(snapshot)
        return snapshot

    def _get_organism_distribution(self) -> dict[str, int]:
        """Get distribution of recent task classifications by organism level."""
        table_name = os.environ.get("ORGANISM_TABLE", "")
        if not table_name:
            return {}
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(table_name)
        try:
            response = table.query(
                KeyConditionExpression="project_id = :pid AND begins_with(organism_key, :prefix)",
                ExpressionAttributeValues={":pid": self._project_id, ":prefix": "classification#"},
                ScanIndexForward=False, Limit=50,
            )
            distribution: dict[str, int] = {}
            for item in response.get("Items", []):
                data = json.loads(item.get("data", "{}"))
                level_name = data.get("organism_name", "O3_COGNITIVE")
                distribution[level_name] = distribution.get(level_name, 0) + 1
            return distribution
        except ClientError as e:
            logger.warning("Failed to get organism distribution: %s", str(e))
            return {}

    def _assess_context_health(self) -> dict[str, Any]:
        """Assess the health of the context hierarchy."""
        total, stale = 0, 0
        for level in ContextLevel:
            items = self._context.get_level(level, include_stale=True)
            total += len(items)
            stale += sum(1 for item in items if item.is_stale)
        coverage = ((total - stale) / max(total, 1)) * 100
        return {"total": total, "stale": stale, "coverage": round(coverage, 1)}

    def _detect_memory_wall(self, context_health: dict[str, Any]) -> tuple[bool, str]:
        """Detect if context hierarchy has hit a memory wall."""
        total = context_health.get("total", 0)
        stale = context_health.get("stale", 0)
        if total > 0 and (stale / total) > _MEMORY_WALL_STALE_RATIO:
            return True, f"Stale ratio {stale}/{total} exceeds {_MEMORY_WALL_STALE_RATIO*100:.0f}% threshold"
        if total > _MEMORY_WALL_TOTAL_ITEMS:
            return True, f"Total items ({total}) exceeds capacity ({_MEMORY_WALL_TOTAL_ITEMS})"
        return False, ""

    def _persist_snapshot(self, snapshot: BrainSimSnapshot) -> None:
        """Persist brain sim snapshot to metrics table."""
        if not self._metrics_table:
            return
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(self._metrics_table)
        try:
            table.put_item(Item={
                "project_id": self._project_id,
                "metric_key": f"brain_sim#snapshot#{snapshot.timestamp}",
                "metric_type": "brain_sim", "task_id": "", "recorded_at": snapshot.timestamp,
                "data": json.dumps({
                    "fidelity_current": snapshot.fidelity_current,
                    "fidelity_meets_target": snapshot.fidelity_meets_target,
                    "emulation_ratio_percent": snapshot.emulation_ratio.emulation_ratio_percent if snapshot.emulation_ratio else 0.0,
                    "emulation_trend": snapshot.emulation_ratio.trend if snapshot.emulation_ratio else "unknown",
                    "organism_default_level": snapshot.organism_default_level,
                    "context_total": snapshot.context_total_items,
                    "context_stale": snapshot.context_stale_items,
                    "memory_wall": snapshot.memory_wall_detected,
                }),
            })
        except ClientError as e:
            logger.warning("Failed to persist brain sim snapshot: %s", str(e))
