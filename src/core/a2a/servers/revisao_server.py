"""
A2A Quality Review Agent Server — Phase 4.

Exposes a Strands agent specialized in quality assessment and structured
feedback generation. Acts as the quality gate in the workflow graph,
deciding whether deliverables are approved or need rework.

Endpoint: http://revisao.fde.local:9003
Agent Card: http://revisao.fde.local:9003/.well-known/agent-card.json

Capabilities:
  - Technical quality assessment against defined criteria
  - Structured feedback with severity classification
  - Approval/rejection verdicts with confidence scoring
  - Output conforming to FeedbackRevisao schema
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

REVIEWER_SYSTEM_PROMPT = """You are a specialized Quality Review Agent within the FDE factory pipeline.

Your role is to assess technical deliverables and provide structured feedback.

## Output Contract

You MUST return a JSON object conforming to this schema:
{
  "veredicto": "APPROVED" | "NEEDS_REVISION" | "REJECTED",
  "score_qualidade": 0.0-1.0,
  "criticas": [
    {
      "categoria": "correctness|completeness|style|security",
      "severidade": "critical|major|minor|suggestion",
      "descricao": "string — description of the issue",
      "localizacao": "string — where in the deliverable",
      "sugestao_correcao": "string — suggested fix"
    }
  ],
  "pontos_positivos": ["string — positive aspects"],
  "recomendacoes": ["string — improvement recommendations"],
  "aprovado": true|false
}

## Verdict Rules

- APPROVED (score >= 0.8): No critical issues, minor issues acceptable
- NEEDS_REVISION (0.5 <= score < 0.8): Has major issues that must be fixed
- REJECTED (score < 0.5): Fundamental problems requiring complete rewrite

## Assessment Criteria

1. **Correctness**: Are facts accurate? Is code functional?
2. **Completeness**: Does it address all aspects of the input?
3. **Style**: Is it well-structured and readable?
4. **Security**: Are there security concerns in code artifacts?

## Rules

1. Be specific in criticisms — vague feedback is useless
2. Always suggest corrections for each criticism
3. Acknowledge positive aspects — balanced feedback
4. Score honestly — don't inflate or deflate
5. Critical issues MUST block approval regardless of other quality
6. On subsequent review attempts, check if previous feedback was addressed
"""


def create_review_server(
    host: str = "0.0.0.0",
    port: int = 9003,
    model_id: str | None = None,
):
    """Create and return the A2A review server instance.

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

        model = BedrockModel(
            model_id=_model_id,
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
            max_tokens=4096,
            temperature=0.2,  # Low temperature for consistent evaluation
        )

        review_agent = Agent(
            model=model,
            system_prompt=REVIEWER_SYSTEM_PROMPT,
            tools=[],  # Reviewer is pure reasoning — no tools needed
        )

        server = A2AServer(
            agent=review_agent,
            host=host,
            port=port,
            name="fde-review-agent",
            description="Specialized agent for quality assessment and structured feedback",
            version="1.0.0",
        )

        logger.info(
            "Review A2A Server configured: %s:%d model=%s",
            host, port, _model_id,
        )
        return server

    except ImportError as e:
        logger.error(
            "Failed to create review server — missing dependency: %s",
            str(e),
        )
        raise


def main():
    """Entrypoint for running the review server standalone."""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    port = int(os.environ.get("A2A_PORT", "9003"))
    logger.info("Starting Review A2A Server on port %d...", port)

    server = create_review_server(port=port)
    server.serve()


if __name__ == "__main__":
    main()
