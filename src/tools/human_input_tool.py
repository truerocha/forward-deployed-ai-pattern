"""
Human Input Tool — Strands tool that blocks agent execution for human input.

Sends a question to the connected portal via WebSocket and waits for the
human response by polling DynamoDB. Behavior varies by autonomy level:

  L1/L2: Abort on timeout (human MUST respond)
  L3:    Proceed with inference + flag for review on timeout
  L4/L5: Tool not available (skip — agent operates autonomously)

Activity 4.03 — Human-in-the-Loop Tool

Usage:
    tool = HumanInputTool(
        project_id="PROJ-123",
        websocket_endpoint="https://abc123.execute-api.us-east-1.amazonaws.com/$default",
        connections_table="fde-ws-connections",
        autonomy_level="L2",
    )
    response = tool.ask("Should I proceed with the database migration?")
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger("fde.human_input_tool")

_AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
_HITL_TABLE = os.environ.get("HITL_TABLE", "fde-hitl-requests")

# Default timeout: 5 minutes
_DEFAULT_TIMEOUT_SECONDS = 300

# Polling interval for checking DynamoDB responses
_POLL_INTERVAL_SECONDS = 2.0


@dataclass
class HumanInputTool:
    """Strands tool that blocks agent execution to request human input.

    The tool sends a question to all connected portal clients for the
    project via WebSocket, then polls DynamoDB for the response written
    by ws_handler when the human replies.

    Attributes:
        project_id: Factory project identifier.
        websocket_endpoint: API Gateway Management API endpoint URL.
        connections_table: DynamoDB table name for active connections.
        autonomy_level: Current autonomy level (L1-L5).
        timeout_seconds: Maximum wait time before timeout behavior kicks in.
    """

    project_id: str
    websocket_endpoint: str
    connections_table: str
    autonomy_level: str = "L2"
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS
    _dynamodb: Any = field(default=None, init=False, repr=False)
    _apigw_client: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._dynamodb = boto3.resource("dynamodb", region_name=_AWS_REGION)
        self._apigw_client = boto3.client(
            "apigatewaymanagementapi",
            endpoint_url=self.websocket_endpoint,
            region_name=_AWS_REGION,
        )

    def is_available(self) -> bool:
        """Check if this tool is available at the current autonomy level.

        Returns False for L4/L5 — agent operates fully autonomously.
        """
        return self.autonomy_level in ("L1", "L2", "L3")

    def ask(
        self,
        question: str,
        context: dict[str, Any] | None = None,
        options: list[str] | None = None,
    ) -> HumanInputResult:
        """Send a question to the human and wait for a response.

        Args:
            question: The question to ask the human operator.
            context: Optional context dict (shown in portal UI).
            options: Optional list of suggested response options.

        Returns:
            HumanInputResult with the response or timeout information.

        Raises:
            HumanInputUnavailable: If tool is not available at current level.
        """
        if not self.is_available():
            raise HumanInputUnavailable(
                f"Human input tool not available at autonomy level {self.autonomy_level}"
            )

        request_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        # Store the request in HITL table
        hitl_table = self._dynamodb.Table(_HITL_TABLE)
        hitl_item = {
            "request_id": request_id,
            "project_id": self.project_id,
            "question": question,
            "context": json.dumps(context or {}),
            "options": options or [],
            "asked_at": now.isoformat(),
            "autonomy_level": self.autonomy_level,
            "status": "pending",
            "ttl": int(time.time()) + self.timeout_seconds + 3600,  # Keep 1h after timeout
        }
        hitl_table.put_item(Item=hitl_item)

        # Send question to all connected portal clients for this project
        self._broadcast_question(request_id, question, context, options)

        # Poll for response
        response = self._poll_for_response(request_id, hitl_table)

        if response is not None:
            return HumanInputResult(
                request_id=request_id,
                answered=True,
                response=response,
                timed_out=False,
            )

        # Timeout — behavior depends on autonomy level
        return self._handle_timeout(request_id, question, hitl_table)

    def _broadcast_question(
        self,
        request_id: str,
        question: str,
        context: dict[str, Any] | None,
        options: list[str] | None,
    ) -> None:
        """Send the HITL question to all connected clients for this project."""
        connections_table = self._dynamodb.Table(self.connections_table)

        # Query connections by project_id using GSI
        try:
            response = connections_table.query(
                IndexName="project-index",
                KeyConditionExpression=boto3.dynamodb.conditions.Key("project_id").eq(self.project_id),
            )
        except ClientError as e:
            logger.error("Failed to query connections for project %s: %s", self.project_id, e)
            return

        message = {
            "type": "hitl_request",
            "request_id": request_id,
            "question": question,
            "context": context or {},
            "options": options or [],
            "timeout_seconds": self.timeout_seconds,
            "autonomy_level": self.autonomy_level,
        }

        connections = response.get("Items", [])
        if not connections:
            logger.warning("No connected clients for project %s", self.project_id)
            return

        for conn in connections:
            connection_id = conn["connectionId"]
            try:
                self._apigw_client.post_to_connection(
                    ConnectionId=connection_id,
                    Data=json.dumps(message).encode("utf-8"),
                )
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "")
                if error_code == "GoneException":
                    # Stale connection — remove it
                    try:
                        connections_table.delete_item(Key={"connectionId": connection_id})
                    except ClientError:
                        pass
                else:
                    logger.warning("Failed to send to %s: %s", connection_id, e)

    def _poll_for_response(self, request_id: str, hitl_table: Any) -> dict[str, Any] | None:
        """Poll DynamoDB for a response until timeout.

        Returns the parsed response dict, or None if timed out.
        """
        deadline = time.time() + self.timeout_seconds

        while time.time() < deadline:
            try:
                result = hitl_table.get_item(Key={"request_id": request_id})
                item = result.get("Item", {})

                if "response" in item:
                    # Response received — parse and return
                    raw_response = item["response"]
                    if isinstance(raw_response, str):
                        try:
                            return json.loads(raw_response)
                        except json.JSONDecodeError:
                            return {"text": raw_response}
                    return raw_response

            except ClientError as e:
                logger.warning("Error polling HITL response: %s", e)

            time.sleep(_POLL_INTERVAL_SECONDS)

        return None

    def _handle_timeout(
        self, request_id: str, question: str, hitl_table: Any
    ) -> HumanInputResult:
        """Handle timeout based on autonomy level.

        L1/L2: Abort — raise error, agent cannot proceed without human.
        L3:    Infer — proceed with best guess, flag for review.
        """
        # Update HITL record status
        try:
            hitl_table.update_item(
                Key={"request_id": request_id},
                UpdateExpression="SET #s = :s, timed_out_at = :ts",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":s": "timed_out",
                    ":ts": datetime.now(timezone.utc).isoformat(),
                },
            )
        except ClientError as e:
            logger.warning("Failed to update HITL timeout status: %s", e)

        if self.autonomy_level in ("L1", "L2"):
            # Abort: human MUST respond at these levels
            logger.warning(
                "HITL timeout at %s — aborting (request_id=%s)",
                self.autonomy_level, request_id,
            )
            return HumanInputResult(
                request_id=request_id,
                answered=False,
                response=None,
                timed_out=True,
                timeout_action="abort",
            )
        else:
            # L3: Proceed with inference, flag for review
            logger.info(
                "HITL timeout at L3 — proceeding with inference (request_id=%s)",
                request_id,
            )
            return HumanInputResult(
                request_id=request_id,
                answered=False,
                response=None,
                timed_out=True,
                timeout_action="infer",
                needs_review=True,
            )


@dataclass
class HumanInputResult:
    """Result of a human input request."""

    request_id: str
    answered: bool
    response: dict[str, Any] | None
    timed_out: bool
    timeout_action: str = ""  # "abort" | "infer" | ""
    needs_review: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "answered": self.answered,
            "response": self.response,
            "timed_out": self.timed_out,
            "timeout_action": self.timeout_action,
            "needs_review": self.needs_review,
        }


class HumanInputUnavailable(Exception):
    """Raised when human input tool is called at L4/L5 autonomy."""

    pass
