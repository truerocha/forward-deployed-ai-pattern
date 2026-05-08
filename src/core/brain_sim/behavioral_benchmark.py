"""
Behavioral Benchmark — Pipeline Output Validation (Activity 3.08).

Validates full pipeline output against behavioral baselines stored in S3.
A baseline is a known-good output for a specific input (golden test).
Compares current output against baseline using structural diff and
semantic similarity scoring.

Scoring:
  - exact_match (1.0): Output is byte-for-byte identical to baseline
  - structural_match (0.8): Same structure/keys, minor value differences
  - semantic_match (0.6): Different structure but equivalent meaning
  - divergent (0.0): Output has fundamentally different content

Baselines stored in S3:
  s3://{bucket}/baselines/{project_id}/{benchmark_name}.json

DynamoDB metrics:
  PK: project_id
  SK: "benchmark#{benchmark_name}#{timestamp}"

Ref: docs/design/fde-core-brain-development.md Section 2 (Wave 2)
     docs/design/fde-brain-simulation-design.md
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_SCORE_EXACT = 1.0
_SCORE_STRUCTURAL = 0.8
_SCORE_SEMANTIC = 0.6
_SCORE_DIVERGENT = 0.0

_STRUCTURAL_THRESHOLD = 0.85
_SEMANTIC_THRESHOLD = 0.55


@dataclass
class Baseline:
    """A known-good output for a specific input (golden test)."""

    name: str
    input_data: dict[str, Any]
    expected_output: dict[str, Any]
    created_at: str = ""
    version: int = 1
    description: str = ""
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dictionary."""
        return {
            "name": self.name,
            "input_data": self.input_data,
            "expected_output": self.expected_output,
            "created_at": self.created_at,
            "version": self.version,
            "description": self.description,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Baseline:
        """Deserialize from dictionary."""
        return cls(
            name=data.get("name", ""),
            input_data=data.get("input_data", {}),
            expected_output=data.get("expected_output", {}),
            created_at=data.get("created_at", ""),
            version=data.get("version", 1),
            description=data.get("description", ""),
            tags=data.get("tags", []),
        )


@dataclass
class BenchmarkResult:
    """Result of comparing actual output against a baseline."""

    benchmark_name: str
    score: float
    classification: str
    structural_similarity: float = 0.0
    semantic_similarity: float = 0.0
    diff_summary: list[str] = field(default_factory=list)
    timestamp: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class BehavioralBenchmark:
    """
    Validates pipeline output against behavioral baselines.

    Stores golden-test baselines in S3 and compares current outputs
    against them using structural diff and semantic similarity.

    Usage:
        bench = BehavioralBenchmark(
            project_id="my-repo",
            artifacts_bucket="fde-dev-artifacts",
            metrics_table="fde-dev-metrics",
        )
        bench.create_baseline("spec-parsing", input_data={...}, expected_output={...})
        result = bench.run_benchmark("spec-parsing", actual_output={...})
    """

    def __init__(
        self,
        project_id: str,
        artifacts_bucket: str | None = None,
        metrics_table: str | None = None,
    ):
        self._project_id = project_id or os.environ.get("PROJECT_ID", "global")
        self._artifacts_bucket = artifacts_bucket or os.environ.get(
            "ARTIFACTS_BUCKET", ""
        )
        self._metrics_table = metrics_table or os.environ.get("METRICS_TABLE", "")
        self._s3 = boto3.client("s3")
        self._dynamodb = boto3.resource("dynamodb")

    def create_baseline(
        self,
        name: str,
        input_data: dict[str, Any],
        expected_output: dict[str, Any],
        description: str = "",
        tags: list[str] | None = None,
    ) -> Baseline:
        """
        Create and store a new behavioral baseline (golden test).

        Args:
            name: Unique name for this baseline.
            input_data: The input that produces the expected output.
            expected_output: The known-good output to compare against.
            description: Human-readable description of what this tests.
            tags: Optional categorization tags.

        Returns:
            The created Baseline object.
        """
        existing = self._load_baseline(name)
        version = (existing.version + 1) if existing else 1

        baseline = Baseline(
            name=name,
            input_data=input_data,
            expected_output=expected_output,
            version=version,
            description=description,
            tags=tags or [],
        )

        self._save_baseline(baseline)
        logger.info(
            "Created baseline: project=%s name=%s version=%d",
            self._project_id, name, version,
        )
        return baseline

    def run_benchmark(
        self,
        name: str,
        actual_output: dict[str, Any],
    ) -> BenchmarkResult:
        """
        Run a benchmark by comparing actual output against stored baseline.

        Args:
            name: Name of the baseline to compare against.
            actual_output: The current pipeline output to validate.

        Returns:
            BenchmarkResult with score and classification.

        Raises:
            ValueError: If no baseline exists with the given name.
        """
        baseline = self._load_baseline(name)
        if not baseline:
            raise ValueError(f"No baseline found with name '{name}'")

        expected = baseline.expected_output

        # Check exact match
        if self._is_exact_match(expected, actual_output):
            result = BenchmarkResult(
                benchmark_name=name,
                score=_SCORE_EXACT,
                classification="exact_match",
                structural_similarity=1.0,
                semantic_similarity=1.0,
                diff_summary=["Output is identical to baseline"],
            )
            self._persist_result(result)
            return result

        # Compute structural similarity
        structural_sim = self._compute_structural_similarity(expected, actual_output)

        # Compute semantic similarity
        semantic_sim = self._compute_semantic_similarity(expected, actual_output)

        # Classify
        diff_summary = self._compute_diff_summary(expected, actual_output)

        if structural_sim >= _STRUCTURAL_THRESHOLD:
            score = _SCORE_STRUCTURAL
            classification = "structural_match"
        elif semantic_sim >= _SEMANTIC_THRESHOLD:
            score = _SCORE_SEMANTIC
            classification = "semantic_match"
        else:
            score = _SCORE_DIVERGENT
            classification = "divergent"

        result = BenchmarkResult(
            benchmark_name=name,
            score=score,
            classification=classification,
            structural_similarity=round(structural_sim, 4),
            semantic_similarity=round(semantic_sim, 4),
            diff_summary=diff_summary,
            metadata={
                "baseline_version": baseline.version,
                "baseline_created_at": baseline.created_at,
            },
        )

        self._persist_result(result)
        logger.info(
            "Benchmark result: name=%s score=%.1f classification=%s structural=%.3f semantic=%.3f",
            name, score, classification, structural_sim, semantic_sim,
        )
        return result

    def list_baselines(self) -> list[dict[str, Any]]:
        """
        List all baselines for this project.

        Returns:
            List of baseline metadata dictionaries (name, version, created_at, tags).
        """
        if not self._artifacts_bucket:
            logger.warning("No artifacts bucket configured")
            return []

        prefix = f"baselines/{self._project_id}/"
        baselines: list[dict[str, Any]] = []

        try:
            paginator = self._s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(
                Bucket=self._artifacts_bucket, Prefix=prefix
            ):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if key.endswith(".json"):
                        name = key.replace(prefix, "").replace(".json", "")
                        baseline = self._load_baseline(name)
                        if baseline:
                            baselines.append({
                                "name": baseline.name,
                                "version": baseline.version,
                                "created_at": baseline.created_at,
                                "description": baseline.description,
                                "tags": baseline.tags,
                            })
        except ClientError as e:
            logger.warning("Failed to list baselines: %s", e)

        return baselines

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _save_baseline(self, baseline: Baseline) -> None:
        """Save baseline to S3."""
        if not self._artifacts_bucket:
            logger.warning("No artifacts bucket configured, cannot save baseline")
            return

        key = f"baselines/{self._project_id}/{baseline.name}.json"
        try:
            self._s3.put_object(
                Bucket=self._artifacts_bucket,
                Key=key,
                Body=json.dumps(baseline.to_dict(), indent=2),
                ContentType="application/json",
            )
        except ClientError as e:
            logger.warning("Failed to save baseline to S3: %s", e)

    def _load_baseline(self, name: str) -> Baseline | None:
        """Load baseline from S3."""
        if not self._artifacts_bucket:
            return None

        key = f"baselines/{self._project_id}/{name}.json"
        try:
            response = self._s3.get_object(
                Bucket=self._artifacts_bucket, Key=key
            )
            data = json.loads(response["Body"].read().decode("utf-8"))
            return Baseline.from_dict(data)
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "NoSuchKey":
                return None
            logger.warning("Failed to load baseline '%s': %s", name, e)
            return None

    def _is_exact_match(self, expected: dict[str, Any], actual: dict[str, Any]) -> bool:
        """Check if two outputs are byte-for-byte identical when serialized."""
        return json.dumps(expected, sort_keys=True) == json.dumps(actual, sort_keys=True)

    def _compute_structural_similarity(
        self, expected: dict[str, Any], actual: dict[str, Any]
    ) -> float:
        """
        Compute structural similarity based on key overlap and value types.

        Measures how similar the structure (keys, nesting, types) is
        between expected and actual outputs.
        """
        expected_keys = self._extract_key_paths(expected)
        actual_keys = self._extract_key_paths(actual)

        if not expected_keys and not actual_keys:
            return 1.0
        if not expected_keys or not actual_keys:
            return 0.0

        intersection = expected_keys & actual_keys
        union = expected_keys | actual_keys

        key_similarity = len(intersection) / len(union) if union else 0.0

        # Also compare serialized structure for value-level similarity
        expected_str = json.dumps(expected, sort_keys=True)
        actual_str = json.dumps(actual, sort_keys=True)
        value_similarity = SequenceMatcher(None, expected_str, actual_str).ratio()

        # Weighted combination: structure matters more
        return key_similarity * 0.6 + value_similarity * 0.4

    def _compute_semantic_similarity(
        self, expected: dict[str, Any], actual: dict[str, Any]
    ) -> float:
        """
        Compute semantic similarity using text content comparison.

        Extracts all string values and compares them using sequence matching
        as a proxy for semantic equivalence.
        """
        expected_text = " ".join(self._extract_text_values(expected))
        actual_text = " ".join(self._extract_text_values(actual))

        if not expected_text and not actual_text:
            return 1.0
        if not expected_text or not actual_text:
            return 0.0

        return SequenceMatcher(None, expected_text, actual_text).ratio()

    def _compute_diff_summary(
        self, expected: dict[str, Any], actual: dict[str, Any]
    ) -> list[str]:
        """Generate a human-readable diff summary."""
        diffs: list[str] = []

        expected_keys = set(expected.keys())
        actual_keys = set(actual.keys())

        missing = expected_keys - actual_keys
        extra = actual_keys - expected_keys

        if missing:
            diffs.append(f"Missing keys: {', '.join(sorted(missing))}")
        if extra:
            diffs.append(f"Extra keys: {', '.join(sorted(extra))}")

        common = expected_keys & actual_keys
        for key in sorted(common):
            if expected[key] != actual[key]:
                exp_type = type(expected[key]).__name__
                act_type = type(actual[key]).__name__
                if exp_type != act_type:
                    diffs.append(f"Key '{key}': type changed {exp_type} -> {act_type}")
                else:
                    diffs.append(f"Key '{key}': value differs")

        return diffs[:20]  # Cap at 20 diff items

    def _extract_key_paths(self, obj: Any, prefix: str = "") -> set[str]:
        """Recursively extract all key paths from a nested dict."""
        paths: set[str] = set()
        if isinstance(obj, dict):
            for key, value in obj.items():
                path = f"{prefix}.{key}" if prefix else key
                paths.add(path)
                paths.update(self._extract_key_paths(value, path))
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                paths.update(self._extract_key_paths(item, f"{prefix}[{i}]"))
        return paths

    def _extract_text_values(self, obj: Any) -> list[str]:
        """Recursively extract all string values from a nested structure."""
        texts: list[str] = []
        if isinstance(obj, str):
            texts.append(obj)
        elif isinstance(obj, dict):
            for value in obj.values():
                texts.extend(self._extract_text_values(value))
        elif isinstance(obj, list):
            for item in obj:
                texts.extend(self._extract_text_values(item))
        return texts

    def _persist_result(self, result: BenchmarkResult) -> None:
        """Persist benchmark result to DynamoDB metrics table."""
        if not self._metrics_table:
            return

        table = self._dynamodb.Table(self._metrics_table)
        try:
            table.put_item(
                Item={
                    "project_id": self._project_id,
                    "metric_key": f"benchmark#{result.benchmark_name}#{result.timestamp}",
                    "metric_type": "benchmark",
                    "task_id": result.benchmark_name,
                    "recorded_at": result.timestamp,
                    "data": json.dumps({
                        "score": result.score,
                        "classification": result.classification,
                        "structural_similarity": result.structural_similarity,
                        "semantic_similarity": result.semantic_similarity,
                        "diff_summary": result.diff_summary,
                        "metadata": result.metadata,
                    }),
                }
            )
        except ClientError as e:
            logger.warning("Failed to persist benchmark result: %s", e)
