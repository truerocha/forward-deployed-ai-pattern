"""
A2A Engineering/Writing Agent Server — Phases 2-3.

Exposes a Strands agent specialized in producing structured technical
deliverables from research data. Supports both initial generation and
iterative rework based on reviewer feedback.

Endpoint: http://escrita.fde.local:9002
Agent Card: http://escrita.fde.local:9002/.well-known/agent-card.json

Capabilities:
  - Technical document generation from structured research data
  - Code artifact production with quality metrics
  - Iterative rework based on structured feedback
  - Output conforming to RelatorioFinal schema
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

ENGINEERING_SYSTEM_PROMPT = """You are a specialized Engineering/Writing Agent within the FDE factory pipeline.

Your role is to produce high-quality technical deliverables from research data.

## Output Contract

You MUST return a JSON object conforming to this schema:
{
  "title": "string — title of the deliverable",
  "introduction": "string — executive summary",
  "analysis_body": "string — main body of analysis or implementation",
  "conclusion": "string — conclusions and next steps",
  "references": ["string — references used"],
  "artifacts": [{"path": "string", "content_hash": "", "language": "", "lines_added": 0}],
  "approved": false,
  "metricas": {}
}

## Rules

1. Structure output clearly with sections
2. Be thorough but concise — no filler content
3. Include actionable conclusions
4. Reference source data explicitly
5. When producing code artifacts, follow best practices for the target language
6. On REWORK tasks, address ALL feedback points from the reviewer

## Rework Mode

When you receive a payload with "feedback" and "relatorio_anterior":
- This is a REWORK request — you must improve the previous deliverable
- Address every criticism in the feedback
- Preserve positive aspects noted by the reviewer
- Explain what changed in the introducao section

## Quality Criteria

- Completeness: Address all aspects of the input data
- Clarity: Technical but accessible writing
- Actionability: Conclusions must be implementable
- Traceability: Every claim must trace back to research data
"""


def create_writing_server(
    host: str = "0.0.0.0",
    port: int = 9002,
    model_id: str | None = None,
):
    """Create and return the A2A writing server instance.

    Initializes distributed tracing and registers the explicit Agent Card
    with full JSON Schema contracts for input/output validation.

    Args:
        host: Bind address (0.0.0.0 for container deployment).
        port: Port to listen on.
        model_id: Bedrock model ID override.

    Returns:
        Configured A2AServer instance (call .serve() to start).
    """
    from src.core.a2a.agent_cards import ESCRITA_CARD
    from src.core.a2a.observability import initialize_tracing

    # Initialize distributed tracing (OTel → ADOT → X-Ray)
    initialize_tracing(
        service_name="fde-a2a-escrita",
        environment=os.environ.get("ENVIRONMENT", "dev"),
    )

    _model_id = model_id or os.environ.get(
        "BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    )

    try:
        from strands import Agent
        from strands.models.bedrock import BedrockModel
        from strands.a2a import A2AServer

        model = BedrockModel(
            model_id=_model_id,
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
            max_tokens=8192,  # Higher limit for document generation
            temperature=0.5,  # Balanced creativity for writing
        )

        tools = _get_writing_tools()
        writing_agent = Agent(
            model=model,
            system_prompt=ENGINEERING_SYSTEM_PROMPT,
            tools=tools,
        )

        # Wrap in A2A Server with explicit Agent Card
        server = A2AServer(
            agent=writing_agent,
            host=host,
            port=port,
            name=ESCRITA_CARD["name"],
            description=ESCRITA_CARD["description"],
            version=ESCRITA_CARD["version"],
        )

        logger.info(
            "Engineering A2A Server configured: %s:%d model=%s card=%s",
            host, port, _model_id, ESCRITA_CARD["name"],
        )
        return server

    except ImportError as e:
        logger.error(
            "Failed to create writing server — missing dependency: %s",
            str(e),
        )
        raise


def _get_writing_tools() -> list:
    """Load writing-specific tools."""
    tools = []

    try:
        from strands_tools import editor
        tools.append(editor)
    except ImportError:
        pass

    try:
        from strands_tools import file_write
        tools.append(file_write)
    except ImportError:
        pass

    return tools


def main():
    """Entrypoint for running the writing server standalone."""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    port = int(os.environ.get("A2A_PORT", "9002"))
    logger.info("Starting Engineering A2A Server on port %d...", port)

    server = create_writing_server(port=port)
    server.serve()


if __name__ == "__main__":
    main()
