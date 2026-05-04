"""
Forward Deployed Engineer — Strands Agent Entrypoint for ECS Fargate.

Wires together: Registry + Router + Orchestrator.

Modes:
1. EVENTBRIDGE_EVENT env var → parse event, route, execute
2. TASK_SPEC env var → direct spec execution
3. Neither → log instructions and exit
"""

import json
import logging
import os
import sys

import boto3
from botocore.exceptions import ClientError

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


def build_registry() -> AgentRegistry:
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
    if not any([os.environ.get("GITHUB_TOKEN"), os.environ.get("ASANA_ACCESS_TOKEN"), os.environ.get("GITLAB_TOKEN")]):
        issues.append("No ALM tokens configured")
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

    registry = build_registry()
    router = AgentRouter()
    orchestrator = Orchestrator(registry=registry, router=router, factory_bucket=FACTORY_BUCKET)

    logger.info("Application ready: %d agents [%s]", len(registry.list_agents()), ", ".join(registry.list_agents()))

    eventbridge_event = os.environ.get("EVENTBRIDGE_EVENT", "")
    task_spec_path = os.environ.get("TASK_SPEC", "")

    if eventbridge_event:
        logger.info("Mode: EventBridge event")
        result = orchestrator.handle_event(json.loads(eventbridge_event))
        logger.info("Result: %s", json.dumps(result, default=str))
    elif task_spec_path:
        logger.info("Mode: Direct spec — %s", task_spec_path)
        result = orchestrator.handle_spec(read_spec.fn(task_spec_path), task_spec_path)
        logger.info("Result: %s", json.dumps(result, default=str))
    else:
        logger.info("No task. Set TASK_SPEC or EVENTBRIDGE_EVENT.")

    logger.info("Agent execution complete.")


if __name__ == "__main__":
    main()
