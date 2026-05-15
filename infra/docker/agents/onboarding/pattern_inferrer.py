"""
Pattern Inferrer — Uses Claude Haiku via Bedrock to infer high-level patterns
that cannot be extracted deterministically: pipeline chain, module boundaries,
and engineering level patterns.

Design ref: §3.6 Pattern Inferrer (Claude Haiku)
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import boto3
from botocore.config import Config

logger = logging.getLogger("fde-onboarding.pattern_inferrer")

# Model configuration (REQ-3.5: cost control)
# Uses inference profile (required for on-demand invocation of newer models)
MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
MAX_INPUT_TOKENS = 8192
MAX_OUTPUT_TOKENS = 2048
MAX_RETRIES = 2

# Cost rates (Haiku pricing)
INPUT_COST_PER_MTOK = 0.25
OUTPUT_COST_PER_MTOK = 1.25
COST_CEILING = 0.01


@dataclass
class PipelineStep:
    """A step in the inferred pipeline chain."""

    step_order: int
    module_name: str
    produces: str
    consumes: str


@dataclass
class ModuleBoundary:
    """A producer/consumer edge where data transforms."""

    edge_id: str
    producer: str
    consumer: str
    transform_description: str


@dataclass
class TechStackTag:
    """A technology tag with category and confidence."""

    tag: str
    category: str  # language | framework | cloud | infra
    confidence: float = 1.0


@dataclass
class LevelPattern:
    """A task pattern indicating engineering complexity level."""

    pattern: str
    level: str  # L2 | L3 | L4
    description: str


@dataclass
class InferenceResult:
    """Aggregate result of pattern inference."""

    pipeline_chain: list[PipelineStep]
    module_boundaries: list[ModuleBoundary]
    tech_stack: list[TechStackTag]
    level_patterns: list[LevelPattern]
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0


INFERENCE_PROMPT = """You are analyzing a codebase structure. Given the dependency graph summary, file type distribution, and conventions, produce:

1. pipeline_chain: The main data/execution flow as ordered steps.
   Format: [{"step_order": 1, "module_name": "...", "produces": "...", "consumes": "..."}]

2. module_boundaries: Producer/consumer edges where data transforms.
   Format: [{"edge_id": "E1", "producer": "...", "consumer": "...", "transform_description": "..."}]

3. tech_stack: Technology tags with categories.
   Format: [{"tag": "Python", "category": "language", "confidence": 0.95}]

4. level_patterns: Task patterns indicating engineering complexity.
   Format: [{"pattern": "bugfix", "level": "L2", "description": "..."}, {"pattern": "new-module", "level": "L3", "description": "..."}, {"pattern": "architecture-change", "level": "L4", "description": "..."}]

Respond in JSON only. No explanation. The JSON must have exactly these four top-level keys: pipeline_chain, module_boundaries, tech_stack, level_patterns."""


def infer_patterns(
    dependency_summary: dict[str, Any],
    file_type_distribution: dict[str, int],
    conventions: list[str],
    entry_points: list[str],
    directory_structure: list[str],
    aws_region: str = "us-east-1",
) -> InferenceResult:
    """
    Send structured summary to Haiku and receive inferred patterns.

    Args:
        dependency_summary: Graph summary (total_modules, top fan-out/in, longest chain).
        file_type_distribution: Language → file count mapping.
        conventions: List of detected convention names.
        entry_points: Detected entry point files.
        directory_structure: Top-level directory listing (depth 2).
        aws_region: AWS region for Bedrock.

    Returns:
        InferenceResult with all inferred patterns and cost tracking.
    """
    start = time.time()

    # Build structured input (never raw source code — REQ-3.5)
    structured_input = json.dumps({
        "dependency_graph_summary": dependency_summary,
        "file_type_distribution": file_type_distribution,
        "conventions": conventions,
        "entry_points": entry_points,
        "directory_structure_depth_2": directory_structure,
    }, indent=2)

    full_prompt = f"{INFERENCE_PROMPT}\n\nCodebase summary:\n```json\n{structured_input}\n```"

    # Invoke Haiku via Bedrock
    response_text, input_tokens, output_tokens = _invoke_haiku(full_prompt, aws_region)

    # Parse response
    result = _parse_response(response_text)

    # Calculate cost
    cost_usd = (
        (input_tokens / 1_000_000) * INPUT_COST_PER_MTOK
        + (output_tokens / 1_000_000) * OUTPUT_COST_PER_MTOK
    )

    if cost_usd > COST_CEILING:
        logger.warning("LLM cost ($%.4f) exceeded ceiling ($%.2f)", cost_usd, COST_CEILING)

    duration_ms = int((time.time() - start) * 1000)

    logger.info(
        "Pattern inference complete: %d pipeline steps, %d boundaries, "
        "%d tech tags, %d level patterns (cost=$%.4f, %dms)",
        len(result.pipeline_chain),
        len(result.module_boundaries),
        len(result.tech_stack),
        len(result.level_patterns),
        cost_usd,
        duration_ms,
    )

    result.input_tokens = input_tokens
    result.output_tokens = output_tokens
    result.cost_usd = cost_usd
    result.duration_ms = duration_ms

    return result


def _invoke_haiku(prompt: str, aws_region: str) -> tuple[str, int, int]:
    """
    Invoke Claude Haiku via Bedrock with retry logic.

    Returns:
        Tuple of (response_text, input_tokens, output_tokens).
    """
    client = boto3.client("bedrock-runtime", region_name=aws_region,
                          config=Config(
                              retries={"max_attempts": 5, "mode": "adaptive"},
                              max_pool_connections=25,
                              connect_timeout=30,
                              read_timeout=120,
                          ))

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.invoke_model(
                modelId=MODEL_ID,
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": MAX_OUTPUT_TOKENS,
                    "messages": [{"role": "user", "content": prompt}],
                }),
            )

            body = json.loads(response["body"].read())
            text = body["content"][0]["text"]
            usage = body.get("usage", {})
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)

            return text, input_tokens, output_tokens

        except Exception as e:
            if attempt < MAX_RETRIES:
                logger.warning(
                    "Haiku invocation failed (attempt %d/%d): %s",
                    attempt + 1, MAX_RETRIES + 1, e,
                )
                time.sleep(1)
            else:
                raise RuntimeError(
                    f"Haiku invocation failed after {MAX_RETRIES + 1} attempts: {e}"
                ) from e

    raise RuntimeError("Unexpected: all retries exhausted")


def _parse_response(response_text: str) -> InferenceResult:
    """Parse the JSON response from Haiku into structured result."""
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse Haiku response as JSON: %s", e)
        return InferenceResult(
            pipeline_chain=[], module_boundaries=[],
            tech_stack=[], level_patterns=[],
        )

    pipeline_chain = [
        PipelineStep(
            step_order=step.get("step_order", i + 1),
            module_name=step.get("module_name", ""),
            produces=step.get("produces", ""),
            consumes=step.get("consumes", ""),
        )
        for i, step in enumerate(data.get("pipeline_chain", []))
    ]

    module_boundaries = [
        ModuleBoundary(
            edge_id=boundary.get("edge_id", f"E{i + 1}"),
            producer=boundary.get("producer", ""),
            consumer=boundary.get("consumer", ""),
            transform_description=boundary.get("transform_description", ""),
        )
        for i, boundary in enumerate(data.get("module_boundaries", []))
    ]

    tech_stack = [
        TechStackTag(
            tag=tag.get("tag", ""),
            category=tag.get("category", "unknown"),
            confidence=tag.get("confidence", 1.0),
        )
        for tag in data.get("tech_stack", [])
    ]

    level_patterns = [
        LevelPattern(
            pattern=pat.get("pattern", ""),
            level=pat.get("level", "L3"),
            description=pat.get("description", ""),
        )
        for pat in data.get("level_patterns", [])
    ]

    return InferenceResult(
        pipeline_chain=pipeline_chain,
        module_boundaries=module_boundaries,
        tech_stack=tech_stack,
        level_patterns=level_patterns,
    )


def build_dependency_summary(
    modules: list,
    edges: list,
) -> dict[str, Any]:
    """
    Build a structured dependency summary for the LLM input.

    Keeps input compact (within 8K token budget) while providing
    enough signal for pattern inference.
    """
    fan_out: dict[str, int] = {}
    fan_in: dict[str, int] = {}

    for edge in edges:
        source = edge.source_module if hasattr(edge, "source_module") else edge.get("source_module", "")
        target = edge.target_module if hasattr(edge, "target_module") else edge.get("target_module", "")
        fan_out[source] = fan_out.get(source, 0) + 1
        fan_in[target] = fan_in.get(target, 0) + 1

    top_fan_out = sorted(fan_out.items(), key=lambda x: x[1], reverse=True)[:10]
    top_fan_in = sorted(fan_in.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "total_modules": len(modules),
        "total_edges": len(edges),
        "top_modules_by_fan_out": [{"module": m, "count": c} for m, c in top_fan_out],
        "top_modules_by_fan_in": [{"module": m, "count": c} for m, c in top_fan_in],
    }
