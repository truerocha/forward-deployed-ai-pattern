"""
Streaming Events — Real-time event types for portal updates via WebSocket.

Defines structured event types that the agent emits during execution.
The EventEmitter broadcasts these to all connected portal clients for
a project, enabling real-time observability in the dashboard.

Activity 4.05 — Streaming Event Types

Event types:
  - gate_result:        Pipeline gate pass/fail result
  - milestone_reached:  Agent reached a significant milestone
  - agent_started:      Agent execution began
  - agent_completed:    Agent execution finished
  - error_occurred:     Error during agent execution
  - autonomy_adjusted:  Autonomy level changed (escalation/de-escalation)
  - cost_update:        Token/compute cost update
  - fidelity_scored:    Fidelity score computed for deliverable

Usage:
    emitter = EventEmitter(
        project_id="PROJ-123",
        websocket_endpoint="https://abc123.execute-api.us-east-1.amazonaws.com/$default",
        connections_table="fde-ws-connections",
    )
    emitter.emit(AgentStartedEvent(task_id="TASK-001", agent_type="engineering"))
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger("fde.events")

_AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


# ─── Event Base Class ───────────────────────────────────────────


@dataclass
class BaseEvent:
    """Base class for all streaming events."""

    event_type: str = field(init=False)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_json(self) -> str:
        """Serialize event to JSON string."""
        data = asdict(self)
        return json.dumps(data, default=str)

    def to_dict(self) -> dict[str, Any]:
        """Serialize event to dictionary."""
        return asdict(self)


# ─── Event Types ────────────────────────────────────────────────


@dataclass
class GateResultEvent(BaseEvent):
    """Pipeline gate pass/fail result."""

    event_type: str = field(default="gate_result", init=False)
    task_id: str = ""
    gate_name: str = ""
    passed: bool = True
    details: str = ""
    duration_ms: int = 0


@dataclass
class MilestoneReachedEvent(BaseEvent):
    """Agent reached a significant milestone in execution."""

    event_type: str = field(default="milestone_reached", init=False)
    task_id: str = ""
    milestone: str = ""
    phase: str = ""
    message: str = ""


@dataclass
class AgentStartedEvent(BaseEvent):
    """Agent execution began."""

    event_type: str = field(default="agent_started", init=False)
    task_id: str = ""
    agent_type: str = ""
    autonomy_level: str = ""
    tools_available: list[str] = field(default_factory=list)


@dataclass
class AgentCompletedEvent(BaseEvent):
    """Agent execution finished (success or failure)."""

    event_type: str = field(default="agent_completed", init=False)
    task_id: str = ""
    agent_type: str = ""
    success: bool = True
    duration_seconds: float = 0.0
    deliverable_url: str = ""
    summary: str = ""


@dataclass
class ErrorOccurredEvent(BaseEvent):
    """Error during agent execution."""

    event_type: str = field(default="error_occurred", init=False)
    task_id: str = ""
    error_type: str = ""
    message: str = ""
    recoverable: bool = True
    phase: str = ""


@dataclass
class AutonomyAdjustedEvent(BaseEvent):
    """Autonomy level changed (escalation or de-escalation)."""

    event_type: str = field(default="autonomy_adjusted", init=False)
    task_id: str = ""
    previous_level: str = ""
    new_level: str = ""
    reason: str = ""
    escalation_count: int = 0


@dataclass
class CostUpdateEvent(BaseEvent):
    """Token/compute cost update during execution."""

    event_type: str = field(default="cost_update", init=False)
    task_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    model_id: str = ""


@dataclass
class FidelityScoredEvent(BaseEvent):
    """Fidelity score computed for a deliverable."""

    event_type: str = field(default="fidelity_scored", init=False)
    task_id: str = ""
    score: float = 0.0
    max_score: float = 1.0
    dimensions: dict[str, float] = field(default_factory=dict)
    passed_threshold: bool = True
    threshold: float = 0.7


# ─── Event Emitter ──────────────────────────────────────────────


@dataclass
class EventEmitter:
    """Broadcasts events to all connected WebSocket clients for a project.

    Uses the API Gateway Management API to post serialized events to
    each active connection. Stale connections are automatically cleaned up.

    Attributes:
        project_id: Factory project identifier.
        websocket_endpoint: API Gateway Management API endpoint URL.
        connections_table: DynamoDB table name for active connections.
    """

    project_id: str
    websocket_endpoint: str
    connections_table: str
    _dynamodb: Any = field(default=None, init=False, repr=False)
    _apigw_client: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._dynamodb = boto3.resource("dynamodb", region_name=_AWS_REGION)
        self._apigw_client = boto3.client(
            "apigatewaymanagementapi",
            endpoint_url=self.websocket_endpoint,
            region_name=_AWS_REGION,
        )

    def emit(self, event: BaseEvent) -> int:
        """Broadcast an event to all connected clients for this project.

        Args:
            event: Event instance to broadcast.

        Returns:
            Number of clients successfully notified.
        """
        connections = self._get_project_connections()
        if not connections:
            logger.debug("No connected clients for project %s", self.project_id)
            return 0

        payload = event.to_json().encode("utf-8")
        success_count = 0

        for conn in connections:
            connection_id = conn["connectionId"]
            if self._post_to_connection(connection_id, payload):
                success_count += 1

        logger.debug(
            "Event %s broadcast to %d/%d clients for project %s",
            event.event_type, success_count, len(connections), self.project_id,
        )
        return success_count

    def emit_batch(self, events: list[BaseEvent]) -> int:
        """Broadcast multiple events in a single pass over connections.

        More efficient than calling emit() for each event when multiple
        events need to be sent at once (e.g., gate results batch).

        Args:
            events: List of events to broadcast.

        Returns:
            Total number of successful deliveries across all events.
        """
        connections = self._get_project_connections()
        if not connections:
            return 0

        total_success = 0
        for event in events:
            payload = event.to_json().encode("utf-8")
            for conn in connections:
                if self._post_to_connection(conn["connectionId"], payload):
                    total_success += 1

        return total_success

    def _get_project_connections(self) -> list[dict[str, Any]]:
        """Query all active connections for this project."""
        table = self._dynamodb.Table(self.connections_table)
        try:
            response = table.query(
                IndexName="project-index",
                KeyConditionExpression=boto3.dynamodb.conditions.Key("project_id").eq(self.project_id),
            )
            return response.get("Items", [])
        except ClientError as e:
            logger.error("Failed to query connections for project %s: %s", self.project_id, e)
            return []

    def _post_to_connection(self, connection_id: str, payload: bytes) -> bool:
        """Post a message to a specific WebSocket connection.

        Returns True on success, False on failure. Cleans up stale connections.
        """
        try:
            self._apigw_client.post_to_connection(
                ConnectionId=connection_id,
                Data=payload,
            )
            return True
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "GoneException":
                # Connection is stale — clean up
                logger.debug("Removing stale connection %s", connection_id)
                table = self._dynamodb.Table(self.connections_table)
                try:
                    table.delete_item(Key={"connectionId": connection_id})
                except ClientError:
                    pass
                return False
            logger.warning("Failed to post to connection %s: %s", connection_id, e)
            return False
