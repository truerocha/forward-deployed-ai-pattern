"""
Spec Complexity Classifier — Textual classification of task execution complexity.

Classifies spec_content into complexity levels based on structural indicators
present in the text. This runs at Lambda time (webhook_ingest) BEFORE the
container starts, enabling routing decisions without repo access.

Classification levels:
  - "simple": No execution indicators. Standard code generation task.
  - "standard": Some structure but no multi-step execution. Normal pipeline.
  - "execution": Multi-step execution with scripts, gates, and sequential deps.
    Requires the Execution Readiness Pipeline (ERP) for proper handling.

Design decisions:
  - Textual only — no repo access needed (Lambda has ~200ms budget)
  - Threshold: 3+ indicators → "execution" (tunable via EXECUTION_THRESHOLD)
  - Indicators are regex-based, not LLM-based (deterministic, fast)
  - Returns both the classification and the matched indicators (observability)

Ref: Issue #146 (class of failure: execution tasks treated as simple)
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Minimum number of indicators to classify as "execution"
EXECUTION_THRESHOLD = 3

# Indicators that suggest the task requires multi-step execution
EXECUTION_INDICATORS: dict[str, str] = {
    "bash_commands": r"```bash\s*\n",
    "pytest_execution": r"pytest\s+\S+",
    "artifact_generation": r"git\s+add\s+\S+",
    "sequential_gates": r"\*\*Gate\*\*\s*:",
    "multi_part": r"###\s+Part\s+[A-Z]",
    "script_execution": r"python3?\s+scripts/",
    "dependency_chain": r"[A-Z]\d+.*→.*[A-Z]\d+|then\s+[A-Z]\d+",
    "step_numbering": r"####\s+[A-Z]\d+[\.\s:]",
    "validation_markers": r"\*\*(?:Validation|Verify|Assert)\*\*\s*:",
    "file_generation": r"(?:generate|create|write)\s+(?:artifacts?|files?)/",
}

# Indicators that suggest standard complexity (some structure, not execution)
STANDARD_INDICATORS: dict[str, str] = {
    "acceptance_criteria": r"(?:acceptance|done)\s*(?:criteria|when)",
    "code_blocks": r"```(?:python|typescript|java|go)",
    "api_references": r"(?:endpoint|route|handler|controller)",
    "test_references": r"(?:unit test|integration test|test case)",
}


@dataclass
class ClassificationResult:
    """Result of spec complexity classification."""

    complexity: str  # "simple" | "standard" | "execution"
    indicator_count: int = 0
    matched_indicators: list[str] = field(default_factory=list)
    confidence: float = 0.0  # 0.0-1.0

    def to_dict(self) -> dict:
        return {
            "complexity": self.complexity,
            "indicator_count": self.indicator_count,
            "matched_indicators": self.matched_indicators,
            "confidence": round(self.confidence, 3),
        }


def classify_spec_complexity(spec_content: str) -> ClassificationResult:
    """Classify the execution complexity of a spec_content string.

    This is the primary entry point, designed to be called from the
    webhook_ingest Lambda at routing time.

    Args:
        spec_content: The full spec/issue body text.

    Returns:
        ClassificationResult with complexity level and matched indicators.
    """
    if not spec_content:
        return ClassificationResult(complexity="simple", confidence=0.9)

    # Count execution indicators
    matched_execution = []
    for name, pattern in EXECUTION_INDICATORS.items():
        if re.search(pattern, spec_content, re.IGNORECASE):
            matched_execution.append(name)

    execution_count = len(matched_execution)

    # Count standard indicators
    matched_standard = []
    for name, pattern in STANDARD_INDICATORS.items():
        if re.search(pattern, spec_content, re.IGNORECASE):
            matched_standard.append(name)

    standard_count = len(matched_standard)

    # Classification logic
    if execution_count >= EXECUTION_THRESHOLD:
        # Strong execution signal — multi-step task
        confidence = min(1.0, 0.6 + (execution_count - EXECUTION_THRESHOLD) * 0.1)
        result = ClassificationResult(
            complexity="execution",
            indicator_count=execution_count,
            matched_indicators=matched_execution,
            confidence=confidence,
        )
    elif execution_count >= 1 or standard_count >= 2:
        # Some structure but not enough for execution pipeline
        confidence = 0.5 + standard_count * 0.1
        result = ClassificationResult(
            complexity="standard",
            indicator_count=execution_count + standard_count,
            matched_indicators=matched_execution + matched_standard,
            confidence=min(1.0, confidence),
        )
    else:
        # No structural indicators — simple task
        result = ClassificationResult(
            complexity="simple",
            indicator_count=0,
            matched_indicators=[],
            confidence=0.8,
        )

    logger.info(
        "Spec complexity: %s (indicators=%d, matched=%s, confidence=%.2f)",
        result.complexity, result.indicator_count,
        result.matched_indicators, result.confidence,
    )

    return result
