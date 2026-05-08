"""
System Maturity Scorer — DORA 2025 Capability Assessment.

Scores a repository/project on all 7 DORA capabilities (0-100 each):
  C1: Explicit AI stance (org has documented AI usage policy)
  C2: Data ecosystems (structured data pipelines exist)
  C3: AI-accessible data (data is labeled, versioned, queryable)
  C4: Version control (trunk-based, CI/CD, branch protection)
  C5: Small batches (PRs < 200 LOC, frequent deploys)
  C6: User-centric focus (user value statements, outcome tracking)
  C7: Quality platforms (internal developer platform, self-service)

Produces a composite "amplifier readiness" score that maps to:
  - Recommended maximum autonomy level
  - DORA team archetype classification

Autonomy mapping:
  <40  -> max L2 (human-in-the-loop required)
  40-70 -> max L4 (supervised autonomy)
  >70  -> L5 eligible (full autonomy with gates)

DynamoDB SK pattern: maturity#{project_id}#{date}

Ref: docs/dora-2025-code-factory-analysis.md
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class DoraCapability(Enum):
    """The 7 DORA capabilities assessed for AI amplifier readiness."""

    C1_AI_STANCE = "c1_ai_stance"
    C2_DATA_ECOSYSTEMS = "c2_data_ecosystems"
    C3_AI_ACCESSIBLE_DATA = "c3_ai_accessible_data"
    C4_VERSION_CONTROL = "c4_version_control"
    C5_SMALL_BATCHES = "c5_small_batches"
    C6_USER_CENTRIC_FOCUS = "c6_user_centric_focus"
    C7_QUALITY_PLATFORMS = "c7_quality_platforms"


class TeamArchetype(Enum):
    """DORA team archetypes based on capability distribution."""

    STARTING = "starting"
    FLOWING = "flowing"
    ACCELERATING = "accelerating"
    THRIVING = "thriving"


class AutonomyRecommendation(Enum):
    """Recommended maximum autonomy level based on maturity score."""

    MAX_L2 = "max_L2"
    MAX_L4 = "max_L4"
    L5_ELIGIBLE = "L5_eligible"


@dataclass
class CapabilityScore:
    """Score for a single DORA capability."""

    capability: DoraCapability
    score: int  # 0-100
    evidence: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.score = max(0, min(100, self.score))


@dataclass
class MaturityAssessment:
    """Complete maturity assessment result."""

    project_id: str
    capability_scores: dict[DoraCapability, CapabilityScore] = field(default_factory=dict)
    composite_score: float = 0.0
    autonomy_recommendation: AutonomyRecommendation = AutonomyRecommendation.MAX_L2
    team_archetype: TeamArchetype = TeamArchetype.STARTING
    assessed_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.assessed_at:
            self.assessed_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "project_id": self.project_id,
            "capability_scores": {
                cap.value: {
                    "score": cs.score,
                    "evidence": cs.evidence,
                    "recommendations": cs.recommendations,
                }
                for cap, cs in self.capability_scores.items()
            },
            "composite_score": self.composite_score,
            "autonomy_recommendation": self.autonomy_recommendation.value,
            "team_archetype": self.team_archetype.value,
            "assessed_at": self.assessed_at,
            "metadata": self.metadata,
        }


# Capability weights for composite score (sum to 1.0)
_CAPABILITY_WEIGHTS: dict[DoraCapability, float] = {
    DoraCapability.C1_AI_STANCE: 0.10,
    DoraCapability.C2_DATA_ECOSYSTEMS: 0.15,
    DoraCapability.C3_AI_ACCESSIBLE_DATA: 0.15,
    DoraCapability.C4_VERSION_CONTROL: 0.20,
    DoraCapability.C5_SMALL_BATCHES: 0.15,
    DoraCapability.C6_USER_CENTRIC_FOCUS: 0.10,
    DoraCapability.C7_QUALITY_PLATFORMS: 0.15,
}


class SystemMaturityScorer:
    """
    Scores a project on DORA capabilities and recommends autonomy level.

    Usage:
        scorer = SystemMaturityScorer(project_id="my-repo", metrics_table="metrics")
        scorer.score_capability(DoraCapability.C4_VERSION_CONTROL, score=85,
                                evidence=["trunk-based dev", "branch protection enabled"])
        assessment = scorer.compute_assessment()
        # assessment.autonomy_recommendation -> AutonomyRecommendation.L5_ELIGIBLE
    """

    def __init__(
        self,
        project_id: str,
        metrics_table: str | None = None,
    ):
        self._project_id = project_id
        self._metrics_table = metrics_table or os.environ.get("METRICS_TABLE", "")
        self._dynamodb = boto3.resource("dynamodb")
        self._scores: dict[DoraCapability, CapabilityScore] = {}

    def score_capability(
        self,
        capability: DoraCapability,
        score: int,
        evidence: list[str] | None = None,
        recommendations: list[str] | None = None,
    ) -> CapabilityScore:
        """
        Set the score for a single capability.

        Args:
            capability: Which DORA capability to score.
            score: Score from 0-100.
            evidence: Supporting evidence for the score.
            recommendations: Improvement recommendations.

        Returns:
            The created CapabilityScore.
        """
        cap_score = CapabilityScore(
            capability=capability,
            score=score,
            evidence=evidence or [],
            recommendations=recommendations or [],
        )
        self._scores[capability] = cap_score
        logger.debug(
            "Scored %s = %d for project %s",
            capability.value,
            score,
            self._project_id,
        )
        return cap_score

    def score_all(self, scores: dict[DoraCapability, int]) -> None:
        """
        Batch-set scores for multiple capabilities.

        Args:
            scores: Mapping of capability to score (0-100).
        """
        for capability, score in scores.items():
            self.score_capability(capability, score)

    def compute_assessment(self) -> MaturityAssessment:
        """
        Compute the full maturity assessment from individual capability scores.

        Calculates:
          - Weighted composite score
          - Autonomy recommendation based on composite
          - Team archetype based on score distribution

        Returns:
            Complete MaturityAssessment with all derived values.
        """
        composite = self._compute_composite_score()
        autonomy = self._map_autonomy_recommendation(composite)
        archetype = self._map_team_archetype()

        assessment = MaturityAssessment(
            project_id=self._project_id,
            capability_scores=dict(self._scores),
            composite_score=composite,
            autonomy_recommendation=autonomy,
            team_archetype=archetype,
            metadata={
                "capabilities_scored": len(self._scores),
                "capabilities_total": len(DoraCapability),
                "weights": {k.value: v for k, v in _CAPABILITY_WEIGHTS.items()},
            },
        )

        self._persist_assessment(assessment)
        logger.info(
            "Maturity assessment: project=%s composite=%.1f autonomy=%s archetype=%s",
            self._project_id,
            composite,
            autonomy.value,
            archetype.value,
        )
        return assessment

    def get_latest_assessment(self) -> MaturityAssessment | None:
        """
        Retrieve the most recent persisted assessment from DynamoDB.

        Returns:
            The latest MaturityAssessment or None if not found.
        """
        if not self._metrics_table:
            return None

        table = self._dynamodb.Table(self._metrics_table)
        try:
            response = table.query(
                KeyConditionExpression=(
                    "project_id = :pid AND begins_with(metric_key, :prefix)"
                ),
                ExpressionAttributeValues={
                    ":pid": self._project_id,
                    ":prefix": f"maturity#{self._project_id}#",
                },
                ScanIndexForward=False,
                Limit=1,
            )

            items = response.get("Items", [])
            if not items:
                return None

            data = json.loads(items[0].get("data", "{}"))
            return self._deserialize_assessment(data)

        except ClientError as e:
            logger.warning("Failed to load latest assessment: %s", str(e))
            return None

    def _compute_composite_score(self) -> float:
        """Compute weighted composite score from individual capabilities."""
        if not self._scores:
            return 0.0

        weighted_sum = 0.0
        weight_sum = 0.0

        for capability, weight in _CAPABILITY_WEIGHTS.items():
            if capability in self._scores:
                weighted_sum += self._scores[capability].score * weight
                weight_sum += weight

        if weight_sum == 0:
            return 0.0

        # Normalize if not all capabilities are scored
        return round(weighted_sum / weight_sum, 1)

    def _map_autonomy_recommendation(
        self, composite: float
    ) -> AutonomyRecommendation:
        """Map composite score to recommended maximum autonomy level."""
        if composite > 70:
            return AutonomyRecommendation.L5_ELIGIBLE
        elif composite >= 40:
            return AutonomyRecommendation.MAX_L4
        else:
            return AutonomyRecommendation.MAX_L2

    def _map_team_archetype(self) -> TeamArchetype:
        """
        Map score distribution to DORA team archetype.

        Archetypes:
          - Starting: composite < 30 or any capability < 20
          - Flowing: composite 30-50, no critical gaps
          - Accelerating: composite 50-75, strong in C4+C5
          - Thriving: composite > 75, all capabilities > 50
        """
        if not self._scores:
            return TeamArchetype.STARTING

        scores = [cs.score for cs in self._scores.values()]
        composite = self._compute_composite_score()
        min_score = min(scores) if scores else 0

        # Check for critical gaps
        has_critical_gap = min_score < 20

        if composite > 75 and min_score >= 50:
            return TeamArchetype.THRIVING
        elif composite > 50 and not has_critical_gap:
            # Check C4 and C5 strength for accelerating
            c4_score = self._scores.get(DoraCapability.C4_VERSION_CONTROL)
            c5_score = self._scores.get(DoraCapability.C5_SMALL_BATCHES)
            if c4_score and c5_score and c4_score.score >= 60 and c5_score.score >= 60:
                return TeamArchetype.ACCELERATING
            return TeamArchetype.FLOWING
        elif composite >= 30 and not has_critical_gap:
            return TeamArchetype.FLOWING
        else:
            return TeamArchetype.STARTING

    def _persist_assessment(self, assessment: MaturityAssessment) -> None:
        """Persist assessment to DynamoDB metrics table."""
        if not self._metrics_table:
            return

        table = self._dynamodb.Table(self._metrics_table)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        try:
            table.put_item(
                Item={
                    "project_id": self._project_id,
                    "metric_key": f"maturity#{self._project_id}#{date_str}",
                    "metric_type": "maturity_assessment",
                    "recorded_at": assessment.assessed_at,
                    "data": json.dumps(assessment.to_dict()),
                }
            )
        except ClientError as e:
            logger.warning("Failed to persist maturity assessment: %s", str(e))

    def _deserialize_assessment(self, data: dict[str, Any]) -> MaturityAssessment:
        """Reconstruct a MaturityAssessment from persisted data."""
        cap_scores: dict[DoraCapability, CapabilityScore] = {}
        for cap_key, cap_data in data.get("capability_scores", {}).items():
            try:
                capability = DoraCapability(cap_key)
                cap_scores[capability] = CapabilityScore(
                    capability=capability,
                    score=cap_data.get("score", 0),
                    evidence=cap_data.get("evidence", []),
                    recommendations=cap_data.get("recommendations", []),
                )
            except ValueError:
                continue

        return MaturityAssessment(
            project_id=data.get("project_id", self._project_id),
            capability_scores=cap_scores,
            composite_score=data.get("composite_score", 0.0),
            autonomy_recommendation=AutonomyRecommendation(
                data.get("autonomy_recommendation", "max_L2")
            ),
            team_archetype=TeamArchetype(data.get("team_archetype", "starting")),
            assessed_at=data.get("assessed_at", ""),
            metadata=data.get("metadata", {}),
        )
