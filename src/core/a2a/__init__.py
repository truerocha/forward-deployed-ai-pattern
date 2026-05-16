"""
Agent-to-Agent (A2A) Protocol — Strands SDK Integration.

This module implements the Google A2A protocol on top of the Strands Agents SDK,
enabling decoupled inter-agent communication within the FDE factory pipeline.

Architecture:
  - Each subagent runs as an A2A Server (FastAPI/Starlette under the hood)
  - The orchestrator consumes subagents via A2AAgent proxy (tool-based handoff)
  - DynamoDB provides checkpointing for fault-tolerant graph execution
  - AWS Cloud Map provides service discovery for ECS-deployed agents

Ref: docs/adr/ADR-034-a2a-protocol-strands-integration.md
"""

from src.core.a2a.contracts import (
    ConteudoBruto,
    RelatorioFinal,
    ContextoWorkflow,
    FeedbackRevisao,
    TaskPayload,
)
from src.core.a2a.state_manager import DynamoDBStateManager
from src.core.a2a.workflow_graph import A2AWorkflowGraph, GrafoResiliente
from src.core.a2a.resilience import ResilientStateManager, ErrorClassification, classify_error
from src.core.a2a.observability import inicializar_tracing, trace_workflow_node, trace_a2a_invocation

__all__ = [
    # Contracts
    "ConteudoBruto",
    "RelatorioFinal",
    "ContextoWorkflow",
    "FeedbackRevisao",
    "TaskPayload",
    # State Management
    "DynamoDBStateManager",
    "ResilientStateManager",
    # Workflow Graph
    "A2AWorkflowGraph",
    "GrafoResiliente",
    # Resilience
    "ErrorClassification",
    "classify_error",
    # Observability
    "inicializar_tracing",
    "trace_workflow_node",
    "trace_a2a_invocation",
]
