"""
Agent Runner — ECS Task Entry Point for Squad Agents.

This module is the entry point for each ECS agent task. It:
  1. Reads its role and configuration from environment variables
  2. Loads the Squad Manifest from S3
  3. Reads its section permissions from the manifest
  4. Reads relevant SCD sections from DynamoDB
  5. Executes the agent logic (Bedrock invocation with tools)
  6. Writes results back to SCD with conditional writes (version check)
  7. Signals completion via SCD status update
  8. Records cost metrics (token usage)

The agent runner is generic — it handles any agent role by loading
the appropriate prompt and tool configuration from the manifest.

Design decisions:
  - Conditional writes prevent parallel agent conflicts (version attr)
  - Each agent reads ONLY its permitted SCD sections
  - Cost tracking is per-invocation (input + output tokens)
  - Health check sentinel file written after initialization
  - Graceful shutdown on SIGTERM (ECS stop signal)

Ref: docs/design/fde-core-brain-development.md Section 3.1
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    """Configuration for a running agent instance, loaded from environment."""

    role: str
    stage: int
    model_tier: str
    task_id: str
    organism_level: str
    knowledge_context: dict[str, Any]
    user_value_statement: str
    squad_manifest_key: str
    scd_table: str
    metrics_table: str
    memory_table: str
    knowledge_table: str
    factory_bucket: str
    bedrock_model_id: str
    aws_region: str
    environment: str

    @classmethod
    def from_environment(cls) -> AgentConfig:
        """Load agent configuration from environment variables set by orchestrator."""
        knowledge_raw = os.environ.get("KNOWLEDGE_CONTEXT", "{}")
        try:
            knowledge = json.loads(knowledge_raw)
        except json.JSONDecodeError:
            knowledge = {}

        return cls(
            role=os.environ.get("AGENT_ROLE", "unknown"),
            stage=int(os.environ.get("AGENT_STAGE", "0")),
            model_tier=os.environ.get("MODEL_TIER", "reasoning"),
            task_id=os.environ.get("TASK_ID", ""),
            organism_level=os.environ.get("ORGANISM_LEVEL", "O1"),
            knowledge_context=knowledge,
            user_value_statement=os.environ.get("USER_VALUE_STATEMENT", ""),
            squad_manifest_key=os.environ.get("SQUAD_MANIFEST_KEY", ""),
            scd_table=os.environ.get("SCD_TABLE", ""),
            metrics_table=os.environ.get("METRICS_TABLE", ""),
            memory_table=os.environ.get("MEMORY_TABLE", ""),
            knowledge_table=os.environ.get("KNOWLEDGE_TABLE", ""),
            factory_bucket=os.environ.get("FACTORY_BUCKET", ""),
            bedrock_model_id=os.environ.get("BEDROCK_MODEL_ID", ""),
            aws_region=os.environ.get("AWS_REGION", "us-east-1"),
            environment=os.environ.get("ENVIRONMENT", "dev"),
        )


@dataclass
class AgentResult:
    """Result produced by an agent execution."""

    role: str
    stage: int
    task_id: str
    status: str  # "completed" | "failed" | "timeout"
    output: dict[str, Any] = field(default_factory=dict)
    token_usage: dict[str, int] = field(default_factory=dict)
    duration_seconds: float = 0.0
    error: str | None = None


# Model tier to Bedrock model ID mapping
_MODEL_TIER_MAP = {
    "fast": "us.anthropic.claude-haiku-3-20240307-v1:0",
    "reasoning": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "deep": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
}


class AgentRunner:
    """
    Executes a single agent's logic within an ECS task.

    Lifecycle:
      1. Initialize (load config, connect to AWS services)
      2. Load manifest and SCD context
      3. Resolve model ID from tier
      4. Execute agent logic (Bedrock Converse API)
      5. Write results to SCD
      6. Record metrics
      7. Signal completion
    """

    def __init__(self, config: AgentConfig | None = None):
        self._config = config or AgentConfig.from_environment()
        self._dynamodb = boto3.resource("dynamodb", region_name=self._config.aws_region)
        self._bedrock = boto3.client("bedrock-runtime", region_name=self._config.aws_region)
        self._s3 = boto3.client("s3", region_name=self._config.aws_region)
        self._shutdown_requested = False

        # Register graceful shutdown handler
        signal.signal(signal.SIGTERM, self._handle_sigterm)

    def run(self) -> AgentResult:
        """
        Execute the full agent lifecycle.

        Returns:
            AgentResult with status, output, and metrics.
        """
        start_time = time.time()
        logger.info(
            "Agent starting: role=%s stage=%d task=%s model_tier=%s",
            self._config.role,
            self._config.stage,
            self._config.task_id,
            self._config.model_tier,
        )

        # Write health check sentinel
        self._write_health_sentinel()

        try:
            # Load SCD context for this agent
            scd_context = self._load_scd_context()

            # Load squad manifest for permissions and prompt config
            manifest_data = self._load_manifest()

            # Resolve the Bedrock model ID from tier
            model_id = self._resolve_model_id()

            # Execute agent logic via Bedrock Converse
            result_output, token_usage = self._execute_agent_logic(
                model_id, scd_context, manifest_data
            )

            # Write results to SCD
            self._write_scd_result(result_output)

            duration = time.time() - start_time
            result = AgentResult(
                role=self._config.role,
                stage=self._config.stage,
                task_id=self._config.task_id,
                status="completed",
                output=result_output,
                token_usage=token_usage,
                duration_seconds=duration,
            )

        except Exception as e:
            duration = time.time() - start_time
            logger.error("Agent failed: role=%s error=%s", self._config.role, str(e))
            result = AgentResult(
                role=self._config.role,
                stage=self._config.stage,
                task_id=self._config.task_id,
                status="failed",
                duration_seconds=duration,
                error=str(e),
            )

        # Record cost metrics regardless of success/failure
        self._record_cost_metric(result)

        logger.info(
            "Agent completed: role=%s status=%s duration=%.1fs tokens=%s",
            result.role,
            result.status,
            result.duration_seconds,
            result.token_usage,
        )
        return result

    def _write_health_sentinel(self) -> None:
        """Write sentinel file for ECS health check."""
        try:
            with open("/tmp/agent_ready", "w") as f:
                f.write(f"{self._config.role}:{self._config.task_id}")
        except OSError:
            pass  # Non-fatal — health check will retry

    def _load_scd_context(self) -> dict[str, Any]:
        """Load relevant SCD sections for this agent from DynamoDB.

        If AGENT_ACCESS_LIST is set (Conductor topology enforcement),
        only loads the sections specified in the access list.
        Otherwise, loads all available previous stage outputs (backward compat).

        Ref: ADR-020 — Communication topology via access lists
        """
        if not self._config.scd_table:
            return {}

        table = self._dynamodb.Table(self._config.scd_table)

        # Parse Conductor access list if available
        access_list_raw = os.environ.get("AGENT_ACCESS_LIST", "")
        access_list: list = []
        if access_list_raw:
            try:
                access_list = json.loads(access_list_raw)
            except json.JSONDecodeError:
                access_list = []

        try:
            context = {}

            # Always load context_enrichment (available to all agents)
            response = table.get_item(
                Key={
                    "task_id": self._config.task_id,
                    "section_key": "context_enrichment",
                }
            )
            if "Item" in response:
                data_raw = response["Item"].get("data", "{}")
                context["context_enrichment"] = json.loads(data_raw)

            # Load previous stage outputs based on access list
            if self._config.stage > 1:
                if "all" in access_list or not access_list:
                    # Full access: load all previous stages (original behavior)
                    stages_to_load = range(1, self._config.stage)
                else:
                    # Conductor topology: load only specified stages
                    # Access list contains step indices (0-based), stages are 1-based
                    stages_to_load = [idx + 1 for idx in access_list if isinstance(idx, int)]

                for prev_stage in stages_to_load:
                    if prev_stage >= self._config.stage:
                        continue  # Cannot access future stages
                    section_key = f"stage_{prev_stage}_output"
                    resp = table.get_item(
                        Key={
                            "task_id": self._config.task_id,
                            "section_key": section_key,
                        }
                    )
                    if "Item" in resp:
                        context[section_key] = json.loads(resp["Item"].get("data", "{}"))

            return context

        except ClientError as e:
            logger.warning("Failed to load SCD context: %s", str(e))
            return {}

    def _load_manifest(self) -> dict[str, Any]:
        """Load the Squad Manifest from S3."""
        if not self._config.factory_bucket or not self._config.squad_manifest_key:
            return {}

        try:
            response = self._s3.get_object(
                Bucket=self._config.factory_bucket,
                Key=self._config.squad_manifest_key,
            )
            return json.loads(response["Body"].read().decode("utf-8"))
        except ClientError as e:
            logger.warning("Failed to load manifest from S3: %s", str(e))
            return {}

    def _resolve_model_id(self) -> str:
        """Resolve Bedrock model ID from the configured tier."""
        tier_model = _MODEL_TIER_MAP.get(self._config.model_tier)
        if tier_model:
            return tier_model
        # Fallback to configured default
        return self._config.bedrock_model_id

    def _execute_agent_logic(
        self,
        model_id: str,
        scd_context: dict[str, Any],
        manifest_data: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, int]]:
        """
        Execute the agent's core logic via Bedrock Converse API.

        Constructs a system prompt from the agent role and context,
        then invokes Bedrock for the response.

        Returns:
            Tuple of (output_dict, token_usage_dict)
        """
        system_prompt = self._build_system_prompt(scd_context, manifest_data)
        user_message = self._build_user_message(scd_context)

        try:
            response = self._bedrock.converse(
                modelId=model_id,
                messages=[
                    {
                        "role": "user",
                        "content": [{"text": user_message}],
                    }
                ],
                system=[{"text": system_prompt}],
                inferenceConfig={
                    "maxTokens": 4096,
                    "temperature": 0.1,
                },
            )

            # Extract response content
            output_content = response.get("output", {}).get("message", {}).get("content", [])
            output_text = ""
            for block in output_content:
                if "text" in block:
                    output_text += block["text"]

            # Extract token usage
            usage = response.get("usage", {})
            token_usage = {
                "input_tokens": usage.get("inputTokens", 0),
                "output_tokens": usage.get("outputTokens", 0),
                "total_tokens": usage.get("inputTokens", 0) + usage.get("outputTokens", 0),
            }

            # Parse structured output if JSON
            try:
                output_data = json.loads(output_text)
            except json.JSONDecodeError:
                output_data = {"raw_output": output_text}

            return output_data, token_usage

        except ClientError as e:
            logger.error("Bedrock Converse failed: %s", str(e))
            raise

    def _build_system_prompt(
        self, scd_context: dict[str, Any], manifest_data: dict[str, Any]
    ) -> str:
        """Build the system prompt for this agent based on role and context.

        If a Conductor-generated subtask instruction is available (via
        AGENT_SUBTASK env var), it is used as the primary instruction.
        This implements the Conductor paper's key finding: focused subtask
        instructions outperform generic role prompts.

        Ref: ADR-020 (Conductor Orchestration Pattern)
        """
        context_enrichment = scd_context.get("context_enrichment", {})
        organism = context_enrichment.get("organism_level", "O1")
        user_value = context_enrichment.get("user_value_statement", "")

        # Check for Conductor-generated focused subtask instruction
        subtask = os.environ.get("AGENT_SUBTASK", "")

        base_prompt = (
            f"You are a Forward Deployed AI Engineer operating as role: {self._config.role}.\n"
            f"Stage: {self._config.stage} | Organism Level: {organism}\n"
            f"User Value: {user_value}\n\n"
            f"Task ID: {self._config.task_id}\n"
        )

        if subtask:
            # Conductor-generated focused instruction takes priority
            base_prompt += (
                f"\n## Your Specific Assignment (from Conductor)\n"
                f"{subtask}\n\n"
                f"Execute this specific subtask. Produce structured JSON output.\n"
                f"Follow the governance rules for your role. Do not exceed your scope.\n"
            )
        else:
            # Fallback to generic role-based prompt (pre-Conductor behavior)
            base_prompt += (
                f"Knowledge Context: {json.dumps(self._config.knowledge_context, indent=2)}\n\n"
                f"You must produce structured JSON output with your findings/results.\n"
                f"Follow the governance rules for your role. Do not exceed your scope."
            )

        return base_prompt

    def _build_user_message(self, scd_context: dict[str, Any]) -> str:
        """Build the user message from SCD context and previous stage outputs."""
        parts = []

        # Include context enrichment summary
        enrichment = scd_context.get("context_enrichment", {})
        if enrichment:
            parts.append(f"Project Context:\n{json.dumps(enrichment, indent=2)}")

        # Include previous stage outputs
        for key, value in scd_context.items():
            if key.startswith("stage_") and key.endswith("_output"):
                parts.append(f"\n{key}:\n{json.dumps(value, indent=2)}")

        if not parts:
            parts.append("Execute your role with the available context.")

        return "\n\n".join(parts)

    def _write_scd_result(self, output: dict[str, Any]) -> None:
        """Write agent results to SCD with conditional write (version check)."""
        if not self._config.scd_table:
            return

        table = self._dynamodb.Table(self._config.scd_table)
        section_key = f"stage_{self._config.stage}_output"
        now = _iso_now()

        try:
            # Use conditional write to prevent conflicts
            table.put_item(
                Item={
                    "task_id": self._config.task_id,
                    "section_key": section_key,
                    "version": 1,
                    "created_at": now,
                    "expires_at": _ttl_7_days(),
                    "agent_role": self._config.role,
                    "data": json.dumps(output),
                },
                ConditionExpression="attribute_not_exists(task_id) OR attribute_not_exists(section_key)",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                # Another agent already wrote this section — append instead
                logger.warning(
                    "SCD section %s already exists, writing as sub-section",
                    section_key,
                )
                sub_key = f"{section_key}#{self._config.role}"
                table.put_item(
                    Item={
                        "task_id": self._config.task_id,
                        "section_key": sub_key,
                        "version": 1,
                        "created_at": now,
                        "expires_at": _ttl_7_days(),
                        "agent_role": self._config.role,
                        "data": json.dumps(output),
                    }
                )
            else:
                logger.error("Failed to write SCD result: %s", str(e))

    def _record_cost_metric(self, result: AgentResult) -> None:
        """Record token usage and cost to the metrics table."""
        if not self._config.metrics_table or not result.token_usage:
            return

        table = self._dynamodb.Table(self._config.metrics_table)
        now = _iso_now()

        # Approximate cost calculation (per 1K tokens)
        cost_per_1k = {
            "fast": {"input": 0.00025, "output": 0.00125},
            "reasoning": {"input": 0.003, "output": 0.015},
            "deep": {"input": 0.015, "output": 0.075},
        }
        tier_costs = cost_per_1k.get(self._config.model_tier, cost_per_1k["reasoning"])
        input_cost = (result.token_usage.get("input_tokens", 0) / 1000) * tier_costs["input"]
        output_cost = (result.token_usage.get("output_tokens", 0) / 1000) * tier_costs["output"]

        try:
            table.put_item(
                Item={
                    "project_id": "global",  # Will be enriched by orchestrator
                    "metric_key": f"cost#{self._config.role}#{now}",
                    "metric_type": "cost",
                    "task_id": self._config.task_id,
                    "recorded_at": now,
                    "data": json.dumps(
                        {
                            "agent_role": self._config.role,
                            "model_tier": self._config.model_tier,
                            "input_tokens": result.token_usage.get("input_tokens", 0),
                            "output_tokens": result.token_usage.get("output_tokens", 0),
                            "total_tokens": result.token_usage.get("total_tokens", 0),
                            "input_cost_usd": round(input_cost, 6),
                            "output_cost_usd": round(output_cost, 6),
                            "total_cost_usd": round(input_cost + output_cost, 6),
                            "duration_seconds": result.duration_seconds,
                        }
                    ),
                }
            )
        except ClientError as e:
            logger.warning("Failed to record cost metric: %s", str(e))

    def _handle_sigterm(self, signum: int, frame: Any) -> None:
        """Handle SIGTERM for graceful shutdown."""
        logger.info("SIGTERM received, initiating graceful shutdown")
        self._shutdown_requested = True


def _iso_now() -> str:
    """Current UTC timestamp in ISO 8601 format."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _ttl_7_days() -> int:
    """Unix timestamp 7 days from now (for DynamoDB TTL)."""
    return int(time.time()) + (7 * 24 * 60 * 60)


def main() -> None:
    """Entry point when running as ECS task."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    runner = AgentRunner()
    result = runner.run()

    # Exit with appropriate code
    if result.status == "completed":
        sys.exit(0)
    else:
        logger.error("Agent exiting with failure: %s", result.error)
        sys.exit(1)


if __name__ == "__main__":
    main()
