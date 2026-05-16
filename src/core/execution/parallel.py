"""
Parallel Step Scheduler — Wave 3.

Identifies independent steps that can run in parallel and executes them
concurrently using ThreadPoolExecutor. Steps within the same Part are
sequential (A1→A2→A3), but steps across Parts are independent (B1 ∥ C1).

Parallelism rules:
  - Steps with no depends_on AND whose dependencies are all completed → eligible
  - Steps from different Parts with no cross-Part dependencies → parallel
  - Max parallelism is bounded (default: 3 concurrent steps)
  - Each parallel step still gets its own checkpoint on completion

Example from Issue #146:
  Part A: A1 → A2 → A3 → A4 (sequential)
  Part B: B1 (independent of A)
  Part C: C1 (independent of A and B)

  Execution plan:
    Stage 1: A1 (must go first — no deps)
    Stage 2: A2 (depends on A1)
    Stage 3: A3 (depends on A2)
    Stage 4: A4, B1, C1 (A4 depends on A3; B1 and C1 are independent)
             → B1 and C1 can start as soon as their deps are met
             → In practice: B1 ∥ C1 ∥ A4 if all deps satisfied

  Simplified for Wave 3: B1 and C1 run in parallel AFTER all of Part A completes.
  True DAG-based parallelism (B1 starts immediately) is Wave 4.

Design decisions:
  - ThreadPoolExecutor (not multiprocessing) — steps share the same workspace
  - Max 3 parallel steps to avoid overwhelming the container's CPU/memory
  - Checkpoint is written per-step (thread-safe via DynamoDB atomic ADD)
  - If any parallel step fails, remaining parallel steps are cancelled
  - Sequential fallback: if parallelism is disabled or only 1 step eligible, runs sequentially

Ref: ADR-038 Wave 3 (Parallel execution of independent steps)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.core.execution.spec_parser import ExecutionStep

logger = logging.getLogger(__name__)

# Maximum concurrent steps (bounded to prevent container resource exhaustion)
MAX_PARALLEL_STEPS = 3


@dataclass
class ExecutionStage:
    """A group of steps that can execute in parallel."""

    stage_index: int
    steps: list[ExecutionStep] = field(default_factory=list)
    is_parallel: bool = False

    @property
    def step_ids(self) -> list[str]:
        return [s.id for s in self.steps]

    def __repr__(self) -> str:
        mode = "parallel" if self.is_parallel else "sequential"
        return f"Stage({self.stage_index}, {mode}, [{', '.join(self.step_ids)}])"


def build_execution_plan(steps: list[ExecutionStep]) -> list[ExecutionStage]:
    """Build an execution plan that identifies parallelizable stages.

    Groups steps into stages where:
    - Steps within a stage can run in parallel (no inter-dependencies)
    - Stages execute sequentially (stage N+1 waits for stage N to complete)

    Algorithm:
    1. Build dependency graph from step.depends_on
    2. Topological sort into levels (steps at same level are independent)
    3. Group into ExecutionStages

    Args:
        steps: Ordered list of ExecutionSteps from the parser.

    Returns:
        List of ExecutionStages in execution order.
    """
    if not steps:
        return []

    # Build lookup
    step_map = {s.id: s for s in steps}
    all_ids = [s.id for s in steps]

    # Compute levels via topological sort
    # Level 0: steps with no dependencies
    # Level N: steps whose dependencies are all at level < N
    levels: dict[str, int] = {}

    def get_level(step_id: str, visited: set | None = None) -> int:
        if step_id in levels:
            return levels[step_id]

        if visited is None:
            visited = set()

        if step_id in visited:
            # Circular dependency — treat as level 0 (shouldn't happen with valid specs)
            logger.warning("Circular dependency detected at step %s", step_id)
            return 0

        visited.add(step_id)
        step = step_map.get(step_id)
        if not step or not step.depends_on:
            levels[step_id] = 0
            return 0

        max_dep_level = 0
        for dep_id in step.depends_on:
            if dep_id in step_map:
                dep_level = get_level(dep_id, visited.copy())
                max_dep_level = max(max_dep_level, dep_level)

        my_level = max_dep_level + 1
        levels[step_id] = my_level
        return my_level

    # Compute levels for all steps
    for step_id in all_ids:
        get_level(step_id)

    # Group by level
    max_level = max(levels.values()) if levels else 0
    stages: list[ExecutionStage] = []

    for level in range(max_level + 1):
        level_steps = [step_map[sid] for sid in all_ids if levels.get(sid) == level]
        if not level_steps:
            continue

        is_parallel = len(level_steps) > 1
        stages.append(ExecutionStage(
            stage_index=len(stages),
            steps=level_steps,
            is_parallel=is_parallel,
        ))

    logger.info(
        "Execution plan: %d stages from %d steps. Parallel stages: %d",
        len(stages), len(steps),
        sum(1 for s in stages if s.is_parallel),
    )
    for stage in stages:
        logger.debug("  %s", stage)

    return stages


def get_parallel_groups(steps: list[ExecutionStep]) -> list[list[ExecutionStep]]:
    """Simplified interface: return groups of steps that can run together.

    Each group is a list of steps that can execute in parallel.
    Groups are returned in execution order (group N must complete before group N+1).

    This is the interface used by the StepExecutor for Wave 3 parallel execution.

    Args:
        steps: Ordered list of ExecutionSteps.

    Returns:
        List of step groups. Single-step groups run sequentially.
        Multi-step groups can run in parallel (up to MAX_PARALLEL_STEPS).
    """
    stages = build_execution_plan(steps)
    groups = []

    for stage in stages:
        if stage.is_parallel and len(stage.steps) > MAX_PARALLEL_STEPS:
            # Split into chunks of MAX_PARALLEL_STEPS
            for i in range(0, len(stage.steps), MAX_PARALLEL_STEPS):
                chunk = stage.steps[i:i + MAX_PARALLEL_STEPS]
                groups.append(chunk)
        else:
            groups.append(stage.steps)

    return groups
