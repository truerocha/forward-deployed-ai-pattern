"""
Conductor Integration — Bridges Conductor Plans with DistributedOrchestrator.

This module provides the integration layer that:
  1. Decides whether to use the Conductor (feature flag + organism level)
  2. Runs the SWE Synapse Engine for pre-execution design intelligence
  3. Converts Conductor WorkflowPlans into canonical SquadManifests
  4. Enriches SCD with access list metadata for topology enforcement
  5. Injects focused subtask instructions into agent environment
  6. Handles recursive refinement loop after execution

The integration preserves backward compatibility: when CONDUCTOR_ENABLED is
False or organism level is below threshold, the existing static manifest
path is used unchanged.

Feature flag: CONDUCTOR_ENABLED (env var, default: "true")
Activation threshold: O3+ (organism levels O3, O4, O5 use Conductor)

Ref: ADR-020 (Conductor Orchestration Pattern)
Ref: fde-design-swe-sinapses.md Section 8.3 (Conductor Enhancement)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from src.core.orchestration.conductor import (
    Conductor,
    TopologyType,
    WorkflowPlan,
    WorkflowStep,
)
from src.core.orchestration.distributed_orchestrator import (
    AgentSpec,
    DistributedOrchestrator,
    SquadManifest,
    StageResult,
    StageStatus,
)
from src.core.synapses.synapse_engine import SynapseEngine, SynapseAssessment

logger = logging.getLogger(__name__)

# Feature flag: enables Conductor-generated plans
CONDUCTOR_ENABLED = os.environ.get("CONDUCTOR_ENABLED", "true").lower() == "true"

# Minimum organism level for Conductor activation
# O1/O2 use static manifests (simple enough), O3+ use Conductor
_CONDUCTOR_THRESHOLD_LEVELS = {"O3", "O4", "O5"}


def should_use_conductor(organism_level: str) -> bool:
    """Determine if the Conductor should generate the plan for this task.

    The Conductor is used when:
      1. CONDUCTOR_ENABLED feature flag is True
      2. Organism level is at or above threshold (O3+)

    For O1/O2 tasks, static manifests are sufficient and the Conductor
    overhead (~200ms + ~$0.02) is not justified.

    Args:
        organism_level: Task complexity classification (O1-O5).

    Returns:
        True if Conductor should generate the plan.
    """
    if not CONDUCTOR_ENABLED:
        logger.debug("Conductor disabled via feature flag")
        return False

    if organism_level not in _CONDUCTOR_THRESHOLD_LEVELS:
        logger.debug(
            "Organism level %s below Conductor threshold (O3+)", organism_level
        )
        return False

    return True


def generate_conductor_manifest(
    task_id: str,
    project_id: str,
    task_description: str,
    organism_level: str,
    user_value_statement: str,
    autonomy_level: int,
    knowledge_context: dict[str, Any] | None = None,
    learning_mode: bool = False,
    data_contract: dict[str, Any] | None = None,
    catalog_metadata: dict[str, Any] | None = None,
    prior_success_rate: float = 0.5,
    failure_recurrence: float = 0.0,
) -> SquadManifest:
    """Generate a SquadManifest using the Conductor's workflow plan.

    This is the primary entry point for Conductor-driven execution.
    It runs the SWE Synapse Engine first to determine design intelligence,
    then passes synapse guidance to the Conductor for plan generation.

    The synapse chain (Section 8.1 of fde-design-swe-sinapses.md):
      1. Epistemic: What do we KNOW about this domain?
      2. Paradigm: Should we plan or explore?
      3. Cost: Should we decompose or keep monolithic?
      4. Harness: Which architectural bundle fits?
      5. Depth: Are agent responsibilities deep enough?

    Args:
        task_id: Unique task identifier.
        project_id: Project this task belongs to.
        task_description: Natural language task description.
        organism_level: Complexity classification (O1-O5).
        user_value_statement: User value being delivered.
        autonomy_level: L1-L5 autonomy level.
        knowledge_context: Relevant knowledge for the task.
        learning_mode: Whether fidelity agent explains reasoning.
        data_contract: Canonical task data contract (for synapse assessment).
        catalog_metadata: Onboarding catalog data (for synapse assessment).
        prior_success_rate: Rate of success for similar tasks [0, 1].
        failure_recurrence: Rate of recurring failures [0, 1].

    Returns:
        SquadManifest ready for DistributedOrchestrator.execute().
    """
    # --- SWE Synapse Engine: Pre-Execution Design Intelligence ---
    synapse_engine = SynapseEngine()
    synapse_assessment = synapse_engine.assess(
        organism_level=organism_level,
        data_contract=data_contract,
        catalog_metadata=catalog_metadata,
        proposed_agents=_estimate_initial_agents(organism_level),
        prior_success_rate=prior_success_rate,
        failure_recurrence=failure_recurrence,
    )

    # Apply synapse recommendations to Conductor inputs
    recommended_agents = synapse_assessment.recommended_agents
    conductor_guidance = synapse_assessment.conductor_guidance

    # Enrich knowledge context with synapse guidance for the Conductor
    enriched_context = dict(knowledge_context or {})
    enriched_context["_synapse_guidance"] = conductor_guidance
    enriched_context["_synapse_paradigm"] = synapse_assessment.paradigm.paradigm.value
    enriched_context["_synapse_recommended_agents"] = recommended_agents

    # P1 (ADR-030): Inject recent ICRL episodes for LLM-as-retriever.
    # The Conductor sees past outcomes and naturally identifies what's relevant
    # when planning the workflow — no embedding infrastructure needed.
    try:
        from src.core.memory.icrl_episode_store import ICRLEpisodeStore
        import os
        _repo = data_contract.get("repo", "") if data_contract else ""
        if _repo:
            _episode_store = ICRLEpisodeStore(
                project_id=os.environ.get("PROJECT_ID", "global"),
                metrics_table=os.environ.get("METRICS_TABLE", ""),
            )
            _episode_context = _episode_store.get_context_for_rework(
                repo=_repo,
                max_episodes=5,
            )
            if _episode_context:
                enriched_context["_past_episodes"] = _episode_context
                logger.info("Injected %d chars of ICRL episode context into Conductor", len(_episode_context))
    except Exception as e:
        logger.debug("ICRL episode injection failed (non-blocking): %s", str(e)[:100])

    # --- Conductor: Generate WorkflowPlan ---
    conductor = Conductor()

    plan = conductor.generate_plan(
        task_id=task_id,
        task_description=task_description,
        organism_level=organism_level,
        knowledge_context=enriched_context,
        user_value_statement=user_value_statement,
    )

    # --- Post-Plan Synapse Validation ---
    # Re-assess with actual plan steps for depth and coherence validation
    post_plan_assessment = synapse_engine.assess(
        organism_level=organism_level,
        data_contract=data_contract,
        catalog_metadata=catalog_metadata,
        proposed_agents=plan.total_steps(),
        proposed_topology=plan.topology_type.value,
        proposed_steps=[
            {"subtask": s.subtask, "agent_role": s.agent_role, "step_index": s.step_index}
            for s in plan.steps
        ],
        scd_access_map={
            s.agent_role: [str(i) for i in s.visible_steps(plan.total_steps())]
            for s in plan.steps
        },
        prior_success_rate=prior_success_rate,
        failure_recurrence=failure_recurrence,
    )

    # If post-plan assessment recommends consolidation, log warning
    if post_plan_assessment.decomposition.recommendation == "consolidate":
        logger.warning(
            "Synapse recommends consolidation: task=%s proposed=%d recommended=%d reason=%s",
            task_id, plan.total_steps(),
            post_plan_assessment.recommended_agents,
            post_plan_assessment.decomposition.reasoning,
        )

    manifest = _convert_plan_to_manifest(
        plan=plan,
        project_id=project_id,
        user_value_statement=user_value_statement,
        autonomy_level=autonomy_level,
        learning_mode=learning_mode,
    )

    # Store plan + synapse metadata for observability and recursion
    manifest.knowledge_context["_conductor_plan"] = {
        "topology": plan.topology_type.value,
        "steps": len(plan.steps),
        "rationale": plan.planning_rationale,
        "recursive_depth": plan.recursive_depth,
        "confidence_threshold": plan.confidence_threshold,
        "estimated_tokens": plan.estimated_tokens,
    }
    manifest.knowledge_context["_synapse_assessment"] = {
        "paradigm": post_plan_assessment.paradigm.paradigm.value,
        "paradigm_confidence": post_plan_assessment.paradigm.confidence,
        "design_quality_score": post_plan_assessment.design_quality_score,
        "risk_signals": post_plan_assessment.risk_signals(),
        "recommended_agents": post_plan_assessment.recommended_agents,
        "coherent": post_plan_assessment.coherence.is_coherent,
        "epistemic_approach": post_plan_assessment.epistemic.recommended_approach,
    }

    logger.info(
        "Conductor manifest generated: task=%s topology=%s stages=%d agents=%d "
        "synapse_paradigm=%s design_quality=%.2f",
        task_id,
        plan.topology_type.value,
        manifest.stage_count(),
        manifest.total_agents(),
        post_plan_assessment.paradigm.paradigm.value,
        post_plan_assessment.design_quality_score,
    )

    return manifest


def _estimate_initial_agents(organism_level: str) -> int:
    """Estimate initial agent count before Conductor generates plan.

    Used by the SynapseEngine for pre-plan decomposition cost assessment.
    Based on organism-level defaults from ADR-019.
    """
    defaults = {"O1": 2, "O2": 3, "O3": 4, "O4": 5, "O5": 6}
    return defaults.get(organism_level, 4)


def execute_with_conductor(
    task_id: str,
    project_id: str,
    task_description: str,
    organism_level: str,
    user_value_statement: str,
    autonomy_level: int,
    knowledge_context: dict[str, Any] | None = None,
    learning_mode: bool = False,
    orchestrator: DistributedOrchestrator | None = None,
) -> list[StageResult]:
    """Execute a task using the Conductor + DistributedOrchestrator pipeline.

    This is the full execution path including recursive refinement:
      1. Conductor generates WorkflowPlan
      2. Plan is converted to SquadManifest
      3. DistributedOrchestrator executes the manifest
      4. Results are assessed for confidence
      5. If confidence is low, Conductor refines and re-executes (max 2x)

    Args:
        task_id: Unique task identifier.
        project_id: Project this task belongs to.
        task_description: Natural language task description.
        organism_level: Complexity classification (O1-O5).
        user_value_statement: User value being delivered.
        autonomy_level: L1-L5 autonomy level.
        knowledge_context: Relevant knowledge for the task.
        learning_mode: Whether fidelity agent explains reasoning.
        orchestrator: Optional pre-configured orchestrator instance.

    Returns:
        List of StageResult from the final execution attempt.
    """
    conductor = Conductor()
    orch = orchestrator or DistributedOrchestrator()

    # Step 1: Generate initial plan
    plan = conductor.generate_plan(
        task_id=task_id,
        task_description=task_description,
        organism_level=organism_level,
        knowledge_context=knowledge_context,
        user_value_statement=user_value_statement,
    )

    # Step 2: Execute
    manifest = _convert_plan_to_manifest(
        plan=plan,
        project_id=project_id,
        user_value_statement=user_value_statement,
        autonomy_level=autonomy_level,
        learning_mode=learning_mode,
    )
    results = orch.execute(manifest)

    # Step 3: Assess confidence and potentially recurse
    execution_result = _results_to_dict(results)

    if conductor.should_recurse(plan, execution_result):
        logger.info(
            "Conductor triggering recursive refinement for task=%s (depth %d -> %d)",
            task_id,
            plan.recursive_depth,
            plan.recursive_depth + 1,
        )

        # Step 4: Refine plan based on results
        refined_plan = conductor.refine_plan(
            original_plan=plan,
            execution_result=execution_result,
            task_description=task_description,
            knowledge_context=knowledge_context,
        )

        # Step 5: Re-execute with refined plan
        refined_manifest = _convert_plan_to_manifest(
            plan=refined_plan,
            project_id=project_id,
            user_value_statement=user_value_statement,
            autonomy_level=autonomy_level,
            learning_mode=learning_mode,
        )
        results = orch.execute(refined_manifest)

        # Check for second recursion (max depth 2)
        execution_result_2 = _results_to_dict(results)
        if conductor.should_recurse(refined_plan, execution_result_2):
            logger.info(
                "Conductor second recursion for task=%s (depth %d -> %d)",
                task_id,
                refined_plan.recursive_depth,
                refined_plan.recursive_depth + 1,
            )
            final_plan = conductor.refine_plan(
                original_plan=refined_plan,
                execution_result=execution_result_2,
                task_description=task_description,
                knowledge_context=knowledge_context,
            )
            final_manifest = _convert_plan_to_manifest(
                plan=final_plan,
                project_id=project_id,
                user_value_statement=user_value_statement,
                autonomy_level=autonomy_level,
                learning_mode=learning_mode,
            )
            results = orch.execute(final_manifest)

    return results


def build_agent_subtask_env(step: WorkflowStep) -> dict[str, str]:
    """Build environment variables for an agent task from a WorkflowStep.

    These env vars are injected into the ECS task override so the
    agent_runner can read the focused subtask instruction and access list.

    Args:
        step: The WorkflowStep containing subtask and access info.

    Returns:
        Dict of env var name -> value for ECS container override.
    """
    return {
        "AGENT_SUBTASK": step.subtask,
        "AGENT_ACCESS_LIST": json.dumps(step.access_list),
        "AGENT_STEP_INDEX": str(step.step_index),
    }


# --- Private Helpers ---


def _convert_plan_to_manifest(
    plan: WorkflowPlan,
    project_id: str,
    user_value_statement: str,
    autonomy_level: int,
    learning_mode: bool,
) -> SquadManifest:
    """Convert a Conductor WorkflowPlan to a SquadManifest.

    Maps:
      - WorkflowStep -> AgentSpec (per stage)
      - TopologyType -> stage grouping
      - access_list -> stored in knowledge_context for agent_runner
    """
    stages_dict = plan.to_squad_manifest_stages()

    # Build SquadManifest stages with AgentSpec objects
    manifest_stages: dict[int, list[AgentSpec]] = {}
    subtask_map: dict[str, str] = {}  # role -> subtask instruction

    for stage_num, agent_dicts in stages_dict.items():
        agent_specs: list[AgentSpec] = []
        for agent_dict in agent_dicts:
            spec = AgentSpec(
                role=agent_dict["role"],
                model_tier=agent_dict["model_tier"],
                stage=stage_num,
                timeout_seconds=agent_dict.get("timeout_seconds", 600),
                retry_max=agent_dict.get("retry_max", 3),
            )
            agent_specs.append(spec)

            # Track subtask for injection into agent environment
            subtask_map[agent_dict["role"]] = agent_dict.get("subtask", "")

        manifest_stages[stage_num] = agent_specs

    # Build knowledge context with Conductor metadata
    knowledge_ctx: dict[str, Any] = {
        "_conductor_subtasks": subtask_map,
        "_conductor_topology": plan.topology_type.value,
        "_conductor_access_lists": {
            step.agent_role: step.access_list for step in plan.steps
        },
    }

    return SquadManifest(
        task_id=plan.task_id,
        project_id=project_id,
        organism_level=plan.organism_level,
        user_value_statement=user_value_statement,
        autonomy_level=autonomy_level,
        stages=manifest_stages,
        knowledge_context=knowledge_ctx,
        learning_mode=learning_mode,
    )


def _results_to_dict(results: list[StageResult]) -> dict[str, Any]:
    """Convert StageResult list to dict for Conductor confidence assessment."""
    return {
        "stage_results": [
            {
                "stage": r.stage,
                "status": r.status.value,
                "duration_seconds": r.duration_seconds,
                "retry_count": r.retry_count,
                "error": r.error,
            }
            for r in results
        ]
    }
