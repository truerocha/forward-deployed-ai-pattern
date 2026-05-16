"""
ERP Integration — Bridges the Orchestrator with the Step Executor.

This module provides the entry point for the orchestrator to use the
Execution Readiness Pipeline (ERP) when a task has complexity=execution.

The integration is designed to be called from the orchestrator's handle_event()
method AFTER workspace setup but BEFORE the standard agent pipeline. If the
task is classified as "execution", this module takes over and runs the
step-by-step executor instead of the standard reconnaissance→engineering flow.

Integration point in orchestrator.py:
  1. Orchestrator reads task from DynamoDB (has `complexity` field)
  2. If complexity == "execution":
     a. Parse spec_content into ExecutionSteps
     b. Run StepExecutor with workspace context
     c. Return result (skip standard agent pipeline)
  3. If complexity != "execution":
     a. Continue with standard pipeline (unchanged)

Design decisions:
  - Separate module (not inline in orchestrator) for testability
  - Returns a dict compatible with orchestrator's result format
  - Non-breaking: orchestrator only calls this if complexity field exists AND == "execution"
  - Graceful fallback: if parsing finds 0 steps, returns None (orchestrator continues normally)

Ref: Issue #146 (class of failure: execution tasks treated as simple)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from src.core.execution.spec_parser import parse_execution_steps, ExecutionStep
from src.core.execution.step_executor import StepExecutor, ExecutionResult
from src.core.execution.preflight import run_preflight, PreflightResult

logger = logging.getLogger(__name__)


def should_use_erp(task_record: dict) -> bool:
    """Determine if a task should use the Execution Readiness Pipeline.

    Checks the `complexity` field written by the webhook_ingest Lambda.
    Only tasks explicitly classified as "execution" use the ERP.

    Args:
        task_record: The DynamoDB task record (or data_contract dict).

    Returns:
        True if the task should use step-by-step execution.
    """
    complexity = task_record.get("complexity", "")
    return complexity == "execution"


def execute_with_erp(
    task_id: str,
    spec_content: str,
    workspace_dir: str,
    stage_callback: Callable | None = None,
    event_callback: Callable | None = None,
    step_timeout: int = 900,
) -> dict[str, Any] | None:
    """Execute a task using the Execution Readiness Pipeline.

    Parses the spec_content into atomic steps and executes them sequentially
    with gate validation. Returns a result dict compatible with the
    orchestrator's output format.

    If parsing finds 0 steps (spec doesn't have recognizable structure),
    returns None — the orchestrator should fall back to the standard pipeline.

    Args:
        task_id: DynamoDB task_id.
        spec_content: The full spec markdown content.
        workspace_dir: Working directory for command execution.
        stage_callback: Callable(task_id, stage, **kwargs) for dashboard.
        event_callback: Callable(task_id, event_type, message, **metadata) for events.
        step_timeout: Max seconds per step.

    Returns:
        Result dict if ERP handled the task, or None if fallback needed.
    """
    # Phase 1: Parse spec into execution steps
    steps = parse_execution_steps(spec_content)

    if not steps:
        logger.info(
            "ERP: task %s classified as execution but no steps parsed — falling back to standard pipeline",
            task_id,
        )
        if event_callback:
            event_callback(
                task_id, "system",
                "⚠️ ERP: spec classified as execution but no structured steps found — using standard pipeline",
                phase="execution",
            )
        return None  # Signal: orchestrator should continue with standard pipeline

    logger.info(
        "ERP: task %s has %d execution steps — using step executor",
        task_id, len(steps),
    )

    if event_callback:
        step_summary = ", ".join(f"{s.id}:{s.title[:30]}" for s in steps[:5])
        event_callback(
            task_id, "system",
            f"🔧 ERP activated: {len(steps)} steps detected [{step_summary}]",
            phase="execution",
        )

    # Phase 1.5: Pre-flight workspace validation (Wave 3)
    preflight_result = run_preflight(steps, workspace_dir)

    if event_callback:
        event_callback(
            task_id, "system",
            f"🔍 Pre-flight: {preflight_result.summary()}",
            phase="execution",
        )

    if not preflight_result.passed:
        logger.warning(
            "ERP pre-flight FAILED for task %s: %s",
            task_id, preflight_result.blocking_errors,
        )
        if event_callback:
            event_callback(
                task_id, "error",
                f"❌ Pre-flight validation failed: {'; '.join(preflight_result.blocking_errors[:3])}",
                phase="execution",
                gate_name="preflight",
                gate_result="fail",
            )
        return {
            "status": "failed",
            "agent_name": "erp-step-executor",
            "output": f"Pre-flight validation failed: {'; '.join(preflight_result.blocking_errors)}",
            "error": f"Pre-flight blocked: {preflight_result.blocking_errors[0]}",
            "preflight_checks": [
                {"name": c.name, "passed": c.passed, "error": c.error}
                for c in preflight_result.checks
            ],
        }

    # Phase 2: Store parsed steps in DynamoDB for dashboard visibility
    if stage_callback:
        execution_steps_json = json.dumps([
            {"id": s.id, "title": s.title, "has_gate": s.has_gate(), "depends_on": s.depends_on}
            for s in steps
        ])
        stage_callback(
            task_id, "erp_executing",
            execution_steps=execution_steps_json,
            total_steps=str(len(steps)),
        )

    # Phase 3: Execute steps
    executor = StepExecutor(
        task_id=task_id,
        workspace_dir=workspace_dir,
        stage_callback=stage_callback,
        event_callback=event_callback,
        step_timeout=step_timeout,
    )

    result = executor.execute(steps)

    # Phase 4: Format result for orchestrator compatibility
    return _format_erp_result(task_id, result, steps)


def _format_erp_result(
    task_id: str,
    result: ExecutionResult,
    steps: list,
) -> dict[str, Any]:
    """Format ExecutionResult into orchestrator-compatible output.

    The orchestrator expects:
      - status: "completed" | "failed"
      - agent_name: who handled it
      - output: human-readable summary
    """
    if result.status == "completed":
        output = (
            f"ERP execution completed successfully.\n"
            f"Steps completed: {len(result.steps_completed)}/{len(steps)}\n"
            f"Duration: {result.total_duration_ms}ms\n"
            f"Steps: {', '.join(result.steps_completed)}"
        )
        return {
            "status": "completed",
            "agent_name": "erp-step-executor",
            "output": output,
            "erp_result": result.to_dict(),
        }
    else:
        output = (
            f"ERP execution failed at step {result.failure_step}.\n"
            f"Reason: {result.failure_reason}\n"
            f"Steps completed before failure: {', '.join(result.steps_completed) or 'none'}\n"
            f"Duration: {result.total_duration_ms}ms"
        )
        return {
            "status": "failed",
            "agent_name": "erp-step-executor",
            "output": output,
            "error": result.failure_reason,
            "erp_result": result.to_dict(),
        }
