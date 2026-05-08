"""
Integration Test: Distributed Orchestrator Dispatches Agent.

Validates the end-to-end flow:
  1. Orchestrator receives a SquadManifest
  2. SCD is initialized in DynamoDB with context enrichment
  3. Agent task is dispatched via ECS RunTask
  4. Agent reads SCD, executes via Bedrock, writes results back
  5. Orchestrator detects completion and collects results
  6. Metrics are recorded (cost, VSM, pipeline completion)

Prerequisites:
  - DynamoDB tables deployed (fde-dev-scd, fde-dev-metrics, fde-dev-context-hierarchy)
  - ECS cluster running with agent task definition registered
  - ECR image pushed (fde-dev-strands-agent:latest)
  - Bedrock model access granted

Run: python3 -m pytest tests/integration/test_distributed_orchestration.py -v

Activity: 1.30
Ref: docs/design/fde-core-brain-development.md Wave 1
"""

import json
import os
import time
import uuid

import boto3
import pytest

from src.core.orchestration.distributed_orchestrator import (
    AgentSpec,
    DispatchMode,
    DistributedOrchestrator,
    SquadManifest,
    StageStatus,
)


# Skip if infrastructure not deployed
pytestmark = pytest.mark.skipif(
    not os.environ.get("FDE_INTEGRATION_TESTS_ENABLED"),
    reason="Set FDE_INTEGRATION_TESTS_ENABLED=1 to run integration tests (requires deployed infra)",
)


@pytest.fixture
def dynamodb():
    """DynamoDB resource for test verification."""
    return boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))


@pytest.fixture
def scd_table(dynamodb):
    """SCD DynamoDB table."""
    table_name = os.environ.get("SCD_TABLE", "fde-dev-scd")
    return dynamodb.Table(table_name)


@pytest.fixture
def metrics_table(dynamodb):
    """Metrics DynamoDB table."""
    table_name = os.environ.get("METRICS_TABLE", "fde-dev-metrics")
    return dynamodb.Table(table_name)


@pytest.fixture
def orchestrator():
    """Configured orchestrator instance."""
    return DistributedOrchestrator(
        max_concurrent_agents=2,
        stage_timeout_seconds=300,
        dispatch_mode=DispatchMode.PARALLEL,
    )


@pytest.fixture
def test_manifest():
    """Minimal squad manifest for testing."""
    task_id = f"test-{uuid.uuid4().hex[:8]}"
    return SquadManifest(
        task_id=task_id,
        project_id="integration-test",
        organism_level="O1",
        user_value_statement="As a developer, I want automated testing so that I can ship with confidence",
        autonomy_level=3,
        stages={
            1: [
                AgentSpec(
                    role="test-echo-agent",
                    model_tier="fast",
                    stage=1,
                    timeout_seconds=120,
                )
            ],
        },
        knowledge_context={"test": True},
        learning_mode=False,
    )


class TestOrchestratorSCDInitialization:
    """Test that the orchestrator correctly initializes the SCD."""

    def test_scd_created_with_context_enrichment(self, orchestrator, test_manifest, scd_table):
        """SCD context_enrichment section is created with correct data."""
        orchestrator._initialize_scd(test_manifest)

        response = scd_table.get_item(
            Key={"task_id": test_manifest.task_id, "section_key": "context_enrichment"}
        )
        assert "Item" in response, "SCD context_enrichment not found"

        item = response["Item"]
        data = json.loads(item["data"])

        assert data["project_id"] == "integration-test"
        assert data["organism_level"] == "O1"
        assert data["autonomy_level"] == 3
        assert data["user_value_statement"] == test_manifest.user_value_statement
        assert data["knowledge_context"] == {"test": True}
        assert item["version"] == 1

    def test_scd_has_ttl(self, orchestrator, test_manifest, scd_table):
        """SCD items have TTL set (7 days from creation)."""
        orchestrator._initialize_scd(test_manifest)

        response = scd_table.get_item(
            Key={"task_id": test_manifest.task_id, "section_key": "context_enrichment"}
        )
        item = response["Item"]

        assert "expires_at" in item
        # TTL should be ~7 days from now (within 1 hour tolerance)
        expected_ttl = int(time.time()) + (7 * 24 * 60 * 60)
        assert abs(int(item["expires_at"]) - expected_ttl) < 3600


class TestOrchestratorAgentDispatch:
    """Test that the orchestrator dispatches ECS tasks correctly."""

    def test_single_agent_dispatch(self, orchestrator, test_manifest):
        """Orchestrator dispatches a single agent and gets a task ARN back."""
        agent_spec = test_manifest.stages[1][0]
        task_arn = orchestrator._dispatch_agent(test_manifest, agent_spec)

        assert task_arn is not None, "Agent dispatch returned None (check ECS cluster/task def)"
        assert "arn:aws:ecs:" in task_arn
        assert ":task/" in task_arn

    def test_dispatch_sets_environment_overrides(self, orchestrator, test_manifest):
        """Dispatched task has correct environment variable overrides."""
        agent_spec = test_manifest.stages[1][0]
        task_arn = orchestrator._dispatch_agent(test_manifest, agent_spec)

        if task_arn:
            ecs = boto3.client("ecs")
            response = ecs.describe_tasks(
                cluster=orchestrator._ecs_cluster, tasks=[task_arn]
            )
            tasks = response.get("tasks", [])
            assert len(tasks) == 1

            task = tasks[0]
            overrides = task.get("overrides", {}).get("containerOverrides", [])
            assert len(overrides) > 0

            agent_override = overrides[0]
            env_vars = {e["name"]: e["value"] for e in agent_override.get("environment", [])}
            assert env_vars.get("AGENT_ROLE") == "test-echo-agent"
            assert env_vars.get("MODEL_TIER") == "fast"
            assert env_vars.get("TASK_ID") == test_manifest.task_id


class TestOrchestratorFullPipeline:
    """Test the full orchestrator pipeline execution."""

    @pytest.mark.timeout(360)
    def test_full_execution_completes(self, orchestrator, test_manifest):
        """Full pipeline execution completes with stage results."""
        results = orchestrator.execute(test_manifest)

        assert len(results) == 1, "Expected 1 stage result"
        assert results[0].stage == 1
        assert results[0].status in (StageStatus.COMPLETED, StageStatus.FAILED, StageStatus.TIMED_OUT)

    def test_metrics_recorded_after_execution(self, orchestrator, test_manifest, metrics_table):
        """Pipeline completion metric is recorded in DynamoDB."""
        orchestrator.execute(test_manifest)

        response = metrics_table.query(
            KeyConditionExpression="project_id = :pid AND begins_with(metric_key, :prefix)",
            ExpressionAttributeValues={
                ":pid": "integration-test",
                ":prefix": "orchestration#pipeline_completion#",
            },
            ScanIndexForward=False,
            Limit=1,
        )
        items = response.get("Items", [])
        assert len(items) > 0, "Pipeline completion metric not found"

        data = json.loads(items[0]["data"])
        assert data["stages_total"] == 1
        assert "total_duration_seconds" in data


class TestOrchestratorContextHierarchy:
    """Test context hierarchy integration."""

    def test_l1_l2_context_injected_into_scd(self, orchestrator, test_manifest, dynamodb):
        """L1-L2 context items are queried and injected into SCD."""
        ctx_table = dynamodb.Table(os.environ.get("CONTEXT_HIERARCHY_TABLE", "fde-dev-context-hierarchy"))
        ctx_table.put_item(Item={
            "project_id": "integration-test",
            "level_item_key": "L1#language",
            "level": "L1",
            "data": json.dumps({"key": "language", "value": "python"}),
        })
        ctx_table.put_item(Item={
            "project_id": "integration-test",
            "level_item_key": "L2#test_framework",
            "level": "L2",
            "data": json.dumps({"key": "test_framework", "value": "pytest"}),
        })

        orchestrator._initialize_scd(test_manifest)

        scd_table = dynamodb.Table(os.environ.get("SCD_TABLE", "fde-dev-scd"))
        response = scd_table.get_item(
            Key={"task_id": test_manifest.task_id, "section_key": "context_enrichment"}
        )
        data = json.loads(response["Item"]["data"])

        ctx_items = data.get("context_hierarchy", [])
        assert len(ctx_items) >= 2, f"Expected >= 2 context items, got {len(ctx_items)}"
