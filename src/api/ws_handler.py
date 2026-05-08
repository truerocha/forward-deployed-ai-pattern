"""
WebSocket Handler — Lambda handler for API Gateway WebSocket messages.

Routes WebSocket events between the portal (React frontend) and agent
containers. Manages connection lifecycle in DynamoDB and forwards
messages to the appropriate agent or back to connected clients.

Activity 4.02 — WebSocket Message Routing

Connection metadata stored per connection:
  - connectionId: API Gateway connection identifier
  - project_id: Factory project this connection belongs to
  - user_id: Authenticated user identifier
  - connected_at: ISO 8601 timestamp

Message routing:
  - Portal → Agent: sendmessage with action="hitl_response" routes to
    the pending HITL request in DynamoDB (picked up by human_input_tool)
  - Agent → Portal: EventEmitter posts via Management API to all
    connections for a project
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger("fde.ws_handler")
logger.setLevel(logging.INFO)

_CONNECTIONS_TABLE = os.environ.get("CONNECTIONS_TABLE", "fde-ws-connections")
_HITL_TABLE = os.environ.get("HITL_TABLE", "fde-hitl-requests")
_AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

_dynamodb = boto3.resource("dynamodb", region_name=_AWS_REGION)
_connections_table = _dynamodb.Table(_CONNECTIONS_TABLE)
_hitl_table = _dynamodb.Table(_HITL_TABLE)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for API Gateway WebSocket events.

    Args:
        event: API Gateway WebSocket event with requestContext and body.
        context: Lambda context (unused).

    Returns:
        API Gateway response dict with statusCode.
    """
    request_context = event.get("requestContext", {})
    route_key = request_context.get("routeKey", "$default")
    connection_id = request_context.get("connectionId", "")

    logger.info("WebSocket event: route=%s connection=%s", route_key, connection_id)

    try:
        if route_key == "$connect":
            return _handle_connect(event, connection_id)
        elif route_key == "$disconnect":
            return _handle_disconnect(connection_id)
        elif route_key == "sendmessage":
            return _handle_sendmessage(event, connection_id)
        else:
            return _handle_default(event, connection_id)
    except Exception as e:
        logger.exception("Unhandled error in route %s: %s", route_key, e)
        return {"statusCode": 500, "body": json.dumps({"error": "Internal server error"})}


def _handle_connect(event: dict[str, Any], connection_id: str) -> dict[str, Any]:
    """Store new connection in DynamoDB with metadata.

    Query string parameters provide project_id and user_id:
      wss://endpoint?project_id=PROJ-123&user_id=user@example.com
    """
    query_params = event.get("queryStringParameters") or {}
    project_id = query_params.get("project_id", "unknown")
    user_id = query_params.get("user_id", "anonymous")

    now = datetime.now(timezone.utc)
    # TTL: 24 hours from connection (stale connections cleaned automatically)
    ttl_epoch = int(time.time()) + 86400

    item = {
        "connectionId": connection_id,
        "project_id": project_id,
        "user_id": user_id,
        "connected_at": now.isoformat(),
        "ttl": ttl_epoch,
    }

    _connections_table.put_item(Item=item)
    logger.info("Connected: %s (project=%s, user=%s)", connection_id, project_id, user_id)

    return {"statusCode": 200, "body": "Connected"}


def _handle_disconnect(connection_id: str) -> dict[str, Any]:
    """Remove connection from DynamoDB."""
    try:
        _connections_table.delete_item(Key={"connectionId": connection_id})
        logger.info("Disconnected: %s", connection_id)
    except ClientError as e:
        logger.warning("Failed to delete connection %s: %s", connection_id, e)

    return {"statusCode": 200, "body": "Disconnected"}


def _handle_sendmessage(event: dict[str, Any], connection_id: str) -> dict[str, Any]:
    """Route a message from the portal to the appropriate handler.

    Expected body format:
    {
        "action": "sendmessage",
        "type": "hitl_response" | "command",
        "request_id": "...",
        "payload": { ... }
    }
    """
    body = _parse_body(event)
    if body is None:
        return _send_error(event, connection_id, "Invalid JSON body")

    message_type = body.get("type", "")

    if message_type == "hitl_response":
        return _handle_hitl_response(body, connection_id)
    elif message_type == "command":
        return _handle_command(body, connection_id)
    else:
        logger.warning("Unknown message type: %s from %s", message_type, connection_id)
        return _send_error(event, connection_id, f"Unknown message type: {message_type}")


def _handle_hitl_response(body: dict[str, Any], connection_id: str) -> dict[str, Any]:
    """Store a human-in-the-loop response for the waiting agent tool.

    The human_input_tool polls the HITL table for responses. This handler
    writes the response so the tool can pick it up.
    """
    request_id = body.get("request_id", "")
    payload = body.get("payload", {})

    if not request_id:
        logger.warning("HITL response missing request_id from %s", connection_id)
        return {"statusCode": 400, "body": "Missing request_id"}

    _hitl_table.update_item(
        Key={"request_id": request_id},
        UpdateExpression="SET #resp = :resp, responded_at = :ts, responded_by = :conn",
        ExpressionAttributeNames={"#resp": "response"},
        ExpressionAttributeValues={
            ":resp": json.dumps(payload),
            ":ts": datetime.now(timezone.utc).isoformat(),
            ":conn": connection_id,
        },
    )

    logger.info("HITL response stored: request_id=%s", request_id)
    return {"statusCode": 200, "body": "Response stored"}


def _handle_command(body: dict[str, Any], connection_id: str) -> dict[str, Any]:
    """Handle portal commands (future: abort agent, adjust autonomy, etc.)."""
    command = body.get("payload", {}).get("command", "")
    logger.info("Command received: %s from %s", command, connection_id)
    # Commands are forwarded to the orchestrator via EventBridge (future)
    return {"statusCode": 200, "body": json.dumps({"status": "acknowledged", "command": command})}


def _handle_default(event: dict[str, Any], connection_id: str) -> dict[str, Any]:
    """Handle unrecognized routes — echo back with error guidance."""
    body = _parse_body(event)
    endpoint_url = _get_endpoint_url(event)

    error_msg = {
        "error": "unrecognized_route",
        "message": "Use action 'sendmessage' with a valid type (hitl_response, command).",
        "received": body,
    }

    if endpoint_url:
        _post_to_connection(endpoint_url, connection_id, error_msg)

    return {"statusCode": 200, "body": "Unrecognized route"}


# ─── Helpers ────────────────────────────────────────────────────


def _parse_body(event: dict[str, Any]) -> dict[str, Any] | None:
    """Parse the event body as JSON, returning None on failure."""
    raw = event.get("body", "")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _get_endpoint_url(event: dict[str, Any]) -> str:
    """Build the API Gateway Management API endpoint from the event."""
    request_context = event.get("requestContext", {})
    domain = request_context.get("domainName", "")
    stage = request_context.get("stage", "")
    if domain and stage:
        return f"https://{domain}/{stage}"
    return ""


def _post_to_connection(endpoint_url: str, connection_id: str, data: dict[str, Any]) -> bool:
    """Post a message to a specific WebSocket connection.

    Returns True on success, False if the connection is stale (gone).
    """
    client = boto3.client(
        "apigatewaymanagementapi",
        endpoint_url=endpoint_url,
        region_name=_AWS_REGION,
    )
    try:
        client.post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps(data).encode("utf-8"),
        )
        return True
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "GoneException":
            # Connection is stale — clean up
            logger.info("Stale connection %s — removing", connection_id)
            try:
                _connections_table.delete_item(Key={"connectionId": connection_id})
            except ClientError:
                pass
            return False
        logger.warning("Failed to post to %s: %s", connection_id, e)
        return False


def _send_error(event: dict[str, Any], connection_id: str, message: str) -> dict[str, Any]:
    """Send an error message back to the client."""
    endpoint_url = _get_endpoint_url(event)
    if endpoint_url:
        _post_to_connection(endpoint_url, connection_id, {"error": message})
    return {"statusCode": 400, "body": message}
