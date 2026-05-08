"""
Fidelity Score — Measuring How Closely Execution Matches Intent.

Elevates FDE from simulation (correct outputs) to emulation (causal
mechanism replication). The fidelity score quantifies how well the
factory's execution process mirrors the reasoning a human Staff Engineer
would apply.

Dimensions scored (0.0 - 1.0 each):
  - spec_adherence: Does the output match the spec's acceptance criteria?
  - reasoning_quality: Are decisions justified with references to ADRs/governance?
  - context_utilization: Was available context (hierarchy, memory) actually used?
  - governance_compliance: Were all applicable gates passed without override?
  - user_value_delivery: Does the output serve the stated user need?

Composite fidelity score = weighted average of all dimensions.
Target: > 0.7 sustained for L4/L5 tasks.

The fde-fidelity-agent runs this scorer in the final pipeline stage
after all implementation is complete.

Ref: docs/design/fde-core-brain-development.md Section 2 (Wave 2)
     docs/design/fde-brain-simulation-design.md
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

_DIMENSION_WEIGHTS = {
    "spec_adherence": 0.30,
    "reasoning_quality": 0.20,
    "context_utilization": 0.15,
    "governance_compliance": 0.20,
    "user_value_delivery": 0.15,
}

_FIDELITY_TARGET = 0.7
_FIDELITY_EXCELLENT = 0.85
_FIDELITY_POOR = 0.4


@dataclass
class DimensionScore:
    """Score for a single fidelity dimension."""

    dimension: str
    score: float
    weight: float
    evidence: list[str] = field(default_factory=list)
    deductions: list[str] = field(default_factory=list)

    @property
    def weighted_score(self) -> float:
        return self.score * self.weight


@dataclass
class FidelityResult:
    """Complete fidelity assessment for a task execution."""

    task_id: str
    project_id: str
    composite_score: float
    dimensions: dict[str, DimensionScore] = field(default_factory=dict)
    classification: str = ""
    meets_target: bool = False
    timestamp: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if not self.classification:
            if self.composite_score >= _FIDELITY_EXCELLENT:
                self.classification = "emulation"
            elif self.composite_score >= _FIDELITY_TARGET:
                self.classification = "simulation"
            else:
                self.classification = "degraded"
        self.meets_target = self.composite_score >= _FIDELITY_TARGET


class FidelityScorer:
    """
    Computes fidelity scores for completed task executions.

    Usage:
        scorer = FidelityScorer(project_id="my-repo")
        result = scorer.score(task_id="task-123", spec={...}, ...)
    """

    def __init__(self, project_id: str = "", metrics_table: str | None = None):
        self._project_id = project_id or os.environ.get("PROJECT_ID", "global")
        self._metrics_table = metrics_table or os.environ.get("METRICS_TABLE", "")
        self._dynamodb = boto3.resource("dynamodb")

    def score(
        self,
        task_id: str,
        spec: dict[str, Any],
        execution_output: dict[str, Any],
        gate_results: list[dict[str, Any]],
        context_available: dict[str, Any],
        context_used: dict[str, Any],
        user_value_statement: str,
    ) -> FidelityResult:
        """Compute fidelity score for a completed task."""
        dimensions: dict[str, DimensionScore] = {}

        dimensions["spec_adherence"] = self._score_spec_adherence(spec, execution_output)
        dimensions["reasoning_quality"] = self._score_reasoning_quality(execution_output)
        dimensions["context_utilization"] = self._score_context_utilization(context_available, context_used)
        dimensions["governance_compliance"] = self._score_governance_compliance(gate_results)
        dimensions["user_value_delivery"] = self._score_user_value_delivery(user_value_statement, execution_output)

        composite = sum(d.weighted_score for d in dimensions.values())

        result = FidelityResult(
            task_id=task_id, project_id=self._project_id,
            composite_score=round(composite, 4), dimensions=dimensions,
            metadata={
                "spec_criteria_count": len(spec.get("acceptance_criteria", [])),
                "gates_total": len(gate_results),
                "context_items_available": sum(len(v) if isinstance(v, list) else 1 for v in context_available.values()),
                "context_items_used": sum(len(v) if isinstance(v, list) else 1 for v in context_used.values()),
            },
        )

        self._persist_result(result)
        logger.info("Fidelity scored: task=%s score=%.3f classification=%s", task_id, result.composite_score, result.classification)
        return result

    def _score_spec_adherence(self, spec: dict[str, Any], output: dict[str, Any]) -> DimensionScore:
        """Score how well output matches spec acceptance criteria."""
        criteria = spec.get("acceptance_criteria", [])
        if not criteria:
            return DimensionScore(dimension="spec_adherence", score=0.5, weight=_DIMENSION_WEIGHTS["spec_adherence"], evidence=["No acceptance criteria defined"])

        output_text = json.dumps(output).lower()
        test_results = output.get("test_results", [])
        criteria_met = 0
        evidence, deductions = [], []

        for criterion in criteria:
            criterion_lower = criterion.lower() if isinstance(criterion, str) else ""
            keywords = [w for w in criterion_lower.split() if len(w) > 4]
            matches = sum(1 for kw in keywords if kw in output_text)
            if matches >= len(keywords) * 0.3:
                criteria_met += 1
                evidence.append(f"Criterion addressed: {criterion[:60]}")
            else:
                deductions.append(f"Criterion not evidenced: {criterion[:60]}")

        score = criteria_met / max(len(criteria), 1)
        if test_results:
            passing = sum(1 for t in test_results if t.get("status") == "passed")
            if passing == len(test_results) and len(test_results) > 0:
                score = min(1.0, score + 0.1)
                evidence.append(f"All {passing} tests passing")

        return DimensionScore(dimension="spec_adherence", score=round(min(1.0, score), 3), weight=_DIMENSION_WEIGHTS["spec_adherence"], evidence=evidence, deductions=deductions)

    def _score_reasoning_quality(self, output: dict[str, Any]) -> DimensionScore:
        """Score whether decisions are justified with references."""
        evidence, deductions = [], []
        score = 0.5
        output_text = json.dumps(output)

        adr_refs = output_text.count("ADR-")
        if adr_refs > 0:
            score += 0.2
            evidence.append(f"References {adr_refs} ADR(s)")

        gov_keywords = ["governance", "policy", "rule", "constraint", "boundary"]
        gov_refs = sum(1 for kw in gov_keywords if kw in output_text.lower())
        if gov_refs >= 2:
            score += 0.15
            evidence.append(f"References {gov_refs} governance concepts")

        rationale_keywords = ["because", "rationale", "reason", "decision", "trade-off", "alternative"]
        rationale_refs = sum(1 for kw in rationale_keywords if kw in output_text.lower())
        if rationale_refs >= 3:
            score += 0.15
            evidence.append("Provides reasoning and justification")
        elif rationale_refs == 0:
            deductions.append("No explicit reasoning provided")
            score -= 0.1

        return DimensionScore(dimension="reasoning_quality", score=round(max(0.0, min(1.0, score)), 3), weight=_DIMENSION_WEIGHTS["reasoning_quality"], evidence=evidence, deductions=deductions)

    def _score_context_utilization(self, available: dict[str, Any], used: dict[str, Any]) -> DimensionScore:
        """Score how well available context was utilized."""
        total_available = sum(len(v) if isinstance(v, list) else 1 for v in available.values())
        total_used = sum(len(v) if isinstance(v, list) else 1 for v in used.values())

        if total_available == 0:
            return DimensionScore(dimension="context_utilization", score=0.7, weight=_DIMENSION_WEIGHTS["context_utilization"], evidence=["No context available"])

        ratio = total_used / total_available
        if ratio >= 0.8:
            score = 1.0
        elif ratio >= 0.6:
            score = 0.8
        elif ratio >= 0.3:
            score = 0.6
        else:
            score = 0.3

        evidence = [f"Context utilization: {total_used}/{total_available} items ({ratio*100:.0f}%)"]
        deductions = [] if ratio >= 0.3 else [f"Low utilization: only {total_used}/{total_available} items used"]

        return DimensionScore(dimension="context_utilization", score=round(score, 3), weight=_DIMENSION_WEIGHTS["context_utilization"], evidence=evidence, deductions=deductions)

    def _score_governance_compliance(self, gate_results: list[dict[str, Any]]) -> DimensionScore:
        """Score governance gate compliance."""
        if not gate_results:
            return DimensionScore(dimension="governance_compliance", score=0.5, weight=_DIMENSION_WEIGHTS["governance_compliance"], evidence=["No gate results"])

        total = len(gate_results)
        passed = sum(1 for g in gate_results if g.get("status") == "passed")
        overridden = sum(1 for g in gate_results if g.get("status") == "overridden")

        score = passed / total
        score -= overridden * 0.15

        gate_rejection_counts: dict[str, int] = {}
        for g in gate_results:
            if g.get("status") == "rejected":
                gate_name = g.get("gate", "unknown")
                gate_rejection_counts[gate_name] = gate_rejection_counts.get(gate_name, 0) + 1

        repeat_rejections = sum(1 for c in gate_rejection_counts.values() if c > 1)
        score -= repeat_rejections * 0.1

        evidence = [f"All {total} gates passed"] if passed == total else []
        deductions = []
        if overridden:
            deductions.append(f"{overridden} gate(s) overridden")
        if repeat_rejections:
            deductions.append(f"{repeat_rejections} gate(s) rejected multiple times")

        return DimensionScore(dimension="governance_compliance", score=round(max(0.0, min(1.0, score)), 3), weight=_DIMENSION_WEIGHTS["governance_compliance"], evidence=evidence, deductions=deductions)

    def _score_user_value_delivery(self, user_value_statement: str, output: dict[str, Any]) -> DimensionScore:
        """Score whether output serves the stated user need."""
        if not user_value_statement:
            return DimensionScore(dimension="user_value_delivery", score=0.4, weight=_DIMENSION_WEIGHTS["user_value_delivery"], deductions=["No user value statement"])

        output_text = json.dumps(output).lower()
        value_lower = user_value_statement.lower()
        score = 0.5
        evidence, deductions = [], []

        if "as a " in value_lower:
            user_role = value_lower.split("as a ")[1].split(",")[0].strip()
            if user_role in output_text:
                score += 0.15
                evidence.append(f"User role '{user_role}' addressed")

        if "i want " in value_lower:
            action = value_lower.split("i want ")[1].split(",")[0].strip()
            action_keywords = [w for w in action.split() if len(w) > 3]
            if sum(1 for kw in action_keywords if kw in output_text) >= len(action_keywords) * 0.4:
                score += 0.2
                evidence.append("Desired action implemented")
            else:
                deductions.append("Desired action not evidenced")

        if "so that " in value_lower:
            value = value_lower.split("so that ")[1].strip()
            value_keywords = [w for w in value.split() if len(w) > 3]
            if sum(1 for kw in value_keywords if kw in output_text) >= len(value_keywords) * 0.3:
                score += 0.15
                evidence.append("Value proposition addressed")

        return DimensionScore(dimension="user_value_delivery", score=round(max(0.0, min(1.0, score)), 3), weight=_DIMENSION_WEIGHTS["user_value_delivery"], evidence=evidence, deductions=deductions)

    def _persist_result(self, result: FidelityResult) -> None:
        """Persist fidelity result to metrics table."""
        if not self._metrics_table:
            return
        table = self._dynamodb.Table(self._metrics_table)
        try:
            table.put_item(Item={
                "project_id": self._project_id,
                "metric_key": f"fidelity#{result.task_id}#{result.timestamp}",
                "metric_type": "fidelity", "task_id": result.task_id,
                "recorded_at": result.timestamp,
                "data": json.dumps({
                    "composite_score": result.composite_score,
                    "classification": result.classification,
                    "meets_target": result.meets_target,
                    "dimensions": {
                        name: {"score": dim.score, "weighted_score": dim.weighted_score, "evidence": dim.evidence, "deductions": dim.deductions}
                        for name, dim in result.dimensions.items()
                    },
                    "metadata": result.metadata,
                }),
            })
        except ClientError as e:
            logger.warning("Failed to persist fidelity result: %s", str(e))

    def get_trend(self, window_tasks: int = 20) -> list[float]:
        """Get fidelity score trend for recent tasks."""
        if not self._metrics_table:
            return []
        table = self._dynamodb.Table(self._metrics_table)
        try:
            response = table.query(
                KeyConditionExpression="project_id = :pid AND begins_with(metric_key, :prefix)",
                ExpressionAttributeValues={":pid": self._project_id, ":prefix": "fidelity#"},
                ScanIndexForward=False, Limit=window_tasks,
            )
            scores = [json.loads(item.get("data", "{}")).get("composite_score", 0.0) for item in response.get("Items", [])]
            return list(reversed(scores))
        except ClientError as e:
            logger.warning("Failed to get fidelity trend: %s", str(e))
            return []
