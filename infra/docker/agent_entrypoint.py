"""
Forward Deployed Engineer — Strands Agent Entrypoint for ECS Fargate.

Wires together: Registry + Router + Constraint Extractor + Agent Builder + Orchestrator.

Pipeline on every InProgress event:
  Router → Constraint Extractor → DoR Gate → Agent Builder → Execute

Modes:
1. EVENTBRIDGE_EVENT env var → parse event, route, extract constraints, build agents, execute
2. TASK_SPEC env var → direct spec execution (still runs constraint extraction)
3. Neither → log instructions and exit
"""

import json
import logging
import os
import sys

import boto3
from botocore.exceptions import ClientError

from agents.agent_builder import AgentBuilder
from agents.constraint_extractor import ConstraintExtractor
from agents.registry import AgentRegistry, AgentDefinition
from agents.router import AgentRouter
from agents.orchestrator import Orchestrator
from agents.prompts import RECONNAISSANCE_PROMPT, ENGINEERING_PROMPT, REPORTING_PROMPT
from agents.tools import RECON_TOOLS, ENGINEERING_TOOLS, REPORTING_TOOLS, read_spec

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fde-entrypoint")


def _init_telemetry():
    """Initialize OpenTelemetry distributed tracing (ADOT sidecar pattern).

    The Strands SDK natively supports OTEL via StrandsTelemetry. When enabled,
    it automatically creates spans for:
      - Agent-level: full agent invocation (model, prompt hash, token counts)
      - Cycle-level: each reasoning cycle (think → act → observe)
      - Tool-level: each tool call (name, duration, success/failure)

    The ADOT sidecar container (in the same ECS task) receives traces on
    localhost:4318 and exports them to AWS X-Ray.

    Environment variables (set in ECS task definition):
      OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
      OTEL_SERVICE_NAME=fde-strands-agent
      OTEL_RESOURCE_ATTRIBUTES=deployment.environment=dev,service.version=1.0
      OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental

    If OTEL is not configured (no endpoint), this is a no-op.
    """
    otel_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if not otel_endpoint:
        logger.info("OTEL tracing disabled (no OTEL_EXPORTER_OTLP_ENDPOINT)")
        return

    try:
        from strands.telemetry import StrandsTelemetry
        StrandsTelemetry()
        logger.info("OTEL tracing enabled → %s (service: %s)",
                    otel_endpoint,
                    os.environ.get("OTEL_SERVICE_NAME", "fde-strands-agent"))
    except ImportError:
        logger.warning("strands.telemetry not available — OTEL tracing disabled")
    except Exception as e:
        logger.warning("OTEL init failed (non-blocking): %s", e)

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
FACTORY_BUCKET = os.environ.get("FACTORY_BUCKET", "")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")


def _build_llm_invoke_fn():
    """Build an LLM invocation function for the Constraint Extractor.

    Uses Bedrock directly (not a Strands agent) for structured extraction.
    Returns None if Bedrock is not available, falling back to rule-based only.
    """
    try:
        bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

        def invoke(prompt: str) -> str:
            response = bedrock.invoke_model(
                modelId=BEDROCK_MODEL_ID,
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 4096,
                    "messages": [{"role": "user", "content": prompt}],
                }),
            )
            body = json.loads(response["body"].read())
            return body["content"][0]["text"]

        logger.info("LLM invoke function ready (model: %s)", BEDROCK_MODEL_ID)
        return invoke
    except Exception as e:
        logger.warning("Bedrock not available for constraint extraction, using rule-based only: %s", e)
        return None


def build_registry() -> AgentRegistry:
    """Build the agent registry with base agent definitions.

    These base agents are used as fallbacks when the Agent Builder
    doesn't find a specialized prompt in the Prompt Registry.
    """
    registry = AgentRegistry(default_model_id=BEDROCK_MODEL_ID, aws_region=AWS_REGION)
    registry.register(AgentDefinition(
        name="reconnaissance", system_prompt=RECONNAISSANCE_PROMPT,
        tools=RECON_TOOLS, description="Phase 1: Reads spec, maps modules, produces intake contract",
    ))
    registry.register(AgentDefinition(
        name="engineering", system_prompt=ENGINEERING_PROMPT,
        tools=ENGINEERING_TOOLS, description="Phases 2-3: Reformulates task, executes engineering recipe",
    ))
    registry.register(AgentDefinition(
        name="reporting", system_prompt=REPORTING_PROMPT,
        tools=REPORTING_TOOLS, description="Phase 4: Writes completion report, updates ALM",
    ))
    return registry


def validate_environment() -> list[str]:
    issues = []
    if not FACTORY_BUCKET:
        issues.append("FACTORY_BUCKET not set")
    # ALM tokens are no longer validated at startup (ADR-014).
    # They are fetched from Secrets Manager at tool invocation time.
    # This prevents token values from being visible in the container env.
    if FACTORY_BUCKET:
        try:
            boto3.client("s3", region_name=AWS_REGION).head_bucket(Bucket=FACTORY_BUCKET)
        except ClientError as e:
            issues.append(f"S3 bucket not accessible: {FACTORY_BUCKET} — {e}")
    return issues


def _should_defer_to_orchestrator() -> bool:
    """Check if the cognitive router already dispatched this task to the orchestrator.

    Dual-path architecture (ADR-030):
      - The webhook_ingest Lambda writes task_queue with status=DISPATCHED
        when it routes a task to the distributed orchestrator (depth >= 0.5).
      - This monolith container ALWAYS starts from the original EventBridge rule.
      - If the task is DISPATCHED, the orchestrator is handling it — exit cleanly.
      - If the task is READY, either:
        a) Lambda decided monolith should handle it (depth < 0.5)
        b) Lambda failed — we are the fallback
      - In both cases, proceed with execution.

    Lookup strategy:
      We identify the task by EVENT_REPO + EVENT_ISSUE_NUMBER (same key the Lambda uses).
      Query the task_queue table for matching issue_id with status=DISPATCHED.
      If found AND target_mode=distributed → defer.
      If found AND target_mode=monolith → proceed (we ARE the target).

    Timeout: 2s max. If DynamoDB is unreachable, proceed (safe fallback).
    """
    task_queue_table = os.environ.get("TASK_QUEUE_TABLE", "")
    event_repo = os.environ.get("EVENT_REPO", "")
    event_issue_number = os.environ.get("EVENT_ISSUE_NUMBER", "")

    # Can't check without identifiers — proceed with execution
    if not task_queue_table or not event_repo or not event_issue_number:
        logger.debug("Dual-path check skipped: missing TASK_QUEUE_TABLE, EVENT_REPO, or EVENT_ISSUE_NUMBER")
        return False

    issue_id = f"{event_repo}#{event_issue_number}"

    try:
        from botocore.config import Config
        fast_config = Config(connect_timeout=2, read_timeout=2, retries={"max_attempts": 1})
        dynamodb_check = boto3.resource("dynamodb", region_name=AWS_REGION, config=fast_config)
        table = dynamodb_check.Table(task_queue_table)

        # Scan for this issue_id with DISPATCHED status
        response = table.scan(
            FilterExpression="issue_id = :iid AND #s = :status",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":iid": issue_id,
                ":status": "DISPATCHED",
            },
            Limit=3,
        )

        items = response.get("Items", [])
        if not items:
            logger.info("Dual-path check: no DISPATCHED task for %s — proceeding as monolith", issue_id)
            return False

        # Check target_mode: only defer if routed to distributed
        for item in items:
            target_mode = item.get("target_mode", "monolith")
            if target_mode == "distributed":
                logger.info(
                    "Dual-path check: task %s for %s is DISPATCHED to distributed (depth=%s) — deferring",
                    item.get("task_id", "?"), issue_id, item.get("depth", "?"),
                )
                return True

        # target_mode=monolith means Lambda decided WE should handle it
        logger.info("Dual-path check: task for %s is DISPATCHED to monolith — proceeding", issue_id)
        return False

    except Exception as e:
        # Safe fallback: if we can't check, proceed with execution
        logger.warning("Dual-path check failed (proceeding as fallback): %s", str(e)[:200])
        return False


def main():
    logger.info("FDE Strands Agent starting...")
    logger.info("Region: %s | Model: %s | Bucket: %s | Env: %s", AWS_REGION, BEDROCK_MODEL_ID, FACTORY_BUCKET, ENVIRONMENT)

    # Initialize OTEL distributed tracing (no-op if not configured)
    _init_telemetry()

    # ─── Dual-Path Check (ADR-030): Defer to orchestrator if Lambda handled routing ──
    # The cognitive router Lambda (webhook_ingest) sets task status to DISPATCHED
    # when it successfully routes a task. If we see DISPATCHED, the orchestrator
    # is handling this task via the distributed path — exit cleanly.
    #
    # If status is READY, the Lambda either:
    #   a) Decided this task should run on monolith (depth < 0.5), OR
    #   b) Failed entirely — we are the fallback
    # In both cases, proceed with execution.
    if _should_defer_to_orchestrator():
        logger.info("Task already DISPATCHED by cognitive router — deferring to orchestrator. Exiting.")
        sys.exit(0)

    issues = validate_environment()
    if issues:
        for issue in issues:
            logger.error("Environment issue: %s", issue)
        sys.exit(1)

    # Build all components
    registry = build_registry()
    router = AgentRouter()

    # Constraint Extractor with optional LLM support
    llm_fn = _build_llm_invoke_fn()
    constraint_extractor = ConstraintExtractor(llm_invoke_fn=llm_fn)

    # Agent Builder reads from Prompt Registry + data contract
    agent_builder = AgentBuilder(registry)

    # Orchestrator wires everything together
    orchestrator = Orchestrator(
        registry=registry,
        router=router,
        factory_bucket=FACTORY_BUCKET,
        constraint_extractor=constraint_extractor,
        agent_builder=agent_builder,
    )

    logger.info(
        "Application ready: %d base agents [%s], constraint extractor=%s",
        len(registry.list_agents()),
        ", ".join(registry.list_agents()),
        "LLM+rules" if llm_fn else "rules-only",
    )

    # ─── Cognitive Autonomy (ADR-029): Compute BEFORE orchestrator runs ────
    # The factory owns the autonomy decision. Customer repo reads AUTONOMY_LEVEL
    # from env — we set it here so no customer code changes are needed.
    try:
        from src.core.orchestration.cognitive_autonomy import compute_cognitive_autonomy
        _repo = os.environ.get("EVENT_REPO", "")
        _deps = int(os.environ.get("TASK_DEPENDENCY_COUNT", "0") or "0")
        _blocks = int(os.environ.get("TASK_BLOCKING_COUNT", "0") or "0")

        # ─── P0a (ADR-030): Read REAL ICRL failure count from episode store ──
        # Previously hardcoded to 0. Now reads from DynamoDB to give cognitive
        # autonomy real signals about past failures for this repo.
        _icrl_failure_count = 0
        _cfr_current = 0.0
        try:
            from src.core.memory.icrl_episode_store import ICRLEpisodeStore
            _episode_store = ICRLEpisodeStore(
                project_id=os.environ.get("PROJECT_ID", "global"),
                metrics_table=os.environ.get("METRICS_TABLE", ""),
            )
            if _repo:
                _icrl_failure_count = _episode_store.get_episode_count(_repo)
                logger.info("ICRL episodes for %s: %d", _repo, _icrl_failure_count)
        except Exception as e:
            logger.debug("ICRL episode read failed (using 0): %s", str(e)[:100])

        # Read CFR from metrics (if available)
        try:
            _metrics_table = os.environ.get("METRICS_TABLE", "")
            if _metrics_table and _repo:
                _ddb = boto3.resource("dynamodb", region_name=AWS_REGION)
                _mt = _ddb.Table(_metrics_table)
                _cfr_resp = _mt.query(
                    KeyConditionExpression="project_id = :pid AND begins_with(metric_key, :prefix)",
                    ExpressionAttributeValues={":pid": _repo, ":prefix": "trust#cfr#"},
                    ScanIndexForward=False, Limit=1,
                )
                _cfr_items = _cfr_resp.get("Items", [])
                if _cfr_items:
                    import json as _json
                    _cfr_data = _json.loads(_cfr_items[0].get("data", "{}"))
                    _cfr_current = float(_cfr_data.get("cfr_value", _cfr_data.get("value", 0.0)))
        except Exception as e:
            logger.debug("CFR read failed (using 0.0): %s", str(e)[:100])

        cognitive = compute_cognitive_autonomy(
            risk_score=0.0,  # Risk Engine not available in monolith cold path
            dependency_count=_deps,
            blocking_count=_blocks,
            icrl_failure_count=_icrl_failure_count,
            cfr_current=_cfr_current,
            trust_score=50.0,
        )

        # Inject into environment — customer orchestrator reads these
        os.environ["AUTONOMY_LEVEL"] = f"L{cognitive.legacy_autonomy_level}"
        os.environ["COGNITIVE_DEPTH"] = str(round(cognitive.capability.depth, 2))
        os.environ["COGNITIVE_SQUAD_SIZE"] = str(cognitive.capability.squad_size)
        os.environ["COGNITIVE_MODEL_TIER"] = cognitive.capability.model_tier
        os.environ["COGNITIVE_AUTHORITY"] = cognitive.authority.authority_level

        logger.info(
            "Cognitive autonomy: depth=%.2f squad=%d authority=%s level=%s",
            cognitive.capability.depth, cognitive.capability.squad_size,
            cognitive.authority.authority_level, os.environ["AUTONOMY_LEVEL"],
        )
    except Exception as e:
        logger.debug("Cognitive autonomy unavailable (using defaults): %s", str(e)[:100])

    eventbridge_event = os.environ.get("EVENTBRIDGE_EVENT", "")
    task_spec_path = os.environ.get("TASK_SPEC", "")

    # Support flat env vars from EventBridge InputTransformer (COE-011 fix).
    # ECS targets cannot reliably pass complex JSON via InputTransformer,
    # so we extract individual fields and reconstruct the event here.
    event_source = os.environ.get("EVENT_SOURCE", "")
    event_action = os.environ.get("EVENT_ACTION", "")
    event_detail_type = os.environ.get("EVENT_DETAIL_TYPE", "")

    # Rework handler (ADR-027): detect task.rework_requested events
    # Works in BOTH monolith and distributed mode — monolith is the universal fallback
    if event_detail_type == "task.rework_requested":
        task_id = os.environ.get("EVENT_TASK_ID", "")
        repo = os.environ.get("EVENT_REPO", "")
        pr_number = os.environ.get("EVENT_PR_NUMBER", "")
        rework_attempt = os.environ.get("EVENT_REWORK_ATTEMPT", "1")
        reviewer = os.environ.get("EVENT_REVIEWER", "")
        constraint = os.environ.get("EVENT_REWORK_CONSTRAINT", "")

        logger.info(
            "Mode: REWORK (task=%s repo=%s pr=#%s attempt=%s reviewer=%s)",
            task_id, repo, pr_number, rework_attempt, reviewer,
        )

        # Reconstruct as a normal issue event but inject the rework constraint
        # The orchestrator will process it as a regular task with additional context
        reconstructed_event = {
            "source": "fde.internal",
            "detail-type": "task.rework_requested",
            "detail": {
                "action": "labeled",
                "label": {"name": "factory-ready"},
                "issue": {
                    "number": int(pr_number or "0"),
                    "title": f"[REWORK #{rework_attempt}] {repo} PR #{pr_number}",
                    "body": (
                        f"## REWORK TASK (attempt {rework_attempt}/2)\n\n"
                        f"**Original PR**: #{pr_number}\n"
                        f"**Reviewer**: {reviewer}\n"
                        f"**Repository**: {repo}\n\n"
                        f"### Rework Constraint\n\n{constraint}\n\n"
                        f"### Acceptance Criteria\n\n"
                        f"- [ ] Address all feedback from reviewer\n"
                        f"- [ ] CI test suite passes locally before PR update\n"
                        f"- [ ] Push fixes to existing branch\n"
                    ),
                    "labels": [{"name": "factory-ready"}],
                },
                "repository": {
                    "full_name": repo,
                },
            },
        }
        result = orchestrator.handle_event(reconstructed_event)
        logger.info("Rework result: %s", json.dumps(result, default=str))

    elif eventbridge_event:
        logger.info("Mode: EventBridge event (EVENTBRIDGE_EVENT)")
        result = orchestrator.handle_event(json.loads(eventbridge_event))
        logger.info("Result: %s", json.dumps(result, default=str))
    elif event_source and event_action:
        logger.info("Mode: EventBridge event (flat env vars)")
        reconstructed_event = {
            "source": event_source,
            "detail-type": os.environ.get("EVENT_DETAIL_TYPE", ""),
            "detail": {
                "action": event_action,
                "label": {"name": os.environ.get("EVENT_LABEL", "")},
                "issue": {
                    "number": int(os.environ.get("EVENT_ISSUE_NUMBER", "0") or "0"),
                    "title": os.environ.get("EVENT_ISSUE_TITLE", ""),
                    "labels": [{"name": os.environ.get("EVENT_LABEL", "")}],
                },
                "repository": {
                    "full_name": os.environ.get("EVENT_REPO", ""),
                },
            },
        }
        logger.info("Reconstructed event: source=%s, issue=#%s %s",
                    event_source,
                    reconstructed_event["detail"]["issue"]["number"],
                    reconstructed_event["detail"]["issue"]["title"])
        result = orchestrator.handle_event(reconstructed_event)
        logger.info("Result: %s", json.dumps(result, default=str))
    elif task_spec_path:
        logger.info("Mode: Direct spec — %s", task_spec_path)
        result = orchestrator.handle_spec(read_spec.fn(task_spec_path), task_spec_path)
        logger.info("Result: %s", json.dumps(result, default=str))
    else:
        logger.info("No task. Set TASK_SPEC, EVENTBRIDGE_EVENT, or EVENT_SOURCE+EVENT_ACTION.")

    # ─── Metrics Emission (ADR-029): Write lifecycle metrics to DynamoDB ────
    # The entrypoint owns metrics emission — customer orchestrator doesn't need to.
    # This populates the portal cards (DORA, Trust, Happy Time, Cognitive Autonomy).
    try:
        _emit_lifecycle_metrics(
            task_id=os.environ.get("EVENT_TASK_ID", "") or os.environ.get("EVENT_ISSUE_NUMBER", ""),
            repo=os.environ.get("EVENT_REPO", ""),
            cognitive_depth=os.environ.get("COGNITIVE_DEPTH", "0.5"),
            cognitive_authority=os.environ.get("COGNITIVE_AUTHORITY", "ready_for_review"),
            squad_size=os.environ.get("COGNITIVE_SQUAD_SIZE", "4"),
            model_tier=os.environ.get("COGNITIVE_MODEL_TIER", "reasoning"),
        )
    except Exception as e:
        logger.debug("Metrics emission failed (non-blocking): %s", str(e)[:100])

    logger.info("Agent execution complete.")


def _emit_lifecycle_metrics(
    task_id: str, repo: str, cognitive_depth: str,
    cognitive_authority: str, squad_size: str, model_tier: str,
) -> None:
    """Emit lifecycle metrics to DynamoDB for portal card population."""
    from datetime import datetime, timezone

    metrics_table = os.environ.get("METRICS_TABLE", "")
    project_id = os.environ.get("PROJECT_ID", "global")

    if not metrics_table or not task_id:
        return

    try:
        import boto3
        dynamodb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        table = dynamodb.Table(metrics_table)
        now = datetime.now(timezone.utc).isoformat()

        # Cognitive Autonomy metrics (CognitiveAutonomyCard)
        table.put_item(Item={
            "project_id": project_id,
            "metric_key": f"cognitive_autonomy#{task_id}#{now}",
            "metric_type": "cognitive_autonomy",
            "task_id": str(task_id),
            "recorded_at": now,
            "data": json.dumps({
                "capability_depth": float(cognitive_depth),
                "squad_size": int(squad_size),
                "model_tier": model_tier,
                "authority_level": cognitive_authority,
                "repo": repo,
                "task_id": str(task_id),
            }),
        })

        # DORA deploy frequency
        table.put_item(Item={
            "project_id": project_id,
            "metric_key": f"dora#deploy_frequency#L4#{now}",
            "metric_type": "dora_deploy_frequency",
            "task_id": str(task_id),
            "recorded_at": now,
            "data": json.dumps({
                "metric": "deploy_frequency",
                "autonomy_level": 4,
                "value": 1.0,
                "unit": "count",
                "repo": repo,
            }),
        })

        logger.info("Lifecycle metrics emitted: task=%s depth=%s authority=%s", task_id, cognitive_depth, cognitive_authority)

    except Exception as e:
        logger.warning("Failed to emit lifecycle metrics: %s", str(e)[:200])


if __name__ == "__main__":
    main()
