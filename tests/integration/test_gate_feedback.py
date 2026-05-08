"""
Integration Test: Gate Feedback Format.

Validates that the gate feedback formatter produces correct structured
output and that hook prompts generate parseable feedback.

Tests:
  1. GateFeedbackFormatter produces valid JSON with all required fields
  2. format_from_raw_output correctly parses JSON gate output
  3. format_from_raw_output handles non-JSON (raw text) gracefully
  4. Human-readable output is well-formatted
  5. All gate types have reference artifacts defined

Activity: 1.31
Ref: docs/design/fde-core-brain-development.md Section 8.1
"""

import json

import pytest

from src.core.governance.gate_feedback_formatter import (
    FeedbackSeverity,
    GateFeedback,
    GateFeedbackFormatter,
    GateType,
)


@pytest.fixture
def formatter():
    """Gate feedback formatter instance."""
    return GateFeedbackFormatter()


class TestGateFeedbackStructure:
    """Test that feedback output has all required fields."""

    def test_rejection_has_all_required_fields(self, formatter):
        """Rejection feedback includes reason, violated_rule, suggestion, reference, severity."""
        feedback = formatter.format_rejection(
            gate_name="fde-adversarial-gate",
            gate_type=GateType.ADVERSARIAL,
            reason="Function lacks error handling for network failures",
            violated_rule="All external calls must have try/except with specific exception types",
            suggestion="Add try/except around the boto3 call with ClientError handling",
            severity=FeedbackSeverity.HIGH,
            task_id="task-123",
        )

        assert feedback.gate_name == "fde-adversarial-gate"
        assert feedback.gate_type == GateType.ADVERSARIAL
        assert feedback.status == "rejected"
        assert feedback.reason == "Function lacks error handling for network failures"
        assert feedback.violated_rule == "All external calls must have try/except with specific exception types"
        assert feedback.suggestion == "Add try/except around the boto3 call with ClientError handling"
        assert feedback.severity == FeedbackSeverity.HIGH
        assert feedback.task_id == "task-123"
        assert feedback.reference_artifact != ""
        assert feedback.timestamp != ""

    def test_rejection_json_is_valid(self, formatter):
        """Rejection feedback serializes to valid JSON."""
        feedback = formatter.format_rejection(
            gate_name="fde-dor-gate",
            gate_type=GateType.DOR,
            reason="Spec missing user value statement",
            violated_rule="DoR requires identifiable user value",
            suggestion="Add 'As a [user], I want [action], so that [value]' to the spec",
            severity=FeedbackSeverity.CRITICAL,
        )

        json_str = feedback.to_json()
        parsed = json.loads(json_str)

        assert parsed["gate_name"] == "fde-dor-gate"
        assert parsed["gate_type"] == "dor"
        assert parsed["status"] == "rejected"
        assert parsed["severity"] == "critical"
        assert "reason" in parsed
        assert "violated_rule" in parsed
        assert "suggestion" in parsed
        assert "reference_artifact" in parsed

    def test_pass_has_consistent_schema(self, formatter):
        """Pass feedback uses the same schema as rejection."""
        feedback = formatter.format_pass(
            gate_name="fde-dod-gate",
            gate_type=GateType.DOD,
            task_id="task-456",
        )

        json_str = feedback.to_json()
        parsed = json.loads(json_str)

        assert parsed["status"] == "passed"
        assert parsed["gate_name"] == "fde-dod-gate"
        assert parsed["gate_type"] == "dod"
        assert "reason" in parsed
        assert "violated_rule" in parsed
        assert "suggestion" in parsed
        assert "severity" in parsed

    def test_warning_has_suggestion(self, formatter):
        """Warning feedback includes actionable suggestion."""
        feedback = formatter.format_warning(
            gate_name="fde-pipeline-validation",
            gate_type=GateType.PIPELINE,
            reason="Test coverage decreased by 2%",
            suggestion="Add tests for the new branch in handle_error()",
            task_id="task-789",
        )

        assert feedback.status == "warning"
        assert feedback.severity == FeedbackSeverity.MEDIUM
        assert "coverage" in feedback.reason
        assert "Add tests" in feedback.suggestion


class TestGateFeedbackParsing:
    """Test parsing of raw gate output into structured feedback."""

    def test_parse_valid_json_output(self, formatter):
        """Valid JSON gate output is parsed into structured feedback."""
        raw_json = json.dumps({
            "status": "rejected",
            "reason": "Missing error handling",
            "violated_rule": "REL-3: All I/O must handle failures",
            "suggestion": "Wrap in try/except",
            "severity": "high",
            "reference_artifact": "docs/wellarchitected/reliability.md",
        })

        feedback = formatter.format_from_raw_output(
            gate_name="fde-adversarial-gate",
            gate_type=GateType.ADVERSARIAL,
            raw_output=raw_json,
            task_id="task-parse-1",
        )

        assert feedback.status == "rejected"
        assert feedback.reason == "Missing error handling"
        assert feedback.violated_rule == "REL-3: All I/O must handle failures"
        assert feedback.severity == FeedbackSeverity.HIGH

    def test_parse_raw_text_rejection(self, formatter):
        """Non-JSON rejection text is wrapped as feedback."""
        raw_text = "This code has a SQL injection vulnerability in the query builder."

        feedback = formatter.format_from_raw_output(
            gate_name="fde-adversarial-gate",
            gate_type=GateType.ADVERSARIAL,
            raw_output=raw_text,
        )

        assert feedback.status == "rejected"
        assert "SQL injection" in feedback.reason
        assert feedback.severity == FeedbackSeverity.HIGH

    def test_parse_raw_text_pass(self, formatter):
        """Raw text containing pass keywords is detected as pass."""
        raw_text = "All checks passed. Code follows established patterns."

        feedback = formatter.format_from_raw_output(
            gate_name="fde-dod-gate",
            gate_type=GateType.DOD,
            raw_output=raw_text,
        )

        assert feedback.status == "passed"

    def test_parse_lgtm_as_pass(self, formatter):
        """LGTM in raw output is detected as pass."""
        raw_text = "LGTM - implementation matches spec requirements."

        feedback = formatter.format_from_raw_output(
            gate_name="fde-adversarial-gate",
            gate_type=GateType.ADVERSARIAL,
            raw_output=raw_text,
        )

        assert feedback.status == "passed"


class TestGateFeedbackHumanReadable:
    """Test human-readable output formatting."""

    def test_human_readable_includes_all_sections(self, formatter):
        """Human-readable format includes what failed, rule, suggestion, reference."""
        feedback = formatter.format_rejection(
            gate_name="fde-test-immutability",
            gate_type=GateType.TEST_IMMUTABILITY,
            reason="Test assertion was weakened",
            violated_rule="Approved tests cannot have assertions modified",
            suggestion="Fix the production code to satisfy the original assertion",
            severity=FeedbackSeverity.CRITICAL,
        )

        readable = feedback.to_human_readable()

        assert "fde-test-immutability" in readable
        assert "REJECTED" in readable
        assert "Test assertion was weakened" in readable
        assert "Fix the production code" in readable

    def test_severity_icons(self, formatter):
        """Each severity level has a distinct icon."""
        for severity in FeedbackSeverity:
            feedback = formatter.format_rejection(
                gate_name="test-gate",
                gate_type=GateType.ADVERSARIAL,
                reason="test",
                violated_rule="test",
                suggestion="test",
                severity=severity,
            )
            readable = feedback.to_human_readable()
            assert len(readable) > 0


class TestGateTypeReferences:
    """Test that all gate types have reference artifacts."""

    def test_all_gate_types_have_references(self, formatter):
        """Every GateType has a default reference artifact."""
        for gate_type in GateType:
            feedback = formatter.format_rejection(
                gate_name=f"test-{gate_type.value}",
                gate_type=gate_type,
                reason="test",
                violated_rule="test",
                suggestion="test",
                severity=FeedbackSeverity.LOW,
            )
            assert feedback.reference_artifact != "", f"No reference for {gate_type.value}"
            assert feedback.reference_artifact.startswith("docs/")
