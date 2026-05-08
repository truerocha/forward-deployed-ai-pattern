"""
Integration Test: Streaming Events Serialization and EventEmitter.

Validates that all 8 event types serialize to valid JSON, BaseEvent.to_json()
produces parseable output, and EventEmitter handles edge cases gracefully.

All tests are local (no AWS needed for serialization tests). EventEmitter
tests use mocked boto3 to verify graceful handling of empty connection lists.

Activity: 4.22
Ref: src/api/events.py
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.api.events import (
    AgentCompletedEvent,
    AgentStartedEvent,
    AutonomyAdjustedEvent,
    BaseEvent,
    CostUpdateEvent,
    ErrorOccurredEvent,
    EventEmitter,
    FidelityScoredEvent,
    GateResultEvent,
    MilestoneReachedEvent,
)

# ─── All 8 Event Types ─────────────────────────────────────────

ALL_EVENT_CLASSES = [
    GateResultEvent,
    MilestoneReachedEvent,
    AgentStartedEvent,
    AgentCompletedEvent,
    ErrorOccurredEvent,
    AutonomyAdjustedEvent,
    CostUpdateEvent,
    FidelityScoredEvent,
]


# ─── Fixtures ───────────────────────────────────────────────────


@pytest.fixture
def gate_result_event():
    """Sample GateResultEvent."""
    return GateResultEvent(
        task_id="TASK-001",
        gate_name="fde-adversarial-gate",
        passed=False,
        details="Missing error handling for network failures",
        duration_ms=1250,
    )


@pytest.fixture
def milestone_event():
    """Sample MilestoneReachedEvent."""
    return MilestoneReachedEvent(
        task_id="TASK-002",
        milestone="spec_approved",
        phase="reconnaissance",
        message="Spec passed DoR gate with score 85/100",
    )


@pytest.fixture
def agent_started_event():
    """Sample AgentStartedEvent."""
    return AgentStartedEvent(
        task_id="TASK-003",
        agent_type="engineering",
        autonomy_level="L3",
        tools_available=["read_spec", "write_artifact", "run_shell_command", "human_input"],
    )


@pytest.fixture
def agent_completed_event():
    """Sample AgentCompletedEvent."""
    return AgentCompletedEvent(
        task_id="TASK-003",
        agent_type="engineering",
        success=True,
        duration_seconds=142.5,
        deliverable_url="https://github.com/org/repo/pull/42",
        summary="Implemented feature with 3 files changed, all tests passing",
    )


@pytest.fixture
def error_event():
    """Sample ErrorOccurredEvent."""
    return ErrorOccurredEvent(
        task_id="TASK-004",
        error_type="CircuitBreakerTripped",
        message="3 consecutive gate failures — halting execution",
        recoverable=False,
        phase="implementation",
    )


@pytest.fixture
def autonomy_event():
    """Sample AutonomyAdjustedEvent."""
    return AutonomyAdjustedEvent(
        task_id="TASK-005",
        previous_level="L4",
        new_level="L3",
        reason="Anti-instability loop detected repeated failures",
        escalation_count=2,
    )


@pytest.fixture
def cost_event():
    """Sample CostUpdateEvent."""
    return CostUpdateEvent(
        task_id="TASK-006",
        input_tokens=15000,
        output_tokens=3200,
        total_tokens=18200,
        estimated_cost_usd=0.045,
        model_id="anthropic.claude-sonnet-4-20250514",
    )


@pytest.fixture
def fidelity_event():
    """Sample FidelityScoredEvent."""
    return FidelityScoredEvent(
        task_id="TASK-007",
        score=0.82,
        max_score=1.0,
        dimensions={"correctness": 0.9, "completeness": 0.75, "style": 0.8},
        passed_threshold=True,
        threshold=0.7,
    )


# ─── Tests: All 8 Event Types Serialize to Valid JSON ───────────


class TestEventSerialization:
    """Test that all 8 event types serialize to valid JSON."""

    @pytest.mark.parametrize("event_class", ALL_EVENT_CLASSES)
    def test_event_type_serializes_to_valid_json(self, event_class):
        """Each event type produces valid JSON from to_json()."""
        event = event_class()
        json_str = event.to_json()

        # Must be valid JSON
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)

        # Must have event_type and timestamp
        assert "event_type" in parsed
        assert "timestamp" in parsed
        assert parsed["event_type"] != ""

    def test_gate_result_json_fields(self, gate_result_event):
        """GateResultEvent JSON includes all domain fields."""
        parsed = json.loads(gate_result_event.to_json())

        assert parsed["event_type"] == "gate_result"
        assert parsed["task_id"] == "TASK-001"
        assert parsed["gate_name"] == "fde-adversarial-gate"
        assert parsed["passed"] is False
        assert parsed["duration_ms"] == 1250

    def test_milestone_json_fields(self, milestone_event):
        """MilestoneReachedEvent JSON includes all domain fields."""
        parsed = json.loads(milestone_event.to_json())

        assert parsed["event_type"] == "milestone_reached"
        assert parsed["milestone"] == "spec_approved"
        assert parsed["phase"] == "reconnaissance"

    def test_agent_started_json_fields(self, agent_started_event):
        """AgentStartedEvent JSON includes tools_available list."""
        parsed = json.loads(agent_started_event.to_json())

        assert parsed["event_type"] == "agent_started"
        assert parsed["autonomy_level"] == "L3"
        assert isinstance(parsed["tools_available"], list)
        assert "human_input" in parsed["tools_available"]

    def test_agent_completed_json_fields(self, agent_completed_event):
        """AgentCompletedEvent JSON includes duration and deliverable."""
        parsed = json.loads(agent_completed_event.to_json())

        assert parsed["event_type"] == "agent_completed"
        assert parsed["success"] is True
        assert parsed["duration_seconds"] == 142.5
        assert "pull/42" in parsed["deliverable_url"]

    def test_error_json_fields(self, error_event):
        """ErrorOccurredEvent JSON includes error classification."""
        parsed = json.loads(error_event.to_json())

        assert parsed["event_type"] == "error_occurred"
        assert parsed["error_type"] == "CircuitBreakerTripped"
        assert parsed["recoverable"] is False
        assert parsed["phase"] == "implementation"

    def test_autonomy_adjusted_json_fields(self, autonomy_event):
        """AutonomyAdjustedEvent JSON includes level transition."""
        parsed = json.loads(autonomy_event.to_json())

        assert parsed["event_type"] == "autonomy_adjusted"
        assert parsed["previous_level"] == "L4"
        assert parsed["new_level"] == "L3"
        assert parsed["escalation_count"] == 2

    def test_cost_update_json_fields(self, cost_event):
        """CostUpdateEvent JSON includes token counts and cost."""
        parsed = json.loads(cost_event.to_json())

        assert parsed["event_type"] == "cost_update"
        assert parsed["total_tokens"] == 18200
        assert parsed["estimated_cost_usd"] == 0.045
        assert "claude" in parsed["model_id"]

    def test_fidelity_scored_json_fields(self, fidelity_event):
        """FidelityScoredEvent JSON includes dimensions dict."""
        parsed = json.loads(fidelity_event.to_json())

        assert parsed["event_type"] == "fidelity_scored"
        assert parsed["score"] == 0.82
        assert parsed["passed_threshold"] is True
        assert "correctness" in parsed["dimensions"]
        assert parsed["dimensions"]["correctness"] == 0.9


# ─── Tests: BaseEvent.to_json() Produces Parseable Output ───────


class TestBaseEventToJson:
    """Test BaseEvent.to_json() contract."""

    @pytest.mark.parametrize("event_class", ALL_EVENT_CLASSES)
    def test_to_json_returns_string(self, event_class):
        """to_json() returns a string, not bytes."""
        event = event_class()
        result = event.to_json()
        assert isinstance(result, str)

    @pytest.mark.parametrize("event_class", ALL_EVENT_CLASSES)
    def test_to_json_is_parseable(self, event_class):
        """to_json() output can be parsed back with json.loads()."""
        event = event_class()
        parsed = json.loads(event.to_json())
        assert isinstance(parsed, dict)

    def test_to_json_timestamp_is_iso_format(self, gate_result_event):
        """Timestamp in JSON is ISO 8601 format."""
        parsed = json.loads(gate_result_event.to_json())
        timestamp = parsed["timestamp"]
        # ISO 8601 timestamps contain 'T' separator and timezone info
        assert "T" in timestamp or "-" in timestamp

    def test_to_dict_matches_to_json(self, cost_event):
        """to_dict() and to_json() produce equivalent data."""
        dict_data = cost_event.to_dict()
        json_data = json.loads(cost_event.to_json())

        assert dict_data["event_type"] == json_data["event_type"]
        assert dict_data["task_id"] == json_data["task_id"]
        assert dict_data["total_tokens"] == json_data["total_tokens"]

    def test_to_json_handles_nested_dict(self, fidelity_event):
        """to_json() correctly serializes nested dict (dimensions)."""
        parsed = json.loads(fidelity_event.to_json())
        assert isinstance(parsed["dimensions"], dict)
        assert len(parsed["dimensions"]) == 3

    def test_to_json_handles_list_field(self, agent_started_event):
        """to_json() correctly serializes list fields (tools_available)."""
        parsed = json.loads(agent_started_event.to_json())
        assert isinstance(parsed["tools_available"], list)
        assert len(parsed["tools_available"]) == 4


# ─── Tests: EventEmitter Handles Empty Connection List ──────────


class TestEventEmitterEmptyConnections:
    """Test EventEmitter gracefully handles empty connection lists."""

    @pytest.fixture
    def mock_emitter(self):
        """Create an EventEmitter with mocked AWS clients."""
        with patch("src.api.events.boto3") as mock_boto3:
            mock_dynamodb = MagicMock()
            mock_apigw = MagicMock()
            mock_boto3.resource.return_value = mock_dynamodb
            mock_boto3.client.return_value = mock_apigw
            mock_boto3.dynamodb = MagicMock()
            mock_boto3.dynamodb.conditions = MagicMock()
            mock_boto3.dynamodb.conditions.Key.return_value = MagicMock()

            # Mock table query to return empty Items
            mock_table = MagicMock()
            mock_table.query.return_value = {"Items": []}
            mock_dynamodb.Table.return_value = mock_table

            emitter = EventEmitter(
                project_id="PROJ-TEST-001",
                websocket_endpoint="https://test.execute-api.us-east-1.amazonaws.com/$default",
                connections_table="fde-ws-connections-test",
            )

            yield {
                "emitter": emitter,
                "table": mock_table,
                "apigw": mock_apigw,
            }

    def test_emit_with_no_connections_returns_zero(self, mock_emitter):
        """emit() returns 0 when no clients are connected."""
        event = AgentStartedEvent(task_id="TASK-001", agent_type="engineering")
        result = mock_emitter["emitter"].emit(event)
        assert result == 0

    def test_emit_with_no_connections_does_not_raise(self, mock_emitter):
        """emit() does not raise when connection list is empty."""
        event = ErrorOccurredEvent(
            task_id="TASK-002",
            error_type="TestError",
            message="This should not raise",
        )
        # Should not raise any exception
        mock_emitter["emitter"].emit(event)

    def test_emit_batch_with_no_connections_returns_zero(self, mock_emitter):
        """emit_batch() returns 0 when no clients are connected."""
        events = [
            AgentStartedEvent(task_id="TASK-001"),
            CostUpdateEvent(task_id="TASK-001", total_tokens=100),
            AgentCompletedEvent(task_id="TASK-001", success=True),
        ]
        result = mock_emitter["emitter"].emit_batch(events)
        assert result == 0

    def test_emit_does_not_call_post_to_connection_when_empty(self, mock_emitter):
        """No post_to_connection calls when connection list is empty."""
        event = GateResultEvent(task_id="TASK-003", gate_name="test-gate")
        mock_emitter["emitter"].emit(event)
        mock_emitter["apigw"].post_to_connection.assert_not_called()

    def test_emit_with_connections_posts_to_each(self, mock_emitter):
        """emit() posts to each connected client."""
        # Override to return 2 connections
        mock_emitter["table"].query.return_value = {
            "Items": [
                {"connectionId": "conn-1", "project_id": "PROJ-TEST-001"},
                {"connectionId": "conn-2", "project_id": "PROJ-TEST-001"},
            ]
        }

        event = MilestoneReachedEvent(task_id="TASK-004", milestone="test")
        result = mock_emitter["emitter"].emit(event)

        assert mock_emitter["apigw"].post_to_connection.call_count == 2
        assert result == 2


# ─── Tests: Event Type Uniqueness ───────────────────────────────


class TestEventTypeUniqueness:
    """Test that all event types have unique type strings."""

    def test_all_event_types_are_unique(self):
        """No two event classes share the same event_type string."""
        type_strings = set()
        for event_class in ALL_EVENT_CLASSES:
            event = event_class()
            assert event.event_type not in type_strings, (
                f"Duplicate event_type: {event.event_type}"
            )
            type_strings.add(event.event_type)

    def test_exactly_8_event_types(self):
        """There are exactly 8 event types defined."""
        assert len(ALL_EVENT_CLASSES) == 8

    def test_event_types_are_snake_case(self):
        """All event_type strings use snake_case convention."""
        for event_class in ALL_EVENT_CLASSES:
            event = event_class()
            assert event.event_type == event.event_type.lower()
            assert " " not in event.event_type
            # snake_case: only lowercase letters and underscores
            assert all(c.isalpha() or c == "_" for c in event.event_type)
