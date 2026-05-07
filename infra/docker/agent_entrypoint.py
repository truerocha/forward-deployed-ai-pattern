"""
Forward Deployed Engineer — Strands Agent Entrypoint for ECS Fargate.

Wires together: Registry + Router + Constraint Extractor + Agent Builder + Orchestrator.

Pipeline on every InProgress event:
  Router → Constraint Extractor → DoR Gate → Agent Builder → Execute

Modes:
1. EVENTBRIDGE_EVENT env var → parse event, route, extract constraints, build agents, execute
2. TASK_SPEC env var → direct spec execution (still runs constraint extraction)
3. Neither → log instructions and exit
"""

import json
import logging
import os
import sys

import boto3
from botocore.exceptions import ClientError

from agents.agent_builder import AgentBuilder
from agents.constraint_extractor import ConstraintExtractor
from agents.registry import AgentRegistry, AgentDefinition
from agents.router import AgentRouter
from agents.orchestrator import Orchestrator
from agents.prompts import RECONNAISSANCE_PROMPT, ENGINEERING_PROMPT, REPORTING_PROMPT
from agents.tools import RECON_TOOLS, ENGINEERING_TOOLS, REPORTING_TOOLS, read_spec

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fde-entrypoint")

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-sonnet-4-5-20250929-v1:0")
FACTORY_BUCKET = os.environ.get("FACTORY_BUCKET", "")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")


def _build_llm_invoke_fn():
    """Build an LLM invocation function for the Constraint Extractor.

    Uses Bedrock directly (not a Strands agent) for structured extraction.
    Returns None if Bedrock is not available, falling back to rule-based only.
    """
    try:
        bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

        def invoke(prompt: str) -> str:
            response = bedrock.invoke_model(
                modelId=BEDROCK_MODEL_ID,
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 4096,
                    "messages": [{"role": "user", "content": prompt}],
                }),
            )
            body = json.loads(response["body"].read())
            return body["content"][0]["text"]

        logger.info("LLM invoke function ready (model: %s)", BEDROCK_MODEL_ID)
        return invoke
    except Exception as e:
        logger.warning("Bedrock not available for constraint extraction, using rule-based only: %s", e)
        return None


def build_registry() -> AgentRegistry:
    """Build the agent registry with base agent definitions.

    These base agents are used as fallbacks when the Agent Builder
    doesn't find a specialized prompt in the Prompt Registry.
    """
    registry = AgentRegistry(default_model_id=BEDROCK_MODEL_ID, aws_region=AWS_REGION)
    registry.register(AgentDefinition(
        name="reconnaissance", system_prompt=RECONNAISSANCE_PROMPT,
        tools=RECON_TOOLS, description="Phase 1: Reads spec, maps modules, produces intake contract",
    ))
    registry.register(AgentDefinition(
        name="engineering", system_prompt=ENGINEERING_PROMPT,
        tools=ENGINEERING_TOOLS, description="Phases 2-3: Reformulates task, executes engineering recipe",
    ))
    registry.register(AgentDefinition(
        name="reporting", system_prompt=REPORTING_PROMPT,
        tools=REPORTING_TOOLS, description="Phase 4: Writes completion report, updates ALM",
    ))
    return registry


def validate_environment() -> list[str]:
    issues = []
    if not FACTORY_BUCKET:
        issues.append("FACTORY_BUCKET not set")
    # ALM tokens are no longer validated at startup (ADR-014).
    # They are fetched from Secrets Manager at tool invocation time.
    # This prevents token values from being visible in the container env.
    if FACTORY_BUCKET:
        try:
            boto3.client("s3", region_name=AWS_REGION).head_bucket(Bucket=FACTORY_BUCKET)
        except ClientError as e:
            issues.append(f"S3 bucket not accessible: {FACTORY_BUCKET} — {e}")
    return issues


def main():
    logger.info("FDE Strands Agent starting...")
    logger.info("Region: %s | Model: %s | Bucket: %s | Env: %s", AWS_REGION, BEDROCK_MODEL_ID, FACTORY_BUCKET, ENVIRONMENT)

    issues = validate_environment()
    if issues:
        for issue in issues:
            logger.error("Environment issue: %s", issue)
        sys.exit(1)

    # Build all components
    registry = build_registry()
    router = AgentRouter()

    # Constraint Extractor with optional LLM support
    llm_fn = _build_llm_invoke_fn()
    constraint_extractor = ConstraintExtractor(llm_invoke_fn=llm_fn)

    # Agent Builder reads from Prompt Registry + data contract
    agent_builder = AgentBuilder(registry)

    # Orchestrator wires everything together
    orchestrator = Orchestrator(
        registry=registry,
        router=router,
        factory_bucket=FACTORY_BUCKET,
        constraint_extractor=constraint_extractor,
        agent_builder=agent_builder,
    )

    logger.info(
        "Application ready: %d base agents [%s], constraint extractor=%s",
        len(registry.list_agents()),
        ", ".join(registry.list_agents()),
        "LLM+rules" if llm_fn else "rules-only",
    )

    eventbridge_event = os.environ.get("EVENTBRIDGE_EVENT", "")
    task_spec_path = os.environ.get("TASK_SPEC", "")

    # Support flat env vars from EventBridge InputTransformer (COE-011 fix).
    # ECS targets cannot reliably pass complex JSON via InputTransformer,
    # so we extract individual fields and reconstruct the event here.
    event_source = os.environ.get("EVENT_SOURCE", "")
    event_action = os.environ.get("EVENT_ACTION", "")

    if eventbridge_event:
        logger.info("Mode: EventBridge event (EVENTBRIDGE_EVENT)")
        result = orchestrator.handle_event(json.loads(eventbridge_event))
        logger.info("Result: %s", json.dumps(result, default=str))
    elif event_source and event_action:
        logger.info("Mode: EventBridge event (flat env vars)")
        reconstructed_event = {
            "source": event_source,
            "detail-type": os.environ.get("EVENT_DETAIL_TYPE", ""),
            "detail": {
                "action": event_action,
                "label": {"name": os.environ.get("EVENT_LABEL", "")},
                "issue": {
                    "number": int(os.environ.get("EVENT_ISSUE_NUMBER", "0") or "0"),
                    "title": os.environ.get("EVENT_ISSUE_TITLE", ""),
                },
                "repository": {
                    "full_name": os.environ.get("EVENT_REPO", ""),
                },
            },
        }
        logger.info("Reconstructed event: source=%s, issue=#%s %s",
                    event_source,
                    reconstructed_event["detail"]["issue"]["number"],
                    reconstructed_event["detail"]["issue"]["title"])
        result = orchestrator.handle_event(reconstructed_event)
        logger.info("Result: %s", json.dumps(result, default=str))
    elif task_spec_path:
        logger.info("Mode: Direct spec — %s", task_spec_path)
        result = orchestrator.handle_spec(read_spec.fn(task_spec_path), task_spec_path)
        logger.info("Result: %s", json.dumps(result, default=str))
    else:
        logger.info("No task. Set TASK_SPEC, EVENTBRIDGE_EVENT, or EVENT_SOURCE+EVENT_ACTION.")

    logger.info("Agent execution complete.")


if __name__ == "__main__":
    main()
