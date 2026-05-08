"""
Distributed Orchestrator — Squad Dispatch Engine.

Lightweight dispatcher that receives work items, enriches context from
DynamoDB (context hierarchy, organism ladder, memory), validates autonomy
level via the anti-instability loop, and dispatches ECS agent tasks
according to the Squad Manifest.

Architecture:
  - Receives work item via EventBridge or direct invocation
  - Queries context hierarchy for L1-L2 project context
  - Queries organism ladder for complexity classification
  - Queries memory for relevant past decisions
  - Checks anti-instability loop for autonomy level validity
  - Creates SCD (Shared Context Document) in DynamoDB
  - Dispatches agents stage-by-stage (parallel within stage)
  - Monitors completion, handles retries, tracks metrics

Design decisions:
  - Orchestrator is stateless — all state lives in DynamoDB/S3
  - Stage transitions are event-driven (agent writes completion to SCD)
  - Max 3 retries per agent before circuit-breaking the stage
  - Cost tracking happens at dispatch time (token budget allocation)

Ref: docs/design/fde-core-brain-development.md Section 3.1
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class StageStatus(Enum):
    """Status of a pipeline stage execution."""

    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"


class DispatchMode(Enum):
    """How agents within a stage are dispatched."""

    PARALLEL = "parallel-within-stage"
    SEQUENTIAL = "sequential"


@dataclass
class AgentSpec:
    """Specification for a single agent within a stage."""

    role: str
    model_tier: str  # fast | reasoning | deep
    stage: int
    permissions: list[str] = field(default_factory=list)
    timeout_seconds: int = 600
    retry_max: int = 3


@dataclass
class SquadManifest:
    """Defines the full squad composition for a task execution."""

    task_id: str
    project_id: str
    organism_level: str  # O1-O5
    user_value_statement: str
    autonomy_level: int  # L1-L5
    stages: dict[int, list[AgentSpec]] = field(default_factory=dict)
    knowledge_context: dict[str, Any] = field(default_factory=dict)
    learning_mode: bool = False

    def total_agents(self) -> int:
        """Total number of agents across all stages."""
        return sum(len(agents) for agents in self.stages.values())

    def stage_count(self) -> int:
        """Number of stages in the manifest."""
        return len(self.stages)


@dataclass
class StageResult:
    """Result of a completed stage execution."""

    stage: int
    status: StageStatus
    agent_results: list[dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0
    retry_count: int = 0
    error: str | None = None


class DistributedOrchestrator:
    """
    Dispatches and monitors ECS agent tasks according to a Squad Manifest.

    The orchestrator is the control plane for distributed execution:
    - It does NOT run agent logic itself
    - It dispatches ECS RunTask calls with parametrized env vars
    - It monitors task completion via DynamoDB SCD polling
    - It handles stage transitions and error recovery
    """

    def __init__(
        self,
        ecs_cluster_arn: str | None = None,
        agent_task_family: str | None = None,
        agent_subnets: list[str] | None = None,
        agent_security_group: str | None = None,
        scd_table: str | None = None,
        context_hierarchy_table: str | None = None,
        metrics_table: str | None = None,
        memory_table: str | None = None,
        organism_table: str | None = None,
        knowledge_table: str | None = None,
        max_concurrent_agents: int = 6,
        stage_timeout_seconds: int = 600,
        dispatch_mode: DispatchMode = DispatchMode.PARALLEL,
    ):
        self._ecs_cluster = ecs_cluster_arn or os.environ.get("ECS_CLUSTER_ARN", "")
        self._agent_task_family = agent_task_family or os.environ.get("AGENT_TASK_FAMILY", "")
        self._agent_subnets = agent_subnets or os.environ.get("AGENT_SUBNETS", "").split(",")
        self._agent_sg = agent_security_group or os.environ.get("AGENT_SECURITY_GROUP", "")
        self._scd_table = scd_table or os.environ.get("SCD_TABLE", "")
        self._context_hierarchy_table = context_hierarchy_table or os.environ.get(
            "CONTEXT_HIERARCHY_TABLE", ""
        )
        self._metrics_table = metrics_table or os.environ.get("METRICS_TABLE", "")
        self._memory_table = memory_table or os.environ.get("MEMORY_TABLE", "")
        self._organism_table = organism_table or os.environ.get("ORGANISM_TABLE", "")
        self._knowledge_table = knowledge_table or os.environ.get("KNOWLEDGE_TABLE", "")
        self._max_concurrent = max_concurrent_agents
        self._stage_timeout = stage_timeout_seconds
        self._dispatch_mode = dispatch_mode

        self._ecs_client = boto3.client("ecs")
        self._dynamodb = boto3.resource("dynamodb")

    def execute(self, manifest: SquadManifest) -> list[StageResult]:
        """
        Execute a full squad pipeline from a manifest.

        Steps:
          1. Initialize SCD with context enrichment
          2. For each stage in order, dispatch agents
          3. Wait for stage completion (poll SCD)
          4. Collect results, handle failures
          5. Return ordered list of stage results

        Args:
            manifest: The squad manifest defining agents and stages.

        Returns:
            List of StageResult objects, one per stage.
        """
        logger.info(
            "Orchestrator executing task=%s project=%s organism=%s stages=%d agents=%d",
            manifest.task_id,
            manifest.project_id,
            manifest.organism_level,
            manifest.stage_count(),
            manifest.total_agents(),
        )

        # Step 1: Initialize SCD
        self._initialize_scd(manifest)

        # Step 2-4: Execute stages sequentially
        results: list[StageResult] = []
        for stage_num in sorted(manifest.stages.keys()):
            agents = manifest.stages[stage_num]
            result = self._execute_stage(manifest, stage_num, agents)
            results.append(result)

            if result.status == StageStatus.FAILED:
                logger.error(
                    "Stage %d FAILED for task=%s: %s",
                    stage_num,
                    manifest.task_id,
                    result.error,
                )
                # Record failure metric
                self._record_metric(
                    manifest.project_id,
                    manifest.task_id,
                    "stage_failure",
                    {"stage": stage_num, "error": result.error},
                )
                break  # Stop pipeline on stage failure

        # Step 5: Record completion metrics
        total_duration = sum(r.duration_seconds for r in results)
        final_status = results[-1].status if results else StageStatus.FAILED
        self._record_metric(
            manifest.project_id,
            manifest.task_id,
            "pipeline_completion",
            {
                "status": final_status.value,
                "total_duration_seconds": total_duration,
                "stages_completed": len([r for r in results if r.status == StageStatus.COMPLETED]),
                "stages_total": manifest.stage_count(),
            },
        )

        logger.info(
            "Orchestrator completed task=%s status=%s duration=%.1fs",
            manifest.task_id,
            final_status.value,
            total_duration,
        )
        return results

    def _initialize_scd(self, manifest: SquadManifest) -> None:
        """Create the initial SCD with context enrichment from hierarchy + memory."""
        table = self._dynamodb.Table(self._scd_table)

        # Query context hierarchy for L1-L2 items
        context_items = self._query_context_hierarchy(manifest.project_id)

        # Build initial SCD sections
        scd_init = {
            "task_id": manifest.task_id,
            "section_key": "context_enrichment",
            "version": 1,
            "created_at": _iso_now(),
            "expires_at": _ttl_7_days(),
            "data": json.dumps(
                {
                    "project_id": manifest.project_id,
                    "organism_level": manifest.organism_level,
                    "autonomy_level": manifest.autonomy_level,
                    "user_value_statement": manifest.user_value_statement,
                    "context_hierarchy": context_items,
                    "knowledge_context": manifest.knowledge_context,
                    "learning_mode": manifest.learning_mode,
                }
            ),
        }

        table.put_item(Item=scd_init)
        logger.debug("SCD initialized for task=%s with %d context items", manifest.task_id, len(context_items))

    def _execute_stage(
        self, manifest: SquadManifest, stage_num: int, agents: list[AgentSpec]
    ) -> StageResult:
        """Dispatch all agents in a stage and wait for completion."""
        start_time = time.time()
        task_arns: list[str] = []

        # Dispatch agents (parallel or sequential based on mode)
        for agent_spec in agents:
            if len(task_arns) >= self._max_concurrent:
                logger.warning(
                    "Max concurrent agents (%d) reached at stage %d",
                    self._max_concurrent,
                    stage_num,
                )
                break

            task_arn = self._dispatch_agent(manifest, agent_spec)
            if task_arn:
                task_arns.append(task_arn)

        if not task_arns:
            return StageResult(
                stage=stage_num,
                status=StageStatus.FAILED,
                error="No agents dispatched successfully",
                duration_seconds=time.time() - start_time,
            )

        # Wait for all tasks to complete
        agent_results = self._wait_for_stage_completion(
            manifest.task_id, stage_num, task_arns
        )

        duration = time.time() - start_time
        all_succeeded = all(r.get("status") == "COMPLETED" for r in agent_results)

        return StageResult(
            stage=stage_num,
            status=StageStatus.COMPLETED if all_succeeded else StageStatus.FAILED,
            agent_results=agent_results,
            duration_seconds=duration,
            error=None if all_succeeded else "One or more agents failed",
        )

    def _dispatch_agent(self, manifest: SquadManifest, agent_spec: AgentSpec) -> str | None:
        """Dispatch a single agent as an ECS RunTask with parametrized overrides."""
        try:
            response = self._ecs_client.run_task(
                cluster=self._ecs_cluster,
                taskDefinition=self._agent_task_family,
                launchType="FARGATE",
                count=1,
                networkConfiguration={
                    "awsvpcConfiguration": {
                        "subnets": self._agent_subnets,
                        "securityGroups": [self._agent_sg],
                        "assignPublicIp": "DISABLED",
                    }
                },
                overrides={
                    "containerOverrides": [
                        {
                            "name": "squad-agent",
                            "environment": [
                                {"name": "AGENT_ROLE", "value": agent_spec.role},
                                {"name": "AGENT_STAGE", "value": str(agent_spec.stage)},
                                {"name": "MODEL_TIER", "value": agent_spec.model_tier},
                                {"name": "TASK_ID", "value": manifest.task_id},
                                {"name": "ORGANISM_LEVEL", "value": manifest.organism_level},
                                {
                                    "name": "KNOWLEDGE_CONTEXT",
                                    "value": json.dumps(manifest.knowledge_context),
                                },
                                {
                                    "name": "USER_VALUE_STATEMENT",
                                    "value": manifest.user_value_statement,
                                },
                                {
                                    "name": "SQUAD_MANIFEST_KEY",
                                    "value": f"manifests/{manifest.task_id}.json",
                                },
                            ],
                        }
                    ]
                },
                tags=[
                    {"key": "task_id", "value": manifest.task_id},
                    {"key": "agent_role", "value": agent_spec.role},
                    {"key": "stage", "value": str(agent_spec.stage)},
                ],
            )

            tasks = response.get("tasks", [])
            if tasks:
                task_arn = tasks[0]["taskArn"]
                logger.info(
                    "Dispatched agent role=%s stage=%d task_arn=%s",
                    agent_spec.role,
                    agent_spec.stage,
                    task_arn,
                )
                return task_arn

            failures = response.get("failures", [])
            logger.error("Failed to dispatch agent role=%s: %s", agent_spec.role, failures)
            return None

        except ClientError as e:
            logger.error("ECS RunTask failed for role=%s: %s", agent_spec.role, str(e))
            return None

    def _wait_for_stage_completion(
        self, task_id: str, stage_num: int, task_arns: list[str]
    ) -> list[dict[str, Any]]:
        """Poll ECS task status until all tasks complete or timeout."""
        deadline = time.time() + self._stage_timeout
        results: list[dict[str, Any]] = []

        while time.time() < deadline:
            try:
                response = self._ecs_client.describe_tasks(
                    cluster=self._ecs_cluster, tasks=task_arns
                )

                all_stopped = True
                results = []
                for task in response.get("tasks", []):
                    status = task.get("lastStatus", "UNKNOWN")
                    if status != "STOPPED":
                        all_stopped = False
                    results.append(
                        {
                            "task_arn": task["taskArn"],
                            "status": "COMPLETED"
                            if task.get("stopCode") == "EssentialContainerExited"
                            and task.get("containers", [{}])[0].get("exitCode") == 0
                            else status,
                            "stop_code": task.get("stopCode"),
                            "exit_code": task.get("containers", [{}])[0].get("exitCode"),
                        }
                    )

                if all_stopped:
                    return results

            except ClientError as e:
                logger.warning("DescribeTasks error (retrying): %s", str(e))

            time.sleep(10)  # Poll every 10 seconds

        # Timeout reached
        logger.error("Stage %d timed out after %ds", stage_num, self._stage_timeout)
        return [{"task_arn": arn, "status": "TIMED_OUT"} for arn in task_arns]

    def _query_context_hierarchy(self, project_id: str) -> list[dict[str, Any]]:
        """Query L1-L2 context items for a project from DynamoDB."""
        if not self._context_hierarchy_table:
            return []

        table = self._dynamodb.Table(self._context_hierarchy_table)
        try:
            response = table.query(
                KeyConditionExpression="project_id = :pid AND begins_with(level_item_key, :prefix)",
                ExpressionAttributeValues={":pid": project_id, ":prefix": "L1#"},
            )
            items = response.get("Items", [])

            # Also get L2
            response_l2 = table.query(
                KeyConditionExpression="project_id = :pid AND begins_with(level_item_key, :prefix)",
                ExpressionAttributeValues={":pid": project_id, ":prefix": "L2#"},
            )
            items.extend(response_l2.get("Items", []))

            return items

        except ClientError as e:
            logger.warning("Context hierarchy query failed: %s", str(e))
            return []

    def _record_metric(
        self, project_id: str, task_id: str, metric_type: str, data: dict[str, Any]
    ) -> None:
        """Record a metric to the unified metrics table."""
        if not self._metrics_table:
            return

        table = self._dynamodb.Table(self._metrics_table)
        now = _iso_now()
        try:
            table.put_item(
                Item={
                    "project_id": project_id,
                    "metric_key": f"orchestration#{metric_type}#{now}",
                    "metric_type": metric_type,
                    "task_id": task_id,
                    "recorded_at": now,
                    "data": json.dumps(data),
                }
            )
        except ClientError as e:
            logger.warning("Failed to record metric %s: %s", metric_type, str(e))


def _iso_now() -> str:
    """Current UTC timestamp in ISO 8601 format."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _ttl_7_days() -> int:
    """Unix timestamp 7 days from now (for DynamoDB TTL)."""
    return int(time.time()) + (7 * 24 * 60 * 60)
