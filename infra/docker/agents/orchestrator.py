"""
Agent Orchestrator — The main entry point that ties Registry + Router together.

Uses Strands GraphBuilder to create a deterministic pipeline:
  Reconnaissance Agent → Engineering Agent → Reporting Agent

For direct spec execution, skips reconnaissance and goes straight to engineering.

The orchestrator:
1. Receives an event (from EventBridge or direct invocation)
2. Routes it to the correct agent via the Router
3. Creates agent instances from the Registry
4. Executes the agent graph
5. Returns the result
"""

import json
import logging
import os
from datetime import datetime, timezone

import boto3

from .registry import AgentRegistry, AgentDefinition
from .router import AgentRouter, RoutingDecision

logger = logging.getLogger("fde.orchestrator")

s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))


class Orchestrator:
    """Main orchestrator that coordinates agent execution."""

    def __init__(self, registry: AgentRegistry, router: AgentRouter, factory_bucket: str):
        self._registry = registry
        self._router = router
        self._factory_bucket = factory_bucket

    def handle_event(self, event: dict) -> dict:
        """Handle an incoming event (EventBridge or direct).

        Args:
            event: The event payload.

        Returns:
            Result dict with status, agent_name, and output.
        """
        decision = self._router.route_event(event)

        if not decision.should_process:
            logger.info("Event skipped: %s", decision.skip_reason)
            return {
                "status": "skipped",
                "reason": decision.skip_reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        return self._execute(decision)

    def handle_spec(self, spec_content: str, spec_path: str) -> dict:
        """Handle a direct spec execution.

        Args:
            spec_content: The spec markdown content.
            spec_path: Path to the spec file.

        Returns:
            Result dict with status, agent_name, and output.
        """
        decision = self._router.route_spec(spec_content, spec_path)
        return self._execute(decision)

    def _execute(self, decision: RoutingDecision) -> dict:
        """Execute an agent based on a routing decision."""
        agent_name = decision.agent_name
        logger.info("Executing agent: %s", agent_name)

        try:
            agent = self._registry.create_agent(agent_name)
        except KeyError as e:
            logger.error("Agent not found: %s", e)
            return {
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        try:
            result = agent(decision.prompt)
            message = str(result.message) if hasattr(result, "message") else str(result)

            # Write result to S3
            self._write_result(agent_name, decision.metadata, message)

            return {
                "status": "completed",
                "agent_name": agent_name,
                "metadata": decision.metadata,
                "message_length": len(message),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            logger.error("Agent execution failed: %s — %s", agent_name, e)
            return {
                "status": "error",
                "agent_name": agent_name,
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    def _write_result(self, agent_name: str, metadata: dict, message: str) -> None:
        """Write agent execution result to S3."""
        if not self._factory_bucket:
            logger.warning("No factory bucket configured — skipping S3 write")
            return

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        source = metadata.get("source", "unknown")
        key = f"results/{source}/{timestamp}/{agent_name}-result.md"

        try:
            s3.put_object(
                Bucket=self._factory_bucket,
                Key=key,
                Body=message.encode("utf-8"),
            )
            logger.info("Result written to s3://%s/%s", self._factory_bucket, key)
        except Exception as e:
            logger.error("Failed to write result to S3: %s", e)
