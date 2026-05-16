"""
Step Executor — Atomic step-by-step execution engine for complex tasks.

Executes parsed ExecutionSteps sequentially with:
  - Per-step DynamoDB stage updates (dashboard visibility)
  - Gate validation after each step
  - Fail-fast on gate failure (don't proceed to next step)
  - Structured result reporting per step
  - Checkpoint per-step for resume-from-failure (Wave 2)

Wave 1 scope:
  - Sequential execution only (no parallelism)
  - Dashboard shows current_step instead of generic "workspace"

Wave 2 additions:
  - Checkpoint after each successful gate (DynamoDB atomic write)
  - Resume from last checkpoint on container restart
  - Checkpoint version conflict detection (zombie container protection)

Design decisions:
  - Executor runs INSIDE the existing ECS container (not a new service)
  - Uses subprocess for command execution (same workspace context)
  - 15-minute timeout per step (fail fast vs 60-min whole-task timeout)
  - Gate failure stops execution immediately — reports which step failed
  - All step results written to DynamoDB for dashboard rendering
  - Checkpoint uses DynamoDB String Set ADD (atomic, no race conditions)

Ref: Issue #146 (class of failure: multi-step execution without decomposition)
Ref: ADR-038 Wave 2 (Checkpoint per-step, resume from last checkpoint)
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

from src.core.execution.spec_parser import ExecutionStep
from src.core.execution.checkpoint import (
    CheckpointState,
    load_checkpoint,
    save_step_checkpoint,
    update_current_step,
    CheckpointConflictError,
)

logger = logging.getLogger(__name__)

# Default timeout per step (15 minutes)
DEFAULT_STEP_TIMEOUT_SECONDS = 900


@dataclass
class StepResult:
    """Result of executing a single step."""

    step_id: str
    status: str  # "passed" | "failed" | "skipped" | "timeout"
    duration_ms: int = 0
    command_output: str = ""
    gate_output: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "command_output": self.command_output[:2000],  # Cap for DynamoDB
            "gate_output": self.gate_output[:2000],
            "error": self.error[:500],
        }


@dataclass
class ExecutionResult:
    """Aggregate result of executing all steps."""

    status: str  # "completed" | "failed" | "partial"
    steps_completed: list[str] = field(default_factory=list)
    steps_failed: list[str] = field(default_factory=list)
    step_results: dict[str, StepResult] = field(default_factory=dict)
    total_duration_ms: int = 0
    failure_step: str = ""
    failure_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "steps_completed": self.steps_completed,
            "steps_failed": self.steps_failed,
            "step_results": {k: v.to_dict() for k, v in self.step_results.items()},
            "total_duration_ms": self.total_duration_ms,
            "failure_step": self.failure_step,
            "failure_reason": self.failure_reason,
        }


class StepExecutor:
    """Executes parsed execution steps atomically with gate validation.

    Usage:
        from src.core.execution.spec_parser import parse_execution_steps
        from src.core.execution.step_executor import StepExecutor

        steps = parse_execution_steps(spec_content)
        executor = StepExecutor(
            task_id="TASK-abc123",
            workspace_dir="/workspace/repo",
            stage_callback=task_queue.update_task_stage,
            event_callback=task_queue.append_task_event,
        )
        result = executor.execute(steps)
    """

    def __init__(
        self,
        task_id: str,
        workspace_dir: str,
        stage_callback=None,
        event_callback=None,
        step_timeout: int = DEFAULT_STEP_TIMEOUT_SECONDS,
    ):
        """Initialize the step executor.

        Args:
            task_id: DynamoDB task_id for stage updates.
            workspace_dir: Working directory for command execution.
            stage_callback: Callable(task_id, stage, **kwargs) for dashboard updates.
            event_callback: Callable(task_id, event_type, message, **metadata) for event log.
            step_timeout: Max seconds per step before timeout.
        """
        self._task_id = task_id
        self._workspace_dir = workspace_dir
        self._stage_callback = stage_callback
        self._event_callback = event_callback
        self._step_timeout = step_timeout

    def execute(self, steps: list[ExecutionStep]) -> ExecutionResult:
        """Execute all steps sequentially with gate validation and checkpointing.

        On first run: executes all steps in order.
        On resume (container restart): loads checkpoint, skips completed steps,
        resumes from the first non-completed step.

        Stops at the first gate failure. Steps without commands are skipped.
        Steps without gates are considered passed after command execution.

        After each successful gate, a checkpoint is written to DynamoDB.
        If the container dies, the next execution resumes from the checkpoint.

        Args:
            steps: Ordered list of ExecutionSteps from the parser.

        Returns:
            ExecutionResult with per-step details.
        """
        if not steps:
            return ExecutionResult(status="completed")

        result = ExecutionResult(status="completed")
        start_time = time.time()
        total_steps = len(steps)

        # ── Wave 2: Load checkpoint for resume ──────────────────
        checkpoint = load_checkpoint(self._task_id)
        checkpoint_version = checkpoint.checkpoint_version
        ordered_ids = [s.id for s in steps]
        resume_index = checkpoint.get_resume_point(ordered_ids)

        # Populate result with previously completed steps
        for step_id in checkpoint.completed_steps:
            result.steps_completed.append(step_id)
            if step_id in checkpoint.step_results:
                result.step_results[step_id] = StepResult(
                    step_id=step_id,
                    status="passed",
                    duration_ms=checkpoint.step_results[step_id].get("duration_ms", 0),
                )

        if resume_index > 0:
            skipped_ids = ordered_ids[:resume_index]
            logger.info(
                "Resuming from checkpoint: task=%s, skipping %d completed steps (%s), "
                "starting at step %s",
                self._task_id, resume_index, ", ".join(skipped_ids),
                ordered_ids[resume_index] if resume_index < total_steps else "ALL_DONE",
            )
            self._emit_event(
                "system",
                f"♻️ Resuming from checkpoint: {resume_index}/{total_steps} steps already completed. "
                f"Starting at step {ordered_ids[resume_index] if resume_index < total_steps else 'DONE'}",
                phase="execution",
            )

        if resume_index >= total_steps:
            # All steps already completed in a previous run
            result.total_duration_ms = int((time.time() - start_time) * 1000)
            self._update_stage("execution_complete")
            self._emit_event("system", "✅ All steps already completed (checkpoint)", phase="execution")
            return result

        logger.info(
            "Step executor starting: task=%s, steps=%d, resume_from=%d, timeout=%ds/step",
            self._task_id, total_steps, resume_index, self._step_timeout,
        )

        for i in range(resume_index, total_steps):
            step = steps[i]

            # Update dashboard: show which step is active
            stage_label = f"step_{step.id}"
            self._update_stage(stage_label, current_step=step.id, step_progress=f"{i+1}/{total_steps}")
            update_current_step(self._task_id, step.id)

            self._emit_event(
                "system",
                f"▶ Step {step.id}: {step.title} ({i+1}/{total_steps})",
                phase="execution",
            )

            # Skip steps without commands
            if not step.has_commands():
                logger.info("Step %s has no commands — skipping", step.id)
                step_result = StepResult(step_id=step.id, status="skipped")
                result.step_results[step.id] = step_result
                result.steps_completed.append(step.id)
                # Checkpoint skipped steps too (so resume doesn't re-visit them)
                checkpoint_version = save_step_checkpoint(
                    self._task_id, step.id, step_result.to_dict(), checkpoint_version,
                )
                self._emit_event("system", f"⏭ Step {step.id} skipped (no commands)", phase="execution")
                continue

            # Execute the step
            step_result = self._execute_step(step)
            result.step_results[step.id] = step_result

            if step_result.status == "passed":
                result.steps_completed.append(step.id)

                # ── Wave 2: Checkpoint after gate pass ──────────
                try:
                    checkpoint_version = save_step_checkpoint(
                        self._task_id, step.id, step_result.to_dict(), checkpoint_version,
                    )
                except CheckpointConflictError:
                    # Another container is running — abort to prevent double execution
                    logger.error(
                        "Checkpoint conflict at step %s — aborting (another container is active)",
                        step.id,
                    )
                    result.status = "failed"
                    result.failure_step = step.id
                    result.failure_reason = "Checkpoint conflict — another container is executing this task"
                    self._emit_event(
                        "error",
                        f"⚠️ Checkpoint conflict at step {step.id} — aborting (zombie protection)",
                        phase="execution",
                    )
                    break

                self._emit_event(
                    "system",
                    f"✅ Step {step.id} passed ({step_result.duration_ms}ms) [checkpointed]",
                    phase="execution",
                )
            else:
                # Gate failed or timeout — stop execution
                result.steps_failed.append(step.id)
                result.status = "failed"
                result.failure_step = step.id
                result.failure_reason = step_result.error or f"Step {step.id} {step_result.status}"

                self._emit_event(
                    "error",
                    f"❌ Step {step.id} {step_result.status}: {step_result.error[:200]}",
                    phase="execution",
                    gate_name=f"step_{step.id}_gate",
                    gate_result="fail",
                )

                logger.warning(
                    "Step %s failed — stopping execution. Completed: %s",
                    step.id, result.steps_completed,
                )
                break

        result.total_duration_ms = int((time.time() - start_time) * 1000)

        # Final stage update
        if result.status == "completed":
            self._update_stage("execution_complete")
            self._emit_event(
                "system",
                f"✅ All {total_steps} steps completed ({result.total_duration_ms}ms)",
                phase="execution",
            )
        else:
            self._update_stage(
                "execution_failed",
                failure_step=result.failure_step,
                failure_reason=result.failure_reason[:200],
            )

        logger.info(
            "Step executor finished: task=%s status=%s completed=%d/%d duration=%dms",
            self._task_id, result.status, len(result.steps_completed),
            total_steps, result.total_duration_ms,
        )

        return result

    def _execute_step(self, step: ExecutionStep) -> StepResult:
        """Execute a single step: run commands, then validate gate.

        Args:
            step: The ExecutionStep to execute.

        Returns:
            StepResult with status and outputs.
        """
        start_time = time.time()

        # Phase 1: Execute commands
        cmd_output, cmd_error = self._run_commands(step.commands)
        if cmd_error:
            duration_ms = int((time.time() - start_time) * 1000)
            return StepResult(
                step_id=step.id,
                status="failed",
                duration_ms=duration_ms,
                command_output=cmd_output,
                error=f"Command execution failed: {cmd_error}",
            )

        # Phase 2: Validate gate (if present)
        if step.has_gate():
            gate_output, gate_error = self._run_gate(step.gate)
            duration_ms = int((time.time() - start_time) * 1000)

            if gate_error:
                return StepResult(
                    step_id=step.id,
                    status="failed",
                    duration_ms=duration_ms,
                    command_output=cmd_output,
                    gate_output=gate_output,
                    error=f"Gate validation failed: {gate_error}",
                )

            return StepResult(
                step_id=step.id,
                status="passed",
                duration_ms=duration_ms,
                command_output=cmd_output,
                gate_output=gate_output,
            )

        # No gate — commands succeeded, step passes
        duration_ms = int((time.time() - start_time) * 1000)
        return StepResult(
            step_id=step.id,
            status="passed",
            duration_ms=duration_ms,
            command_output=cmd_output,
        )

    def _run_commands(self, commands: list[str]) -> tuple[str, str]:
        """Run a list of shell commands sequentially.

        Returns:
            Tuple of (combined_output, error_message).
            error_message is empty string on success.
        """
        combined_output = []

        for cmd in commands:
            logger.debug("Executing: %s", cmd)
            try:
                proc = subprocess.run(
                    cmd,
                    shell=True,
                    cwd=self._workspace_dir,
                    capture_output=True,
                    text=True,
                    timeout=self._step_timeout,
                )

                output = proc.stdout + proc.stderr
                combined_output.append(f"$ {cmd}\n{output}")

                if proc.returncode != 0:
                    error_msg = (
                        f"Command exited with code {proc.returncode}: {cmd}\n"
                        f"stderr: {proc.stderr[:500]}"
                    )
                    return "\n".join(combined_output), error_msg

            except subprocess.TimeoutExpired:
                return "\n".join(combined_output), f"Command timed out ({self._step_timeout}s): {cmd}"
            except Exception as e:
                return "\n".join(combined_output), f"Command execution error: {e}"

        return "\n".join(combined_output), ""

    def _run_gate(self, gate_command: str) -> tuple[str, str]:
        """Run a gate validation command.

        Returns:
            Tuple of (output, error_message).
            error_message is empty string if gate passes.
        """
        logger.debug("Running gate: %s", gate_command)
        try:
            proc = subprocess.run(
                gate_command,
                shell=True,
                cwd=self._workspace_dir,
                capture_output=True,
                text=True,
                timeout=self._step_timeout,
            )

            output = proc.stdout + proc.stderr

            if proc.returncode != 0:
                return output, f"Gate failed (exit code {proc.returncode}): {proc.stderr[:300]}"

            return output, ""

        except subprocess.TimeoutExpired:
            return "", f"Gate timed out ({self._step_timeout}s): {gate_command}"
        except Exception as e:
            return "", f"Gate execution error: {e}"

    def _update_stage(self, stage: str, **kwargs) -> None:
        """Update DynamoDB stage via callback (non-blocking)."""
        if self._stage_callback:
            try:
                self._stage_callback(self._task_id, stage, **kwargs)
            except Exception as e:
                logger.debug("Stage update failed (non-blocking): %s", e)

    def _emit_event(self, event_type: str, message: str, **metadata) -> None:
        """Emit event via callback (non-blocking)."""
        if self._event_callback:
            try:
                self._event_callback(self._task_id, event_type, message, **metadata)
            except Exception as e:
                logger.debug("Event emission failed (non-blocking): %s", e)
