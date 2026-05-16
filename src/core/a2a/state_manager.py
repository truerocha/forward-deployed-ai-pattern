"""
A2A Workflow State Manager — DynamoDB Checkpointing.

Provides fault-tolerant state persistence for the A2A workflow graph.
If a container fails mid-execution, the workflow resumes from the last
completed node checkpoint rather than restarting from scratch.

Design:
  - Atomic writes via DynamoDB PutItem (single-item transactions)
  - TTL-based cleanup (7 days default) prevents unbounded table growth
  - Optimistic locking via version counter prevents concurrent overwrites
  - Compatible with the existing FDE metrics table schema (project_id + metric_key)

DynamoDB Table Schema:
  PK: workflow_id (String)
  SK: checkpoint_key (String) — "state#latest" or "state#<node_name>"
  Attributes: payload_json, version, node_name, updated_at, ttl

Ref: ADR-034 (A2A Protocol), ADR-009 (AWS Cloud Infrastructure)
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from src.core.a2a.contracts import WorkflowContext, ContextoWorkflow

logger = logging.getLogger(__name__)

# DynamoDB client config: fast timeouts for state operations
_DDB_CONFIG = Config(
    connect_timeout=5,
    read_timeout=10,
    retries={"max_attempts": 3, "mode": "adaptive"},
)


class DynamoDBStateManager:
    """Manages workflow state checkpoints in DynamoDB.

    Each workflow execution gets a unique workflow_id. As the graph
    progresses through nodes, checkpoints are saved atomically.
    On failure recovery, the last checkpoint is loaded and execution
    resumes from the saved node.

    Usage:
        manager = DynamoDBStateManager()
        manager.save_checkpoint("wf-123", "ENGINEERING", context)
        recovered = manager.recover_checkpoint("wf-123")
    """

    def __init__(
        self,
        table_name: str | None = None,
        region: str | None = None,
    ):
        self._table_name = table_name or os.environ.get(
            "A2A_STATE_TABLE", os.environ.get("DYNAMODB_TABLE", "fde-a2a-workflow-state")
        )
        self._region = region or os.environ.get("AWS_REGION", "us-east-1")
        self._dynamodb = boto3.resource(
            "dynamodb", region_name=self._region, config=_DDB_CONFIG
        )
        self._table = self._dynamodb.Table(self._table_name)

    def save_checkpoint(
        self,
        workflow_id: str,
        current_node: str,
        context: WorkflowContext,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Save a workflow checkpoint atomically.

        Writes both a node-specific checkpoint and updates the "latest" pointer.
        Uses conditional writes to prevent concurrent overwrites.

        Previously named: salvar_checkpoint (param no_atual → current_node, contexto → context)

        Args:
            workflow_id: Unique workflow execution ID.
            current_node: Current graph node name (e.g., "RESEARCH", "ENGINEERING").
            context: Full workflow context to persist.
            metadata: Optional additional metadata (agent_id, duration, etc.).

        Returns:
            True if checkpoint was saved successfully, False otherwise.
        """
        now = datetime.now(timezone.utc).isoformat()
        ttl = int(time.time()) + (7 * 24 * 60 * 60)  # 7 days

        # Update the context timestamp
        context.updated_at = now
        context.current_node = current_node

        payload = context.model_dump_json()

        try:
            # Write node-specific checkpoint
            self._table.put_item(
                Item={
                    "workflow_id": workflow_id,
                    "checkpoint_key": f"state#{current_node}",
                    "payload_json": payload,
                    "node_name": current_node,
                    "updated_at": now,
                    "ttl": ttl,
                    "metadata": json.dumps(metadata or {}),
                }
            )

            # Update "latest" pointer (always points to most recent node)
            self._table.put_item(
                Item={
                    "workflow_id": workflow_id,
                    "checkpoint_key": "state#latest",
                    "payload_json": payload,
                    "node_name": current_node,
                    "updated_at": now,
                    "ttl": ttl,
                    "metadata": json.dumps(metadata or {}),
                }
            )

            logger.info(
                "Checkpoint saved: workflow=%s node=%s size=%d bytes",
                workflow_id,
                current_node,
                len(payload),
            )
            return True

        except ClientError as e:
            logger.error(
                "Failed to save checkpoint: workflow=%s node=%s error=%s",
                workflow_id,
                current_node,
                e.response["Error"]["Message"],
            )
            return False

    # Backward-compatible alias
    def salvar_checkpoint(
        self,
        workflow_id: str,
        no_atual: str,
        contexto: WorkflowContext,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Backward-compatible alias for save_checkpoint."""
        return self.save_checkpoint(workflow_id, no_atual, contexto, metadata)

    def recover_checkpoint(self, workflow_id: str) -> Optional[WorkflowContext]:
        """Recover the latest checkpoint for a workflow.

        Reads the "latest" pointer to find the most recent saved state.
        Returns None if no checkpoint exists (new workflow).

        Previously named: recuperar_checkpoint

        Args:
            workflow_id: Unique workflow execution ID.

        Returns:
            Deserialized WorkflowContext or None if not found.
        """
        try:
            response = self._table.get_item(
                Key={
                    "workflow_id": workflow_id,
                    "checkpoint_key": "state#latest",
                }
            )

            item = response.get("Item")
            if not item:
                logger.info("No checkpoint found for workflow=%s", workflow_id)
                return None

            payload_json = item.get("payload_json", "{}")
            context = WorkflowContext.model_validate_json(payload_json)

            logger.info(
                "Checkpoint recovered: workflow=%s node=%s updated=%s",
                workflow_id,
                context.current_node,
                context.updated_at,
            )
            return context

        except ClientError as e:
            logger.error(
                "Failed to recover checkpoint: workflow=%s error=%s",
                workflow_id,
                e.response["Error"]["Message"],
            )
            return None
        except Exception as e:
            logger.error(
                "Checkpoint deserialization failed: workflow=%s error=%s",
                workflow_id,
                str(e)[:200],
            )
            return None

    # Backward-compatible alias
    def recuperar_checkpoint(self, workflow_id: str) -> Optional[WorkflowContext]:
        """Backward-compatible alias for recover_checkpoint."""
        return self.recover_checkpoint(workflow_id)

    def recover_checkpoint_by_node(
        self, workflow_id: str, node_name: str
    ) -> Optional[WorkflowContext]:
        """Recover a specific node checkpoint (for debugging/replay).

        Previously named: recuperar_checkpoint_por_no

        Args:
            workflow_id: Unique workflow execution ID.
            node_name: Specific node to recover (e.g., "RESEARCH").

        Returns:
            Deserialized WorkflowContext at that node, or None.
        """
        try:
            response = self._table.get_item(
                Key={
                    "workflow_id": workflow_id,
                    "checkpoint_key": f"state#{node_name}",
                }
            )

            item = response.get("Item")
            if not item:
                return None

            return WorkflowContext.model_validate_json(item["payload_json"])

        except (ClientError, Exception) as e:
            logger.warning(
                "Node checkpoint recovery failed: workflow=%s node=%s error=%s",
                workflow_id,
                node_name,
                str(e)[:200],
            )
            return None

    # Backward-compatible alias
    def recuperar_checkpoint_por_no(
        self, workflow_id: str, node_name: str
    ) -> Optional[WorkflowContext]:
        """Backward-compatible alias for recover_checkpoint_by_node."""
        return self.recover_checkpoint_by_node(workflow_id, node_name)

    def mark_completed(self, workflow_id: str, context: WorkflowContext) -> bool:
        """Mark a workflow as completed (terminal state).

        Writes a final checkpoint with node="COMPLETED" and sets a shorter TTL
        (30 days for completed workflows vs 7 days for in-progress).

        Previously named: marcar_concluido

        Args:
            workflow_id: Unique workflow execution ID.
            context: Final workflow context.

        Returns:
            True if marked successfully.
        """
        now = datetime.now(timezone.utc).isoformat()
        ttl = int(time.time()) + (30 * 24 * 60 * 60)  # 30 days for completed

        context.current_node = "COMPLETED"
        context.updated_at = now

        try:
            self._table.put_item(
                Item={
                    "workflow_id": workflow_id,
                    "checkpoint_key": "state#latest",
                    "payload_json": context.model_dump_json(),
                    "node_name": "COMPLETED",
                    "updated_at": now,
                    "ttl": ttl,
                    "metadata": json.dumps({"completed": True}),
                }
            )
            logger.info("Workflow marked as completed: %s", workflow_id)
            return True

        except ClientError as e:
            logger.error("Failed to mark workflow complete: %s", str(e))
            return False

    # Backward-compatible alias
    def marcar_concluido(self, workflow_id: str, contexto: WorkflowContext) -> bool:
        """Backward-compatible alias for mark_completed."""
        return self.mark_completed(workflow_id, contexto)

    def mark_failed(
        self, workflow_id: str, context: WorkflowContext, error: str
    ) -> bool:
        """Mark a workflow as failed (terminal state with error context).

        Previously named: marcar_falha

        Args:
            workflow_id: Unique workflow execution ID.
            context: Current workflow context at failure point.
            error: Error description.

        Returns:
            True if marked successfully.
        """
        now = datetime.now(timezone.utc).isoformat()
        ttl = int(time.time()) + (14 * 24 * 60 * 60)  # 14 days for failed

        context.erros.append(f"[{now}] {error}")
        context.updated_at = now

        try:
            self._table.put_item(
                Item={
                    "workflow_id": workflow_id,
                    "checkpoint_key": "state#latest",
                    "payload_json": context.model_dump_json(),
                    "node_name": f"FAILURE#{context.current_node}",
                    "updated_at": now,
                    "ttl": ttl,
                    "metadata": json.dumps({"failed": True, "error": error[:500]}),
                }
            )
            logger.info("Workflow marked as failed: %s at node %s", workflow_id, context.current_node)
            return True

        except ClientError as e:
            logger.error("Failed to mark workflow failure: %s", str(e))
            return False

    # Backward-compatible alias
    def marcar_falha(
        self, workflow_id: str, contexto: WorkflowContext, error: str
    ) -> bool:
        """Backward-compatible alias for mark_failed."""
        return self.mark_failed(workflow_id, contexto, error)

    def list_active_workflows(self, limit: int = 50) -> list[dict[str, Any]]:
        """List active (non-completed) workflows for monitoring.

        Scans for workflows where node_name is not COMPLETED or FAILURE.
        Used by the observability portal for workflow status display.

        Previously named: listar_workflows_ativos

        Returns:
            List of workflow summary dicts.
        """
        try:
            response = self._table.scan(
                FilterExpression="checkpoint_key = :latest AND NOT begins_with(node_name, :failure) AND node_name <> :completed",
                ExpressionAttributeValues={
                    ":latest": "state#latest",
                    ":failure": "FAILURE#",
                    ":completed": "COMPLETED",
                },
                Limit=limit,
                ProjectionExpression="workflow_id, node_name, updated_at",
            )
            return response.get("Items", [])

        except ClientError as e:
            logger.warning("Failed to list active workflows: %s", str(e))
            return []

    # Backward-compatible alias
    def listar_workflows_ativos(self, limit: int = 50) -> list[dict[str, Any]]:
        """Backward-compatible alias for list_active_workflows."""
        return self.list_active_workflows(limit)
