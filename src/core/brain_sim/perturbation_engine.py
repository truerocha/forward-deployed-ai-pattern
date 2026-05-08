"""
Perturbation Engine — Controlled Robustness Testing (Activity 3.07).

Introduces controlled perturbations to test agent robustness under
adversarial conditions. Used by swe-adversarial-agent and
swe-redteam-agent to validate that agents degrade gracefully when
inputs are noisy, context is incomplete, or constraints are injected.

Perturbation types:
  - input_noise: Modify spec slightly (typos, reworded requirements)
  - context_removal: Hide some context items from the agent
  - constraint_injection: Add fake constraints (budget, time, tech)
  - timeout_simulation: Simulate slow responses / partial timeouts

Each perturbation has a severity level (low / medium / high) that
controls the magnitude of the distortion applied.

Metrics recorded to DynamoDB:
  PK: project_id
  SK: "perturbation#{task_id}#{type}"

Ref: docs/design/fde-core-brain-development.md Section 2 (Wave 2)
     docs/design/fde-brain-simulation-design.md
"""

from __future__ import annotations

import json
import logging
import os
import random
import string
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class PerturbationType(str, Enum):
    """Types of perturbation that can be applied."""

    INPUT_NOISE = "input_noise"
    CONTEXT_REMOVAL = "context_removal"
    CONSTRAINT_INJECTION = "constraint_injection"
    TIMEOUT_SIMULATION = "timeout_simulation"


class Severity(str, Enum):
    """Severity level controlling perturbation magnitude."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# Severity multipliers for each perturbation type
_SEVERITY_PARAMS: dict[Severity, dict[str, float]] = {
    Severity.LOW: {"noise_ratio": 0.05, "removal_ratio": 0.2, "constraint_count": 1, "timeout_ms": 500},
    Severity.MEDIUM: {"noise_ratio": 0.15, "removal_ratio": 0.5, "constraint_count": 3, "timeout_ms": 2000},
    Severity.HIGH: {"noise_ratio": 0.30, "removal_ratio": 0.8, "constraint_count": 5, "timeout_ms": 5000},
}

_FAKE_CONSTRAINTS = [
    "Must complete within 30 seconds",
    "Cannot use any external libraries",
    "Must support Python 2.7 compatibility",
    "Budget limited to $0.001 per invocation",
    "Must not exceed 50 lines of code",
    "Cannot access network resources",
    "Must run in 128MB memory",
    "Output must be under 1KB",
    "Cannot use any caching",
    "Must be stateless across invocations",
]


@dataclass
class PerturbationConfig:
    """Configuration for a single perturbation run."""

    perturbation_type: PerturbationType
    severity: Severity
    task_id: str
    seed: int | None = None

    def __post_init__(self) -> None:
        if self.seed is None:
            self.seed = random.randint(0, 2**32 - 1)


@dataclass
class PerturbationResult:
    """Result of applying a perturbation and measuring agent response."""

    task_id: str
    perturbation_type: str
    severity: str
    detected: bool = False
    quality_score_before: float = 0.0
    quality_score_after: float = 0.0
    degradation: float = 0.0
    agent_response_summary: str = ""
    perturbation_details: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        self.degradation = round(
            max(0.0, self.quality_score_before - self.quality_score_after), 4
        )


class PerturbationEngine:
    """
    Introduces controlled perturbations to test agent robustness.

    Runs inside swe-adversarial-agent or swe-redteam-agent to validate
    that agents handle degraded inputs gracefully.

    Usage:
        engine = PerturbationEngine(project_id="my-repo", metrics_table="fde-dev-metrics")
        perturbed_spec = engine.apply_input_noise(original_spec, severity=Severity.MEDIUM, task_id="task-42")
        result = engine.record_result(task_id="task-42", perturbation_type=PerturbationType.INPUT_NOISE, ...)
    """

    def __init__(
        self,
        project_id: str,
        metrics_table: str | None = None,
    ):
        self._project_id = project_id or os.environ.get("PROJECT_ID", "global")
        self._metrics_table = metrics_table or os.environ.get("METRICS_TABLE", "")
        self._dynamodb = boto3.resource("dynamodb")
        self._rng = random.Random()

    def apply_input_noise(
        self,
        spec: dict[str, Any],
        severity: Severity,
        task_id: str,
    ) -> dict[str, Any]:
        """
        Apply input noise to a spec by introducing typos and rewording.

        Args:
            spec: Original task specification.
            severity: How much noise to introduce.
            task_id: Identifier for the task being perturbed.

        Returns:
            Modified spec with noise applied.
        """
        config = PerturbationConfig(
            perturbation_type=PerturbationType.INPUT_NOISE,
            severity=severity,
            task_id=task_id,
        )
        self._rng.seed(config.seed)
        params = _SEVERITY_PARAMS[severity]
        noise_ratio = params["noise_ratio"]

        perturbed = json.loads(json.dumps(spec))
        self._inject_noise_recursive(perturbed, noise_ratio)

        logger.info(
            "Applied input_noise: task=%s severity=%s noise_ratio=%.2f",
            task_id, severity.value, noise_ratio,
        )
        return perturbed

    def apply_context_removal(
        self,
        context: dict[str, list[Any]],
        severity: Severity,
        task_id: str,
    ) -> dict[str, list[Any]]:
        """
        Remove a portion of context items to simulate incomplete information.

        Args:
            context: Dictionary of context categories to item lists.
            severity: How much context to remove.
            task_id: Identifier for the task being perturbed.

        Returns:
            Context with items removed according to severity.
        """
        config = PerturbationConfig(
            perturbation_type=PerturbationType.CONTEXT_REMOVAL,
            severity=severity,
            task_id=task_id,
        )
        self._rng.seed(config.seed)
        params = _SEVERITY_PARAMS[severity]
        removal_ratio = params["removal_ratio"]

        perturbed_context: dict[str, list[Any]] = {}
        total_removed = 0
        total_original = 0

        for category, items in context.items():
            total_original += len(items)
            keep_count = max(1, int(len(items) * (1 - removal_ratio)))
            kept = self._rng.sample(items, min(keep_count, len(items)))
            perturbed_context[category] = kept
            total_removed += len(items) - len(kept)

        logger.info(
            "Applied context_removal: task=%s severity=%s removed=%d/%d items",
            task_id, severity.value, total_removed, total_original,
        )
        return perturbed_context

    def apply_constraint_injection(
        self,
        spec: dict[str, Any],
        severity: Severity,
        task_id: str,
    ) -> dict[str, Any]:
        """
        Inject fake constraints into a spec to test constraint handling.

        Args:
            spec: Original task specification.
            severity: How many fake constraints to inject.
            task_id: Identifier for the task being perturbed.

        Returns:
            Spec with fake constraints added.
        """
        config = PerturbationConfig(
            perturbation_type=PerturbationType.CONSTRAINT_INJECTION,
            severity=severity,
            task_id=task_id,
        )
        self._rng.seed(config.seed)
        params = _SEVERITY_PARAMS[severity]
        constraint_count = int(params["constraint_count"])

        perturbed = json.loads(json.dumps(spec))
        injected = self._rng.sample(
            _FAKE_CONSTRAINTS, min(constraint_count, len(_FAKE_CONSTRAINTS))
        )

        existing_constraints = perturbed.get("constraints", [])
        if isinstance(existing_constraints, list):
            perturbed["constraints"] = existing_constraints + injected
        else:
            perturbed["constraints"] = injected

        logger.info(
            "Applied constraint_injection: task=%s severity=%s injected=%d constraints",
            task_id, severity.value, len(injected),
        )
        return perturbed

    def apply_timeout_simulation(
        self,
        severity: Severity,
        task_id: str,
    ) -> dict[str, Any]:
        """
        Generate timeout simulation parameters for the agent runtime.

        Args:
            severity: How severe the timeout simulation should be.
            task_id: Identifier for the task being perturbed.

        Returns:
            Dictionary with timeout parameters for the agent runtime to enforce.
        """
        params = _SEVERITY_PARAMS[severity]
        timeout_ms = int(params["timeout_ms"])

        simulation_params = {
            "task_id": task_id,
            "simulated_timeout_ms": timeout_ms,
            "partial_response_at_ms": int(timeout_ms * 0.6),
            "force_truncation": severity == Severity.HIGH,
            "retry_allowed": severity != Severity.HIGH,
        }

        logger.info(
            "Applied timeout_simulation: task=%s severity=%s timeout_ms=%d",
            task_id, severity.value, timeout_ms,
        )
        return simulation_params

    def record_result(
        self,
        task_id: str,
        perturbation_type: PerturbationType,
        severity: Severity,
        detected: bool,
        quality_score_before: float,
        quality_score_after: float,
        agent_response_summary: str = "",
        perturbation_details: dict[str, Any] | None = None,
    ) -> PerturbationResult:
        """
        Record the result of a perturbation test.

        Measures whether the agent detected the perturbation and
        whether output quality degraded.

        Args:
            task_id: The task that was perturbed.
            perturbation_type: Type of perturbation applied.
            severity: Severity level used.
            detected: Whether the agent detected the perturbation.
            quality_score_before: Quality score of unperturbed output.
            quality_score_after: Quality score of perturbed output.
            agent_response_summary: Brief description of agent behavior.
            perturbation_details: Additional details about the perturbation.

        Returns:
            PerturbationResult with computed degradation.
        """
        result = PerturbationResult(
            task_id=task_id,
            perturbation_type=perturbation_type.value,
            severity=severity.value,
            detected=detected,
            quality_score_before=quality_score_before,
            quality_score_after=quality_score_after,
            agent_response_summary=agent_response_summary,
            perturbation_details=perturbation_details or {},
        )

        self._persist_result(result)
        logger.info(
            "Perturbation result: task=%s type=%s severity=%s detected=%s degradation=%.3f",
            task_id, perturbation_type.value, severity.value, detected, result.degradation,
        )
        return result

    def get_robustness_summary(self, window: int = 50) -> dict[str, Any]:
        """
        Get a summary of recent perturbation results for this project.

        Args:
            window: Number of recent results to consider.

        Returns:
            Summary with detection rates and degradation averages per type.
        """
        if not self._metrics_table:
            return {}

        table = self._dynamodb.Table(self._metrics_table)
        try:
            response = table.query(
                KeyConditionExpression="project_id = :pid AND begins_with(metric_key, :prefix)",
                ExpressionAttributeValues={
                    ":pid": self._project_id,
                    ":prefix": "perturbation#",
                },
                ScanIndexForward=False,
                Limit=window,
            )
        except ClientError as e:
            logger.warning("Failed to query perturbation results: %s", e)
            return {}

        items = response.get("Items", [])
        if not items:
            return {"total_tests": 0}

        by_type: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            data = json.loads(item.get("data", "{}"))
            ptype = data.get("perturbation_type", "unknown")
            by_type.setdefault(ptype, []).append(data)

        summary: dict[str, Any] = {"total_tests": len(items), "by_type": {}}
        for ptype, results in by_type.items():
            detected_count = sum(1 for r in results if r.get("detected"))
            avg_degradation = (
                sum(r.get("degradation", 0.0) for r in results) / len(results)
            )
            summary["by_type"][ptype] = {
                "count": len(results),
                "detection_rate": round(detected_count / len(results), 3),
                "avg_degradation": round(avg_degradation, 4),
            }

        return summary

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _inject_noise_recursive(self, obj: Any, noise_ratio: float) -> None:
        """Recursively inject noise into string values."""
        if isinstance(obj, dict):
            for key in list(obj.keys()):
                if isinstance(obj[key], str) and len(obj[key]) > 10:
                    if self._rng.random() < noise_ratio * 3:
                        obj[key] = self._add_typos(obj[key], noise_ratio)
                elif isinstance(obj[key], (dict, list)):
                    self._inject_noise_recursive(obj[key], noise_ratio)
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, (dict, list)):
                    self._inject_noise_recursive(item, noise_ratio)

    def _add_typos(self, text: str, ratio: float) -> str:
        """Add character-level typos to a string."""
        chars = list(text)
        num_typos = max(1, int(len(chars) * ratio))
        for _ in range(num_typos):
            idx = self._rng.randint(0, len(chars) - 1)
            action = self._rng.choice(["swap", "delete", "insert", "replace"])
            if action == "swap" and idx < len(chars) - 1:
                chars[idx], chars[idx + 1] = chars[idx + 1], chars[idx]
            elif action == "delete" and len(chars) > 5:
                chars.pop(idx)
            elif action == "insert":
                chars.insert(idx, self._rng.choice(string.ascii_lowercase))
            elif action == "replace":
                chars[idx] = self._rng.choice(string.ascii_lowercase)
        return "".join(chars)

    def _persist_result(self, result: PerturbationResult) -> None:
        """Persist perturbation result to DynamoDB metrics table."""
        if not self._metrics_table:
            logger.debug("No metrics table configured, skipping persistence")
            return

        table = self._dynamodb.Table(self._metrics_table)
        try:
            table.put_item(
                Item={
                    "project_id": self._project_id,
                    "metric_key": f"perturbation#{result.task_id}#{result.perturbation_type}",
                    "metric_type": "perturbation",
                    "task_id": result.task_id,
                    "recorded_at": result.timestamp,
                    "data": json.dumps({
                        "perturbation_type": result.perturbation_type,
                        "severity": result.severity,
                        "detected": result.detected,
                        "quality_score_before": result.quality_score_before,
                        "quality_score_after": result.quality_score_after,
                        "degradation": result.degradation,
                        "agent_response_summary": result.agent_response_summary,
                        "perturbation_details": result.perturbation_details,
                    }),
                }
            )
        except ClientError as e:
            logger.warning("Failed to persist perturbation result: %s", e)
