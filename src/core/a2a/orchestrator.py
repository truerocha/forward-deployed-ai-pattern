"""
A2A Squad Orchestrator — Production Entrypoint for the AI Squad Pipeline.

Wires together all A2A components into a single cohesive execution path:
  - GrafoResiliente (workflow graph with DynamoDB checkpointing)
  - ResilientStateManager (retry + DLQ circuit breaker)
  - OpenTelemetry tracing (distributed traces via ADOT → X-Ray)
  - Agent Cards (explicit contract enforcement)
  - Squad Bridge (connects A2A protocol to Conductor squad composition)

This is the entrypoint invoked by:
  - ECS Task (production): via `python -m src.core.a2a.orchestrator`
  - EventBridge Rule → ECS RunTask (cloud-native trigger)
  - Local development: via `make a2a-run`

The orchestrator does NOT contain agent logic — it only routes tasks
between A2A servers and manages the workflow lifecycle.

Ref: ADR-034 (A2A Protocol), ADR-019 (Agentic Squad Architecture),
     ADR-020 (Conductor Orchestration Pattern)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Optional

from src.core.a2a.agent_cards import AGENT_CARD_REGISTRY, list_cards
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
from src.core.a2a.observability import (
    initialize_tracing,
    trace_a2a_invocation,
    trace_workflow_node,
)
from src.core.a2a.resilience import ResilientStateManager, classify_error
from src.core.a2a.workflow_graph import A2AWorkflowGraph

logger = logging.getLogger(__name__)


class SquadOrchestrator:
    """Production-grade A2A orchestrator with full observability and resilience.

    Combines the workflow graph execution with:
      - Contract validation (input/output against Pydantic schemas)
      - Distributed tracing (OTel spans per node + per invocation)
      - Resilient state management (atomic retries + DLQ)
      - Squad metadata emission (for Conductor integration)

    This is the class that ECS tasks instantiate to run A2A workflows.
    """

    def __init__(
        self,
        pesquisa_endpoint: str | None = None,
        escrita_endpoint: str | None = None,
        revisao_endpoint: str | None = None,
        state_manager: ResilientStateManager | None = None,
        timeout: int = 120,
        max_attempts: int = 3,
        enable_tracing: bool = True,
        # Backward-compatible parameter name
        max_tentativas: int | None = None,
    ):
        """Initialize the squad orchestrator.

        Args:
            pesquisa_endpoint: Research agent A2A endpoint.
            escrita_endpoint: Engineering agent A2A endpoint.
            revisao_endpoint: Review agent A2A endpoint.
            state_manager: Resilient state manager (DynamoDB + SQS DLQ).
            timeout: Default A2A invocation timeout in seconds.
            max_attempts: Maximum review feedback loops.
            enable_tracing: Whether to initialize OTel tracing.
            max_tentativas: Backward-compatible alias for max_attempts.
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
        self._max_attempts = max_tentativas if max_tentativas is not None else max_attempts

        # State management with resilience (retry + DLQ)
        self._state = state_manager or ResilientStateManager()

        # Initialize distributed tracing
        if enable_tracing:
            initialize_tracing(
                service_name="fde-a2a-orchestrator",
                environment=os.environ.get("ENVIRONMENT", "dev"),
            )

        # Workflow graph (lazy — connects to agents on first use)
        self._graph = A2AWorkflowGraph(
            pesquisa_endpoint=self._pesquisa_endpoint,
            escrita_endpoint=self._escrita_endpoint,
            revisao_endpoint=self._revisao_endpoint,
            timeout=self._timeout,
        )

        logger.info(
            "SquadOrchestrator initialized: pesquisa=%s escrita=%s revisao=%s",
            self._pesquisa_endpoint,
            self._escrita_endpoint,
            self._revisao_endpoint,
        )

    async def execute(
        self,
        prompt: str,
        workflow_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a full A2A squad workflow with resilience and observability.

        This is the primary entry point for production execution.
        Handles the complete lifecycle: research → engineering → review → approval.

        Previously named: executar

        Args:
            prompt: User task description / spec content.
            workflow_id: Optional workflow ID (for recovery). Generated if not provided.
            metadata: Optional metadata (task_id, spec_path, source platform, etc.).

        Returns:
            Execution result dict containing:
              - workflow_id: Unique execution ID
              - status: "completed" | "failed" | "dlq"
              - report: Final FinalReport (if completed)
              - metricas: Execution metrics (durations, tokens, attempts)
              - erros: Accumulated errors (if any)
        """
        wf_id = workflow_id or f"wf-{uuid.uuid4().hex[:12]}"
        start_time = time.time()

        logger.info("[%s] Starting squad workflow: %s...", wf_id, prompt[:80])

        # ─── Recovery Check ──────────────────────────────────────────────
        context = self._state.recover_checkpoint(wf_id)

        if context:
            logger.info(
                "[%s] Recovering from checkpoint at node: %s (attempt %d)",
                wf_id, context.current_node, context.review_attempts,
            )
        else:
            context = WorkflowContext(
                workflow_id=wf_id,
                user_input=prompt,
                max_attempts=self._max_attempts,
            )

        try:
            # ─── Node: RESEARCH ──────────────────────────────────────────
            if context.current_node in ("RESEARCH", ""):
                context = await self._execute_research(wf_id, context)

            # ─── Node: ENGINEERING ───────────────────────────────────────
            if context.current_node == "ENGINEERING":
                context = await self._execute_engineering(wf_id, context)

            # ─── Node: REVIEW (feedback loop) ────────────────────────────
            if context.current_node == "REVIEW":
                context = await self._execute_review_loop(wf_id, context)

            # ─── Terminal: COMPLETED ─────────────────────────────────────
            total_duration = round(time.time() - start_time, 2)
            context.execution_metrics["total_duration_s"] = total_duration
            context.execution_metrics["metadata"] = metadata or {}

            self._state.mark_completed(wf_id, context)

            logger.info(
                "[%s] Workflow COMPLETED in %.1fs (attempts=%d)",
                wf_id, total_duration, context.review_attempts,
            )

            return {
                "workflow_id": wf_id,
                "status": "completed",
                "relatorio": context.report.model_dump() if context.report else None,
                "metricas": context.execution_metrics,
                "erros": context.erros,
                "tentativas_revisao": context.review_attempts,
            }

        except Exception as e:
            # ─── Resilient Failure Handling ───────────────────────────────
            should_retry = self._state.registrar_falha_com_retry(
                workflow_id=wf_id,
                current_node=context.current_node,
                context=context,
                erro=e,
            )

            total_duration = round(time.time() - start_time, 2)

            if should_retry:
                logger.warning(
                    "[%s] Workflow failed at %s — retry allowed (%.1fs)",
                    wf_id, context.current_node, total_duration,
                )
                return {
                    "workflow_id": wf_id,
                    "status": "retryable",
                    "no_falho": context.current_node,
                    "erro": str(e)[:300],
                    "metricas": context.execution_metrics,
                }
            else:
                logger.error(
                    "[%s] Workflow sent to DLQ after exhausting retries (%.1fs)",
                    wf_id, total_duration,
                )
                return {
                    "workflow_id": wf_id,
                    "status": "dlq",
                    "no_falho": context.current_node,
                    "erro": str(e)[:300],
                    "classificacao": classify_error(e).value,
                    "metricas": context.execution_metrics,
                    "erros": context.erros,
                }

    # Backward-compatible alias
    async def executar(
        self,
        prompt: str,
        workflow_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Backward-compatible alias for execute."""
        return await self.execute(prompt, workflow_id, metadata)

    async def _execute_research(
        self, wf_id: str, context: WorkflowContext
    ) -> WorkflowContext:
        """Execute the RESEARCH node with tracing and validation.

        Previously named: _executar_pesquisa
        """
        with trace_workflow_node(wf_id, "RESEARCH", {"query": context.user_input[:100]}):
            logger.info("[%s] → RESEARCH: collecting research data...", wf_id)
            start = time.time()

            with trace_a2a_invocation("pesquisa", "research", self._pesquisa_endpoint):
                response = await self._graph.research_agent.invoke(
                    task="Coleta de dados detalhada e estruturada sobre o tópico solicitado",
                    payload={"query": context.user_input},
                )

            # Contract validation — enforce RawContent schema
            context.research_data = RawContent.model_validate(response)
            context.current_node = "ENGINEERING"
            context.execution_metrics["pesquisa_duration_s"] = round(time.time() - start, 2)

            # Checkpoint after successful research
            self._state.save_checkpoint(wf_id, "ENGINEERING", context)

            logger.info(
                "[%s] ✓ RESEARCH complete: %d facts, confidence=%.2f (%.1fs)",
                wf_id,
                len(context.research_data.findings),
                context.research_data.confidence,
                context.execution_metrics["pesquisa_duration_s"],
            )

        return context

    # Backward-compatible alias
    _executar_pesquisa = _execute_research

    async def _execute_engineering(
        self, wf_id: str, context: WorkflowContext
    ) -> WorkflowContext:
        """Execute the ENGINEERING node with tracing and validation.

        Previously named: _executar_escrita
        """
        with trace_workflow_node(wf_id, "ENGINEERING"):
            logger.info("[%s] → ENGINEERING: generating deliverable...", wf_id)
            start = time.time()

            with trace_a2a_invocation("escrita", "engineering", self._escrita_endpoint):
                response = await self._graph.engineering_agent.invoke(
                    task="Produzir documento técnico estruturado com base nos dados de pesquisa",
                    payload=context.research_data.model_dump(),
                )

            # Contract validation — enforce FinalReport schema
            context.report = FinalReport.model_validate(response)
            context.current_node = "REVIEW"
            context.execution_metrics["escrita_duration_s"] = round(time.time() - start, 2)

            # Checkpoint after successful engineering
            self._state.save_checkpoint(wf_id, "REVIEW", context)

            logger.info(
                "[%s] ✓ ENGINEERING complete: %d artifacts (%.1fs)",
                wf_id,
                len(context.report.artifacts),
                context.execution_metrics["escrita_duration_s"],
            )

        return context

    # Backward-compatible alias
    _executar_escrita = _execute_engineering

    async def _execute_review_loop(
        self, wf_id: str, context: WorkflowContext
    ) -> WorkflowContext:
        """Execute the REVIEW node with feedback loop back to ENGINEERING.

        Previously named: _executar_revisao_loop
        """
        remaining = context.max_attempts - context.review_attempts

        for ciclo in range(1, remaining + 1):
            current_attempt = context.review_attempts + 1

            with trace_workflow_node(
                wf_id, "REVIEW", {"attempt": current_attempt}
            ):
                logger.info(
                    "[%s] → REVIEW: review attempt %d/%d...",
                    wf_id, current_attempt, context.max_attempts,
                )
                start = time.time()

                with trace_a2a_invocation("revisao", "review", self._revisao_endpoint):
                    result = await self._graph.review_agent.invoke(
                        task="Avaliar qualidade técnica do relatório produzido",
                        payload=context.report.model_dump(),
                    )

                # Contract validation — enforce ReviewFeedback schema
                feedback = ReviewFeedback.model_validate(result)
                feedback.tentativa = current_attempt
                context.feedback = feedback
                context.review_attempts = current_attempt

                duration = round(time.time() - start, 2)
                context.execution_metrics[f"revisao_{current_attempt}_duration_s"] = duration

                logger.info(
                    "[%s] REVIEW result: verdict=%s score=%.2f criticisms=%d (%.1fs)",
                    wf_id,
                    feedback.verdict.value,
                    feedback.quality_score,
                    len(feedback.criticisms),
                    duration,
                )

            # ─── Routing Decision ────────────────────────────────────────
            if feedback.verdict == QualityVerdict.APPROVED or feedback.approved:
                context.report.approved = True
                logger.info("[%s] ✓ APPROVED on attempt %d", wf_id, current_attempt)
                break

            if current_attempt >= context.max_attempts:
                context.report.approved = True
                logger.warning(
                    "[%s] Max review attempts reached — force-approving", wf_id
                )
                break

            # ─── Feedback Loop: Route back to ENGINEERING ────────────────
            with trace_workflow_node(wf_id, "ENGINEERING_REWORK", {"attempt": current_attempt}):
                logger.info(
                    "[%s] → ENGINEERING (rework): addressing %d criticisms...",
                    wf_id, len(feedback.criticisms),
                )
                start = time.time()

                with trace_a2a_invocation("escrita", "rework", self._escrita_endpoint):
                    response = await self._graph.engineering_agent.invoke(
                        task="Corrigir relatório com base no feedback da revisão",
                        payload={
                            "dados_originais": context.research_data.model_dump(),
                            "relatorio_anterior": context.report.model_dump(),
                            "feedback": feedback.model_dump(),
                        },
                    )

                context.report = FinalReport.model_validate(response)
                context.execution_metrics[f"rework_{current_attempt}_duration_s"] = round(
                    time.time() - start, 2
                )

                # Checkpoint after each rework cycle
                self._state.save_checkpoint(wf_id, "REVIEW", context)

        return context

    # Backward-compatible alias
    _executar_revisao_loop = _execute_review_loop

    def get_status(self, workflow_id: str) -> dict[str, Any]:
        """Get current status of a workflow (for monitoring/portal).

        Args:
            workflow_id: The workflow to check.

        Returns:
            Status dict with node, attempts, and last update time.
        """
        context = self._state.recover_checkpoint(workflow_id)
        if not context:
            return {"workflow_id": workflow_id, "status": "not_found"}

        return {
            "workflow_id": workflow_id,
            "status": "in_progress" if "FAILURE" not in context.current_node else "failed",
            "current_node": context.current_node,
            "review_attempts": context.review_attempts,
            "updated_at": context.updated_at,
            "erros": context.erros,
        }

    def list_active_workflows(self) -> list[dict[str, Any]]:
        """List all active (non-terminal) workflows.

        Returns:
            List of workflow summaries from DynamoDB.
        """
        return self._state.list_active_workflows()

    @staticmethod
    def available_agents() -> list[dict[str, Any]]:
        """List all A2A agents available for squad composition.

        Used by the Conductor to understand what agents are available
        in the A2A microservice layer.

        Returns:
            List of agent cards with capabilities and schemas.
        """
        return list_cards()


# ─── CLI Entrypoint ──────────────────────────────────────────────────────────


async def _run_from_cli():
    """Run a workflow from CLI arguments or environment variables."""
    import argparse

    parser = argparse.ArgumentParser(description="FDE A2A Squad Orchestrator")
    parser.add_argument("--prompt", "-p", type=str, help="Task prompt to execute")
    parser.add_argument("--workflow-id", "-w", type=str, help="Workflow ID (for recovery)")
    parser.add_argument("--timeout", "-t", type=int, default=120, help="A2A timeout (seconds)")
    parser.add_argument("--max-attempts", "-m", type=int, default=3, help="Max review attempts")
    parser.add_argument("--status", "-s", type=str, help="Check workflow status")
    parser.add_argument("--list-active", action="store_true", help="List active workflows")
    parser.add_argument("--list-agents", action="store_true", help="List available A2A agents")

    args = parser.parse_args()

    orchestrator = SquadOrchestrator(
        timeout=args.timeout,
        max_attempts=args.max_attempts,
    )

    if args.list_agents:
        agents = orchestrator.available_agents()
        for agent in agents:
            print(f"  {agent['name']}: {agent['description']}")
            print(f"    Capabilities: {agent['capabilities']['tasks']}")
            print(f"    Model: {agent['x-fde']['model_tier']} (cost={agent['x-fde']['cost_weight']})")
            print()
        return

    if args.list_active:
        workflows = orchestrator.list_active_workflows()
        if not workflows:
            print("No active workflows.")
        for wf in workflows:
            print(f"  {wf['workflow_id']}: node={wf['node_name']} updated={wf['updated_at']}")
        return

    if args.status:
        status = orchestrator.get_status(args.status)
        print(json.dumps(status, indent=2, default=str))
        return

    if not args.prompt:
        # Check for prompt from stdin (EventBridge payload)
        import sys
        if not sys.stdin.isatty():
            payload = json.load(sys.stdin)
            args.prompt = payload.get("prompt", payload.get("detail", {}).get("prompt", ""))
            args.workflow_id = payload.get("workflow_id")

    if not args.prompt:
        parser.error("--prompt is required (or pipe JSON via stdin)")

    result = await orchestrator.execute(
        prompt=args.prompt,
        workflow_id=args.workflow_id,
    )

    print(json.dumps(result, indent=2, default=str))


def main():
    """Synchronous entrypoint for `python -m src.core.a2a.orchestrator`."""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(_run_from_cli())


if __name__ == "__main__":
    main()
