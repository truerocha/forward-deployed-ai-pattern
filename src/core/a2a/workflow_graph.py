"""
A2A Workflow Graph — Resilient Agent Orchestration via Strands A2A Protocol.

Implements a directed graph of A2A agents with:
  - Sequential node execution with conditional routing
  - DynamoDB checkpointing for fault recovery (Saga pattern)
  - Dynamic feedback loops (reviewer → writer rework cycles)
  - AWS Cloud Map service discovery for ECS-deployed agents
  - Streaming support via A2AAgent.stream()

Graph Topology:
  RESEARCH → ENGINEERING → REVIEW → [APPROVED | loop back to ENGINEERING]
                                         ↓ (max 3 attempts)
                                      COMPLETED

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
    RawContent,
    WorkflowContext,
    ReviewFeedback,
    QualityVerdict,
    FinalReport,
    TaskPayload,
    # Backward-compatible aliases
    ConteudoBruto,
    ContextoWorkflow,
    FeedbackRevisao,
    RelatorioFinal,
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
        self._research_agent = None
        self._engineering_agent = None
        self._review_agent = None

    def _get_a2a_agent(self, endpoint: str):
        """Lazily create an A2A agent proxy for the given endpoint.

        Uses the Strands SDK A2AExecutor (client-side) which communicates
        with any A2A-compliant server via JSON-RPC over HTTP.
        The executor fetches the Agent Card from /.well-known/agent-card.json
        on first invocation, discovering capabilities dynamically.

        Fallback chain:
          1. strands.multiagent.a2a.executor.A2AExecutor (preferred — native Strands)
          2. _MockA2AAgent (local dev without Strands installed)
        """
        try:
            from strands.multiagent.a2a.executor import A2AExecutor
            return A2AExecutor(url=endpoint, timeout=self._timeout)
        except ImportError:
            logger.warning(
                "strands.multiagent.a2a.executor not available — using mock A2A agent for %s. "
                "Install with: pip install strands-agents[a2a]",
                endpoint,
            )
            return _MockA2AAgent(endpoint)

    @property
    def research_agent(self):
        """Research agent proxy (lazy initialization)."""
        if self._research_agent is None:
            self._research_agent = self._get_a2a_agent(self._pesquisa_endpoint)
        return self._research_agent

    @property
    def engineering_agent(self):
        """Writing agent proxy (lazy initialization)."""
        if self._engineering_agent is None:
            self._engineering_agent = self._get_a2a_agent(self._escrita_endpoint)
        return self._engineering_agent

    @property
    def review_agent(self):
        """Reviewer agent proxy (lazy initialization)."""
        if self._review_agent is None:
            self._review_agent = self._get_a2a_agent(self._revisao_endpoint)
        return self._review_agent

    # Backward-compatible property aliases
    @property
    def agente_pesquisa(self):
        """Backward-compatible alias for research_agent."""
        return self.research_agent

    @property
    def agente_escrita(self):
        """Backward-compatible alias for engineering_agent."""
        return self.engineering_agent

    @property
    def agente_revisao(self):
        """Backward-compatible alias for review_agent."""
        return self.review_agent

    async def execute_workflow(self, initial_prompt: str) -> FinalReport:
        """Execute the full A2A workflow graph from a user prompt.

        This is the simple (non-resilient) execution path — no checkpointing.
        Use GrafoResiliente for production workloads with fault recovery.

        Previously named: executar_workflow (param prompt_inicial → initial_prompt)

        Args:
            initial_prompt: The user's task description.

        Returns:
            The final approved FinalReport.
        """
        workflow_id = f"wf-{uuid.uuid4().hex[:12]}"
        context = WorkflowContext(
            workflow_id=workflow_id,
            user_input=initial_prompt,
        )

        # ─── Node 1: RESEARCH ────────────────────────────────────────────
        logger.info("[%s] Node RESEARCH: Starting research...", workflow_id)
        start = time.time()

        research_response = await self.research_agent.invoke(
            task="Coleta de dados detalhada e estruturada",
            payload={"query": context.user_input},
        )
        context.research_data = RawContent.model_validate(research_response)
        context.execution_metrics["pesquisa_duration_s"] = round(time.time() - start, 2)

        # ─── Node 2: ENGINEERING ─────────────────────────────────────────
        logger.info("[%s] Node ENGINEERING: Generating deliverable...", workflow_id)
        start = time.time()

        engineering_response = await self.engineering_agent.invoke(
            task="Produzir documento técnico estruturado com base nos dados de pesquisa",
            payload=context.research_data.model_dump(),
        )
        context.report = FinalReport.model_validate(engineering_response)
        context.execution_metrics["escrita_duration_s"] = round(time.time() - start, 2)

        # ─── Node 3: REVIEW (with feedback loop) ─────────────────────────
        for attempt in range(1, context.max_attempts + 1):
            logger.info(
                "[%s] Node REVIEW: Review attempt %d/%d...",
                workflow_id, attempt, context.max_attempts,
            )
            start = time.time()

            review_result = await self.review_agent.invoke(
                task="Avaliar qualidade técnica do relatório",
                payload=context.report.model_dump(),
            )

            feedback = ReviewFeedback.model_validate(review_result)
            context.feedback = feedback
            context.review_attempts = attempt

            duration = round(time.time() - start, 2)
            context.execution_metrics[f"revisao_{attempt}_duration_s"] = duration

            # ─── Dynamic Routing Decision ────────────────────────────────
            if feedback.verdict == QualityVerdict.APPROVED or feedback.approved:
                logger.info("[%s] Deliverable APPROVED on attempt %d", workflow_id, attempt)
                context.report.approved = True
                break

            if attempt >= context.max_attempts:
                logger.warning(
                    "[%s] Max review attempts reached — force-approving", workflow_id
                )
                context.report.approved = True
                break

            # ─── Feedback Loop: Route back to ENGINEERING ────────────────
            logger.info(
                "[%s] NEEDS_REVISION — routing back to ENGINEERING (attempt %d)",
                workflow_id, attempt + 1,
            )

            rewrite_response = await self.engineering_agent.invoke(
                task="Corrigir relatório com base no feedback da revisão",
                payload={
                    "dados_originais": context.research_data.model_dump(),
                    "relatorio_anterior": context.report.model_dump(),
                    "feedback": feedback.model_dump(),
                },
            )
            context.report = FinalReport.model_validate(rewrite_response)

        return context.report

    # Backward-compatible alias
    async def executar_workflow(self, prompt_inicial: str) -> FinalReport:
        """Backward-compatible alias for execute_workflow."""
        return await self.execute_workflow(prompt_inicial)


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

    async def execute_with_recovery(
        self,
        workflow_id: str,
        initial_prompt: str = "",
    ) -> FinalReport:
        """Execute workflow with checkpoint-based fault recovery.

        On first call, starts from RESEARCH. On subsequent calls with the
        same workflow_id, resumes from the last saved checkpoint.

        Previously named: executar_com_recuperacao (param prompt_inicial → initial_prompt)

        Args:
            workflow_id: Unique workflow ID (use same ID for recovery).
            initial_prompt: User prompt (only needed for new workflows).

        Returns:
            The final FinalReport (approved or force-approved).

        Raises:
            RuntimeError: If workflow fails after all retry attempts.
        """
        # ─── Recovery: Load existing checkpoint ──────────────────────────
        context = self._db.recover_checkpoint(workflow_id)

        if context:
            logger.info(
                "Recovering workflow %s from node: %s",
                workflow_id, context.current_node,
            )
            initial_node = context.current_node
        else:
            if not initial_prompt:
                raise ValueError(
                    f"No checkpoint found for {workflow_id} and no initial_prompt provided"
                )
            logger.info("Starting new workflow: %s", workflow_id)
            context = WorkflowContext(
                workflow_id=workflow_id,
                user_input=initial_prompt,
            )
            initial_node = "RESEARCH"

        try:
            # ─── Node: RESEARCH ──────────────────────────────────────────
            if initial_node == "RESEARCH":
                logger.info("[%s] Executing node RESEARCH...", workflow_id)
                start = time.time()

                response = await self.research_agent.invoke(
                    task="Coleta de dados detalhada e estruturada",
                    payload={"query": context.user_input},
                )
                context.research_data = RawContent.model_validate(response)
                context.execution_metrics["pesquisa_duration_s"] = round(
                    time.time() - start, 2
                )

                # Checkpoint: next node is ENGINEERING
                self._db.save_checkpoint(workflow_id, "ENGINEERING", context)
                initial_node = "ENGINEERING"

            # ─── Node: ENGINEERING ───────────────────────────────────────
            if initial_node == "ENGINEERING":
                logger.info("[%s] Executing node ENGINEERING...", workflow_id)
                start = time.time()

                response = await self.engineering_agent.invoke(
                    task="Produzir documento técnico estruturado",
                    payload=context.research_data.model_dump(),
                )
                context.report = FinalReport.model_validate(response)
                context.execution_metrics["escrita_duration_s"] = round(
                    time.time() - start, 2
                )

                # Checkpoint: next node is REVIEW
                self._db.save_checkpoint(workflow_id, "REVIEW", context)
                initial_node = "REVIEW"

            # ─── Node: REVIEW (with feedback loop) ───────────────────────
            if initial_node == "REVIEW":
                remaining = context.max_attempts - context.review_attempts

                for attempt in range(1, remaining + 1):
                    logger.info(
                        "[%s] Executing node REVIEW (attempt %d)...",
                        workflow_id, context.review_attempts + 1,
                    )
                    start = time.time()

                    result = await self.review_agent.invoke(
                        task="Avaliar qualidade técnica do relatório",
                        payload=context.report.model_dump(),
                    )

                    feedback = ReviewFeedback.model_validate(result)
                    context.feedback = feedback
                    context.review_attempts += 1

                    duration = round(time.time() - start, 2)
                    context.execution_metrics[
                        f"revisao_{context.review_attempts}_duration_s"
                    ] = duration

                    if feedback.verdict == QualityVerdict.APPROVED or feedback.approved:
                        context.report.approved = True
                        logger.info(
                            "[%s] APPROVED on attempt %d",
                            workflow_id, context.review_attempts,
                        )
                        break

                    if context.review_attempts >= context.max_attempts:
                        context.report.approved = True
                        logger.warning(
                            "[%s] Max attempts reached — force-approving", workflow_id
                        )
                        break

                    # Feedback loop: rewrite
                    logger.info("[%s] Routing back to ENGINEERING for rework...", workflow_id)
                    response = await self.engineering_agent.invoke(
                        task="Corrigir relatório com base no feedback",
                        payload={
                            "dados_originais": context.research_data.model_dump(),
                            "relatorio_anterior": context.report.model_dump(),
                            "feedback": feedback.model_dump(),
                        },
                    )
                    context.report = FinalReport.model_validate(response)

                    # Checkpoint after each rework cycle
                    self._db.save_checkpoint(workflow_id, "REVIEW", context)

            # ─── Terminal: COMPLETED ─────────────────────────────────────
            self._db.mark_completed(workflow_id, context)
            return context.report

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)[:300]}"
            logger.error("[%s] Workflow failed: %s", workflow_id, error_msg)
            self._db.mark_failed(workflow_id, context, error_msg)
            raise RuntimeError(
                f"Workflow {workflow_id} failed at node {context.current_node}: {error_msg}"
            ) from e

    # Backward-compatible alias
    async def executar_com_recuperacao(
        self, workflow_id: str, prompt_inicial: str = ""
    ) -> FinalReport:
        """Backward-compatible alias for execute_with_recovery."""
        return await self.execute_with_recovery(workflow_id, prompt_inicial)


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
