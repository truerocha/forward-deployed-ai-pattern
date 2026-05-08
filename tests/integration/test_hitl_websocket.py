"""
Integration Test: Human-in-the-Loop WebSocket Behavior.

Validates that the HumanInputTool behaves correctly at different autonomy
levels, including tool availability, timeout behavior, and result serialization.

Tests are split into two groups:
  - Local tests: autonomy logic, dataclass serialization (no AWS needed)
  - WebSocket tests: gated by FDE_INTEGRATION_TESTS_ENABLED (require AWS)

Activity: 4.21
Ref: src/tools/human_input_tool.py, src/core/autonomy.py
"""

import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest

from src.core.autonomy import (
    AutonomyLevel,
    AutonomyState,
    can_use_hitl,
    get_timeout_behavior,
)
from src.tools.human_input_tool import (
    HumanInputResult,
    HumanInputTool,
    HumanInputUnavailable,
)

# ─── Fixtures ───────────────────────────────────────────────────

INTEGRATION_ENABLED = os.environ.get("FDE_INTEGRATION_TESTS_ENABLED", "false").lower() == "true"

skip_integration = pytest.mark.skipif(
    not INTEGRATION_ENABLED,
    reason="FDE_INTEGRATION_TESTS_ENABLED not set — skipping WebSocket integration tests",
)


@pytest.fixture
def mock_boto3():
    """Patch boto3 to avoid real AWS calls in local tests."""
    with patch("src.tools.human_input_tool.boto3") as mock:
        mock_dynamodb = MagicMock()
        mock_apigw = MagicMock()
        mock.resource.return_value = mock_dynamodb
        mock.client.return_value = mock_apigw
        mock.dynamodb = MagicMock()
        mock.dynamodb.conditions = MagicMock()
        mock.dynamodb.conditions.Key.return_value = MagicMock()
        yield {
            "boto3": mock,
            "dynamodb": mock_dynamodb,
            "apigw": mock_apigw,
        }


def _make_tool(autonomy_level: str, mock_boto3_fixture) -> HumanInputTool:
    """Create a HumanInputTool with mocked AWS clients."""
    tool = HumanInputTool(
        project_id="PROJ-TEST-001",
        websocket_endpoint="https://test.execute-api.us-east-1.amazonaws.com/$default",
        connections_table="fde-ws-connections-test",
        autonomy_level=autonomy_level,
        timeout_seconds=2,  # Short timeout for tests
    )
    return tool


# ─── Local Tests: Autonomy Level Gating ─────────────────────────


class TestHITLAvailabilityByLevel:
    """Test that HITL tool availability matches autonomy level rules."""

    def test_l1_hitl_available(self, mock_boto3):
        """L1 (Operator) — HITL tool is available."""
        tool = _make_tool("L1", mock_boto3)
        assert tool.is_available() is True

    def test_l2_hitl_available(self, mock_boto3):
        """L2 (Collaborator) — HITL tool is available."""
        tool = _make_tool("L2", mock_boto3)
        assert tool.is_available() is True

    def test_l3_hitl_available(self, mock_boto3):
        """L3 (Consultant) — HITL tool is available."""
        tool = _make_tool("L3", mock_boto3)
        assert tool.is_available() is True

    def test_l4_hitl_not_available(self, mock_boto3):
        """L4 (Approver) — HITL tool is NOT available."""
        tool = _make_tool("L4", mock_boto3)
        assert tool.is_available() is False

    def test_l5_hitl_not_available(self, mock_boto3):
        """L5 (Observer) — HITL tool is NOT available."""
        tool = _make_tool("L5", mock_boto3)
        assert tool.is_available() is False

    def test_l4_ask_raises_unavailable(self, mock_boto3):
        """L4 — calling ask() raises HumanInputUnavailable."""
        tool = _make_tool("L4", mock_boto3)
        with pytest.raises(HumanInputUnavailable) as exc_info:
            tool.ask("Should I proceed?")
        assert "L4" in str(exc_info.value)

    def test_l5_ask_raises_unavailable(self, mock_boto3):
        """L5 — calling ask() raises HumanInputUnavailable."""
        tool = _make_tool("L5", mock_boto3)
        with pytest.raises(HumanInputUnavailable) as exc_info:
            tool.ask("Should I proceed?")
        assert "L5" in str(exc_info.value)


class TestHITLAvailabilityViaAutonomyModule:
    """Test can_use_hitl() from the autonomy module directly."""

    @pytest.mark.parametrize("level", ["L1", "L2", "L3"])
    def test_hitl_enabled_levels(self, level):
        """L1/L2/L3 allow HITL."""
        assert can_use_hitl(level) is True

    @pytest.mark.parametrize("level", ["L4", "L5"])
    def test_hitl_disabled_levels(self, level):
        """L4/L5 do not allow HITL."""
        assert can_use_hitl(level) is False

    def test_hitl_with_enum(self):
        """Works with AutonomyLevel enum values."""
        assert can_use_hitl(AutonomyLevel.L2) is True
        assert can_use_hitl(AutonomyLevel.L5) is False


# ─── Local Tests: Timeout Behavior ──────────────────────────────


class TestTimeoutBehavior:
    """Test timeout behavior varies correctly by autonomy level."""

    def test_l2_timeout_aborts(self):
        """L2 timeout behavior is 'abort' — human MUST respond."""
        assert get_timeout_behavior("L2") == "abort"

    def test_l3_timeout_infers(self):
        """L3 timeout behavior is 'infer' — agent proceeds with best guess."""
        assert get_timeout_behavior("L3") == "infer"

    def test_l1_timeout_aborts(self):
        """L1 timeout behavior is 'abort'."""
        assert get_timeout_behavior("L1") == "abort"

    def test_l4_timeout_skips(self):
        """L4 timeout behavior is 'skip' — HITL not used."""
        assert get_timeout_behavior("L4") == "skip"

    def test_l5_timeout_skips(self):
        """L5 timeout behavior is 'skip' — HITL not used."""
        assert get_timeout_behavior("L5") == "skip"

    def test_timeout_with_enum(self):
        """Works with AutonomyLevel enum values."""
        assert get_timeout_behavior(AutonomyLevel.L2) == "abort"
        assert get_timeout_behavior(AutonomyLevel.L3) == "infer"


class TestTimeoutHandling:
    """Test that timeout produces correct HumanInputResult based on level."""

    def test_l2_timeout_result_has_abort_action(self, mock_boto3):
        """L2 timeout produces result with timeout_action='abort'."""
        tool = _make_tool("L2", mock_boto3)

        # Mock the DynamoDB table to simulate no response (timeout)
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": {"request_id": "test", "status": "pending"}}
        mock_table.put_item.return_value = {}
        mock_table.update_item.return_value = {}
        mock_boto3["dynamodb"].Table.return_value = mock_table

        # Mock connections query to return empty (no clients)
        mock_table.query.return_value = {"Items": []}

        result = tool.ask("Should I proceed?")

        assert result.timed_out is True
        assert result.timeout_action == "abort"
        assert result.answered is False
        assert result.needs_review is False

    def test_l3_timeout_result_has_infer_action(self, mock_boto3):
        """L3 timeout produces result with timeout_action='infer' and needs_review=True."""
        tool = _make_tool("L3", mock_boto3)

        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": {"request_id": "test", "status": "pending"}}
        mock_table.put_item.return_value = {}
        mock_table.update_item.return_value = {}
        mock_boto3["dynamodb"].Table.return_value = mock_table
        mock_table.query.return_value = {"Items": []}

        result = tool.ask("Should I proceed?")

        assert result.timed_out is True
        assert result.timeout_action == "infer"
        assert result.answered is False
        assert result.needs_review is True


# ─── Local Tests: HumanInputResult Serialization ────────────────


class TestHumanInputResultSerialization:
    """Test HumanInputResult dataclass serialization."""

    def test_answered_result_to_dict(self):
        """Answered result serializes all fields correctly."""
        result = HumanInputResult(
            request_id="req-123",
            answered=True,
            response={"text": "Yes, proceed with migration"},
            timed_out=False,
            timeout_action="",
            needs_review=False,
        )

        d = result.to_dict()

        assert d["request_id"] == "req-123"
        assert d["answered"] is True
        assert d["response"] == {"text": "Yes, proceed with migration"}
        assert d["timed_out"] is False
        assert d["timeout_action"] == ""
        assert d["needs_review"] is False

    def test_timed_out_result_to_dict(self):
        """Timed-out result serializes timeout fields correctly."""
        result = HumanInputResult(
            request_id="req-456",
            answered=False,
            response=None,
            timed_out=True,
            timeout_action="abort",
            needs_review=False,
        )

        d = result.to_dict()

        assert d["request_id"] == "req-456"
        assert d["answered"] is False
        assert d["response"] is None
        assert d["timed_out"] is True
        assert d["timeout_action"] == "abort"

    def test_result_to_dict_is_json_serializable(self):
        """to_dict() output can be serialized to JSON without errors."""
        result = HumanInputResult(
            request_id="req-789",
            answered=True,
            response={"choice": "option_a", "confidence": 0.95},
            timed_out=False,
        )

        json_str = json.dumps(result.to_dict())
        parsed = json.loads(json_str)

        assert parsed["request_id"] == "req-789"
        assert parsed["response"]["confidence"] == 0.95

    def test_result_with_none_response_serializes(self):
        """Result with None response serializes cleanly."""
        result = HumanInputResult(
            request_id="req-000",
            answered=False,
            response=None,
            timed_out=True,
            timeout_action="infer",
            needs_review=True,
        )

        json_str = json.dumps(result.to_dict())
        parsed = json.loads(json_str)

        assert parsed["response"] is None
        assert parsed["needs_review"] is True


# ─── Local Tests: AutonomyState Integration ─────────────────────


class TestAutonomyStateHITLIntegration:
    """Test AutonomyState provides correct HITL information."""

    def test_state_can_hitl_at_l2(self):
        """AutonomyState.can_hitl is True at L2."""
        state = AutonomyState(level=AutonomyLevel.L2, project_id="PROJ-1", task_id="T-1")
        assert state.can_hitl is True

    def test_state_cannot_hitl_at_l4(self):
        """AutonomyState.can_hitl is False at L4."""
        state = AutonomyState(level=AutonomyLevel.L4, project_id="PROJ-1", task_id="T-1")
        assert state.can_hitl is False

    def test_state_timeout_behavior_at_l3(self):
        """AutonomyState.timeout_behavior is 'infer' at L3."""
        state = AutonomyState(level=AutonomyLevel.L3, project_id="PROJ-1", task_id="T-1")
        assert state.timeout_behavior == "infer"

    def test_state_to_dict_includes_hitl_fields(self):
        """AutonomyState.to_dict() includes can_hitl and timeout_behavior."""
        state = AutonomyState(level=AutonomyLevel.L2, project_id="PROJ-1", task_id="T-1")
        d = state.to_dict()

        assert "can_hitl" in d
        assert "timeout_behavior" in d
        assert d["can_hitl"] is True
        assert d["timeout_behavior"] == "abort"

    def test_human_input_in_available_tools_at_l2(self):
        """'human_input' is in available_tools at L2."""
        state = AutonomyState(level=AutonomyLevel.L2, project_id="PROJ-1", task_id="T-1")
        assert "human_input" in state.available_tools

    def test_human_input_not_in_available_tools_at_l5(self):
        """'human_input' is NOT in available_tools at L5."""
        state = AutonomyState(level=AutonomyLevel.L5, project_id="PROJ-1", task_id="T-1")
        assert "human_input" not in state.available_tools


# ─── WebSocket Integration Tests (gated) ────────────────────────


@skip_integration
class TestHITLWebSocketIntegration:
    """Integration tests requiring live AWS WebSocket infrastructure.

    Gated by FDE_INTEGRATION_TESTS_ENABLED=true.
    These tests validate the full round-trip: question → WebSocket → DynamoDB → response.
    """

    @pytest.fixture
    def live_tool(self):
        """Create a HumanInputTool connected to real AWS infrastructure."""
        return HumanInputTool(
            project_id=os.environ.get("FDE_TEST_PROJECT_ID", "PROJ-INTEGRATION-TEST"),
            websocket_endpoint=os.environ["FDE_WS_ENDPOINT"],
            connections_table=os.environ.get("FDE_CONNECTIONS_TABLE", "fde-ws-connections"),
            autonomy_level="L2",
            timeout_seconds=10,
        )

    def test_broadcast_question_no_error(self, live_tool):
        """Broadcasting a question to WebSocket does not raise errors."""
        # Even with no connected clients, this should not raise
        result = live_tool.ask("Integration test question — please ignore")
        # With no connected clients, it will timeout
        assert result.timed_out is True

    def test_hitl_request_stored_in_dynamodb(self, live_tool):
        """HITL request is persisted in DynamoDB after ask()."""
        import boto3

        result = live_tool.ask("DynamoDB persistence test")
        # Verify the request was stored
        dynamodb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        table = dynamodb.Table(os.environ.get("HITL_TABLE", "fde-hitl-requests"))
        item = table.get_item(Key={"request_id": result.request_id})
        assert "Item" in item
        assert item["Item"]["question"] == "DynamoDB persistence test"
        assert item["Item"]["status"] in ("pending", "timed_out")

    def test_timeout_updates_status_in_dynamodb(self, live_tool):
        """After timeout, HITL record status is updated to 'timed_out'."""
        import boto3

        result = live_tool.ask("Timeout status test")
        assert result.timed_out is True

        dynamodb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        table = dynamodb.Table(os.environ.get("HITL_TABLE", "fde-hitl-requests"))
        item = table.get_item(Key={"request_id": result.request_id})
        assert item["Item"]["status"] == "timed_out"
