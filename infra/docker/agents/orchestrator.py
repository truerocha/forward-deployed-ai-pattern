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
from .constraint_extractor import ConstraintExtractor, ExtractionResult, DoRValidationResult
from .registry import AgentRegistry, AgentDefinition
from .router import AgentRouter, RoutingDecision

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
    ):
        self._registry = registry
        self._router = router
        self._factory_bucket = factory_bucket
        self._constraint_extractor = constraint_extractor or ConstraintExtractor()
        self._agent_builder = agent_builder or AgentBuilder(registry)

    def handle_event(self, event: dict) -> dict:
        """Handle an incoming event (EventBridge or direct).

        This is the main entry point. When a task moves to InProgress:
        1. Route the event and extract the data contract
        2. Run Constraint Extraction on the data contract
        3. Validate constraints via DoR Gate
        4. If DoR passes, build specialized agents via Agent Builder
        5. Execute the pipeline

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

        # ── Step 1: Constraint Extraction ───────────────────────
        # Fast path: skip extraction for simple tasks with no constraints/docs.
        # Adversarial rationale (Red Team review 2026-05-04):
        # A one-line bugfix should not pay 6-stage overhead. If both
        # constraints and related_docs are empty, there is nothing to
        # extract. The DoR Gate auto-passes with zero constraints.
        # This cuts ~2-5s for the majority of bugfix/small tasks.
        data_contract = decision.data_contract

        if self._is_fast_path(data_contract):
            logger.info("Fast path: no constraints/related_docs — skipping extraction")
            extraction_result = ExtractionResult(source_field="fast_path")
            dor_result = DoRValidationResult(passed=True)
        else:
            extraction_result, dor_result = self._run_constraint_extraction(data_contract)

        # ── Step 2: DoR Gate ────────────────────────────────────
        if not dor_result.passed:
            return self._handle_dor_failure(decision, extraction_result, dor_result)

        # Log warnings even if DoR passed
        for warning in dor_result.warnings:
            logger.warning("DoR warning: %s", warning)

        # ── Step 3: Agent Builder ───────────────────────────────
        agent_names = self._build_pipeline(data_contract, extraction_result)

        # ── Step 4: Execute Pipeline ────────────────────────────
        return self._execute_pipeline(agent_names, decision, extraction_result, dor_result)

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
