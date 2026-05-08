"""
Data Quality Scorer — Knowledge Artifact Quality Assessment (Activity 3.06).

Scores knowledge artifacts on four dimensions:
  - Freshness: Days since last update (>90 days = stale alert)
  - Completeness: Coverage vs corpus (how many WAF questions have mappings)
  - Consistency: Cross-reference integrity (all referenced artifacts exist)
  - Accuracy: Validated against source of truth (manual flag)

Composite score = weighted average of all dimensions.
Designed to run weekly via EventBridge cron to maintain knowledge health.

DynamoDB key schema:
  PK: project_id
  SK: "quality#{artifact_name}"

Ref: docs/design/fde-core-brain-development.md Section 3 (Knowledge Plane)
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

logger = logging.getLogger(__name__)

# Dimension weights for composite score
_DIMENSION_WEIGHTS = {
    "freshness": 0.25,
    "completeness": 0.30,
    "consistency": 0.25,
    "accuracy": 0.20,
}

# Freshness thresholds (days)
_FRESHNESS_EXCELLENT = 7    # Updated within a week
_FRESHNESS_GOOD = 30        # Updated within a month
_FRESHNESS_ACCEPTABLE = 60  # Updated within 2 months
_FRESHNESS_STALE = 90       # Stale alert threshold

# Completeness thresholds
_COMPLETENESS_EXCELLENT = 0.90
_COMPLETENESS_GOOD = 0.70
_COMPLETENESS_ACCEPTABLE = 0.50

# Quality alert thresholds
_COMPOSITE_ALERT_THRESHOLD = 0.5
_STALE_ALERT_DAYS = 90


@dataclass
class DimensionScore:
    """Score for a single quality dimension."""

    dimension: str
    score: float  # 0.0 - 1.0
    details: str = ""
    raw_value: Any = None  # The underlying measurement


@dataclass
class QualityAssessment:
    """Complete quality assessment for a knowledge artifact."""

    artifact_name: str
    project_id: str
    freshness: DimensionScore = field(
        default_factory=lambda: DimensionScore(dimension="freshness", score=0.0)
    )
    completeness: DimensionScore = field(
        default_factory=lambda: DimensionScore(dimension="completeness", score=0.0)
    )
    consistency: DimensionScore = field(
        default_factory=lambda: DimensionScore(dimension="consistency", score=0.0)
    )
    accuracy: DimensionScore = field(
        default_factory=lambda: DimensionScore(dimension="accuracy", score=0.0)
    )
    composite_score: float = 0.0
    is_stale: bool = False
    alerts: list[str] = field(default_factory=list)
    assessed_at: str = ""

    def __post_init__(self) -> None:
        if not self.assessed_at:
            self.assessed_at = datetime.now(timezone.utc).isoformat()

    def compute_composite(self) -> float:
        """Compute the weighted composite score from all dimensions."""
        self.composite_score = round(
            self.freshness.score * _DIMENSION_WEIGHTS["freshness"]
            + self.completeness.score * _DIMENSION_WEIGHTS["completeness"]
            + self.consistency.score * _DIMENSION_WEIGHTS["consistency"]
            + self.accuracy.score * _DIMENSION_WEIGHTS["accuracy"],
            4,
        )
        return self.composite_score

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "artifact_name": self.artifact_name,
            "project_id": self.project_id,
            "freshness": {
                "score": self.freshness.score,
                "details": self.freshness.details,
                "raw_value": self.freshness.raw_value,
            },
            "completeness": {
                "score": self.completeness.score,
                "details": self.completeness.details,
                "raw_value": self.completeness.raw_value,
            },
            "consistency": {
                "score": self.consistency.score,
                "details": self.consistency.details,
                "raw_value": self.consistency.raw_value,
            },
            "accuracy": {
                "score": self.accuracy.score,
                "details": self.accuracy.details,
                "raw_value": self.accuracy.raw_value,
            },
            "composite_score": self.composite_score,
            "is_stale": self.is_stale,
            "alerts": self.alerts,
            "assessed_at": self.assessed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QualityAssessment:
        """Deserialize from a dictionary."""
        assessment = cls(
            artifact_name=data.get("artifact_name", ""),
            project_id=data.get("project_id", ""),
            assessed_at=data.get("assessed_at", ""),
        )

        freshness_data = data.get("freshness", {})
        assessment.freshness = DimensionScore(
            dimension="freshness",
            score=freshness_data.get("score", 0.0),
            details=freshness_data.get("details", ""),
            raw_value=freshness_data.get("raw_value"),
        )

        completeness_data = data.get("completeness", {})
        assessment.completeness = DimensionScore(
            dimension="completeness",
            score=completeness_data.get("score", 0.0),
            details=completeness_data.get("details", ""),
            raw_value=completeness_data.get("raw_value"),
        )

        consistency_data = data.get("consistency", {})
        assessment.consistency = DimensionScore(
            dimension="consistency",
            score=consistency_data.get("score", 0.0),
            details=consistency_data.get("details", ""),
            raw_value=consistency_data.get("raw_value"),
        )

        accuracy_data = data.get("accuracy", {})
        assessment.accuracy = DimensionScore(
            dimension="accuracy",
            score=accuracy_data.get("score", 0.0),
            details=accuracy_data.get("details", ""),
            raw_value=accuracy_data.get("raw_value"),
        )

        assessment.composite_score = data.get("composite_score", 0.0)
        assessment.is_stale = data.get("is_stale", False)
        assessment.alerts = data.get("alerts", [])

        return assessment


class DataQualityScorer:
    """
    Scores knowledge artifacts on freshness, completeness, consistency, and accuracy.

    Designed to run weekly via EventBridge cron to maintain knowledge health.
    Produces alerts when artifacts fall below quality thresholds.

    Usage:
        scorer = DataQualityScorer(project_id="my-repo")

        # Score a single artifact
        assessment = scorer.assess_artifact(
            artifact_name="callgraph#src/core/metrics/cost_tracker.py",
            last_updated="2024-01-15T10:00:00Z",
            coverage_ratio=0.85,
            referenced_artifacts=["ADR-009", "ADR-014"],
            accuracy_validated=True,
        )

        # Run weekly assessment on all artifacts
        results = scorer.run_weekly_assessment()

        # Get stored assessment
        stored = scorer.get_assessment("callgraph#src/core/metrics/cost_tracker.py")
    """

    def __init__(
        self,
        project_id: str,
        knowledge_table: str | None = None,
    ):
        self._project_id = project_id
        self._knowledge_table = knowledge_table or os.environ.get(
            "KNOWLEDGE_TABLE", "fde-knowledge"
        )
        self._dynamodb = boto3.resource("dynamodb")
        self._cloudwatch = boto3.client("cloudwatch")

    def assess_artifact(
        self,
        artifact_name: str,
        last_updated: str = "",
        coverage_ratio: float = 0.0,
        referenced_artifacts: list[str] | None = None,
        accuracy_validated: bool = False,
        total_corpus_items: int = 0,
        mapped_items: int = 0,
    ) -> QualityAssessment:
        """
        Assess the quality of a single knowledge artifact.

        Args:
            artifact_name: Identifier of the artifact (e.g., "callgraph#module.py").
            last_updated: ISO timestamp of last update.
            coverage_ratio: Fraction of corpus covered (0.0 - 1.0).
                           Alternatively computed from total_corpus_items/mapped_items.
            referenced_artifacts: List of artifact IDs this artifact references.
            accuracy_validated: Whether accuracy has been manually confirmed.
            total_corpus_items: Total items in the corpus (for completeness calc).
            mapped_items: Number of items with mappings (for completeness calc).

        Returns:
            QualityAssessment with scores and alerts.
        """
        assessment = QualityAssessment(
            artifact_name=artifact_name,
            project_id=self._project_id,
        )

        # Score freshness
        assessment.freshness = self._score_freshness(last_updated)

        # Score completeness
        if total_corpus_items > 0 and mapped_items > 0:
            coverage_ratio = mapped_items / total_corpus_items
        assessment.completeness = self._score_completeness(coverage_ratio)

        # Score consistency
        assessment.consistency = self._score_consistency(referenced_artifacts or [])

        # Score accuracy
        assessment.accuracy = self._score_accuracy(accuracy_validated)

        # Compute composite
        assessment.compute_composite()

        # Check for stale alert
        if assessment.freshness.raw_value and assessment.freshness.raw_value > _STALE_ALERT_DAYS:
            assessment.is_stale = True
            assessment.alerts.append(
                f"STALE: Artifact not updated in {assessment.freshness.raw_value} days"
            )

        # Check composite threshold
        if assessment.composite_score < _COMPOSITE_ALERT_THRESHOLD:
            assessment.alerts.append(
                f"LOW_QUALITY: Composite score {assessment.composite_score:.2f} "
                f"below threshold {_COMPOSITE_ALERT_THRESHOLD}"
            )

        return assessment

    def persist_assessment(self, assessment: QualityAssessment) -> bool:
        """
        Store a quality assessment in DynamoDB.

        Args:
            assessment: The QualityAssessment to persist.

        Returns:
            True if persistence succeeded, False otherwise.
        """
        table = self._dynamodb.Table(self._knowledge_table)
        try:
            table.put_item(
                Item={
                    "project_id": self._project_id,
                    "sk": f"quality#{assessment.artifact_name}",
                    "artifact_name": assessment.artifact_name,
                    "data": json.dumps(assessment.to_dict()),
                    "composite_score": str(assessment.composite_score),
                    "is_stale": assessment.is_stale,
                    "assessed_at": assessment.assessed_at,
                    "alert_count": len(assessment.alerts),
                }
            )
            return True
        except ClientError as e:
            logger.warning(
                "Failed to persist quality assessment for %s: %s",
                assessment.artifact_name,
                e,
            )
            return False

    def get_assessment(self, artifact_name: str) -> QualityAssessment | None:
        """
        Retrieve a stored quality assessment.

        Args:
            artifact_name: The artifact identifier.

        Returns:
            QualityAssessment or None if not found.
        """
        table = self._dynamodb.Table(self._knowledge_table)
        try:
            response = table.get_item(
                Key={
                    "project_id": self._project_id,
                    "sk": f"quality#{artifact_name}",
                }
            )
            item = response.get("Item")
            if not item:
                return None

            data = json.loads(item.get("data", "{}"))
            return QualityAssessment.from_dict(data)
        except ClientError as e:
            logger.warning(
                "Failed to get quality assessment for %s: %s", artifact_name, e
            )
            return None

    def run_weekly_assessment(self) -> list[QualityAssessment]:
        """
        Run a full quality assessment on all knowledge artifacts.

        Scans all call graphs, descriptions, annotations, and vectors
        in the knowledge table and scores each one.

        This method is designed to be invoked by an EventBridge cron rule
        (weekly schedule).

        Returns:
            List of QualityAssessment results.
        """
        table = self._dynamodb.Table(self._knowledge_table)
        assessments: list[QualityAssessment] = []

        # Collect all artifacts for this project
        artifacts = self._discover_artifacts(table)

        for artifact_name, artifact_meta in artifacts.items():
            assessment = self.assess_artifact(
                artifact_name=artifact_name,
                last_updated=artifact_meta.get("last_updated", ""),
                coverage_ratio=artifact_meta.get("coverage_ratio", 0.0),
                referenced_artifacts=artifact_meta.get("referenced_artifacts", []),
                accuracy_validated=artifact_meta.get("accuracy_validated", False),
            )
            self.persist_assessment(assessment)
            assessments.append(assessment)

        # Emit CloudWatch metrics for monitoring
        self._emit_quality_metrics(assessments)

        logger.info(
            "Weekly assessment complete: project=%s artifacts=%d stale=%d alerts=%d",
            self._project_id,
            len(assessments),
            sum(1 for a in assessments if a.is_stale),
            sum(len(a.alerts) for a in assessments),
        )

        return assessments

    def get_all_assessments(self) -> list[QualityAssessment]:
        """
        Retrieve all stored quality assessments for this project.

        Returns:
            List of QualityAssessment objects.
        """
        table = self._dynamodb.Table(self._knowledge_table)
        assessments: list[QualityAssessment] = []

        try:
            response = table.query(
                KeyConditionExpression=(
                    boto3.dynamodb.conditions.Key("project_id").eq(self._project_id)
                    & boto3.dynamodb.conditions.Key("sk").begins_with("quality#")
                )
            )

            for item in response.get("Items", []):
                data = json.loads(item.get("data", "{}"))
                if data:
                    assessments.append(QualityAssessment.from_dict(data))

            while "LastEvaluatedKey" in response:
                response = table.query(
                    KeyConditionExpression=(
                        boto3.dynamodb.conditions.Key("project_id").eq(self._project_id)
                        & boto3.dynamodb.conditions.Key("sk").begins_with("quality#")
                    ),
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                for item in response.get("Items", []):
                    data = json.loads(item.get("data", "{}"))
                    if data:
                        assessments.append(QualityAssessment.from_dict(data))

        except ClientError as e:
            logger.warning("Failed to list quality assessments: %s", e)

        return assessments

    def get_stale_artifacts(self) -> list[QualityAssessment]:
        """Return all artifacts flagged as stale."""
        return [a for a in self.get_all_assessments() if a.is_stale]

    def get_low_quality_artifacts(
        self, threshold: float = _COMPOSITE_ALERT_THRESHOLD
    ) -> list[QualityAssessment]:
        """Return all artifacts below the quality threshold."""
        return [
            a for a in self.get_all_assessments() if a.composite_score < threshold
        ]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _score_freshness(self, last_updated: str) -> DimensionScore:
        """Score freshness based on days since last update."""
        if not last_updated:
            return DimensionScore(
                dimension="freshness",
                score=0.0,
                details="No update timestamp available",
                raw_value=None,
            )

        try:
            updated_dt = datetime.fromisoformat(last_updated)
            now = datetime.now(timezone.utc)
            days_since_update = (now - updated_dt).days
        except (ValueError, TypeError):
            return DimensionScore(
                dimension="freshness",
                score=0.0,
                details=f"Cannot parse timestamp: {last_updated}",
                raw_value=None,
            )

        # Score based on age
        if days_since_update <= _FRESHNESS_EXCELLENT:
            score = 1.0
            details = f"Excellent: updated {days_since_update} days ago"
        elif days_since_update <= _FRESHNESS_GOOD:
            score = 0.8
            details = f"Good: updated {days_since_update} days ago"
        elif days_since_update <= _FRESHNESS_ACCEPTABLE:
            score = 0.5
            details = f"Acceptable: updated {days_since_update} days ago"
        elif days_since_update <= _FRESHNESS_STALE:
            score = 0.3
            details = f"Aging: updated {days_since_update} days ago"
        else:
            score = 0.1
            details = f"Stale: updated {days_since_update} days ago (>{_FRESHNESS_STALE} days)"

        return DimensionScore(
            dimension="freshness",
            score=score,
            details=details,
            raw_value=days_since_update,
        )

    def _score_completeness(self, coverage_ratio: float) -> DimensionScore:
        """Score completeness based on coverage ratio."""
        coverage_ratio = max(0.0, min(1.0, coverage_ratio))

        if coverage_ratio >= _COMPLETENESS_EXCELLENT:
            details = f"Excellent coverage: {coverage_ratio:.0%}"
        elif coverage_ratio >= _COMPLETENESS_GOOD:
            details = f"Good coverage: {coverage_ratio:.0%}"
        elif coverage_ratio >= _COMPLETENESS_ACCEPTABLE:
            details = f"Acceptable coverage: {coverage_ratio:.0%}"
        else:
            details = f"Low coverage: {coverage_ratio:.0%}"

        return DimensionScore(
            dimension="completeness",
            score=round(coverage_ratio, 4),
            details=details,
            raw_value=coverage_ratio,
        )

    def _score_consistency(self, referenced_artifacts: list[str]) -> DimensionScore:
        """
        Score consistency by checking if referenced artifacts exist.

        Queries DynamoDB to verify each referenced artifact is present.
        """
        if not referenced_artifacts:
            return DimensionScore(
                dimension="consistency",
                score=1.0,
                details="No cross-references to validate",
                raw_value={"total": 0, "valid": 0},
            )

        table = self._dynamodb.Table(self._knowledge_table)
        valid_count = 0

        for artifact_ref in referenced_artifacts:
            exists = self._artifact_exists(table, artifact_ref)
            if exists:
                valid_count += 1

        total = len(referenced_artifacts)
        ratio = valid_count / total if total > 0 else 0.0

        if ratio >= 1.0:
            details = f"All {total} references valid"
        else:
            missing = total - valid_count
            details = f"{missing}/{total} references broken"

        return DimensionScore(
            dimension="consistency",
            score=round(ratio, 4),
            details=details,
            raw_value={"total": total, "valid": valid_count},
        )

    def _score_accuracy(self, validated: bool) -> DimensionScore:
        """Score accuracy based on manual validation flag."""
        if validated:
            return DimensionScore(
                dimension="accuracy",
                score=1.0,
                details="Manually validated against source of truth",
                raw_value=True,
            )
        return DimensionScore(
            dimension="accuracy",
            score=0.5,
            details="Not yet validated (auto-generated)",
            raw_value=False,
        )

    def _artifact_exists(self, table: Any, artifact_ref: str) -> bool:
        """Check if a referenced artifact exists in the knowledge table."""
        sk_patterns = [
            f"callgraph#{artifact_ref}",
            f"description#{artifact_ref}",
            f"annotation#{artifact_ref}",
            f"quality#{artifact_ref}",
            artifact_ref,
        ]

        for sk in sk_patterns:
            try:
                response = table.get_item(
                    Key={
                        "project_id": self._project_id,
                        "sk": sk,
                    },
                    ProjectionExpression="sk",
                )
                if response.get("Item"):
                    return True
            except ClientError:
                continue

        return False

    def _discover_artifacts(self, table: Any) -> dict[str, dict[str, Any]]:
        """
        Discover all knowledge artifacts for this project.

        Returns a dict mapping artifact_name to metadata needed for scoring.
        """
        artifacts: dict[str, dict[str, Any]] = {}

        try:
            response = table.query(
                KeyConditionExpression=(
                    boto3.dynamodb.conditions.Key("project_id").eq(self._project_id)
                ),
                ProjectionExpression="sk, extracted_at, generated_at, created_at, #d",
                ExpressionAttributeNames={"#d": "data"},
            )

            self._process_discovery_items(response.get("Items", []), artifacts)

            while "LastEvaluatedKey" in response:
                response = table.query(
                    KeyConditionExpression=(
                        boto3.dynamodb.conditions.Key("project_id").eq(self._project_id)
                    ),
                    ProjectionExpression="sk, extracted_at, generated_at, created_at, #d",
                    ExpressionAttributeNames={"#d": "data"},
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                self._process_discovery_items(response.get("Items", []), artifacts)

        except ClientError as e:
            logger.warning("Failed to discover artifacts: %s", e)

        return artifacts

    def _process_discovery_items(
        self, items: list[dict[str, Any]], artifacts: dict[str, dict[str, Any]]
    ) -> None:
        """Process DynamoDB items into the artifacts discovery dict."""
        for item in items:
            sk = item.get("sk", "")
            # Skip quality entries (we're scoring those, not scoring ourselves)
            if sk.startswith("quality#"):
                continue
            # Skip vector entries (scored via their parent descriptions)
            if sk.startswith("vector#"):
                continue

            # Determine last_updated from available timestamps
            last_updated = (
                item.get("extracted_at")
                or item.get("generated_at")
                or item.get("created_at")
                or ""
            )

            # Try to extract referenced artifacts from data
            referenced: list[str] = []
            data_str = item.get("data", "")
            if data_str:
                try:
                    data = json.loads(data_str)
                    referenced.extend(data.get("imports", []))
                    referenced.extend(data.get("governing_artifacts", []))
                except (json.JSONDecodeError, TypeError):
                    pass

            artifacts[sk] = {
                "last_updated": last_updated,
                "coverage_ratio": 0.5,
                "referenced_artifacts": referenced,
                "accuracy_validated": False,
            }

    def _emit_quality_metrics(self, assessments: list[QualityAssessment]) -> None:
        """Emit CloudWatch metrics for quality monitoring."""
        if not assessments:
            return

        avg_composite = sum(a.composite_score for a in assessments) / len(assessments)
        stale_count = sum(1 for a in assessments if a.is_stale)
        alert_count = sum(len(a.alerts) for a in assessments)

        try:
            self._cloudwatch.put_metric_data(
                Namespace="FDE/Knowledge",
                MetricData=[
                    {
                        "MetricName": "AverageQualityScore",
                        "Value": avg_composite,
                        "Unit": "None",
                        "Dimensions": [
                            {"Name": "ProjectId", "Value": self._project_id},
                        ],
                    },
                    {
                        "MetricName": "StaleArtifactCount",
                        "Value": stale_count,
                        "Unit": "Count",
                        "Dimensions": [
                            {"Name": "ProjectId", "Value": self._project_id},
                        ],
                    },
                    {
                        "MetricName": "QualityAlertCount",
                        "Value": alert_count,
                        "Unit": "Count",
                        "Dimensions": [
                            {"Name": "ProjectId", "Value": self._project_id},
                        ],
                    },
                ],
            )
        except ClientError as e:
            logger.warning("Failed to emit quality metrics: %s", e)
