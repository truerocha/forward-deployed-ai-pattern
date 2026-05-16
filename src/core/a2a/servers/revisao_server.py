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
  "verdict": "APPROVED" | "NEEDS_REVISION" | "REJECTED",
  "quality_score": 0.0-1.0,
  "criticisms": [
    {
      "categoria": "correctness|completeness|style|security",
      "severidade": "critical|major|minor|suggestion",
      "descricao": "string — description of the issue",
      "localizacao": "string — where in the deliverable",
      "sugestao_correcao": "string — suggested fix"
    }
  ],
  "positive_points": ["string — positive aspects"],
  "recomendacoes": ["string — improvement recommendations"],
  "approved": true|false
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

    Initializes distributed tracing and registers the explicit Agent Card
    with full JSON Schema contracts for input/output validation.

    Args:
        host: Bind address (0.0.0.0 for container deployment).
        port: Port to listen on.
        model_id: Bedrock model ID override.

    Returns:
        Configured A2AServer instance (call .serve() to start).
    """
    from src.core.a2a.agent_cards import REVISAO_CARD
    from src.core.a2a.observability import initialize_tracing

    # Initialize distributed tracing (OTel → ADOT → X-Ray)
    initialize_tracing(
        service_name="fde-a2a-revisao",
        environment=os.environ.get("ENVIRONMENT", "dev"),
    )

    _model_id = model_id or os.environ.get(
        "BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    )

    try:
        from strands import Agent
        from strands.models.bedrock import BedrockModel
        from strands.multiagent.a2a import A2AServer

        model = BedrockModel(
            model_id=_model_id,
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
            max_tokens=4096,
            temperature=0.2,  # Low temperature for consistent evaluation
        )

        # Session manager for iterative review memory.
        # Enables the reviewer to recall its own prior feedback within
        # the same workflow's review cycle (max 3 iterations).
        # Uses S3 with workflow-scoped session IDs for distributed safety.
        session_manager = _build_session_manager()

        review_agent = Agent(
            model=model,
            system_prompt=REVIEWER_SYSTEM_PROMPT,
            tools=[],  # Reviewer is pure reasoning — no tools needed
            name=REVISAO_CARD["name"],
            description=REVISAO_CARD["description"],
            session_manager=session_manager,
        )

        # Wrap in A2A Server
        server = A2AServer(
            agent=review_agent,
            host=host,
            port=port,
            version=REVISAO_CARD["version"],
        )

        logger.info(
            "Review A2A Server configured: %s:%d model=%s card=%s session=%s",
            host, port, _model_id, REVISAO_CARD["name"],
            "s3" if session_manager else "none",
        )
        return server

    except ImportError as e:
        logger.error(
            "Failed to create review server — missing dependency: %s",
            str(e),
        )
        raise


def _build_session_manager():
    """Build an S3SessionManager for iterative review memory.

    The session manager persists conversation history in S3, enabling
    the review agent to recall its prior feedback across iterations
    within the same workflow. This avoids re-sending full feedback
    history in the payload (complementary to context_compressor).

    Session isolation:
      - Bucket: fde-{env}-artifacts (existing bucket from infra)
      - Prefix: a2a-sessions/revisao/
      - Session ID: Set per-request by the orchestrator via workflow_id

    Falls back to None (stateless) if S3SessionManager is not available
    or if the S3 bucket is not configured.

    Returns:
        S3SessionManager instance or None.
    """
    bucket = os.environ.get("A2A_SESSIONS_BUCKET", "")
    if not bucket:
        logger.info("A2A_SESSIONS_BUCKET not set — review agent will be stateless")
        return None

    try:
        from strands.session.s3_session_manager import S3SessionManager
        import boto3

        session_mgr = S3SessionManager(
            bucket_name=bucket,
            prefix="a2a-sessions/revisao/",
            s3_client=boto3.client(
                "s3",
                region_name=os.environ.get("AWS_REGION", "us-east-1"),
            ),
        )
        logger.info(
            "S3SessionManager configured for review agent: bucket=%s prefix=a2a-sessions/revisao/",
            bucket,
        )
        return session_mgr

    except ImportError:
        logger.warning(
            "strands.session.s3_session_manager not available — review agent will be stateless"
        )
        return None
    except Exception as e:
        logger.warning(
            "Failed to initialize S3SessionManager (non-blocking): %s", str(e)[:100]
        )
        return None


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
