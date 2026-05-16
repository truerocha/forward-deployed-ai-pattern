"""
Agent-to-Agent (A2A) Protocol — Strands SDK Integration.

This module implements the Google A2A protocol on top of the Strands Agents SDK,
enabling decoupled inter-agent communication within the FDE factory pipeline.

Architecture:
  - Each subagent runs as an A2A Server (FastAPI/Starlette under the hood)
  - The orchestrator consumes subagents via A2AAgent proxy (tool-based handoff)
  - DynamoDB provides checkpointing for fault-tolerant graph execution
  - AWS Cloud Map provides service discovery for ECS-deployed agents
  - Agent Cards expose JSON Schema contracts for service discovery
  - Squad Bridge connects A2A to the Conductor's dynamic squad composition

Ref: docs/adr/ADR-034-a2a-protocol-strands-integration.md
"""

from src.core.a2a.contracts import (
    RawContent,
    FinalReport,
    WorkflowContext,
    ReviewFeedback,
    GeneratedArtifact,
    CriticismItem,
    TaskPayload,
    # Backward-compatible aliases (pt-BR names)
    ConteudoBruto,
    RelatorioFinal,
    ContextoWorkflow,
    FeedbackRevisao,
    ArtefatoGerado,
    CriticaItem,
)
from src.core.a2a.state_manager import DynamoDBStateManager
from src.core.a2a.workflow_graph import A2AWorkflowGraph, GrafoResiliente
from src.core.a2a.resilience import ResilientStateManager, ErrorClassification, classify_error
from src.core.a2a.observability import initialize_tracing, inicializar_tracing, trace_workflow_node, trace_a2a_invocation
from src.core.a2a.agent_cards import (
    AGENT_CARD_REGISTRY,
    PESQUISA_CARD,
    ESCRITA_CARD,
    REVISAO_CARD,
    get_card,
    list_cards,
)
from src.core.a2a.orchestrator import SquadOrchestrator
from src.core.a2a.squad_bridge import (
    SquadBridge,
    SQUAD_ROLE_TO_A2A_AGENT,
    create_bridge,
    get_a2a_capabilities_for_conductor,
)

__all__ = [
    # Contracts (new en-US names)
    "RawContent",
    "FinalReport",
    "WorkflowContext",
    "ReviewFeedback",
    "GeneratedArtifact",
    "CriticismItem",
    "TaskPayload",
    # Contracts (backward-compatible pt-BR aliases)
    "ConteudoBruto",
    "RelatorioFinal",
    "ContextoWorkflow",
    "FeedbackRevisao",
    "ArtefatoGerado",
    "CriticaItem",
    # State Management
    "DynamoDBStateManager",
    "ResilientStateManager",
    # Workflow Graph
    "A2AWorkflowGraph",
    "GrafoResiliente",
    # Orchestrator (production entrypoint)
    "SquadOrchestrator",
    # Agent Cards (service discovery)
    "AGENT_CARD_REGISTRY",
    "PESQUISA_CARD",
    "ESCRITA_CARD",
    "REVISAO_CARD",
    "get_card",
    "list_cards",
    # Squad Bridge (Conductor integration)
    "SquadBridge",
    "SQUAD_ROLE_TO_A2A_AGENT",
    "create_bridge",
    "get_a2a_capabilities_for_conductor",
    # Resilience
    "ErrorClassification",
    "classify_error",
    # Observability
    "initialize_tracing",
    "inicializar_tracing",
    "trace_workflow_node",
    "trace_a2a_invocation",
]
