"""
BDD Scenarios: Autonomy Level in Data Contract (ADR-013, Decision 1)

These tests validate that the Code Factory correctly computes and applies
autonomy levels based on the data contract fields (type + level).

Source: "Levels of Autonomy for AI Agents" (Feng et al., Jun 2025)
Source: "WhatsCode" (Mao et al., Dec 2025) — two stable collaboration patterns

All scenarios MUST FAIL until the autonomy_level module is implemented.
"""

import pytest


# ═══════════════════════════════════════════════════════════════════
# Feature: Autonomy Level Computation
# ═══════════════════════════════════════════════════════════════════


class TestAutonomyLevelComputation:
    """
    Feature: The factory computes an autonomy level for each task
      As a Staff Engineer
      I want the factory to automatically determine how much supervision a task needs
      So that simple tasks run fast and complex tasks get human checkpoints
    """

    def test_bugfix_l2_defaults_to_observer(self):
        """
        Scenario: Bugfix with low engineering level gets maximum autonomy
          Given a data contract with type "bugfix" and level "L2"
          When the autonomy level is computed
          Then the autonomy_level should be "L5" (Observer)
          And the pipeline should use fast-path execution
        """
        from agents.autonomy import compute_autonomy_level

        contract = {"type": "bugfix", "level": "L2", "tech_stack": ["Python"]}
        result = compute_autonomy_level(contract)

        assert result.level == "L5"
        assert result.name == "Observer"
        assert result.human_checkpoints == []
        assert result.fast_path is True

    def test_feature_l3_defaults_to_approver(self):
        """
        Scenario: Standard feature gets Approver level
          Given a data contract with type "feature" and level "L3"
          When the autonomy level is computed
          Then the autonomy_level should be "L4" (Approver)
          And the pipeline should require human approval at PR
        """
        from agents.autonomy import compute_autonomy_level

        contract = {"type": "feature", "level": "L3", "tech_stack": ["Python", "FastAPI"]}
        result = compute_autonomy_level(contract)

        assert result.level == "L4"
        assert result.name == "Approver"
        assert "pr_review" in result.human_checkpoints
        assert result.fast_path is False

    def test_feature_l4_defaults_to_consultant(self):
        """
        Scenario: Architectural feature gets Consultant level (more supervision)
          Given a data contract with type "feature" and level "L4"
          When the autonomy level is computed
          Then the autonomy_level should be "L3" (Consultant)
          And the pipeline should checkpoint after Reconnaissance
        """
        from agents.autonomy import compute_autonomy_level

        contract = {"type": "feature", "level": "L4", "tech_stack": ["Terraform", "AWS"]}
        result = compute_autonomy_level(contract)

        assert result.level == "L3"
        assert result.name == "Consultant"
        assert "after_reconnaissance" in result.human_checkpoints
        assert "pr_review" in result.human_checkpoints

    def test_documentation_defaults_to_observer(self):
        """
        Scenario: Documentation tasks run fully autonomous
          Given a data contract with type "documentation"
          When the autonomy level is computed
          Then the autonomy_level should be "L5" (Observer)
        """
        from agents.autonomy import compute_autonomy_level

        contract = {"type": "documentation", "level": "L3", "tech_stack": []}
        result = compute_autonomy_level(contract)

        assert result.level == "L5"
        assert result.name == "Observer"

    def test_explicit_override_takes_precedence(self):
        """
        Scenario: Human can override the computed autonomy level
          Given a data contract with type "bugfix" and level "L2"
          And an explicit autonomy_level "L3" in the contract
          When the autonomy level is computed
          Then the autonomy_level should be "L3" (Consultant)
          Because the human override takes precedence over defaults
        """
        from agents.autonomy import compute_autonomy_level

        contract = {
            "type": "bugfix", "level": "L2",
            "tech_stack": ["Python"],
            "autonomy_level": "L3",  # Human override
        }
        result = compute_autonomy_level(contract)

        assert result.level == "L3"
        assert result.name == "Consultant"

    def test_infrastructure_defaults_to_approver(self):
        """
        Scenario: Infrastructure tasks get Approver level (risky but well-scoped)
          Given a data contract with type "infrastructure" and level "L3"
          When the autonomy level is computed
          Then the autonomy_level should be "L4" (Approver)
        """
        from agents.autonomy import compute_autonomy_level

        contract = {"type": "infrastructure", "level": "L3", "tech_stack": ["Terraform"]}
        result = compute_autonomy_level(contract)

        assert result.level == "L4"
        assert result.name == "Approver"


# ═══════════════════════════════════════════════════════════════════
# Feature: Pipeline Adapts to Autonomy Level
# ═══════════════════════════════════════════════════════════════════


class TestPipelineAdaptsToAutonomy:
    """
    Feature: The Orchestrator adapts pipeline behavior based on autonomy level
      As a Code Factory
      I want to run fewer gates for high-autonomy tasks
      So that simple tasks complete faster without sacrificing safety for complex ones
    """

    def test_l5_observer_skips_adversarial_gate(self):
        """
        Scenario: Observer level skips the adversarial challenge
          Given a task with autonomy_level "L5"
          When the pipeline gates are resolved
          Then the adversarial gate should be skipped
          And the inner loop gates should still run (lint, test, build)
        """
        from agents.autonomy import resolve_pipeline_gates

        gates = resolve_pipeline_gates(autonomy_level="L5")

        assert "adversarial_challenge" not in gates.outer_gates
        assert "lint" in gates.inner_gates
        assert "unit_test" in gates.inner_gates
        assert "build" in gates.inner_gates

    def test_l4_approver_runs_full_outer_loop(self):
        """
        Scenario: Approver level runs the full outer loop
          Given a task with autonomy_level "L4"
          When the pipeline gates are resolved
          Then all outer loop gates should run
          And the only human checkpoint is PR review
        """
        from agents.autonomy import resolve_pipeline_gates

        gates = resolve_pipeline_gates(autonomy_level="L4")

        assert "dor_gate" in gates.outer_gates
        assert "constraint_extraction" in gates.outer_gates
        assert "adversarial_challenge" in gates.outer_gates
        assert "ship_readiness" in gates.outer_gates
        assert gates.human_checkpoints == ["pr_review"]

    def test_l3_consultant_adds_mid_pipeline_checkpoint(self):
        """
        Scenario: Consultant level adds a checkpoint after reconnaissance
          Given a task with autonomy_level "L3"
          When the pipeline gates are resolved
          Then there should be a human checkpoint after reconnaissance
          And another checkpoint at PR review
        """
        from agents.autonomy import resolve_pipeline_gates

        gates = resolve_pipeline_gates(autonomy_level="L3")

        assert "after_reconnaissance" in gates.human_checkpoints
        assert "pr_review" in gates.human_checkpoints

    def test_l2_collaborator_checkpoints_every_phase(self):
        """
        Scenario: Collaborator level requires human approval at every phase
          Given a task with autonomy_level "L2"
          When the pipeline gates are resolved
          Then there should be checkpoints after recon, after engineering, and at PR
        """
        from agents.autonomy import resolve_pipeline_gates

        gates = resolve_pipeline_gates(autonomy_level="L2")

        assert "after_reconnaissance" in gates.human_checkpoints
        assert "after_engineering" in gates.human_checkpoints
        assert "pr_review" in gates.human_checkpoints
