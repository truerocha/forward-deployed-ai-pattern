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

from pydantic import BaseModel, ConfigDict, Field


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


class RawContent(BaseModel):
    """Output contract for the Research/Reconnaissance agent (Phase 1).

    Contains raw factual data collected from multiple sources,
    structured for consumption by the Engineering/Writing agent.

    Previously named: ConteudoBruto
    """

    model_config = ConfigDict(populate_by_name=True)

    topic: str = Field(alias="topico", description="The primary subject researched")
    findings: list[str] = Field(
        alias="fatos_encontrados",
        description="List of factual findings and data points collected",
    )
    sources: list[SourceReference] = Field(
        alias="fontes",
        default_factory=list,
        description="Structured source references",
    )
    additional_context: dict[str, Any] = Field(
        alias="contexto_adicional",
        default_factory=dict,
        description="Additional context metadata (repo info, constraints, etc.)",
    )
    confidence: float = Field(
        alias="confianca",
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Confidence score in the research completeness",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="When the research was completed",
    )


# Backward-compatible alias
ConteudoBruto = RawContent


# ─── Phase 2-3: Engineering Agent Output ────────────────────────────────────


class GeneratedArtifact(BaseModel):
    """A single artifact produced by the engineering agent.

    Previously named: ArtefatoGerado
    """

    model_config = ConfigDict(populate_by_name=True)

    path: str = Field(description="File path relative to workspace root")
    content_hash: str = Field(default="", description="SHA-256 hash of the content")
    language: str = Field(default="", description="Programming language or file type")
    lines_added: int = Field(default=0, description="Lines of code added")
    lines_modified: int = Field(default=0, description="Lines of code modified")


# Backward-compatible alias
ArtefatoGerado = GeneratedArtifact


class FinalReport(BaseModel):
    """Output contract for the Engineering/Writing agent (Phases 2-3).

    Contains the structured deliverable produced from research data,
    ready for quality review by the Reviewer agent.

    Previously named: RelatorioFinal
    """

    model_config = ConfigDict(populate_by_name=True)

    title: str = Field(alias="titulo", description="Title of the deliverable")
    introduction: str = Field(alias="introducao", description="Executive summary / introduction")
    analysis_body: str = Field(alias="corpo_analise", description="Main body of analysis or implementation")
    conclusion: str = Field(alias="conclusao", description="Conclusions and next steps")
    references: list[str] = Field(
        alias="referencias",
        default_factory=list,
        description="References used in the deliverable",
    )
    artifacts: list[GeneratedArtifact] = Field(
        alias="artefatos",
        default_factory=list,
        description="Generated code/doc artifacts",
    )
    approved: bool = Field(
        alias="aprovado",
        default=False,
        description="Whether the deliverable passed quality validation",
    )
    metricas: dict[str, Any] = Field(
        default_factory=dict,
        description="Execution metrics (tokens used, duration, etc.)",
    )


# Backward-compatible alias
RelatorioFinal = FinalReport


# ─── Phase 4: Reviewer Agent Output ─────────────────────────────────────────


class CriticismItem(BaseModel):
    """A single review criticism or suggestion.

    Previously named: CriticaItem
    """

    model_config = ConfigDict(populate_by_name=True)

    categoria: str = Field(description="Category: correctness|completeness|style|security")
    severidade: str = Field(description="Severity: critical|major|minor|suggestion")
    descricao: str = Field(description="Description of the issue found")
    localizacao: str = Field(default="", description="Where in the deliverable the issue is")
    sugestao_correcao: str = Field(default="", description="Suggested fix")


# Backward-compatible alias
CriticaItem = CriticismItem


class ReviewFeedback(BaseModel):
    """Output contract for the Reviewer agent (Phase 4).

    Contains structured quality feedback that can be routed back
    to the Engineering agent for iterative improvement.

    Previously named: FeedbackRevisao
    """

    model_config = ConfigDict(populate_by_name=True)

    verdict: QualityVerdict = Field(alias="veredicto", description="Overall quality verdict")
    quality_score: float = Field(
        alias="score_qualidade",
        ge=0.0,
        le=1.0,
        description="Quality score (0-1)",
    )
    criticisms: list[CriticismItem] = Field(
        alias="criticas",
        default_factory=list,
        description="List of issues found",
    )
    positive_points: list[str] = Field(
        alias="pontos_positivos",
        default_factory=list,
        description="Positive aspects of the deliverable",
    )
    recomendacoes: list[str] = Field(
        default_factory=list, description="Recommendations for improvement"
    )
    approved: bool = Field(
        alias="aprovado",
        default=False,
        description="Whether the deliverable is approved for release",
    )
    tentativa: int = Field(
        default=1, description="Which review iteration this is"
    )


# Backward-compatible alias
FeedbackRevisao = ReviewFeedback


# ─── Workflow Context (Shared State) ─────────────────────────────────────────


class WorkflowContext(BaseModel):
    """Shared context that flows through the entire workflow graph.

    This is the state object persisted in DynamoDB for checkpointing.
    Each node reads from and writes to this context.

    Previously named: ContextoWorkflow
    """

    model_config = ConfigDict(populate_by_name=True)

    workflow_id: str = Field(description="Unique workflow execution ID")
    user_input: str = Field(alias="input_usuario", description="Original user request / task description")
    current_node: str = Field(alias="no_atual", default="RESEARCH", description="Current graph node name")
    research_data: Optional[RawContent] = Field(
        alias="dados_pesquisa",
        default=None,
        description="Research output (populated after Phase 1)",
    )
    report: Optional[FinalReport] = Field(
        alias="relatorio",
        default=None,
        description="Engineering output (populated after Phases 2-3)",
    )
    feedback: Optional[ReviewFeedback] = Field(
        default=None, description="Review feedback (populated after Phase 4)"
    )
    review_attempts: int = Field(
        alias="tentativas_revisao",
        default=0,
        description="Number of review iterations completed",
    )
    max_attempts: int = Field(
        alias="max_tentativas",
        default=3,
        description="Maximum review iterations before force-approve",
    )
    erros: list[str] = Field(
        default_factory=list, description="Accumulated error messages"
    )
    execution_metrics: dict[str, Any] = Field(
        alias="metricas_execucao",
        default_factory=dict,
        description="Execution metrics (timing, tokens, etc.)",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Workflow creation timestamp",
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Last update timestamp",
    )


# Backward-compatible alias
ContextoWorkflow = WorkflowContext


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
