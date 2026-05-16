"""
A2A Workflow Graph — Resilient Agent Orchestration via Strands A2A Protocol.

Implements a directed graph of A2A agents with:
  - Sequential node execution with conditional routing
  - DynamoDB checkpointing for fault recovery (Saga pattern)
  - Dynamic feedback loops (reviewer → writer rework cycles)
  - AWS Cloud Map service discovery for ECS-deployed agents
  - Streaming support via A2AAgent.stream()

Graph Topology:
  PESQUISA → ESCRITA → REVISAO → [APROVADO | loop back to ESCRITA]
                                         ↓ (max 3 attempts)
                                      CONCLUIDO

Each node is an independent A2A Server running in its own ECS container.
The orchestrator connects to them via Cloud Map DNS (e.g., pesquisa.fde.local:9001).

Ref: ADR-034 (A2A Protocol), ADR-019 (Agentic Squad Architecture)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from typing import Any, Optional

from src.core.a2a.contracts import (
    ConteudoBruto,
    ContextoWorkflow,
    FeedbackRevisao,
    QualityVerdict,
    RelatorioFinal,
    TaskPayload,
)
from src.core.a2a.state_manager import DynamoDBStateManager

logger = logging.getLogger(__name__)


class A2AWorkflowGraph:
    """Orchestrates a multi-agent workflow via the A2A protocol.

    Each agent is consumed as an A2AAgent proxy pointing to a Cloud Map
    DNS endpoint. The graph executes nodes sequentially with conditional
    routing based on agent outputs.

    The orchestrator does NOT import agent code — it communicates exclusively
    via the A2A protocol (JSON-RPC over HTTP). This enables:
      - Independent scaling of each agent container
      - Zero-downtime agent upgrades (blue/green via Cloud Map)
      - Language-agnostic agents (any A2A-compliant server works)
    """

    def __init__(
        self,
        pesquisa_endpoint: str | None = None,
        escrita_endpoint: str | None = None,
        revisao_endpoint: str | None = None,
        timeout: int = 120,
    ):
        """Initialize the workflow graph with agent endpoints.

        Endpoints are resolved from environment variables if not provided,
        supporting both local development and ECS Cloud Map discovery.

        Args:
            pesquisa_endpoint: URL for the research agent A2A server.
            escrita_endpoint: URL for the writing agent A2A server.
            revisao_endpoint: URL for the reviewer agent A2A server.
            timeout: Default timeout in seconds for A2A invocations.
        """
        self._pesquisa_endpoint = pesquisa_endpoint or os.environ.get(
            "A2A_PESQUISA_ENDPOINT", "http://pesquisa.fde.local:9001"
        )
        self._escrita_endpoint = escrita_endpoint or os.environ.get(
            "A2A_ESCRITA_ENDPOINT", "http://escrita.fde.local:9002"
        )
        self._revisao_endpoint = revisao_endpoint or os.environ.get(
            "A2A_REVISAO_ENDPOINT", "http://revisao.fde.local:9003"
        )
        self._timeout = timeout

        # Lazy-loaded A2A agent proxies (initialized on first use)
        self._agente_pesquisa = None
        self._agente_escrita = None
        self._agente_revisao = None

    def _get_a2a_agent(self, endpoint: str):
        """Lazily create an A2AAgent proxy for the given endpoint.

        The Strands SDK fetches the Agent Card from /.well-known/agent-card.json
        on first invocation, discovering the agent's capabilities dynamically.
        """
        try:
            from strands.a2a import A2AAgent
            return A2AAgent(endpoint=endpoint, timeout=self._timeout)
        except ImportError:
            logger.warning(
                "strands.a2a not available — using mock A2A agent for endpoint %s",
                endpoint,
            )
            return _MockA2AAgent(endpoint)

    @property
    def agente_pesquisa(self):
        """Research agent proxy (lazy initialization)."""
        if self._agente_pesquisa is None:
            self._agente_pesquisa = self._get_a2a_agent(self._pesquisa_endpoint)
        return self._agente_pesquisa

    @property
    def agente_escrita(self):
        """Writing agent proxy (lazy initialization)."""
        if self._agente_escrita is None:
            self._agente_escrita = self._get_a2a_agent(self._escrita_endpoint)
        return self._agente_escrita

    @property
    def agente_revisao(self):
        """Reviewer agent proxy (lazy initialization)."""
        if self._agente_revisao is None:
            self._agente_revisao = self._get_a2a_agent(self._revisao_endpoint)
        return self._agente_revisao

    async def executar_workflow(self, prompt_inicial: str) -> RelatorioFinal:
        """Execute the full A2A workflow graph from a user prompt.

        This is the simple (non-resilient) execution path — no checkpointing.
        Use GrafoResiliente for production workloads with fault recovery.

        Args:
            prompt_inicial: The user's task description.

        Returns:
            The final approved RelatorioFinal.
        """
        workflow_id = f"wf-{uuid.uuid4().hex[:12]}"
        contexto = ContextoWorkflow(
            workflow_id=workflow_id,
            input_usuario=prompt_inicial,
        )

        # ─── Node 1: PESQUISA (Research) ─────────────────────────────────
        logger.info("[%s] Node PESQUISA: Starting research...", workflow_id)
        start = time.time()

        resposta_pesquisa = await self.agente_pesquisa.invoke(
            task="Coleta de dados detalhada e estruturada",
            payload={"query": contexto.input_usuario},
        )
        contexto.dados_pesquisa = ConteudoBruto.model_validate(resposta_pesquisa)
        contexto.metricas_execucao["pesquisa_duration_s"] = round(time.time() - start, 2)

        # ─── Node 2: ESCRITA (Engineering/Writing) ───────────────────────
        logger.info("[%s] Node ESCRITA: Generating deliverable...", workflow_id)
        start = time.time()

        resposta_escrita = await self.agente_escrita.invoke(
            task="Produzir documento técnico estruturado com base nos dados de pesquisa",
            payload=contexto.dados_pesquisa.model_dump(),
        )
        contexto.relatorio = RelatorioFinal.model_validate(resposta_escrita)
        contexto.metricas_execucao["escrita_duration_s"] = round(time.time() - start, 2)

        # ─── Node 3: REVISAO (Review with feedback loop) ─────────────────
        for tentativa in range(1, contexto.max_tentativas + 1):
            logger.info(
                "[%s] Node REVISAO: Review attempt %d/%d...",
                workflow_id, tentativa, contexto.max_tentativas,
            )
            start = time.time()

            resultado_revisao = await self.agente_revisao.invoke(
                task="Avaliar qualidade técnica do relatório",
                payload=contexto.relatorio.model_dump(),
            )

            feedback = FeedbackRevisao.model_validate(resultado_revisao)
            contexto.feedback = feedback
            contexto.tentativas_revisao = tentativa

            duration = round(time.time() - start, 2)
            contexto.metricas_execucao[f"revisao_{tentativa}_duration_s"] = duration

            # ─── Dynamic Routing Decision ────────────────────────────────
            if feedback.veredicto == QualityVerdict.APPROVED or feedback.aprovado:
                logger.info("[%s] Deliverable APPROVED on attempt %d", workflow_id, tentativa)
                contexto.relatorio.aprovado = True
                break

            if tentativa >= contexto.max_tentativas:
                logger.warning(
                    "[%s] Max review attempts reached — force-approving", workflow_id
                )
                contexto.relatorio.aprovado = True
                break

            # ─── Feedback Loop: Route back to ESCRITA ────────────────────
            logger.info(
                "[%s] NEEDS_REVISION — routing back to ESCRITA (attempt %d)",
                workflow_id, tentativa + 1,
            )

            resposta_reescrita = await self.agente_escrita.invoke(
                task="Corrigir relatório com base no feedback da revisão",
                payload={
                    "dados_originais": contexto.dados_pesquisa.model_dump(),
                    "relatorio_anterior": contexto.relatorio.model_dump(),
                    "feedback": feedback.model_dump(),
                },
            )
            contexto.relatorio = RelatorioFinal.model_validate(resposta_reescrita)

        return contexto.relatorio


class GrafoResiliente(A2AWorkflowGraph):
    """Fault-tolerant workflow graph with DynamoDB checkpointing.

    Extends A2AWorkflowGraph with:
      - Checkpoint after each node completion
      - Recovery from last checkpoint on restart
      - Metrics emission for observability
      - Error classification and circuit-breaking

    This is the production-grade execution path for ECS Fargate deployment.
    """

    def __init__(
        self,
        state_manager: DynamoDBStateManager | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._db = state_manager or DynamoDBStateManager()

    async def executar_com_recuperacao(
        self,
        workflow_id: str,
        prompt_inicial: str = "",
    ) -> RelatorioFinal:
        """Execute workflow with checkpoint-based fault recovery.

        On first call, starts from PESQUISA. On subsequent calls with the
        same workflow_id, resumes from the last saved checkpoint.

        Args:
            workflow_id: Unique workflow ID (use same ID for recovery).
            prompt_inicial: User prompt (only needed for new workflows).

        Returns:
            The final RelatorioFinal (approved or force-approved).

        Raises:
            RuntimeError: If workflow fails after all retry attempts.
        """
        # ─── Recovery: Load existing checkpoint ──────────────────────────
        contexto = self._db.recuperar_checkpoint(workflow_id)

        if contexto:
            logger.info(
                "Recovering workflow %s from node: %s",
                workflow_id, contexto.no_atual,
            )
            no_inicial = contexto.no_atual
        else:
            if not prompt_inicial:
                raise ValueError(
                    f"No checkpoint found for {workflow_id} and no prompt_inicial provided"
                )
            logger.info("Starting new workflow: %s", workflow_id)
            contexto = ContextoWorkflow(
                workflow_id=workflow_id,
                input_usuario=prompt_inicial,
            )
            no_inicial = "PESQUISA"

        try:
            # ─── Node: PESQUISA ──────────────────────────────────────────
            if no_inicial == "PESQUISA":
                logger.info("[%s] Executing node PESQUISA...", workflow_id)
                start = time.time()

                resposta = await self.agente_pesquisa.invoke(
                    task="Coleta de dados detalhada e estruturada",
                    payload={"query": contexto.input_usuario},
                )
                contexto.dados_pesquisa = ConteudoBruto.model_validate(resposta)
                contexto.metricas_execucao["pesquisa_duration_s"] = round(
                    time.time() - start, 2
                )

                # Checkpoint: next node is ESCRITA
                self._db.salvar_checkpoint(workflow_id, "ESCRITA", contexto)
                no_inicial = "ESCRITA"

            # ─── Node: ESCRITA ───────────────────────────────────────────
            if no_inicial == "ESCRITA":
                logger.info("[%s] Executing node ESCRITA...", workflow_id)
                start = time.time()

                resposta = await self.agente_escrita.invoke(
                    task="Produzir documento técnico estruturado",
                    payload=contexto.dados_pesquisa.model_dump(),
                )
                contexto.relatorio = RelatorioFinal.model_validate(resposta)
                contexto.metricas_execucao["escrita_duration_s"] = round(
                    time.time() - start, 2
                )

                # Checkpoint: next node is REVISAO
                self._db.salvar_checkpoint(workflow_id, "REVISAO", contexto)
                no_inicial = "REVISAO"

            # ─── Node: REVISAO (with feedback loop) ──────────────────────
            if no_inicial == "REVISAO":
                remaining = contexto.max_tentativas - contexto.tentativas_revisao

                for tentativa in range(1, remaining + 1):
                    logger.info(
                        "[%s] Executing node REVISAO (attempt %d)...",
                        workflow_id, contexto.tentativas_revisao + 1,
                    )
                    start = time.time()

                    resultado = await self.agente_revisao.invoke(
                        task="Avaliar qualidade técnica do relatório",
                        payload=contexto.relatorio.model_dump(),
                    )

                    feedback = FeedbackRevisao.model_validate(resultado)
                    contexto.feedback = feedback
                    contexto.tentativas_revisao += 1

                    duration = round(time.time() - start, 2)
                    contexto.metricas_execucao[
                        f"revisao_{contexto.tentativas_revisao}_duration_s"
                    ] = duration

                    if feedback.veredicto == QualityVerdict.APPROVED or feedback.aprovado:
                        contexto.relatorio.aprovado = True
                        logger.info(
                            "[%s] APPROVED on attempt %d",
                            workflow_id, contexto.tentativas_revisao,
                        )
                        break

                    if contexto.tentativas_revisao >= contexto.max_tentativas:
                        contexto.relatorio.aprovado = True
                        logger.warning(
                            "[%s] Max attempts reached — force-approving", workflow_id
                        )
                        break

                    # Feedback loop: rewrite
                    logger.info("[%s] Routing back to ESCRITA for rework...", workflow_id)
                    resposta = await self.agente_escrita.invoke(
                        task="Corrigir relatório com base no feedback",
                        payload={
                            "dados_originais": contexto.dados_pesquisa.model_dump(),
                            "relatorio_anterior": contexto.relatorio.model_dump(),
                            "feedback": feedback.model_dump(),
                        },
                    )
                    contexto.relatorio = RelatorioFinal.model_validate(resposta)

                    # Checkpoint after each rework cycle
                    self._db.salvar_checkpoint(workflow_id, "REVISAO", contexto)

            # ─── Terminal: CONCLUIDO ─────────────────────────────────────
            self._db.marcar_concluido(workflow_id, contexto)
            return contexto.relatorio

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)[:300]}"
            logger.error("[%s] Workflow failed: %s", workflow_id, error_msg)
            self._db.marcar_falha(workflow_id, contexto, error_msg)
            raise RuntimeError(
                f"Workflow {workflow_id} failed at node {contexto.no_atual}: {error_msg}"
            ) from e


class _MockA2AAgent:
    """Mock A2A agent for local development without Strands A2A installed.

    Returns empty structured responses matching expected schemas.
    Used when strands.a2a is not available in the environment.
    """

    def __init__(self, endpoint: str):
        self._endpoint = endpoint
        logger.warning("Using mock A2A agent for %s (strands.a2a not installed)", endpoint)

    async def invoke(self, task: str, payload: dict[str, Any] = None, **kwargs) -> dict:
        """Return a minimal valid response for testing."""
        logger.info("Mock A2A invoke: task=%s endpoint=%s", task[:50], self._endpoint)
        return {
            "topico": payload.get("query", "mock") if payload else "mock",
            "fatos_encontrados": ["Mock response — install strands-agents[a2a] for real execution"],
            "fontes": [],
            "titulo": "Mock Deliverable",
            "introducao": "This is a mock response.",
            "corpo_analise": "Install strands-agents[a2a] for real A2A execution.",
            "conclusao": "Mock complete.",
            "referencias": [],
            "aprovado": True,
            "veredicto": "APPROVED",
            "score_qualidade": 1.0,
            "criticas": [],
        }

    async def stream(self, task: str, payload: dict[str, Any] = None, **kwargs):
        """Mock streaming — yields a single chunk."""
        result = await self.invoke(task, payload, **kwargs)
        yield result
