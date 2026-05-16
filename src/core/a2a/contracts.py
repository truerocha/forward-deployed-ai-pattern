"""
A2A Data Contracts — Pydantic Models for Inter-Agent Communication.

These contracts enforce strict typing between workflow graph nodes.
Each agent's output MUST validate against the next agent's input schema,
preventing runtime failures during distributed execution.

Design:
  - All models use Pydantic v2 for JSON Schema generation
  - Schemas are exposed via the A2A Agent Card (/.well-known/agent-card.json)
  - DynamoDB checkpointing serializes/deserializes via model_dump_json()
  - Bedrock Converse API structured output uses these as response schemas

Ref: ADR-010 (Data Contract Task Input), ADR-034 (A2A Protocol)
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class WorkflowNodeStatus(str, Enum):
    """Status of a workflow graph node execution."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class QualityVerdict(str, Enum):
    """Quality gate verdict from the reviewer agent."""

    APPROVED = "APPROVED"
    NEEDS_REVISION = "NEEDS_REVISION"
    REJECTED = "REJECTED"


# ─── Phase 1: Research Agent Output ─────────────────────────────────────────


class SourceReference(BaseModel):
    """A single source reference from research."""

    url: str = Field(description="URL or document path of the source")
    title: str = Field(default="", description="Title or description of the source")
    relevance_score: float = Field(
        default=0.0, ge=0.0, le=1.0, description="How relevant this source is (0-1)"
    )


class ConteudoBruto(BaseModel):
    """Output contract for the Research/Reconnaissance agent (Phase 1).

    Contains raw factual data collected from multiple sources,
    structured for consumption by the Engineering/Writing agent.
    """

    topico: str = Field(description="The primary subject researched")
    fatos_encontrados: list[str] = Field(
        description="List of factual findings and data points collected"
    )
    fontes: list[SourceReference] = Field(
        default_factory=list, description="Structured source references"
    )
    contexto_adicional: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context metadata (repo info, constraints, etc.)",
    )
    confianca: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Confidence score in the research completeness",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="When the research was completed",
    )


# ─── Phase 2-3: Engineering Agent Output ────────────────────────────────────


class ArtefatoGerado(BaseModel):
    """A single artifact produced by the engineering agent."""

    path: str = Field(description="File path relative to workspace root")
    content_hash: str = Field(default="", description="SHA-256 hash of the content")
    language: str = Field(default="", description="Programming language or file type")
    lines_added: int = Field(default=0, description="Lines of code added")
    lines_modified: int = Field(default=0, description="Lines of code modified")


class RelatorioFinal(BaseModel):
    """Output contract for the Engineering/Writing agent (Phases 2-3).

    Contains the structured deliverable produced from research data,
    ready for quality review by the Reviewer agent.
    """

    titulo: str = Field(description="Title of the deliverable")
    introducao: str = Field(description="Executive summary / introduction")
    corpo_analise: str = Field(description="Main body of analysis or implementation")
    conclusao: str = Field(description="Conclusions and next steps")
    referencias: list[str] = Field(
        default_factory=list, description="References used in the deliverable"
    )
    artefatos: list[ArtefatoGerado] = Field(
        default_factory=list, description="Generated code/doc artifacts"
    )
    aprovado: bool = Field(
        default=False, description="Whether the deliverable passed quality validation"
    )
    metricas: dict[str, Any] = Field(
        default_factory=dict,
        description="Execution metrics (tokens used, duration, etc.)",
    )


# ─── Phase 4: Reviewer Agent Output ─────────────────────────────────────────


class CriticaItem(BaseModel):
    """A single review criticism or suggestion."""

    categoria: str = Field(description="Category: correctness|completeness|style|security")
    severidade: str = Field(description="Severity: critical|major|minor|suggestion")
    descricao: str = Field(description="Description of the issue found")
    localizacao: str = Field(default="", description="Where in the deliverable the issue is")
    sugestao_correcao: str = Field(default="", description="Suggested fix")


class FeedbackRevisao(BaseModel):
    """Output contract for the Reviewer agent (Phase 4).

    Contains structured quality feedback that can be routed back
    to the Engineering agent for iterative improvement.
    """

    veredicto: QualityVerdict = Field(description="Overall quality verdict")
    score_qualidade: float = Field(
        ge=0.0, le=1.0, description="Quality score (0-1)"
    )
    criticas: list[CriticaItem] = Field(
        default_factory=list, description="List of issues found"
    )
    pontos_positivos: list[str] = Field(
        default_factory=list, description="Positive aspects of the deliverable"
    )
    recomendacoes: list[str] = Field(
        default_factory=list, description="Recommendations for improvement"
    )
    aprovado: bool = Field(
        default=False, description="Whether the deliverable is approved for release"
    )
    tentativa: int = Field(
        default=1, description="Which review iteration this is"
    )


# ─── Workflow Context (Shared State) ─────────────────────────────────────────


class ContextoWorkflow(BaseModel):
    """Shared context that flows through the entire workflow graph.

    This is the state object persisted in DynamoDB for checkpointing.
    Each node reads from and writes to this context.
    """

    workflow_id: str = Field(description="Unique workflow execution ID")
    input_usuario: str = Field(description="Original user request / task description")
    no_atual: str = Field(default="PESQUISA", description="Current graph node name")
    dados_pesquisa: Optional[ConteudoBruto] = Field(
        default=None, description="Research output (populated after Phase 1)"
    )
    relatorio: Optional[RelatorioFinal] = Field(
        default=None, description="Engineering output (populated after Phases 2-3)"
    )
    feedback: Optional[FeedbackRevisao] = Field(
        default=None, description="Review feedback (populated after Phase 4)"
    )
    tentativas_revisao: int = Field(
        default=0, description="Number of review iterations completed"
    )
    max_tentativas: int = Field(
        default=3, description="Maximum review iterations before force-approve"
    )
    erros: list[str] = Field(
        default_factory=list, description="Accumulated error messages"
    )
    metricas_execucao: dict[str, Any] = Field(
        default_factory=dict, description="Execution metrics (timing, tokens, etc.)"
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Workflow creation timestamp",
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Last update timestamp",
    )


# ─── Task Payload (A2A Invoke Input) ────────────────────────────────────────


class TaskPayload(BaseModel):
    """Standard payload sent to any A2A agent via invoke().

    This is the universal input contract for all A2A server endpoints.
    The 'task' field describes what to do, 'payload' carries the data.
    """

    task: str = Field(description="Task description for the agent")
    payload: dict[str, Any] = Field(
        default_factory=dict, description="Input data for the task"
    )
    output_schema: Optional[str] = Field(
        default=None,
        description="Fully qualified name of the expected output Pydantic model",
    )
    constraints: list[str] = Field(
        default_factory=list, description="Additional constraints for execution"
    )
    timeout_seconds: int = Field(
        default=120, description="Maximum execution time for this task"
    )
