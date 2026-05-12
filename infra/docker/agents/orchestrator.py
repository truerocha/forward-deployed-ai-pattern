"""
Agent Orchestrator — The main entry point that ties all components together.

Pipeline (triggered when a task moves to InProgress):
  1. Router receives event → extracts data contract + routing decision
  2. Constraint Extractor runs on the data contract (rule-based + LLM)
  3. DoR Gate validates extracted constraints against tech_stack
  4. If DoR fails → pipeline blocked, error reported to ALM
  5. Agent Builder provisions specialized agents using tech_stack + type + constraints
  6. Pipeline executes: Reconnaissance → Engineering → Reporting
  7. Results written to S3, ALM updated

The data contract is the single input to everything:
  - tech_stack drives the Agent Builder (prompt selection)
  - target_environment is preserved for future use (see ADR-011)
  - constraints + related_docs drive the Constraint Extractor
  - All components read from the same well-scoped input
"""

import json
import logging
import os
from dataclasses import asdict
from datetime import datetime, timezone

import boto3

from .agent_builder import AgentBuilder
from .autonomy import compute_autonomy_level, resolve_pipeline_gates
from .constraint_extractor import ConstraintExtractor, ExtractionResult, DoRValidationResult
from .execution_plan import (
    ExecutionPlan, create_plan, start_milestone, complete_milestone,
    skip_milestone, save_plan, load_plan, plan_exists, resume_from_plan,
)
from .registry import AgentRegistry, AgentDefinition
from .router import AgentRouter, RoutingDecision
from .scope_boundaries import check_scope
from .workspace_setup import setup_workspace, push_and_create_pr, WorkspaceContext
from .project_registry import get_registry
from .status_sync import StatusSync
from .stream_callback import DashboardCallback
from .squad_composer import (
    should_use_dynamic_squad, compose_default_squad, compose_from_manifest_json,
    SquadManifest, AGENT_CAPABILITIES, get_model_for_agent,
)
from .squad_context import SquadContext, create_squad_context
from .squad_prompts import SQUAD_PROMPTS
from . import task_queue

logger = logging.getLogger("fde.orchestrator")

s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))


class Orchestrator:
    """Main orchestrator that coordinates the full FDE pipeline.

    Flow for every InProgress event:
      Router → Constraint Extractor → DoR Gate → Agent Builder → Execute
    """

    def __init__(
        self,
        registry: AgentRegistry,
        router: AgentRouter,
        factory_bucket: str,
        constraint_extractor: ConstraintExtractor | None = None,
        agent_builder: AgentBuilder | None = None,
        plans_dir: str = "",
    ):
        self._registry = registry
        self._router = router
        self._factory_bucket = factory_bucket
        self._constraint_extractor = constraint_extractor or ConstraintExtractor()
        self._agent_builder = agent_builder or AgentBuilder(registry)
        self._plans_dir = plans_dir or os.environ.get("PLANS_DIR", "/tmp/plans")

    def handle_event(self, event: dict) -> dict:
        """Handle an incoming event (EventBridge or direct).

        This is the main entry point. When a task moves to InProgress:
        1. Route the event and extract the data contract
        2. Scope check — reject out-of-scope tasks immediately
        3. Compute autonomy level and resolve pipeline gates
        4. Create or resume execution plan
        5. Run Constraint Extraction (if gate is active)
        6. Validate constraints via DoR Gate (if gate is active)
        7. If DoR passes, build specialized agents via Agent Builder
        8. Execute the pipeline with milestone tracking

        Args:
            event: The event payload.

        Returns:
            Result dict with status, agent_name, and output.
        """
        decision = self._router.route_event(event)

        if not decision.should_process:
            logger.info("Event skipped: %s", decision.skip_reason)
            return {
                "status": "skipped",
                "reason": decision.skip_reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        data_contract = decision.data_contract

        # ── Step 1: Scope Check ─────────────────────────────────
        scope_result = check_scope(data_contract)
        if not scope_result.in_scope:
            logger.warning("Task rejected by scope check: %s", scope_result.rejection_reason)
            return {
                "status": "rejected",
                "reason": scope_result.rejection_reason,
                "details": scope_result.details,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # ── Step 2: Autonomy + Gate Resolution ──────────────────
        autonomy_result = compute_autonomy_level(data_contract)
        gates = resolve_pipeline_gates(
            autonomy_level=autonomy_result.level,
            confidence_level=scope_result.confidence_level,
        )

        logger.info(
            "Pipeline resolved: autonomy=%s confidence=%s outer_gates=%s",
            autonomy_result.level, scope_result.confidence_level, gates.outer_gates,
        )

        # ── Step 3: Execution Plan (create or resume) ───────────
        task_id = data_contract.get("task_id", f"TASK-{id(event)}")
        all_milestones = gates.outer_gates + gates.inner_gates

        # ── Step 3.1: Claim task from queue (correlate with webhook_ingest) ──
        # The webhook_ingest Lambda creates the task record in DynamoDB.
        # We need to find and claim that record so stage updates go to the
        # same row the dashboard reads from.
        issue_id = data_contract.get("issue_id", "")
        if not issue_id:
            repo = data_contract.get("repo", "")
            issue_num = data_contract.get("issue_number", 0)
            if repo and issue_num:
                issue_id = f"{repo}#{issue_num}"

        if issue_id:
            existing_task = task_queue.find_task_by_issue(issue_id)
            if existing_task:
                existing_status = existing_task.get("status", "")
                # If task is already IN_PROGRESS, another container is executing it.
                # Exit gracefully to prevent duplicate execution (idempotency guard).
                if existing_status == "IN_PROGRESS":
                    logger.info(
                        "Task %s for issue %s is already IN_PROGRESS — "
                        "exiting to prevent duplicate execution (idempotency guard)",
                        existing_task["task_id"], issue_id,
                    )
                    return {
                        "status": "duplicate_skipped",
                        "task_id": existing_task["task_id"],
                        "reason": "Task already in progress by another container",
                    }
                task_id = existing_task["task_id"]
                task_queue.claim_task(task_id, "fde-orchestrator")
                logger.info("Claimed existing task %s (issue: %s)", task_id, issue_id)
            else:
                logger.info("No existing task for issue %s — using generated ID %s", issue_id, task_id)

        # Emit initial stage update
        task_queue.update_task_stage(task_id, "ingested")
        task_queue.append_task_event(
            task_id, "system",
            f"Pipeline started — autonomy={autonomy_result.level}, confidence={scope_result.confidence_level}",
            phase="intake",
            autonomy_level=str(autonomy_result.level),
            confidence=scope_result.confidence_level,
            context=f"Scope check passed. Gates resolved: outer={gates.outer_gates}, inner={gates.inner_gates}",
        )

        # ── Step 3.2: Concurrency Guard ─────────────────────────
        # Prevent too many parallel agents on the same repo (merge conflict risk).
        # First, reap any stuck tasks to free slots (COE-016: stuck task cleanup).
        repo = data_contract.get("repo", "")
        if repo:
            reaped = task_queue.reap_stuck_tasks(max_age_minutes=60)
            if reaped:
                task_queue.append_task_event(
                    task_id, "system",
                    f"Reaped {len(reaped)} stuck task(s) before concurrency check",
                    phase="intake",
                )

            project_config = get_registry().get_project(repo)
            can_proceed, active_count = task_queue.check_concurrency(
                repo, project_config.max_concurrent_tasks,
            )
            if not can_proceed:
                task_queue.append_task_event(
                    task_id, "gate",
                    f"Concurrency guard: {active_count}/{project_config.max_concurrent_tasks} slots used — queued",
                    gate_name="concurrency",
                    gate_result="fail",
                    criteria=f"max_concurrent={project_config.max_concurrent_tasks} for repo={repo}",
                    context=f"Active tasks: {active_count}. Task queued until a slot opens.",
                )
                task_queue.update_task_stage(task_id, "ingested")
                return {
                    "status": "queued",
                    "reason": f"Concurrency limit reached for {repo} ({active_count}/{project_config.max_concurrent_tasks})",
                    "task_id": task_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

        existing_plan = load_plan(task_id, self._plans_dir)
        if existing_plan:
            resume_index = resume_from_plan(existing_plan)
            plan = existing_plan
            logger.info("Resuming plan for %s from milestone %d", task_id, resume_index)
        else:
            plan = create_plan(task_id, all_milestones)
            save_plan(plan, self._plans_dir)

        # ── Step 4: Constraint Extraction (if gate is active) ───
        if "constraint_extraction" in gates.outer_gates:
            plan = start_milestone(plan)
            task_queue.append_task_event(
                task_id, "gate", "Constraint extraction started",
                phase="intake", gate_name="constraint_extraction", gate_result="pass",
            )
            if self._is_fast_path(data_contract):
                logger.info("Fast path: no constraints/related_docs — skipping extraction")
                extraction_result = ExtractionResult(source_field="fast_path")
                dor_result = DoRValidationResult(passed=True)
            else:
                extraction_result, dor_result = self._run_constraint_extraction(data_contract)
            plan = complete_milestone(plan, f"Extracted {len(extraction_result.constraints)} constraints")
            save_plan(plan, self._plans_dir)
            task_queue.append_task_event(
                task_id, "gate",
                f"Constraint extraction complete: {len(extraction_result.constraints)} constraints",
                phase="intake", gate_name="constraint_extraction", gate_result="pass",
            )
        else:
            extraction_result = ExtractionResult(source_field="skipped")
            dor_result = DoRValidationResult(passed=True)

        # ── Step 5: DoR Gate (if gate is active) ────────────────
        if "dor_gate" in gates.outer_gates:
            plan = start_milestone(plan)
            if not dor_result.passed:
                plan = complete_milestone(plan, "DoR FAILED")
                save_plan(plan, self._plans_dir)
                task_queue.append_task_event(
                    task_id, "gate", "DoR Gate FAILED — pipeline blocked",
                    phase="intake", gate_name="dor", gate_result="fail",
                    criteria="Definition of Ready validation",
                )
                return self._handle_dor_failure(decision, extraction_result, dor_result)
            plan = complete_milestone(plan, "DoR passed")
            save_plan(plan, self._plans_dir)
            task_queue.append_task_event(
                task_id, "gate", "DoR Gate passed ✓",
                phase="intake", gate_name="dor", gate_result="pass",
            )
        else:
            # DoR skipped (L5 + high confidence)
            if not dor_result.passed:
                return self._handle_dor_failure(decision, extraction_result, dor_result)

        # Log warnings even if DoR passed
        for warning in dor_result.warnings:
            logger.warning("DoR warning: %s", warning)

        # ── Step 6: Adversarial Challenge (if gate is active) ───
        if "adversarial_challenge" in gates.outer_gates:
            plan = start_milestone(plan)
            # Adversarial challenge is handled by the hook system (preToolUse)
            # Here we just track the milestone
            plan = complete_milestone(plan, "Adversarial gate active via hook")
            save_plan(plan, self._plans_dir)
            task_queue.append_task_event(
                task_id, "gate", "Adversarial challenge gate active",
                phase="intake", gate_name="adversarial_challenge", gate_result="pass",
            )

        # ── Step 7: Agent Builder ───────────────────────────────
        # ADR-019: Dynamic squad composition when SQUAD_MODE=dynamic
        if should_use_dynamic_squad():
            task_type = data_contract.get("type", "feature")
            manifest = compose_default_squad(task_type, task_id, complexity="medium")
            agent_names = manifest.get_all_agents()
            task_queue.append_task_event(
                task_id, "system",
                f"Squad pipeline (dynamic): {' → '.join(agent_names)}",
                phase="intake",
            )
        else:
            agent_names = self._build_pipeline(data_contract, extraction_result)
            manifest = None
        task_queue.append_task_event(
            task_id, "system",
            f"Pipeline built: {' → '.join(agent_names)}",
            phase="intake",
        )

        # ── Step 7.5: Workspace Setup (COE-011) ────────────────
        # Clone the target repo and create a feature branch.
        # This must happen AFTER gates pass but BEFORE agents execute.
        task_queue.update_task_stage(task_id, "workspace")
        workspace = setup_workspace(event.get("detail", event), decision.metadata)
        if workspace.ready:
            logger.info("Workspace ready: %s (branch: %s)", workspace.repo_path, workspace.branch_name)
            task_queue.append_task_event(task_id, "system", f"Workspace ready: {workspace.repo_full_name} → {workspace.branch_name}", phase="workspace")
            # Inject workspace context into the agent's prompt so it knows
            # it's in a cloned repo and doesn't re-initialize git
            workspace_context = (
                f"\n\n## Workspace Context\n"
                f"- **Repository**: {workspace.repo_full_name} (already cloned)\n"
                f"- **Branch**: `{workspace.branch_name}` (already created and checked out)\n"
                f"- **Working directory**: `{workspace.repo_path}`\n"
                f"- **Issue**: #{workspace.issue_number}\n"
                f"- **IMPORTANT**: Do NOT run `git init` or `git clone`. The repo is ready.\n"
                f"- **IMPORTANT**: All file operations happen in `{workspace.repo_path}`.\n"
                f"- **Delivery**: Commit your changes with `git add` + `git commit`. "
                f"Push and PR creation are handled automatically after you finish.\n"
            )
            decision = RoutingDecision(
                agent_name=decision.agent_name,
                prompt=decision.prompt + workspace_context,
                metadata=decision.metadata,
                should_process=decision.should_process,
                data_contract=decision.data_contract,
            )
        else:
            logger.warning("Workspace setup failed: %s — agents will run without repo context", workspace.error)
            task_queue.update_task_stage(task_id, "workspace", workspace_error=workspace.error)
            task_queue.append_task_event(task_id, "error", f"Workspace failed: {workspace.error[:150]}", phase="workspace")

        # ── Step 8: Execute Pipeline (inner loop with plan tracking) ──
        task_queue.update_task_stage(task_id, "reconnaissance")

        # ADR-019: Use squad pipeline when in dynamic mode
        if manifest is not None and should_use_dynamic_squad():
            workspace_ctx_str = workspace_context if workspace.ready else ""
            result = self._execute_squad_pipeline(
                manifest, decision, extraction_result, task_id,
                workspace_context=workspace_ctx_str,
            )
        else:
            result = self._execute_pipeline_with_plan(
                agent_names, decision, extraction_result, dor_result, plan, gates,
            )

        # ── Step 9: Ship Readiness (if gate is active) ──────────
        if "ship_readiness" in gates.outer_gates:
            plan = start_milestone(plan)
            plan = complete_milestone(plan, "Ship readiness validated")
            save_plan(plan, self._plans_dir)

        # ── Step 9.4: Initialize StatusSync for ALM visibility ──
        # StatusSync posts structured comments to the originating GitHub issue
        # so the PM has visibility even without the portal (ADR-006).
        issue_url = data_contract.get("issue_url", "")
        if not issue_url:
            repo = data_contract.get("repo", "")
            issue_num = data_contract.get("issue_number", 0)
            if repo and issue_num:
                issue_url = f"https://github.com/{repo}/issues/{issue_num}"

        status_sync = None
        if issue_url:
            try:
                environment = os.environ.get("ENVIRONMENT", "dev")
                status_sync = StatusSync(
                    issue_url=issue_url,
                    correlation_id=task_id,
                    environment=environment,
                )
            except Exception as e:
                logger.warning("StatusSync init failed (non-blocking): %s", e)

        # ── Step 9.5: Push & Create PR (if workspace is ready) ──
        if workspace.ready and result.get("status") == "completed":
            task_queue.update_task_stage(task_id, "review")
            task_queue.append_task_event(
                task_id, "system", "Pushing branch and creating PR...",
                phase="review",
            )
            pr_title = f"feat(GH-{workspace.issue_number}): {data_contract.get('title', 'Task completion')}"
            agent_name = os.environ.get("FDE_AGENT_NAME", "FDE Agent")
            agent_email = os.environ.get("FDE_AGENT_EMAIL", "fde-agent@factory.local")
            pr_body = (
                f"## Automated PR from FDE Code Factory\n\n"
                f"**Issue**: #{workspace.issue_number}\n"
                f"**Branch**: `{workspace.branch_name}`\n"
                f"**Autonomy Level**: {autonomy_result.level}\n"
                f"**Confidence**: {scope_result.confidence_level}\n\n"
                f"### Pipeline Summary\n"
                f"- Milestones: {plan.completed_count}/{plan.total_count}\n"
                f"- Constraints extracted: {len(extraction_result.constraints)}\n"
                f"- Agents executed: {', '.join(agent_names)}\n\n"
                f"### Attribution\n"
                f"- **Author (hands-on)**: {agent_name} <{agent_email}>\n"
                f"- **Reviewer (codebase owner)**: Assigned via CODEOWNERS\n"
                f"- **Task ID**: {task_id}\n\n"
                f"---\n"
                f"*This PR was generated autonomously by the FDE pipeline. "
                f"The codebase owner reviews and approves.*\n"
            )
            pr_result = push_and_create_pr(workspace, pr_title, pr_body)

            # Retry with rebase if push failed due to stale ref (COE-019)
            if not pr_result.get("pr_url") and "stale" in pr_result.get("error", "").lower():
                logger.info("Push failed with stale ref — attempting rebase retry")
                task_queue.append_task_event(
                    task_id, "system",
                    "Push rejected (stale ref) — retrying with git pull --rebase",
                    phase="review",
                )
                rebase_ok = self._attempt_rebase_retry(workspace)
                if rebase_ok:
                    pr_result = push_and_create_pr(workspace, pr_title, pr_body)

            if pr_result.get("pr_url"):
                logger.info("PR delivered: %s", pr_result["pr_url"])
                result["pr_url"] = pr_result["pr_url"]
                result["pr_number"] = pr_result.get("pr_number")
                task_queue.update_task_stage(task_id, "completion", pr_url=pr_result["pr_url"])
                task_queue.append_task_event(
                    task_id, "system",
                    f"PR created: {pr_result['pr_url']}",
                    phase="completion",
                )
                # Post success to GitHub issue via StatusSync
                if status_sync:
                    try:
                        status_sync.post_pipeline_complete(pr_url=pr_result["pr_url"])
                    except Exception as e:
                        logger.debug("StatusSync post_pipeline_complete failed: %s", e)
            else:
                pr_error = pr_result.get("error", "unknown")
                logger.warning("PR delivery failed: %s", pr_error)
                # Emit visible error event so portal CoT shows the failure
                task_queue.update_task_stage(task_id, "completion")
                task_queue.append_task_event(
                    task_id, "error",
                    f"PR delivery failed: {pr_error[:150]}",
                    phase="review",
                    context="Pipeline completed successfully but code delivery failed. "
                            "The work is preserved in the container artifacts.",
                )
                result["pr_error"] = pr_error
                # Post failure to GitHub issue via StatusSync
                if status_sync:
                    try:
                        status_sync.post_pipeline_failed(
                            stage="review",
                            reason=f"Push/PR delivery failed: {pr_error[:100]}",
                        )
                    except Exception as e:
                        logger.debug("StatusSync post_pipeline_failed failed: %s", e)

        # ── Step 10: DAG Resolution (ADR-014) ───────────────────
        # Signal task completion to the task queue. This triggers
        # _resolve_dependencies() which promotes dependent tasks to READY.
        # The DynamoDB Stream + Lambda fan-out picks up READY transitions
        # and starts new ECS tasks for parallel execution.
        #
        # NOTE: A task with pr_error is still COMPLETED (pipeline ran fine)
        # but the pr_error field signals "completed-without-delivery" to the
        # dashboard so the PM knows to investigate.
        if result.get("status") == "completed":
            try:
                task_queue.complete_task(task_id, json.dumps(result, default=str))
                logger.info("Task %s marked COMPLETED in queue (DAG resolution triggered)", task_id)
            except Exception as e:
                logger.warning("Task queue update failed (non-blocking): %s", e)
        elif result.get("status") in ("partial", "error"):
            try:
                error_msg = result.get("pipeline", [{}])[-1].get("error", "Pipeline incomplete")
                task_queue.fail_task(task_id, error_msg)
                logger.info("Task %s marked FAILED in queue (dependents blocked)", task_id)
            except Exception as e:
                logger.warning("Task queue failure update failed (non-blocking): %s", e)

        return result

    @staticmethod
    def _attempt_rebase_retry(workspace: "WorkspaceContext") -> bool:
        """Attempt to rebase the feature branch on top of the latest remote.

        Called when push fails with 'stale info' — meaning the remote branch
        was updated by another process (e.g., a previous retry or concurrent task).

        Strategy: fetch + rebase onto origin/main. If conflicts arise, abort.

        Returns:
            True if rebase succeeded and the branch is ready for push retry.
        """
        import subprocess

        repo_path = workspace.repo_path
        try:
            # Fetch latest from remote
            fetch = subprocess.run(
                ["git", "fetch", "origin"],
                capture_output=True, text=True, timeout=30, cwd=repo_path,
            )
            if fetch.returncode != 0:
                logger.warning("Rebase retry: fetch failed: %s", fetch.stderr[:200])
                return False

            # Try to rebase onto origin/main
            rebase = subprocess.run(
                ["git", "rebase", "origin/main"],
                capture_output=True, text=True, timeout=60, cwd=repo_path,
            )
            if rebase.returncode != 0:
                # Abort the rebase to leave the workspace clean
                logger.warning("Rebase retry: rebase failed (conflicts): %s", rebase.stderr[:200])
                subprocess.run(
                    ["git", "rebase", "--abort"],
                    capture_output=True, text=True, timeout=10, cwd=repo_path,
                )
                return False

            logger.info("Rebase retry: successfully rebased onto origin/main")
            return True

        except Exception as e:
            logger.warning("Rebase retry failed: %s", e)
            return False

    # ─── Squad Pipeline Execution (ADR-019) ─────────────────────

    def _execute_squad_pipeline(
        self,
        manifest: "SquadManifest",
        decision: "RoutingDecision",
        extraction_result: "ExtractionResult",
        task_id: str,
        workspace_context: str = "",
    ) -> dict:
        """Execute the dynamic squad pipeline using the Shared Context Document.

        Instead of passing raw output between agents, each agent:
        1. Reads its permitted SCD sections (structured context)
        2. Executes with its specialized prompt
        3. Writes its output to its designated SCD section

        This prevents token explosion and ensures specification fidelity.

        Args:
            manifest: The Squad Manifest from task-intake-eval or default composition.
            decision: The routing decision (contains the task prompt).
            extraction_result: Constraints for injection.
            task_id: The task identifier.
            workspace_context: Workspace context string to inject.

        Returns:
            Result dict with pipeline execution summary.
        """
        from .tools import RECON_TOOLS, ENGINEERING_TOOLS, REPORTING_TOOLS

        # Create the Shared Context Document for this task
        scd = create_squad_context(task_id)

        # Get execution order from manifest
        stages = manifest.get_execution_order()
        all_agents = manifest.get_all_agents()

        logger.info(
            "Squad pipeline: task=%s agents=%d stages=%d mode=dynamic",
            task_id, len(all_agents), len(stages),
        )
        task_queue.append_task_event(
            task_id, "reasoning",
            f"Squad composed: {len(all_agents)} agents across {len(stages)} stages",
            phase="intake",
            criteria=f"Task type \u2192 squad composition: {' \u2192 '.join(all_agents)}",
            context=(
                f"Topology: sequential stages with parallel agents within stage. "
                f"Each agent reads only its permitted SCD sections (isolation). "
                f"Model selection: capability-matched per agent role."
            ),
        )

        results: list[dict] = []
        constraints = extraction_result.constraints if extraction_result else []

        # Tool set mapping
        _TOOL_MAP = {
            "RECON_TOOLS": RECON_TOOLS,
            "ENGINEERING_TOOLS": ENGINEERING_TOOLS,
            "REPORTING_TOOLS": REPORTING_TOOLS,
        }

        for stage in stages:
            # Each stage is a list of agents (parallel within stage, sequential between stages)
            for agent_role in stage:
                logger.info("Squad executing: %s", agent_role)

                # Resolve prompt (from SQUAD_PROMPTS or Prompt Registry)
                base_prompt = SQUAD_PROMPTS.get(agent_role, "")
                if not base_prompt:
                    logger.warning("No prompt for agent %s — skipping", agent_role)
                    continue

                # Build the full prompt: base + SCD context + workspace + constraints
                scd_context = scd.read_for_agent(agent_role)
                full_prompt = base_prompt

                if scd_context:
                    full_prompt += f"\n\n{scd_context}"

                if workspace_context:
                    full_prompt += f"\n\n{workspace_context}"

                if constraints:
                    from .agent_builder import _build_constraints_block
                    full_prompt += f"\n\n{_build_constraints_block(constraints)}"

                # Add the task prompt (from the issue/spec)
                full_prompt += f"\n\n## Task Specification\n\n{decision.prompt}"

                # Resolve tools for this agent
                capability = AGENT_CAPABILITIES.get(agent_role, {})
                tool_key = capability.get("tools", "RECON_TOOLS")
                tools = list(_TOOL_MAP.get(tool_key, RECON_TOOLS))

                # Register transient agent definition
                agent_name = f"{agent_role}-{task_id}"
                model_id = get_model_for_agent(agent_role)
                defn = AgentDefinition(
                    name=agent_name,
                    system_prompt=full_prompt,
                    tools=tools,
                    model_id=model_id,
                    description=f"Squad {agent_role} for task {task_id}",
                )
                self._registry.register(defn)

                # Update dashboard with reasoning about WHY this agent
                task_queue.update_task_stage(task_id, agent_role.split("-")[0])
                task_queue.append_task_event(
                    task_id, "reasoning",
                    f"\u25B6 Executing: {agent_role}",
                    phase=agent_role,
                    criteria=f"Role: {capability.get('description', agent_role)} | Model: {model_id.split('/')[-1] if '/' in model_id else model_id}",
                    context=(
                        f"Tools: {tool_key} ({len(tools)} available). "
                        f"SCD access: {'enriched context from prior stages' if scd_context else 'no prior context (first stage)'}. "
                        f"Constraints: {len(constraints)} active."
                    ),
                )

                # Create callback and execute
                callback = DashboardCallback(task_id=task_id, agent_role=agent_role)

                try:
                    agent = self._registry.create_agent(agent_name, callback_handler=callback)
                    result = agent(full_prompt)
                    message = str(result.message) if hasattr(result, "message") else str(result)

                    # Write output to SCD
                    scd.write_from_agent(agent_role, message)

                    # Write result to S3
                    self._write_result(agent_name, decision.metadata, message)

                    results.append({
                        "agent_name": agent_role,
                        "status": "completed",
                        "message_length": len(message),
                    })

                    task_queue.append_task_event(
                        task_id, "reasoning",
                        f"\u2713 {agent_role} complete",
                        phase=agent_role,
                        criteria=f"Output: {len(message)} chars written to SCD section '{agent_role}'",
                        context=f"Result persisted to S3. Next stage can read this agent's output via SCD.",
                    )

                except Exception as e:
                    logger.error("Squad agent %s failed: %s", agent_role, e)
                    task_queue.append_task_event(
                        task_id, "reasoning",
                        f"\u2717 {agent_role} failed: {str(e)[:80]}",
                        phase=agent_role,
                        criteria=f"Exception type: {type(e).__name__}",
                        context=(
                            f"Agent failed during execution. Pipeline continues with remaining agents "
                            f"(graceful degradation). This agent's SCD section will be empty for downstream consumers."
                        ),
                    )
                    results.append({
                        "agent_name": agent_role,
                        "status": "error",
                        "error": str(e),
                    })
                    # Don't break — try remaining agents (graceful degradation)
                    continue

        all_completed = all(r["status"] == "completed" for r in results)

        # Log SCD summary for observability
        scd_summary = scd.get_summary()
        logger.info("SCD summary: %s", json.dumps(scd_summary, default=str))

        return {
            "status": "completed" if all_completed else "partial",
            "pipeline": results,
            "squad_mode": "dynamic",
            "squad_manifest": manifest.to_dict(),
            "scd_summary": scd_summary,
            "constraints_extracted": len(constraints),
            "metadata": decision.metadata,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def handle_spec(self, spec_content: str, spec_path: str) -> dict:
        """Handle a direct spec execution.

        Args:
            spec_content: The spec markdown content.
            spec_path: Path to the spec file.

        Returns:
            Result dict with status, agent_name, and output.
        """
        decision = self._router.route_spec(spec_content, spec_path)

        # Run constraint extraction even for direct specs
        data_contract = decision.data_contract
        extraction_result, dor_result = self._run_constraint_extraction(data_contract)

        if not dor_result.passed:
            return self._handle_dor_failure(decision, extraction_result, dor_result)

        for warning in dor_result.warnings:
            logger.warning("DoR warning: %s", warning)

        # For direct specs, use the single-agent path (engineering)
        agent_name = self._agent_builder.build_agent(data_contract, extraction_result)
        return self._execute_single(agent_name, decision, extraction_result, dor_result)

    # ─── Fast Path Detection ────────────────────────────────────

    @staticmethod
    def _is_fast_path(data_contract: dict) -> bool:
        """Determine if a task qualifies for the fast path (skip extraction).

        A task qualifies when:
        1. No constraints text provided
        2. No related_docs provided
        3. Task type is bugfix or documentation (lower complexity)

        Feature tasks with empty constraints still go through extraction
        because the Agent Builder benefits from the full pipeline even
        without explicit constraints.

        Args:
            data_contract: The canonical data contract.

        Returns:
            True if the task can skip constraint extraction.
        """
        has_constraints = bool((data_contract.get("constraints") or "").strip())
        has_related_docs = bool(data_contract.get("related_docs"))
        task_type = data_contract.get("type", "feature")

        # Feature and infrastructure tasks always go through full extraction
        # because they're higher risk and benefit from constraint validation
        if task_type in ("feature", "infrastructure"):
            return False

        # Bugfix and documentation with no constraints/docs → fast path
        return not has_constraints and not has_related_docs

    # ─── Constraint Extraction ──────────────────────────────────

    def _run_constraint_extraction(
        self, data_contract: dict,
    ) -> tuple[ExtractionResult, DoRValidationResult]:
        """Run the Constraint Extractor and DoR validation on the data contract.

        This is the first thing that happens after routing, before any agent
        is provisioned. The extraction result feeds into the Agent Builder.

        Args:
            data_contract: The canonical data contract extracted by the Router.

        Returns:
            Tuple of (ExtractionResult, DoRValidationResult).
        """
        logger.info(
            "Running constraint extraction (tech_stack=%s, type=%s, "
            "has_constraints=%s, related_docs=%d)",
            data_contract.get("tech_stack", []),
            data_contract.get("type", "unknown"),
            bool(data_contract.get("constraints")),
            len(data_contract.get("related_docs", [])),
        )

        extraction_result, dor_result = self._constraint_extractor.extract_and_validate(
            data_contract
        )

        logger.info(
            "Constraint extraction complete: %d constraints extracted, "
            "%d ambiguous, DoR passed=%s, %d failures, %d warnings",
            len(extraction_result.constraints),
            extraction_result.ambiguous_count,
            dor_result.passed,
            len(dor_result.failures),
            len(dor_result.warnings),
        )

        # Write extraction results to S3 for audit trail
        self._write_extraction_report(data_contract, extraction_result, dor_result)

        return extraction_result, dor_result

    def _handle_dor_failure(
        self,
        decision: RoutingDecision,
        extraction_result: ExtractionResult,
        dor_result: DoRValidationResult,
    ) -> dict:
        """Handle a DoR Gate failure — block the pipeline and report.

        Args:
            decision: The routing decision (for metadata/ALM reporting).
            extraction_result: The extraction result.
            dor_result: The failed DoR validation result.

        Returns:
            Result dict with status "blocked".
        """
        failure_details = [
            f"- {f.constraint_id}: {f.message} (expected: {f.expected}, actual: {f.actual})"
            for f in dor_result.failures
        ]
        failure_msg = "\n".join(failure_details)

        logger.error(
            "DoR Gate FAILED — pipeline blocked.\n%s", failure_msg,
        )

        return {
            "status": "blocked",
            "reason": "DoR Gate validation failed",
            "failures": [
                {"constraint_id": f.constraint_id, "subject": f.subject,
                 "expected": f.expected, "actual": f.actual, "message": f.message}
                for f in dor_result.failures
            ],
            "warnings": dor_result.warnings,
            "constraints_extracted": len(extraction_result.constraints),
            "metadata": decision.metadata,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ─── Agent Builder Integration ──────────────────────────────

    def _build_pipeline(
        self, data_contract: dict, extraction_result: ExtractionResult,
    ) -> list[str]:
        """Build the full agent pipeline via the Agent Builder.

        The Agent Builder uses tech_stack + type + constraints to provision
        specialized agents with context-aware prompts from the Prompt Registry.

        Args:
            data_contract: The canonical data contract.
            extraction_result: Constraints extracted from the data contract.

        Returns:
            Ordered list of agent names for the pipeline.
        """
        agent_names = self._agent_builder.build_pipeline_agents(
            data_contract, extraction_result,
        )
        logger.info("Pipeline built: %s", " → ".join(agent_names))
        return agent_names

    # ─── Execution ──────────────────────────────────────────────

    def _execute_pipeline(
        self,
        agent_names: list[str],
        decision: RoutingDecision,
        extraction_result: ExtractionResult,
        dor_result: DoRValidationResult,
    ) -> dict:
        """Execute the full agent pipeline sequentially.

        Args:
            agent_names: Ordered list of agent names to execute.
            decision: The routing decision (for prompt and metadata).
            extraction_result: Constraints for audit trail.
            dor_result: DoR result for audit trail.

        Returns:
            Result dict with pipeline execution summary.
        """
        results: list[dict] = []
        current_prompt = decision.prompt

        for agent_name in agent_names:
            logger.info("Executing pipeline stage: %s", agent_name)

            try:
                agent = self._registry.create_agent(agent_name)
            except KeyError as e:
                logger.error("Agent not found: %s", e)
                results.append({
                    "agent_name": agent_name,
                    "status": "error",
                    "error": str(e),
                })
                break

            try:
                result = agent(current_prompt)
                message = str(result.message) if hasattr(result, "message") else str(result)

                self._write_result(agent_name, decision.metadata, message)

                results.append({
                    "agent_name": agent_name,
                    "status": "completed",
                    "message_length": len(message),
                })

                # Pass the output as context to the next stage
                current_prompt = (
                    f"Previous agent ({agent_name}) output:\n\n{message}\n\n"
                    "Continue the FDE pipeline from where the previous agent left off."
                )

            except Exception as e:
                logger.error("Agent execution failed: %s — %s", agent_name, e)
                results.append({
                    "agent_name": agent_name,
                    "status": "error",
                    "error": str(e),
                })
                break

        all_completed = all(r["status"] == "completed" for r in results)

        return {
            "status": "completed" if all_completed else "partial",
            "pipeline": results,
            "constraints_extracted": len(extraction_result.constraints),
            "dor_warnings": dor_result.warnings,
            "metadata": decision.metadata,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _execute_pipeline_with_plan(
        self,
        agent_names: list[str],
        decision: RoutingDecision,
        extraction_result: ExtractionResult,
        dor_result: DoRValidationResult,
        plan: ExecutionPlan,
        gates: "PipelineGates",
    ) -> dict:
        """Execute the agent pipeline with milestone tracking.

        Each inner loop gate (lint, typecheck, unit_test, build) is tracked
        as a milestone in the execution plan. If the pipeline is interrupted
        and restarted, completed milestones are skipped.

        Args:
            agent_names: Ordered list of agent names to execute.
            decision: The routing decision.
            extraction_result: Constraints for audit trail.
            dor_result: DoR result for audit trail.
            plan: The execution plan with milestone tracking.
            gates: The resolved pipeline gates.

        Returns:
            Result dict with pipeline execution summary.
        """
        results: list[dict] = []
        current_prompt = decision.prompt

        # Track inner loop gates as milestones
        for gate_name in gates.inner_gates:
            if plan.current_milestone < plan.total_count:
                current_ms = plan.milestones[plan.current_milestone]
                if current_ms.name == gate_name and current_ms.status in ("pending", "in_progress"):
                    plan = start_milestone(plan)
                    plan = complete_milestone(plan, f"Inner loop: {gate_name}")
                    save_plan(plan, self._plans_dir)

        # Execute agents
        # Map agent names to dashboard stage names for real-time progress
        _AGENT_TO_STAGE = {
            "reconnaissance": "reconnaissance",
            "engineering": "engineering",
            "reporting": "completion",
        }

        for agent_name in agent_names:
            logger.info("Executing pipeline stage: %s", agent_name)

            # Update dashboard stage (non-blocking)
            dashboard_stage = _AGENT_TO_STAGE.get(agent_name, agent_name)
            task_queue.update_task_stage(plan.task_id, dashboard_stage)
            task_queue.append_task_event(plan.task_id, "system", f"▶ Stage started: {agent_name}", phase=dashboard_stage)

            # Create callback to stream agent brain events to portal CoT
            callback = DashboardCallback(task_id=plan.task_id)

            try:
                agent = self._registry.create_agent(agent_name, callback_handler=callback)
            except KeyError as e:
                logger.error("Agent not found: %s", e)
                task_queue.append_task_event(
                    plan.task_id, "error",
                    f"Agent '{agent_name}' not found in registry",
                    phase=dashboard_stage,
                )
                results.append({
                    "agent_name": agent_name,
                    "status": "error",
                    "error": str(e),
                })
                break

            try:
                result = agent(current_prompt)
                message = str(result.message) if hasattr(result, "message") else str(result)

                self._write_result(agent_name, decision.metadata, message)

                results.append({
                    "agent_name": agent_name,
                    "status": "completed",
                    "message_length": len(message),
                })

                # Emit stage completion event for portal visibility (mirrors CloudWatch logs)
                task_queue.append_task_event(
                    plan.task_id, "system",
                    f"✅ Stage complete: {agent_name} ({len(message)} chars)",
                    phase=dashboard_stage,
                )

                current_prompt = (
                    f"Previous agent ({agent_name}) output:\n\n{message}\n\n"
                    "Continue the FDE pipeline from where the previous agent left off."
                )

            except Exception as e:
                logger.error("Agent execution failed: %s — %s", agent_name, e)
                task_queue.append_task_event(
                    plan.task_id, "error",
                    f"❌ Agent '{agent_name}' failed: {str(e)[:120]}",
                    phase=dashboard_stage,
                )
                results.append({
                    "agent_name": agent_name,
                    "status": "error",
                    "error": str(e),
                })
                break

        all_completed = all(r["status"] == "completed" for r in results)

        return {
            "status": "completed" if all_completed else "partial",
            "pipeline": results,
            "autonomy_level": plan.task_id,
            "milestones_completed": plan.completed_count,
            "milestones_total": plan.total_count,
            "constraints_extracted": len(extraction_result.constraints),
            "dor_warnings": dor_result.warnings,
            "metadata": decision.metadata,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _execute_single(
        self,
        agent_name: str,
        decision: RoutingDecision,
        extraction_result: ExtractionResult,
        dor_result: DoRValidationResult,
    ) -> dict:
        """Execute a single agent (for direct spec execution).

        Args:
            agent_name: The agent to execute.
            decision: The routing decision.
            extraction_result: Constraints for audit trail.
            dor_result: DoR result for audit trail.

        Returns:
            Result dict.
        """
        logger.info("Executing single agent: %s", agent_name)

        try:
            agent = self._registry.create_agent(agent_name)
        except KeyError as e:
            logger.error("Agent not found: %s", e)
            return {
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        try:
            result = agent(decision.prompt)
            message = str(result.message) if hasattr(result, "message") else str(result)

            self._write_result(agent_name, decision.metadata, message)

            return {
                "status": "completed",
                "agent_name": agent_name,
                "metadata": decision.metadata,
                "message_length": len(message),
                "constraints_extracted": len(extraction_result.constraints),
                "dor_warnings": dor_result.warnings,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            logger.error("Agent execution failed: %s — %s", agent_name, e)
            return {
                "status": "error",
                "agent_name": agent_name,
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    # ─── S3 Writes ──────────────────────────────────────────────

    def _write_result(self, agent_name: str, metadata: dict, message: str) -> None:
        """Write agent execution result to S3."""
        if not self._factory_bucket:
            logger.warning("No factory bucket configured — skipping S3 write")
            return

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        source = metadata.get("source", "unknown")
        key = f"results/{source}/{timestamp}/{agent_name}-result.md"

        try:
            s3.put_object(
                Bucket=self._factory_bucket,
                Key=key,
                Body=message.encode("utf-8"),
            )
            logger.info("Result written to s3://%s/%s", self._factory_bucket, key)
        except Exception as e:
            logger.error("Failed to write result to S3: %s", e)

    def _write_extraction_report(
        self,
        data_contract: dict,
        extraction_result: ExtractionResult,
        dor_result: DoRValidationResult,
    ) -> None:
        """Write the constraint extraction report to S3 for audit trail."""
        if not self._factory_bucket:
            return

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        source = data_contract.get("source", "unknown")
        key = f"extraction/{source}/{timestamp}/constraint-report.json"

        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data_contract_summary": {
                "source": data_contract.get("source"),
                "type": data_contract.get("type"),
                "tech_stack": data_contract.get("tech_stack"),
                "has_constraints": bool(data_contract.get("constraints")),
                "related_docs_count": len(data_contract.get("related_docs", [])),
            },
            "extraction": extraction_result.to_dict(),
            "dor_validation": dor_result.to_dict(),
        }

        try:
            s3.put_object(
                Bucket=self._factory_bucket,
                Key=key,
                Body=json.dumps(report, indent=2, default=str).encode("utf-8"),
            )
            logger.info("Extraction report written to s3://%s/%s", self._factory_bucket, key)
        except Exception as e:
            logger.error("Failed to write extraction report to S3: %s", e)
