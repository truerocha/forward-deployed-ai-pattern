"""
Integration Test: Conductor -> Orchestrator -> Agent End-to-End Flow.

Tests the full Conductor orchestration pipeline with mocked AWS services.
Validates:
  1. Conductor generates valid WorkflowPlans from task descriptions
  2. Plans convert correctly to SquadManifest stages
  3. Feature flag controls Conductor activation
  4. Access lists are correctly propagated to agent environment
  5. Recursive refinement triggers when confidence is low
  6. Fallback plan is used when Conductor reasoning fails

All AWS calls (Bedrock, DynamoDB, ECS) are mocked via unittest.mock.

Ref: ADR-020 (Conductor Orchestration Pattern)
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest


class TestConductorPlanGeneration:
    """Tests for Conductor.generate_plan() with mocked Bedrock."""

    def _mock_bedrock_response(self, plan_json: dict) -> dict:
        """Create a mock Bedrock Converse API response."""
        return {
            "output": {
                "message": {
                    "content": [{"text": json.dumps(plan_json)}]
                }
            },
            "usage": {"inputTokens": 1500, "outputTokens": 800},
        }

    @patch("boto3.client")
    def test_generates_sequential_plan_for_o2(self, mock_boto_client):
        """O2 tasks should produce sequential topology with 2-3 steps."""
        from src.core.orchestration.conductor import Conductor, TopologyType

        mock_bedrock = MagicMock()
        mock_bedrock.converse.return_value = self._mock_bedrock_response({
            "rationale": "Simple task: plan then implement",
            "topology": "sequential",
            "steps": [
                {
                    "subtask": "Analyze the requirements and plan approach",
                    "agent_role": "fde-tech-lead-agent",
                    "model_tier": "reasoning",
                    "access_list": [],
                },
                {
                    "subtask": "Implement the planned changes",
                    "agent_role": "swe-developer-agent",
                    "model_tier": "reasoning",
                    "access_list": ["all"],
                },
            ],
        })
        mock_boto_client.return_value = mock_bedrock

        conductor = Conductor()
        plan = conductor.generate_plan(
            task_id="test-001",
            task_description="Add input validation to login form",
            organism_level="O2",
            user_value_statement="Users get clear error messages on invalid input",
        )

        assert plan.topology_type == TopologyType.SEQUENTIAL
        assert plan.total_steps() == 2
        assert plan.steps[0].agent_role == "fde-tech-lead-agent"
        assert plan.steps[1].agent_role == "swe-developer-agent"
        assert plan.steps[0].access_list == []
        assert plan.steps[1].access_list == ["all"]

    @patch("boto3.client")
    def test_generates_debate_plan_for_o4(self, mock_boto_client):
        """O4 tasks should produce debate topology with verification."""
        from src.core.orchestration.conductor import Conductor, TopologyType

        mock_bedrock = MagicMock()
        mock_bedrock.converse.return_value = self._mock_bedrock_response({
            "rationale": "Complex task: multiple approaches then arbiter selects best",
            "topology": "debate",
            "steps": [
                {
                    "subtask": "Propose approach A: event-driven architecture",
                    "agent_role": "swe-architect-agent",
                    "model_tier": "reasoning",
                    "access_list": [],
                },
                {
                    "subtask": "Propose approach B: layered architecture",
                    "agent_role": "swe-developer-agent",
                    "model_tier": "reasoning",
                    "access_list": [],
                },
                {
                    "subtask": "Evaluate both approaches and select the best one",
                    "agent_role": "fde-tech-lead-agent",
                    "model_tier": "deep",
                    "access_list": ["all"],
                },
            ],
        })
        mock_boto_client.return_value = mock_bedrock

        conductor = Conductor()
        plan = conductor.generate_plan(
            task_id="test-002",
            task_description="Redesign payment processing pipeline",
            organism_level="O4",
            user_value_statement="Payments process in under 2 seconds",
        )

        assert plan.topology_type == TopologyType.DEBATE
        assert plan.total_steps() == 3
        assert plan.steps[0].access_list == []
        assert plan.steps[1].access_list == []
        assert plan.steps[2].access_list == ["all"]

    @patch("boto3.client")
    def test_fallback_on_bedrock_failure(self, mock_boto_client):
        """When Bedrock fails, Conductor should return a safe fallback plan."""
        from botocore.exceptions import ClientError
        from src.core.orchestration.conductor import Conductor, TopologyType

        mock_bedrock = MagicMock()
        mock_bedrock.converse.side_effect = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
            "Converse",
        )
        mock_boto_client.return_value = mock_bedrock

        conductor = Conductor()
        plan = conductor.generate_plan(
            task_id="test-003",
            task_description="Any task",
            organism_level="O3",
        )

        assert plan.topology_type == TopologyType.SEQUENTIAL
        assert plan.total_steps() == 3
        assert plan.steps[0].agent_role == "fde-tech-lead-agent"
        assert plan.steps[1].agent_role == "swe-developer-agent"
        assert plan.steps[2].agent_role == "fde-fidelity-agent"


class TestConductorManifestConversion:
    """Tests for WorkflowPlan -> SquadManifest conversion."""

    def test_sequential_plan_produces_sequential_stages(self):
        """Sequential topology: each step becomes its own stage."""
        from src.core.orchestration.conductor import (
            TopologyType,
            WorkflowPlan,
            WorkflowStep,
        )

        plan = WorkflowPlan(
            task_id="test-conv-001",
            organism_level="O3",
            topology_type=TopologyType.SEQUENTIAL,
            steps=[
                WorkflowStep(step_index=0, subtask="Plan", agent_role="planner", model_tier="reasoning"),
                WorkflowStep(step_index=1, subtask="Implement", agent_role="developer", model_tier="fast"),
                WorkflowStep(step_index=2, subtask="Review", agent_role="reviewer", model_tier="reasoning"),
            ],
        )

        stages = plan.to_squad_manifest_stages()
        assert len(stages) == 3
        assert len(stages[1]) == 1
        assert stages[1][0]["role"] == "planner"
        assert stages[2][0]["role"] == "developer"
        assert stages[3][0]["role"] == "reviewer"

    def test_debate_plan_produces_parallel_plus_arbiter(self):
        """Debate topology: N-1 parallel + 1 arbiter stage."""
        from src.core.orchestration.conductor import (
            TopologyType,
            WorkflowPlan,
            WorkflowStep,
        )

        plan = WorkflowPlan(
            task_id="test-conv-002",
            organism_level="O4",
            topology_type=TopologyType.DEBATE,
            steps=[
                WorkflowStep(step_index=0, subtask="Approach A", agent_role="agent-a", model_tier="reasoning"),
                WorkflowStep(step_index=1, subtask="Approach B", agent_role="agent-b", model_tier="reasoning"),
                WorkflowStep(step_index=2, subtask="Select best", agent_role="arbiter", model_tier="deep"),
            ],
        )

        stages = plan.to_squad_manifest_stages()
        assert len(stages) == 2
        assert len(stages[1]) == 2
        assert stages[1][0]["role"] == "agent-a"
        assert stages[1][1]["role"] == "agent-b"
        assert len(stages[2]) == 1
        assert stages[2][0]["role"] == "arbiter"

    def test_parallel_plan_produces_single_stage(self):
        """Parallel topology: all steps in one stage."""
        from src.core.orchestration.conductor import (
            TopologyType,
            WorkflowPlan,
            WorkflowStep,
        )

        plan = WorkflowPlan(
            task_id="test-conv-003",
            organism_level="O3",
            topology_type=TopologyType.PARALLEL,
            steps=[
                WorkflowStep(step_index=0, subtask="Task A", agent_role="agent-a", model_tier="fast"),
                WorkflowStep(step_index=1, subtask="Task B", agent_role="agent-b", model_tier="fast"),
                WorkflowStep(step_index=2, subtask="Task C", agent_role="agent-c", model_tier="fast"),
            ],
        )

        stages = plan.to_squad_manifest_stages()
        assert len(stages) == 1
        assert len(stages[1]) == 3


class TestConductorFeatureFlag:
    """Tests for feature flag and organism level gating."""

    def test_conductor_skipped_for_o1_o2(self):
        """O1, O2 should NOT use Conductor (overhead not justified)."""
        with patch.dict(os.environ, {"CONDUCTOR_ENABLED": "true"}):
            import importlib
            import src.core.orchestration.conductor_integration as ci
            importlib.reload(ci)
            assert ci.should_use_conductor("O1") is False
            assert ci.should_use_conductor("O2") is False

    def test_conductor_enabled_for_o3_plus(self):
        """O3, O4, O5 should use Conductor when enabled."""
        with patch.dict(os.environ, {"CONDUCTOR_ENABLED": "true"}):
            import importlib
            import src.core.orchestration.conductor_integration as ci
            importlib.reload(ci)
            assert ci.should_use_conductor("O3") is True
            assert ci.should_use_conductor("O4") is True
            assert ci.should_use_conductor("O5") is True


class TestConductorRecursion:
    """Tests for recursive refinement logic."""

    def test_should_recurse_when_confidence_low(self):
        """Recursion triggers when confidence < threshold."""
        from src.core.orchestration.conductor import (
            Conductor,
            TopologyType,
            WorkflowPlan,
        )

        plan = WorkflowPlan(
            task_id="test-rec-001",
            organism_level="O4",
            topology_type=TopologyType.SEQUENTIAL,
            recursive_depth=0,
            confidence_threshold=0.7,
        )

        execution_result = {
            "stage_results": [
                {"status": "COMPLETED", "retry_count": 0},
                {"status": "FAILED", "retry_count": 2},
                {"status": "TIMED_OUT", "retry_count": 0},
            ]
        }

        conductor = Conductor.__new__(Conductor)
        conductor._max_depth = 2
        assert conductor.should_recurse(plan, execution_result) is True

    def test_should_not_recurse_at_max_depth(self):
        """Recursion stops at max depth regardless of confidence."""
        from src.core.orchestration.conductor import (
            Conductor,
            TopologyType,
            WorkflowPlan,
        )

        plan = WorkflowPlan(
            task_id="test-rec-002",
            organism_level="O5",
            topology_type=TopologyType.RECURSIVE,
            recursive_depth=2,
            confidence_threshold=0.7,
        )

        execution_result = {
            "stage_results": [
                {"status": "FAILED", "retry_count": 3},
            ]
        }

        conductor = Conductor.__new__(Conductor)
        conductor._max_depth = 2
        assert conductor.should_recurse(plan, execution_result) is False

    def test_should_not_recurse_when_confidence_high(self):
        """No recursion when all stages complete successfully."""
        from src.core.orchestration.conductor import (
            Conductor,
            TopologyType,
            WorkflowPlan,
        )

        plan = WorkflowPlan(
            task_id="test-rec-003",
            organism_level="O3",
            topology_type=TopologyType.SEQUENTIAL,
            recursive_depth=0,
            confidence_threshold=0.7,
        )

        execution_result = {
            "stage_results": [
                {"status": "COMPLETED", "retry_count": 0},
                {"status": "COMPLETED", "retry_count": 0},
                {"status": "COMPLETED", "retry_count": 0},
            ]
        }

        conductor = Conductor.__new__(Conductor)
        conductor._max_depth = 2
        assert conductor.should_recurse(plan, execution_result) is False


class TestAccessListEnforcement:
    """Tests for communication topology enforcement."""

    def test_build_agent_subtask_env(self):
        """build_agent_subtask_env produces correct env var dict."""
        from src.core.orchestration.conductor import WorkflowStep
        from src.core.orchestration.conductor_integration import build_agent_subtask_env

        step = WorkflowStep(
            step_index=2,
            subtask="Review the implementation for security vulnerabilities",
            agent_role="swe-adversarial-agent",
            model_tier="reasoning",
            access_list=[0, 1],
        )

        env = build_agent_subtask_env(step)
        assert env["AGENT_SUBTASK"] == "Review the implementation for security vulnerabilities"
        assert env["AGENT_ACCESS_LIST"] == "[0, 1]"
        assert env["AGENT_STEP_INDEX"] == "2"

    def test_full_access_env(self):
        """Access list with 'all' produces correct JSON."""
        from src.core.orchestration.conductor import WorkflowStep
        from src.core.orchestration.conductor_integration import build_agent_subtask_env

        step = WorkflowStep(
            step_index=3,
            subtask="Validate all outputs",
            agent_role="fde-fidelity-agent",
            model_tier="fast",
            access_list=["all"],
        )

        env = build_agent_subtask_env(step)
        assert json.loads(env["AGENT_ACCESS_LIST"]) == ["all"]
