"""
A2A Research Agent Server — Phase 1 (Reconnaissance).

Exposes a Strands agent specialized in data collection and research
via the A2A protocol. The agent uses Amazon Bedrock for reasoning
and http_request tools for external data gathering.

Endpoint: http://pesquisa.fde.local:9001
Agent Card: http://pesquisa.fde.local:9001/.well-known/agent-card.json

Capabilities:
  - Factual data collection from multiple sources
  - Structured output conforming to ConteudoBruto schema
  - Confidence scoring for research completeness
  - Source attribution and relevance ranking
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

RESEARCH_SYSTEM_PROMPT = """You are a specialized Research Agent within the FDE factory pipeline.

Your role is to collect, validate, and structure factual data for downstream agents.

## Output Contract

You MUST return a JSON object conforming to this schema:
{
  "topico": "string — the primary subject researched",
  "fatos_encontrados": ["string — list of factual findings"],
  "fontes": [{"url": "string", "title": "string", "relevance_score": 0.0-1.0}],
  "contexto_adicional": {},
  "confianca": 0.0-1.0
}

## Rules

1. Focus on FACTUAL data — no opinions or speculation
2. Always cite sources with URLs when available
3. Score your confidence honestly (0.8+ means high confidence)
4. If data is insufficient, say so in fatos_encontrados
5. Structure findings as discrete, atomic facts
6. Include at least 3 distinct data points per research query
7. Prioritize official documentation and primary sources

## Quality Criteria

- Completeness: Cover all aspects of the query
- Accuracy: Only include verified information
- Relevance: Filter out tangential information
- Structure: Each fact should be self-contained and clear
"""


def create_research_server(
    host: str = "0.0.0.0",
    port: int = 9001,
    model_id: str | None = None,
):
    """Create and return the A2A research server instance.

    Args:
        host: Bind address (0.0.0.0 for container deployment).
        port: Port to listen on.
        model_id: Bedrock model ID override.

    Returns:
        Configured A2AServer instance (call .serve() to start).
    """
    _model_id = model_id or os.environ.get(
        "BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    )

    try:
        from strands import Agent
        from strands.models.bedrock import BedrockModel
        from strands.a2a import A2AServer

        # Configure Bedrock model with appropriate parameters
        model = BedrockModel(
            model_id=_model_id,
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
            max_tokens=4096,
            temperature=0.3,  # Low temperature for factual research
        )

        # Build the research agent with tools
        tools = _get_research_tools()
        research_agent = Agent(
            model=model,
            system_prompt=RESEARCH_SYSTEM_PROMPT,
            tools=tools,
        )

        # Wrap in A2A Server
        server = A2AServer(
            agent=research_agent,
            host=host,
            port=port,
            name="fde-research-agent",
            description="Specialized agent for factual data collection and research",
            version="1.0.0",
        )

        logger.info(
            "Research A2A Server configured: %s:%d model=%s",
            host, port, _model_id,
        )
        return server

    except ImportError as e:
        logger.error(
            "Failed to create research server — missing dependency: %s. "
            "Install with: pip install strands-agents[a2a]",
            str(e),
        )
        raise


def _get_research_tools() -> list:
    """Load research-specific tools for the agent.

    Returns tools available in the Strands ecosystem for research tasks.
    Falls back to empty list if tools are not available.
    """
    tools = []

    try:
        from strands_tools import http_request
        tools.append(http_request)
    except ImportError:
        logger.warning("http_request tool not available")

    try:
        from strands_tools import retrieve
        tools.append(retrieve)
    except ImportError:
        pass  # Optional: RAG retrieval tool

    return tools


def main():
    """Entrypoint for running the research server standalone."""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    port = int(os.environ.get("A2A_PORT", "9001"))
    logger.info("Starting Research A2A Server on port %d...", port)

    server = create_research_server(port=port)
    server.serve()


if __name__ == "__main__":
    main()
