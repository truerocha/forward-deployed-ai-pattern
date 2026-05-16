"""
A2A Resilience Layer — SQS Dead Letter Queue + Retry Management.

Extends the DynamoDB state manager with circuit-breaking behavior:
  - Atomic retry counter increment via DynamoDB UpdateItem
  - Automatic DLQ dispatch when max retries are exhausted
  - Full workflow context preservation in the DLQ message
  - Structured error classification for operational triage

Design:
  - Retry counter is stored atomically in DynamoDB (no race conditions)
  - DLQ message contains full ContextoWorkflow + error metadata
  - SQS message attributes enable filtering by error type in CloudWatch
  - Compatible with SQS → Lambda → SNS alerting pipelines

DLQ Message Schema:
  {
    "workflow_id": "wf-abc123",
    "no_falho": "ESCRITA",
    "erro": "TimeoutError: Bedrock invocation exceeded 120s",
    "tentativas": 3,
    "contexto_final": { ... full ContextoWorkflow ... },
    "classificacao": "INFRASTRUCTURE|CODE|MODEL|TIMEOUT",
    "timestamp": "2026-05-16T..."
  }

Ref: ADR-034 (A2A Protocol), ADR-004 (Circuit Breaker Error Classification)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from src.core.a2a.contracts import ContextoWorkflow
from src.core.a2a.state_manager import DynamoDBStateManager

logger = logging.getLogger(__name__)


class ErrorClassification(str, Enum):
    """Error classification for operational triage in DLQ consumers."""

    INFRASTRUCTURE = "INFRASTRUCTURE"  # AWS service errors, network, permissions
    CODE = "CODE"  # Application logic errors, validation failures
    MODEL = "MODEL"  # Bedrock model errors, content filtering, token limits
    TIMEOUT = "TIMEOUT"  # Invocation timeouts (Bedrock or A2A)
    CONTRACT = "CONTRACT"  # Data contract validation failures (Pydantic)
    UNKNOWN = "UNKNOWN"  # Unclassified errors


def classify_error(error: Exception | str) -> ErrorClassification:
    """Classify an error for operational routing.

    Maps exception types and error messages to categories that
    determine alerting severity and remediation paths.

    Args:
        error: The exception or error message string.

    Returns:
        ErrorClassification enum value.
    """
    error_str = str(error).lower()

    # Infrastructure errors (AWS service issues)
    infra_patterns = [
        "clienterror", "endpointconnectionerror", "connecttimeouterror",
        "nosuchbucket", "accessdenied", "econnrefused", "eaddrinuse",
        "credentialretrievalerror", "noregionerror", "serviceunavailable",
    ]
    if any(p in error_str for p in infra_patterns):
        return ErrorClassification.INFRASTRUCTURE

    # Model errors (Bedrock-specific)
    model_patterns = [
        "throttlingexception", "modeltimeoutexception", "validationexception",
        "modelnotreadyexception", "contentfiltered", "tokenlimit",
        "invocationmetrics", "bedrock",
    ]
    if any(p in error_str for p in model_patterns):
        return ErrorClassification.MODEL

    # Timeout errors
    timeout_patterns = ["timeout", "timedout", "deadline exceeded", "read timed out"]
    if any(p in error_str for p in timeout_patterns):
        return ErrorClassification.TIMEOUT

    # Contract/validation errors
    contract_patterns = [
        "validationerror", "pydantic", "model_validate", "field required",
        "value_error", "json_invalid",
    ]
    if any(p in error_str for p in contract_patterns):
        return ErrorClassification.CONTRACT

    # Code errors (application logic)
    code_patterns = [
        "typeerror", "attributeerror", "keyerror", "indexerror",
        "valueerror", "assertionerror", "importerror", "nameerror",
    ]
    if any(p in error_str for p in code_patterns):
        return ErrorClassification.CODE

    return ErrorClassification.UNKNOWN


class ResilientStateManager(DynamoDBStateManager):
    """DynamoDB state manager with SQS DLQ integration.

    Extends the base state manager with:
      - Atomic retry counter management
      - Automatic DLQ dispatch on retry exhaustion
      - Error classification for operational routing
      - Structured DLQ messages for downstream consumers

    Usage:
        manager = ResilientStateManager()
        should_retry = manager.registrar_falha_com_retry(
            workflow_id="wf-123",
            no_atual="ESCRITA",
            contexto=contexto,
            erro=exception,
        )
        if not should_retry:
            # Workflow has been sent to DLQ — stop execution
            return
    """

    def __init__(
        self,
        table_name: str | None = None,
        region: str | None = None,
        dlq_url: str | None = None,
        max_retries: int | None = None,
    ):
        super().__init__(table_name=table_name, region=region)

        self._dlq_url = dlq_url or os.environ.get("A2A_DLQ_URL", "")
        self._max_retries = max_retries or int(
            os.environ.get("A2A_MAX_RETRIES", "3")
        )

        # SQS client with fast timeouts
        self._sqs = boto3.client(
            "sqs",
            region_name=self._region,
            config=Config(connect_timeout=5, read_timeout=10),
        )

    def registrar_falha_com_retry(
        self,
        workflow_id: str,
        no_atual: str,
        contexto: ContextoWorkflow,
        erro: Exception | str,
    ) -> bool:
        """Register a failure and determine if retry is allowed.

        Atomically increments the retry counter in DynamoDB.
        If max retries are exhausted, dispatches to SQS DLQ.

        Args:
            workflow_id: Unique workflow execution ID.
            no_atual: Current graph node where failure occurred.
            contexto: Full workflow context at failure point.
            erro: The exception or error message.

        Returns:
            True if retry is allowed (counter < max), False if sent to DLQ.
        """
        erro_str = f"{type(erro).__name__}: {str(erro)[:500]}" if isinstance(erro, Exception) else str(erro)[:500]
        classificacao = classify_error(erro)
        now = datetime.now(timezone.utc).isoformat()

        # Append error to context
        contexto.erros.append(f"[{now}] [{classificacao.value}] {erro_str}")
        contexto.updated_at = now

        try:
            # Atomic increment of retry counter
            response = self._table.update_item(
                Key={
                    "workflow_id": workflow_id,
                    "checkpoint_key": "state#retries",
                },
                UpdateExpression=(
                    "SET retry_count = if_not_exists(retry_count, :zero) + :one, "
                    "node_name = :node, "
                    "last_error = :erro, "
                    "classification = :cls, "
                    "updated_at = :now, "
                    "payload_json = :payload"
                ),
                ExpressionAttributeValues={
                    ":zero": 0,
                    ":one": 1,
                    ":node": no_atual,
                    ":erro": erro_str,
                    ":cls": classificacao.value,
                    ":now": now,
                    ":payload": contexto.model_dump_json(),
                },
                ReturnValues="UPDATED_NEW",
            )

            tentativas = int(response["Attributes"]["retry_count"])
            logger.warning(
                "Workflow %s failed at node %s (attempt %d/%d, class=%s): %s",
                workflow_id, no_atual, tentativas, self._max_retries,
                classificacao.value, erro_str[:100],
            )

            # Check if retries exhausted
            if tentativas >= self._max_retries:
                logger.error(
                    "Workflow %s exhausted %d retries — dispatching to DLQ",
                    workflow_id, self._max_retries,
                )
                self._enviar_para_dlq(
                    workflow_id=workflow_id,
                    no_atual=no_atual,
                    contexto=contexto,
                    erro_str=erro_str,
                    classificacao=classificacao,
                    tentativas=tentativas,
                )
                # Mark as failed in state table
                self.marcar_falha(workflow_id, contexto, f"DLQ after {tentativas} retries: {erro_str}")
                return False

            # Retry allowed — save checkpoint at current node for recovery
            self.salvar_checkpoint(workflow_id, no_atual, contexto)
            return True

        except ClientError as e:
            logger.error(
                "Critical infrastructure error in retry management: %s",
                e.response["Error"]["Message"],
            )
            # On infrastructure failure, allow retry (fail-open)
            return True

    def _enviar_para_dlq(
        self,
        workflow_id: str,
        no_atual: str,
        contexto: ContextoWorkflow,
        erro_str: str,
        classificacao: ErrorClassification,
        tentativas: int,
    ) -> bool:
        """Dispatch failed workflow state to SQS Dead Letter Queue.

        The DLQ message contains all information needed to:
          - Debug the failure (full context + error)
          - Replay the workflow (context can be re-injected)
          - Alert operations (classification + severity)

        Args:
            workflow_id: Unique workflow execution ID.
            no_atual: Node where final failure occurred.
            contexto: Full workflow context.
            erro_str: Formatted error string.
            classificacao: Error classification.
            tentativas: Total retry attempts made.

        Returns:
            True if message was sent successfully.
        """
        if not self._dlq_url:
            logger.warning(
                "DLQ URL not configured (A2A_DLQ_URL) — cannot dispatch workflow %s",
                workflow_id,
            )
            return False

        now = datetime.now(timezone.utc).isoformat()

        dlq_message = {
            "workflow_id": workflow_id,
            "no_falho": no_atual,
            "erro": erro_str,
            "tentativas": tentativas,
            "classificacao": classificacao.value,
            "contexto_final": contexto.model_dump(),
            "timestamp": now,
            "environment": os.environ.get("ENVIRONMENT", "dev"),
            "agent_endpoints": {
                "pesquisa": os.environ.get("A2A_PESQUISA_ENDPOINT", ""),
                "escrita": os.environ.get("A2A_ESCRITA_ENDPOINT", ""),
                "revisao": os.environ.get("A2A_REVISAO_ENDPOINT", ""),
            },
        }

        try:
            self._sqs.send_message(
                QueueUrl=self._dlq_url,
                MessageBody=json.dumps(dlq_message, default=str),
                MessageAttributes={
                    "WorkflowId": {
                        "DataType": "String",
                        "StringValue": workflow_id,
                    },
                    "ErrorClassification": {
                        "DataType": "String",
                        "StringValue": classificacao.value,
                    },
                    "FailedNode": {
                        "DataType": "String",
                        "StringValue": no_atual,
                    },
                    "RetryCount": {
                        "DataType": "Number",
                        "StringValue": str(tentativas),
                    },
                },
            )
            logger.info(
                "DLQ message sent: workflow=%s node=%s class=%s attempts=%d",
                workflow_id, no_atual, classificacao.value, tentativas,
            )
            return True

        except ClientError as e:
            logger.error(
                "CRITICAL: Failed to send DLQ message for workflow %s: %s",
                workflow_id, e.response["Error"]["Message"],
            )
            return False

    def resetar_retries(self, workflow_id: str) -> bool:
        """Reset retry counter for a workflow (used after manual intervention).

        Args:
            workflow_id: Workflow to reset.

        Returns:
            True if reset successfully.
        """
        try:
            self._table.delete_item(
                Key={
                    "workflow_id": workflow_id,
                    "checkpoint_key": "state#retries",
                }
            )
            logger.info("Retry counter reset for workflow %s", workflow_id)
            return True
        except ClientError as e:
            logger.warning("Failed to reset retries: %s", str(e))
            return False
