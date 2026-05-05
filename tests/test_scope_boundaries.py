"""
BDD Scenarios: Formal Scope Boundaries (ADR-013, Decision 4)

These tests validate that the Code Factory has explicit, enforceable
scope boundaries — what it does, what it doesn't, and how it rejects
out-of-scope tasks.

Source: "Levels of Autonomy for AI Agents" (Feng et al., Jun 2025) — autonomy certificates
Source: "WhatsCode" (Mao et al., Dec 2025) — organizational factors

All scenarios MUST FAIL until the scope_boundaries module is implemented.
"""

import pytest


# ═══════════════════════════════════════════════════════════════════
# Feature: Scope Boundary Enforcement
# ═══════════════════════════════════════════════════════════════════


class TestScopeBoundaryEnforcement:
    """
    Feature: The DoR Gate rejects tasks that are out of scope
      As a Code Factory
      I want to reject tasks I cannot handle with measurable confidence
      So that my performance metrics reflect actual capability, not failed attempts
    """

    def test_reject_task_without_acceptance_criteria(self):
        """
        Scenario: Task without acceptance criteria is out of scope
          Given a data contract with empty acceptance_criteria
          When the scope boundary check runs
          Then the task should be rejected with reason "no_halting_condition"
          Because without acceptance criteria, the agent has no halting condition
        """
        from agents.scope_boundaries import check_scope

        contract = {
            "title": "Make the app better",
            "type": "feature",
            "level": "L3",
            "tech_stack": ["Python"],
            "acceptance_criteria": [],
        }
        result = check_scope(contract)

        assert result.in_scope is False
        assert result.rejection_reason == "no_halting_condition"
        assert "acceptance_criteria" in result.details

    def test_reject_task_without_tech_stack(self):
        """
        Scenario: Task without tech_stack is out of scope
          Given a data contract with empty tech_stack
          When the scope boundary check runs
          Then the task should be rejected with reason "no_tech_stack"
          Because the Agent Builder cannot provision a specialized agent
        """
        from agents.scope_boundaries import check_scope

        contract = {
            "title": "Fix the login bug",
            "type": "bugfix",
            "level": "L2",
            "tech_stack": [],
            "acceptance_criteria": ["Login works"],
        }
        result = check_scope(contract)

        assert result.in_scope is False
        assert result.rejection_reason == "no_tech_stack"

    def test_reject_task_requesting_production_deploy(self):
        """
        Scenario: Task that requests production deployment is out of scope
          Given a data contract with description containing "deploy to production"
          When the scope boundary check runs
          Then the task should be rejected with reason "production_deploy_forbidden"
          Because the factory NEVER deploys to production (governance boundary)
        """
        from agents.scope_boundaries import check_scope

        contract = {
            "title": "Deploy v2.1 to production",
            "type": "infrastructure",
            "level": "L3",
            "tech_stack": ["AWS"],
            "acceptance_criteria": ["v2.1 is live in production"],
            "description": "Deploy the new version to production environment",
        }
        result = check_scope(contract)

        assert result.in_scope is False
        assert result.rejection_reason == "production_deploy_forbidden"

    def test_accept_well_scoped_feature(self):
        """
        Scenario: Well-scoped feature with all required fields is in scope
          Given a data contract with title, type, level, tech_stack, and acceptance_criteria
          When the scope boundary check runs
          Then the task should be accepted
          And the confidence_level should be "high"
        """
        from agents.scope_boundaries import check_scope

        contract = {
            "title": "Add pagination to /users endpoint",
            "type": "feature",
            "level": "L3",
            "tech_stack": ["Python", "FastAPI"],
            "acceptance_criteria": [
                "GET /users accepts page and page_size params",
                "Response includes total_count and next_page",
                "Default page_size is 20",
            ],
            "description": "Add offset-based pagination to the users list endpoint.",
        }
        result = check_scope(contract)

        assert result.in_scope is True
        assert result.confidence_level == "high"

    def test_warn_task_with_unsupported_language(self):
        """
        Scenario: Task with a tech_stack that has no tooling gets a warning
          Given a data contract with tech_stack ["Haskell"]
          And Haskell has no configured lint/test/build commands
          When the scope boundary check runs
          Then the task should be accepted with confidence "low"
          And a warning should indicate "no_inner_loop_tooling"
        """
        from agents.scope_boundaries import check_scope

        contract = {
            "title": "Fix type error in parser",
            "type": "bugfix",
            "level": "L2",
            "tech_stack": ["Haskell"],
            "acceptance_criteria": ["Parser compiles without errors"],
        }
        result = check_scope(contract)

        assert result.in_scope is True
        assert result.confidence_level == "low"
        assert "no_inner_loop_tooling" in result.warnings

    def test_reject_task_requesting_merge(self):
        """
        Scenario: Task that requests merging a PR is out of scope
          Given a data contract with description containing "merge the PR"
          When the scope boundary check runs
          Then the task should be rejected with reason "merge_forbidden"
          Because the factory NEVER merges — human approves outcomes
        """
        from agents.scope_boundaries import check_scope

        contract = {
            "title": "Merge PR #42 to main",
            "type": "infrastructure",
            "level": "L2",
            "tech_stack": ["Git"],
            "acceptance_criteria": ["PR #42 is merged"],
            "description": "Merge the approved PR to main branch",
        }
        result = check_scope(contract)

        assert result.in_scope is False
        assert result.rejection_reason == "merge_forbidden"

    def test_scope_check_returns_measurable_confidence(self):
        """
        Scenario: Every scope check returns a confidence level
          Given any data contract
          When the scope boundary check runs
          Then the result should include confidence_level in ["high", "medium", "low"]
          And the confidence should be based on:
            - tech_stack has tooling configured → +1
            - acceptance_criteria are specific (>= 3 items) → +1
            - constraints are present → +1
            - related_docs are present → +1
        """
        from agents.scope_boundaries import check_scope

        # High confidence: all signals present
        contract_high = {
            "title": "Add caching layer",
            "type": "feature",
            "level": "L3",
            "tech_stack": ["Python", "Redis"],
            "acceptance_criteria": ["Cache hit returns in <10ms", "Cache miss falls through", "TTL is configurable"],
            "constraints": "Must not change the existing API contract",
            "related_docs": ["docs/design/caching-strategy.md"],
        }
        result_high = check_scope(contract_high)
        assert result_high.confidence_level == "high"

        # Low confidence: minimal signals
        contract_low = {
            "title": "Fix something",
            "type": "bugfix",
            "level": "L2",
            "tech_stack": ["Cobol"],
            "acceptance_criteria": ["It works"],
        }
        result_low = check_scope(contract_low)
        assert result_low.confidence_level == "low"

    def test_scope_boundaries_document_exists(self):
        """
        Scenario: The scope boundaries are documented as a formal artifact
          Given the Code Factory repository
          When I look for the scope boundaries document
          Then docs/design/scope-boundaries.md should exist
          And it should define in-scope capabilities
          And it should define out-of-scope items
          And it should define performance targets per autonomy level
        """
        import os

        doc_path = "docs/design/scope-boundaries.md"
        assert os.path.exists(doc_path), f"Scope boundaries document not found at {doc_path}"

        with open(doc_path) as f:
            content = f.read()

        assert "## In-Scope" in content
        assert "## Out-of-Scope" in content
        assert "## Performance Targets" in content
