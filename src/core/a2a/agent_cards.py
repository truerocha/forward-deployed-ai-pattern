"""
A2A Agent Cards — JSON Schema Manifests for Service Discovery.

Each A2A agent exposes a card at /.well-known/agent-card.json describing:
  - Identity (name, version, description)
  - Capabilities (input/output schemas, supported tasks)
  - Endpoint metadata (URL, authentication, rate limits)

The Strands A2AServer auto-generates a basic card, but this module provides
EXPLICIT cards with full Pydantic JSON Schema integration. This ensures:
  - Clients can validate payloads BEFORE sending (fail-fast)
  - The orchestrator can route tasks based on declared capabilities
  - The Conductor (ADR-020) can compose squads from card metadata

Design:
  - Cards are generated from Pydantic models at import time (zero runtime cost)
  - Each server imports its card and passes it to A2AServer(agent_card=...)
  - Cards include the full JSON Schema for input AND output contracts

Ref: ADR-034 (A2A Protocol), ADR-019 (Agentic Squad Architecture)
     Google A2A Spec: /.well-known/agent.json
"""

from __future__ import annotations

from typing import Any

from src.core.a2a.contracts import (
    RawContent,
    ReviewFeedback,
    FinalReport,
    TaskPayload,
    # Backward-compatible aliases
    ConteudoBruto,
    FeedbackRevisao,
    RelatorioFinal,
)


def _build_card(
    name: str,
    description: str,
    version: str,
    endpoint: str,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
    capabilities: list[str],
    model_tier: str = "standard",
    temperature: float = 0.5,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """Build a compliant A2A Agent Card.

    Follows the Google A2A specification with FDE extensions for
    squad composition metadata.

    Args:
        name: Agent identifier (used in Cloud Map registration).
        description: Human-readable description of capabilities.
        version: Semantic version of the agent.
        endpoint: Base URL (Cloud Map DNS or localhost).
        input_schema: JSON Schema for accepted input payloads.
        output_schema: JSON Schema for guaranteed output format.
        capabilities: List of task types this agent can handle.
        model_tier: Bedrock model tier (fast/standard/reasoning/deep).
        temperature: Default temperature for this agent's model.
        max_tokens: Maximum output tokens.

    Returns:
        Complete Agent Card dictionary (JSON-serializable).
    """
    return {
        "name": name,
        "description": description,
        "version": version,
        "url": endpoint,
        "protocol": "a2a",
        "protocol_version": "1.0",
        "capabilities": {
            "tasks": capabilities,
            "streaming": True,
            "push_notifications": False,
        },
        "input_schema": input_schema,
        "output_schema": output_schema,
        "authentication": {
            "type": "none",  # Internal VPC — no auth needed (Cloud Map)
        },
        "rate_limits": {
            "requests_per_minute": 60,
            "concurrent_tasks": 5,
        },
        # FDE Extensions (used by Conductor for squad composition)
        "x-fde": {
            "model_tier": model_tier,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "squad_role": name.replace("fde-", "").replace("-agent", ""),
            "cost_weight": _cost_weight_for_tier(model_tier),
        },
    }


def _cost_weight_for_tier(tier: str) -> float:
    """Map model tier to cost weight for budget estimation."""
    return {
        "fast": 0.3,
        "standard": 0.5,
        "reasoning": 1.0,
        "deep": 1.5,
    }.get(tier, 0.5)


# ─── Pesquisa (Research) Agent Card ──────────────────────────────────────────

PESQUISA_CARD = _build_card(
    name="fde-research-agent",
    description=(
        "Specialized agent for factual data collection and research. "
        "Collects structured data from multiple sources with confidence scoring "
        "and source attribution."
    ),
    version="1.0.0",
    endpoint="http://pesquisa.fde.local:9001",
    input_schema=TaskPayload.model_json_schema(),
    output_schema=RawContent.model_json_schema(),
    capabilities=[
        "factual_research",
        "source_attribution",
        "confidence_scoring",
        "multi_source_collection",
    ],
    model_tier="standard",
    temperature=0.3,
    max_tokens=4096,
)


# ─── Escrita (Engineering/Writing) Agent Card ────────────────────────────────

ESCRITA_CARD = _build_card(
    name="fde-engineering-agent",
    description=(
        "Specialized agent for technical document and code generation. "
        "Produces structured deliverables from research data with iterative "
        "rework capability based on reviewer feedback."
    ),
    version="1.0.0",
    endpoint="http://escrita.fde.local:9002",
    input_schema=TaskPayload.model_json_schema(),
    output_schema=FinalReport.model_json_schema(),
    capabilities=[
        "document_generation",
        "code_generation",
        "iterative_rework",
        "structured_output",
    ],
    model_tier="standard",
    temperature=0.5,
    max_tokens=8192,
)


# ─── Revisão (Review) Agent Card ────────────────────────────────────────────

REVISAO_CARD = _build_card(
    name="fde-review-agent",
    description=(
        "Specialized agent for quality assessment and structured feedback. "
        "Evaluates technical deliverables against defined criteria and produces "
        "approval/rejection verdicts with actionable feedback."
    ),
    version="1.0.0",
    endpoint="http://revisao.fde.local:9003",
    input_schema=TaskPayload.model_json_schema(),
    output_schema=ReviewFeedback.model_json_schema(),
    capabilities=[
        "quality_assessment",
        "structured_feedback",
        "approval_verdicts",
        "security_review",
    ],
    model_tier="standard",
    temperature=0.2,
    max_tokens=4096,
)


# ─── Registry (all cards indexed by name) ────────────────────────────────────

AGENT_CARD_REGISTRY: dict[str, dict[str, Any]] = {
    "fde-research-agent": PESQUISA_CARD,
    "fde-engineering-agent": ESCRITA_CARD,
    "fde-review-agent": REVISAO_CARD,
}


def get_card(agent_name: str) -> dict[str, Any] | None:
    """Retrieve an agent card by name.

    Args:
        agent_name: The agent identifier (e.g., "fde-research-agent").

    Returns:
        Agent card dict or None if not found.
    """
    return AGENT_CARD_REGISTRY.get(agent_name)


def list_cards() -> list[dict[str, Any]]:
    """List all registered agent cards.

    Used by the Conductor to discover available A2A agents
    for squad composition.

    Returns:
        List of all agent card dicts.
    """
    return list(AGENT_CARD_REGISTRY.values())
