"""
BDD Scenarios: Failure Mode Taxonomy (ADR-013, Decision 2)

These tests validate that the Code Factory classifies WHY tasks fail,
not just IF they fail. The taxonomy enables learning from failures.

Source: "SWE-Bench Pro" (Deng et al., Sep 2025) — failure mode clustering
Source: "SWE-AGI" (Zhang et al., Feb 2026) — spec-intensive degradation

All scenarios MUST FAIL until the failure_modes module is implemented.
"""

import pytest


# ═══════════════════════════════════════════════════════════════════
# Feature: Failure Mode Classification
# ═══════════════════════════════════════════════════════════════════


class TestFailureModeClassification:
    """
    Feature: The Circuit Breaker classifies failure modes
      As a Staff Engineer
      I want to know WHY tasks fail (not just that they failed)
      So that I can fix systemic issues and improve the factory
    """

    def test_classify_spec_ambiguity(self):
        """
        Scenario: Task fails because the spec is ambiguous
          Given a task execution that produced 4+ DoR warnings about ambiguity
          And the agent could not determine intent from the description
          When the failure mode is classified
          Then the failure_mode should be "FM-01" (SPEC_AMBIGUITY)
          And the recovery_action should be "request_clarification"
        """
        from agents.failure_modes import classify_failure

        context = {
            "dor_warnings": [
                "CTR-001: Ambiguous constraint on 'auth_method'",
                "CTR-002: Ambiguous constraint on 'data_format'",
                "CTR-003: Ambiguous constraint on 'error_handling'",
                "CTR-004: Ambiguous constraint on 'retry_policy'",
            ],
            "error_message": "Cannot determine implementation approach from spec",
            "exit_code": 1,
            "stage": "engineering",
        }
        result = classify_failure(context)

        assert result.code == "FM-01"
        assert result.category == "SPEC_AMBIGUITY"
        assert result.recovery_action == "request_clarification"

    def test_classify_constraint_conflict(self):
        """
        Scenario: Task fails because constraints contradict each other
          Given extracted constraints where "auth must_be OAuth2" AND "auth must_be BasicAuth"
          When the failure mode is classified
          Then the failure_mode should be "FM-02" (CONSTRAINT_CONFLICT)
          And the recovery_action should be "request_human_resolution"
        """
        from agents.failure_modes import classify_failure

        context = {
            "dor_failures": [
                {"constraint_id": "CTR-001", "message": "Conflicting auth requirements"},
            ],
            "error_message": "Constraint conflict: auth_method has contradictory values",
            "exit_code": 1,
            "stage": "constraint_extraction",
        }
        result = classify_failure(context)

        assert result.code == "FM-02"
        assert result.category == "CONSTRAINT_CONFLICT"
        assert result.recovery_action == "request_human_resolution"

    def test_classify_tool_failure(self):
        """
        Scenario: Task fails because an external tool (npm, docker) crashed
          Given a shell command that returned exit code != 0
          And the error contains "ECONNREFUSED" or "command not found"
          When the failure mode is classified
          Then the failure_mode should be "FM-03" (TOOL_FAILURE)
          And the recovery_action should be "retry_with_backoff"
        """
        from agents.failure_modes import classify_failure

        context = {
            "error_message": "npm install failed: ECONNREFUSED",
            "exit_code": 1,
            "stage": "engineering",
            "command_output": "npm ERR! network request to https://registry.npmjs.org failed",
        }
        result = classify_failure(context)

        assert result.code == "FM-03"
        assert result.category == "TOOL_FAILURE"
        assert result.recovery_action == "retry_with_backoff"

    def test_classify_test_regression(self):
        """
        Scenario: Task fails because new code breaks existing tests
          Given tests that passed before the agent's changes
          And those same tests now fail
          When the failure mode is classified
          Then the failure_mode should be "FM-06" (TEST_REGRESSION)
          And the recovery_action should be "rollback_and_retry"
        """
        from agents.failure_modes import classify_failure

        context = {
            "error_message": "3 tests failed that previously passed",
            "exit_code": 1,
            "stage": "inner_loop.unit_test",
            "tests_before": {"passed": 42, "failed": 0},
            "tests_after": {"passed": 39, "failed": 3},
        }
        result = classify_failure(context)

        assert result.code == "FM-06"
        assert result.category == "TEST_REGRESSION"
        assert result.recovery_action == "rollback_and_retry"

    def test_classify_complexity_exceeded(self):
        """
        Scenario: Task fails because it's too complex for the agent
          Given a task that requires changes across 20+ files
          And the agent exceeded the maximum execution time
          When the failure mode is classified
          Then the failure_mode should be "FM-05" (COMPLEXITY_EXCEEDED)
          And the recovery_action should be "decompose_into_subtasks"
        """
        from agents.failure_modes import classify_failure

        context = {
            "error_message": "Execution exceeded time limit",
            "exit_code": 1,
            "stage": "engineering",
            "files_modified": 23,
            "execution_time_ms": 600000,  # 10 minutes
            "max_execution_time_ms": 300000,  # 5 minute limit
        }
        result = classify_failure(context)

        assert result.code == "FM-05"
        assert result.category == "COMPLEXITY_EXCEEDED"
        assert result.recovery_action == "decompose_into_subtasks"

    def test_classify_timeout(self):
        """
        Scenario: Task fails due to timeout without complexity indicators
          Given a task that exceeded the time limit
          And the number of files modified is small (< 5)
          When the failure mode is classified
          Then the failure_mode should be "FM-08" (TIMEOUT)
          And the recovery_action should be "rollback_and_report"
        """
        from agents.failure_modes import classify_failure

        context = {
            "error_message": "TIMEOUT: exceeded 300s",
            "exit_code": 1,
            "stage": "engineering",
            "files_modified": 2,
            "execution_time_ms": 300000,
            "max_execution_time_ms": 300000,
        }
        result = classify_failure(context)

        assert result.code == "FM-08"
        assert result.category == "TIMEOUT"
        assert result.recovery_action == "rollback_and_report"

    def test_classify_unknown_falls_to_catchall(self):
        """
        Scenario: Unrecognized failure gets FM-99 (UNKNOWN)
          Given a failure with no recognizable pattern
          When the failure mode is classified
          Then the failure_mode should be "FM-99" (UNKNOWN)
          And the full context should be preserved for post-mortem
        """
        from agents.failure_modes import classify_failure

        context = {
            "error_message": "Something unexpected happened",
            "exit_code": 137,
            "stage": "reporting",
        }
        result = classify_failure(context)

        assert result.code == "FM-99"
        assert result.category == "UNKNOWN"
        assert result.recovery_action == "log_and_report"
        assert result.raw_context == context

    def test_failure_mode_recorded_in_dora_metrics(self):
        """
        Scenario: Failure mode is recorded as a DORA metric dimension
          Given a classified failure with code "FM-06"
          When the task outcome is recorded
          Then the metric event dimensions should include failure_mode "FM-06"
          And the metric event dimensions should include failure_category "TEST_REGRESSION"
        """
        from agents.failure_modes import FailureModeResult

        result = FailureModeResult(
            code="FM-06",
            category="TEST_REGRESSION",
            recovery_action="rollback_and_retry",
            raw_context={},
        )

        # The DORA collector should accept this as a dimension
        dimensions = result.to_metric_dimensions()

        assert dimensions["failure_mode"] == "FM-06"
        assert dimensions["failure_category"] == "TEST_REGRESSION"
        assert dimensions["recovery_action"] == "rollback_and_retry"
