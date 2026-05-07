# Changelog

All notable changes to the Forward Deployed Engineer pattern are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased] — 2026-05-06

### Added — EventBridge Observability (COE-011)
- `infra/terraform/eventbridge-observability.tf` — Catch-all logging rule (all events → CloudWatch Logs), FailedInvocations alarm, API Gateway 4xx/5xx alarms, CloudWatch Log resource policy for EventBridge delivery.
- `scripts/validate-webhook-eventbridge.sh` — Three-test isolation script for webhook→ECS path validation.

### Fixed — EventBridge → ECS Pipeline (COE-011)
- `infra/terraform/eventbridge.tf` — InputTransformer changed from broken single-JSON-string pattern to flat scalar env vars (EVENT_SOURCE, EVENT_ACTION, EVENT_LABEL, EVENT_ISSUE_NUMBER, EVENT_ISSUE_TITLE, EVENT_REPO). Root cause: ECS RunTask silently rejects overrides with unescaped JSON objects in string values.
- `infra/docker/agent_entrypoint.py` — Added flat env var reconstruction mode: when EVENT_SOURCE+EVENT_ACTION are set, reconstructs the event object from individual env vars. Maintains backward compatibility with EVENTBRIDGE_EVENT and TASK_SPEC modes.
- `infra/docker/Dockerfile.strands-agent` — Rebuilt with `--platform linux/amd64` for ECS Fargate compatibility (was arm64 from Apple Silicon build).
- `docs/corrections-of-error.md` — COE-011: Full root cause analysis with production evidence (task 03b21106).

### Added — Repo Onboarding Agent (Phase 0, ADR-015)
- `infra/docker/agents/onboarding/` — Phase 0 codebase reasoning brain (13 modules). Sequential pipeline: Trigger Handler → Repo Cloner → File Scanner (Magika) → AST Extractor (tree-sitter) → Convention Detector → Pattern Inferrer (Claude Haiku) → Catalog Writer (SQLite) → Steering Generator → S3 Persister.
- `infra/docker/agents/onboarding/pipeline.py` — Orchestrates all 9 stages sequentially with observability, failure reporting, and incremental re-scan support.
- `infra/docker/agents/onboarding/trigger_handler.py` — Event reception, input validation (URL allowlist, UUID format), mode detection (cloud vs local), incremental skip check.
- `infra/docker/agents/onboarding/repo_cloner.py` — Git clone with ADR-014 credential isolation (fetch-use-discard via GIT_ASKPASS). Supports GitHub, GitLab, Bitbucket.
- `infra/docker/agents/onboarding/file_scanner.py` — Magika-based content classification for every file. Detects generated code, skips binaries >1MB, respects skip directories.
- `infra/docker/agents/onboarding/ast_extractor.py` — tree-sitter AST parsing for Python, JS/TS, Go, Java, Rust, HCL. Extracts module signatures, import graphs, dependency edges.
- `infra/docker/agents/onboarding/convention_detector.py` — Detects 60+ project conventions (package managers, test frameworks, linters, CI/CD, IaC, containers).
- `infra/docker/agents/onboarding/pattern_inferrer.py` — Claude Haiku (Bedrock) inference for pipeline chain, module boundaries, tech stack, and engineering level patterns. Cost-capped at $0.01/run.
- `infra/docker/agents/onboarding/catalog_writer.py` — SQLite persistence (9 tables per REQ-4.1) + catalog query interface for FDE intake integration (get_tech_stack, get_suggested_level, get_module_context).
- `infra/docker/agents/onboarding/steering_generator.py` — Generates project-specific `.kiro/steering/fde.md` from catalog data with unified diff on re-scan.
- `infra/docker/agents/onboarding/s3_persister.py` — Uploads catalog + steering draft + diff to S3 (cloud mode only).
- `infra/docker/agents/onboarding/observability.py` — Structured JSON logging, CloudWatch metrics (fde/onboarding namespace), failure report generation.
- `infra/docker/Dockerfile.onboarding-agent` — Python 3.12 slim + gh CLI + Magika + tree-sitter grammars.
- `infra/docker/requirements-onboarding.txt` — magika>=0.5.0, tree-sitter>=0.21.0, tree-sitter-languages>=1.10.0, networkx>=3.2, boto3>=1.35.0.
- `infra/terraform/onboarding.tf` — ECS task definition (1 vCPU / 2GB), IAM role (least privilege: S3, Secrets, Bedrock, CloudWatch), EventBridge rule, CloudWatch alarms (stage P99 latency, total duration budget).
- `.kiro/hooks/fde-repo-onboard.kiro.hook` — userTriggered hook for local mode onboarding.
- `docs/adr/ADR-015-repo-onboarding-phase-zero.md` — Architecture decision: hybrid deterministic scan + lightweight LLM.
- `docs/flows/14-repo-onboarding.md` — Phase 0 flow diagram with Mermaid (9 stages + incremental re-scan).

### Added — Ephemeral Catalog for Regulated Environments (ADR-016, SEC 7-10)
- `docs/adr/ADR-016-ephemeral-catalog-data-residency.md` — Data residency architecture: three persistence modes (cloud/local/ephemeral), customer-controlled encryption via KMS, TTL-based auto-destruction, audit sidecar without data exposure.

### Added — Operational Tooling and Observability
- `scripts/validate-e2e-cloud.sh` — Full infrastructure health check (11 checks). Single command validates factory readiness.
- `scripts/deploy-dashboard.sh` — Automated dashboard deployment with config injection from terraform outputs.
- `scripts/setup-fde-client.sh` — One-command FDE client setup for any project (hooks + ALM integration).
- `scripts/setup-alm-integration.sh` — Platform-agnostic ALM setup (`--platform github|gitlab|asana`).
- `scripts/bootstrap-fde-workspace.sh` — Installs minimal FDE hooks into any target workspace.
- `infra/docker/agents/status_sync.py` — Posts structured progress comments to GitHub issues during pipeline execution.
- `infra/dashboard/index.html` — Agentic UX dashboard (Cyber-Industrial theme, chain-of-thought log, light/dark mode, ProServe logo).
- `infra/terraform/dashboard.tf` — Dashboard status Lambda + API Gateway route (`GET /status/tasks`).
- `infra/terraform/dashboard-cdn.tf` — CloudFront distribution + OAC for dashboard static hosting.
- `infra/terraform/lambda/dashboard_status/index.py` — Lambda reading DynamoDB task_queue for dashboard metrics.
- `docs/guides/staff-engineer-post-deploy.md` — Complete post-deploy operations guide.
- `docs/corrections-of-error-cloudfront-kms.md` — COE: CloudFront OAC + SSE-KMS access denied root cause and fix.

### Changed — Bedrock Model (Legacy → Active)
- Migrated from `anthropic.claude-3-haiku-20240307-v1:0` (LEGACY) to `us.anthropic.claude-haiku-4-5-20251001-v1:0` (ACTIVE inference profile).

### Changed — Security Cleanup
- Removed all hardcoded account IDs, endpoint URLs, and profile names from active code and docs.
- Dashboard API URL injected at deploy time via `<meta>` tag.
- Dockerfile: added non-root user, suppressed ONNX Runtime warning.

### Infrastructure Deployed
- 9 new resources added to existing stack (ECR onboarding repo, ECS task def, IAM role, EventBridge rule, CloudWatch alarms, dashboard Lambda, CloudFront distribution).
- Docker images pushed: `fde-dev-onboarding-agent:latest`, `fde-dev-strands-agent:latest`.
- Dashboard live via CloudFront. Status API responding at `/status/tasks`.

### Changed — Dependencies (Repo Onboarding Agent)
- `infra/docker/requirements.txt` — Added magika, tree-sitter, tree-sitter-languages, networkx to shared dependencies.

### Added — Dead-Letter Handler and Observability (ADR-014, OPS 6 + OPS 8)
- `infra/terraform/lambda/dead_letter/index.py` — Dead-letter Lambda handler for permanently failed DAG fan-out invocations. Extracts failed task metadata from SQS messages, publishes structured alerts to SNS, marks tasks as `DEAD_LETTER` in DynamoDB for visibility.
- `infra/terraform/observability.tf` — Full observability layer: SNS topic (`fde-dev-pipeline-alerts`), SQS dead-letter queue (`fde-dev-dag-fanout-dlq`), dead-letter Lambda with IAM role, SQS→Lambda event source mapping, 6 CloudWatch alarms (fan-out errors, dead-letter invocations, fan-out throttles, DynamoDB read/write throttles, fan-out duration approaching timeout).
- `docs/guides/deployment-setup.md` — AWS deployment prerequisites guide: SSO profile configuration, session authentication, Terraform variables, init/plan/apply commands, common errors and fixes, teardown, post-deploy steps.
- CloudWatch alarms route to SNS topic for operator notification (email subscription supported).

### Changed — DAG Fan-Out On-Failure Destination (ADR-014)
- `infra/terraform/dag_fanout.tf` — Added `destination_config.on_failure` pointing to SQS dead-letter queue. Added `sqs:SendMessage` permission to fan-out Lambda IAM policy. Failed batches (after DynamoDB Stream's 3 retries) now route to SQS → dead-letter Lambda → SNS alert.

### Changed — README Documentation Index
- `README.md` — Added [AWS Deployment Setup](docs/guides/deployment-setup.md) and [Auth Setup](docs/guides/auth-setup.md) to the Documentation Index table.

### Infrastructure Deployed
- Stack applied to AWS account 785640717688 (us-east-1): 74 resources total (4 added, 3 changed, 1 destroyed in final apply).
- SNS email subscription created for `rocand@amazon.com` (pending confirmation).

---

## [Unreleased] — 2026-05-05

### Added — E2E Pipeline Data Travel Validation
- `tests/test_pipeline_data_travel.py` — 7 cross-module contract tests validating data flows across: Scope Check → Autonomy → Gate Resolution → Execution Plan → SDLC Gates (with enrichment). Proves module interfaces are compatible.
- `tests/test_orchestrator_e2e.py` — 3 E2E tests calling `orchestrator.handle_event()` with real EventBridge events. Proves the Orchestrator ACTUALLY wires scope check, autonomy, gate resolution, and execution plan tracking in production code.
- Resolves the "Node-scoped verification" anti-pattern (COE-052): modules are now validated as a composed system, not just in isolation.

### Changed — Orchestrator Wiring (v2 → v3)
- `infra/docker/agents/orchestrator.py` — `handle_event()` now wires the full pipeline:
  1. Scope Check (`check_scope()`) rejects out-of-scope tasks before any work starts
  2. Autonomy Level (`compute_autonomy_level()`) determines supervision level
  3. Gate Resolution (`resolve_pipeline_gates(level, confidence)`) determines which gates to run
  4. Execution Plan (`create_plan()` / `load_plan()` / `resume_from_plan()`) enables resumable execution
  5. Milestone tracking persists progress to disk after each gate completion
- New imports: `autonomy`, `execution_plan`, `scope_boundaries`
- New constructor parameter: `plans_dir` (filesystem path for execution plan persistence)
- New method: `_execute_pipeline_with_plan()` tracks inner loop gates as milestones
- Backward compatible: `handle_spec()` path unchanged

### Added — Agent-to-Agent PR Review (Task 5)
- `review_pr_with_llm()` in `pipeline_safety.py` — LLM-powered PR review that evaluates diffs against spec and constraints. Returns structured `PRReviewResult` with approved/concerns/suggestions
- `PRReviewResult` dataclass with `to_dict()` serialization
- Opt-in via `PR_REVIEW_LLM_ENABLED=true` env var (same pattern as constraint extraction)
- `_build_review_prompt()` — structured prompt with diff truncation (8000 char limit)
- `_parse_review_response()` — handles clean JSON, markdown code blocks, and invalid responses gracefully
- `_invoke_bedrock()` — same Bedrock invocation pattern as Constraint Extractor
- `tests/test_pr_llm_review.py` — 12 BDD scenarios covering opt-in behavior, response parsing, prompt construction, and dataclass serialization

### Added — Observability Accessible to Agent (Task 6)
- `read_factory_metrics` @tool in `tools.py` — returns DORA metrics for a specific task_id as JSON (read-only)
- `read_factory_health` @tool in `tools.py` — returns Factory Health Report as JSON (read-only, configurable window_days)
- Both tools added to `REPORTING_TOOLS` list (Reporting Agent only, not Engineering Agent)
- `tests/test_observability_tools.py` — 7 BDD scenarios validating tool registration, read-only separation, signatures, and callability

### Added — Execution Plans with Progress Tracking (Task 1)
- `infra/docker/agents/execution_plan.py` — Resumable pipeline execution with `ExecutionPlan` dataclass, milestone tracking (pending → in_progress → completed/skipped), append-only progress and decision logs, filesystem persistence (save/load/plan_exists), and `resume_from_plan()` that finds the first non-completed milestone
- `tests/test_execution_plans.py` — 15 BDD scenarios covering: plan creation, milestone progression, interruption/resume cycle (the core value prop), persistence roundtrip, corrupted file handling, and decision logging
- Source: OpenAI PLANS.md Cookbook — enables L3/L4 tasks to resume from interruption point

### Added — Doc-Gardening Agent (Task 2)
- `infra/docker/agents/doc_gardening.py` — Documentation drift detection with function registry pattern. 5 built-in checks: hook count badge, ADR count, flow count, design-document components, CHANGELOG freshness
- `.kiro/hooks/fde-doc-gardening.kiro.hook` — userTriggered hook to scan for documentation drift
- `tests/test_doc_gardening.py` — 12 BDD scenarios validating drift detection for all check types, registry extensibility, and crash resilience
- Resolves COE pattern: 6 of 9 entries were "doc was outdated"

### Added — Golden Principles + Garbage Collection (Task 4)
- `docs/design/golden-principles.md` — 5 mechanical code quality invariants (GP-01 through GP-05) with rule, rationale, detection logic, and remediation for each
- `infra/docker/agents/golden_principles.py` — Principle validation engine with `@register_principle` decorator pattern. Checks: max file size (500 lines), no print() in production, module docstrings, no import *, max function length (50 lines)
- `.kiro/hooks/fde-golden-principles.kiro.hook` — userTriggered hook to validate code against structural invariants
- `tests/test_golden_principles.py` — 13 BDD scenarios validating all 5 principles (positive + negative cases) plus integration and registry tests

### Added — Custom Linters with Remediation Messages (Task 3)
- `REMEDIATION_MAP` in `sdlc_gates.py` — 20 error code → remediation instruction mappings covering Python (ruff/flake8), TypeScript/JavaScript (eslint), Go (staticcheck), and Terraform (fmt)
- `_enrich_lint_output()` in `sdlc_gates.py` — post-processes raw lint output, appending actionable fix instructions after each recognized error line
- `check_lint()` now returns enriched errors so the agent sees remediation hints in the inner loop retry
- `tests/test_lint_remediation.py` — 12 BDD scenarios validating enrichment for Python, TypeScript, Go, multi-error, unknown codes, and edge cases

### Added — Minimal Gates for L5 High-Confidence Tasks (Task 7)
- `resolve_pipeline_gates()` in `autonomy.py` now accepts optional `confidence_level` parameter
- L5 tasks with `confidence_level == "high"` skip `dor_gate` and `ship_readiness` (inner loop gates provide sufficient validation)
- L5 tasks with any other confidence level retain standard L5 behavior (backward compatible)
- L4 and below are unaffected regardless of confidence level
- 5 new BDD scenarios in `tests/test_autonomy_level.py` (class `TestMinimalGatesL5`)

### Changed — Sprint 1 Throughput Improvements
- Source: OpenAI Harness Engineering ("custom lints with remediation instructions") + Ralph Loop ("corrections are cheap, waiting is expensive")
- Impact: Inner loop first-pass rate improvement (Task 3) + reduced latency for high-confidence L5 tasks (Task 7)

---

## [Unreleased] — 2026-05-04

### Added — Authentication and Data Journey Validation
- `docs/guides/auth-setup.md` — Step-by-step token creation guide for GitHub (PAT classic, scopes `repo` + `project`), GitLab (PAT, scope `api`, expiry check), and Asana (PAT, inherited permissions). Includes progressive configuration, token rotation, cloud deployment (Secrets Manager), and troubleshooting.
- `examples/web-app/test_data_journey.py` — 13 integration tests validating the full data contract flow per platform (GitHub, GitLab, Asana). Each test covers: Router extraction → Constraint detection → Scope check → Autonomy computation → Routing decision.
- `scripts/validate-alm-api.sh` — Extended GitLab validation: PAT self-introspection (`GET /personal_access_tokens/self`), scope verification (`api` required), and token expiry check.

### Added — Enterprise-Grade Autonomy and Observability (ADR-013)
- `infra/docker/agents/autonomy.py` — Autonomy Level computation (L1-L5) with pipeline gate adaptation. Computes level from data contract (type + level), supports human override, resolves which gates and checkpoints to apply per task.
- `infra/docker/agents/failure_modes.py` — Failure Mode Taxonomy (FM-01 through FM-99). Classifies WHY tasks do not complete using heuristic rules on execution context signals. Integrates with DORA metrics as dimensions.
- `infra/docker/agents/scope_boundaries.py` — Scope Boundary Enforcement. Rejects tasks outside factory capability (no acceptance criteria, no tech_stack, forbidden actions like production deploy or PR merge). Computes confidence level (high/medium/low) from available signals.
- `docs/design/scope-boundaries.md` — Formal scope boundaries document defining in-scope capabilities, out-of-scope items, performance targets per autonomy level, and confidence scoring.
- `tests/test_autonomy_level.py` — 10 BDD scenarios for autonomy computation and pipeline adaptation
- `tests/test_failure_mode_taxonomy.py` — 8 BDD scenarios for failure classification
- `tests/test_domain_segmented_metrics.py` — 5 BDD scenarios for tech_stack segmentation
- `tests/test_scope_boundaries.py` — 8 BDD scenarios for scope enforcement
- ADR-013: Enterprise-Grade Autonomy, Failure Classification, and Scope Boundaries

### Added — Constraint Extractor and Agent Builder (ADR-010)
- `infra/docker/agents/constraint_extractor.py` — Two-pass constraint extraction (rule-based regex + opt-in LLM). Extracts version pins, latency thresholds, auth mandates, encryption requirements, dependency exclusions. DoR Gate validates extracted constraints against tech_stack.
- `infra/docker/agents/agent_builder.py` — Just-in-time agent provisioning from data contract. Queries Prompt Registry by tech_stack context tags, injects extracted constraints into agent prompts, selects tool set by task type.
- `infra/docker/agents/project_isolation.py` — SaaS-kernel project isolation. Each task gets isolated S3 prefix, workspace directory, git branch, and correlation ID. Zero cross-project interference.
- `infra/docker/agents/sdlc_gates.py` — Inner loop (lint → typecheck → unit-test → build) and outer loop (DoR → Constraint Extraction → Adversarial → Ship-Readiness) gate enforcement with retry logic and timing.
- `infra/docker/agents/pipeline_safety.py` — PR Diff Review Gate (secret scanning, debug code detection, size checks) + Automatic Rollback (checkpoint + git reset to known-good state on feature branches).
- `infra/docker/agents/dora_metrics.py` — DORA Metrics Collector with 4 core metrics (Lead Time, Deployment Frequency, Change Failure Rate, MTTR) + 5 factory metrics. Domain segmentation by tech_stack. Factory Health Report with DORA level classification (Elite/High/Medium/Low).

### Added — Over-Engineering Mitigations (ADR-012)
- LLM constraint extraction is opt-in (default off). Enable via env var, constructor flag, or per-task field.
- Fast path for bugfix/documentation tasks with empty constraints — skips extraction entirely.
- ADR-011: Multi-Cloud Adapter deferred until customer demand. `target_environment` preserved in data contract.
- ADR-012: Over-Engineering Mitigations and Gap Closures (6 decisions with adversarial analysis)

### Changed — Router (v1 → v2)
- `infra/docker/agents/router.py` — Now extracts the full canonical data contract from platform-specific event payloads (GitHub issue form sections, GitLab scoped labels, Asana custom fields). `RoutingDecision` carries `data_contract` dict.

### Changed — Orchestrator (v1 → v2)
- `infra/docker/agents/orchestrator.py` — Full pipeline: Router → Constraint Extraction → DoR Gate → Agent Builder → Execute. Fast path for simple tasks. Writes extraction reports to S3 for audit trail.

### Changed — Entrypoint
- `infra/docker/agent_entrypoint.py` — Wires Constraint Extractor (with optional LLM) + Agent Builder into the Orchestrator.

### Changed — DynamoDB (Terraform)
- `infra/terraform/dynamodb.tf` — Added `fde-dev-dora-metrics` table with GSIs for task_id and metric_type queries.
- `infra/terraform/main.tf` — Added DORA_METRICS_TABLE env var to ECS task definition, added DynamoDB access to IAM policy.

### Changed — Data Contract Design
- `docs/design/data-contract-task-input.md` — Updated Agent Consumption Matrix with new components (Constraint Extractor, DoR Gate, Agent Builder). Added Pipeline Flow diagram showing the full InProgress event sequence.

### Added — Multi-Platform ALM Integration (ADR-008)
- Portable task templates for GitHub Projects, Asana, and GitLab Ultimate (`docs/templates/task-template-*.md`)
- Canonical task schema (`docs/templates/canonical-task-schema.yaml`) — platform-agnostic format all adapters map to
- `fde-work-intake` hook (14th hook) — scans ALM boards for "In Progress" items, creates specs, starts pipeline
- Asana MCP server added to `.kiro/settings/mcp.json`
- GitLab MCP server expanded with issue operations in autoApprove list
- `scripts/validate-alm-api.sh` — pre-flight API connectivity checks for all three platforms
- Flow 11: Multi-Platform Work Intake (`docs/flows/11-multi-platform-intake.md`)
- ADR-008: Multi-Platform Project Tooling

### Added — Staff Engineer Onboarding Pipeline (ADR-009)
- `scripts/pre-flight-fde.sh` — validates machine tools, credentials (including AWS SSO/profile), IAM permissions, collects project config interactively
- `scripts/validate-deploy-fde.sh` — validates four planes: Control (Kiro), Data (ALM APIs), FDE (MCP/hooks), Cloud (AWS)
- `scripts/code-factory-setup.sh` — deploys everything: global infra, per-project workspaces, optional AWS cloud
- Three project modes: experiment (local-only), greenfield (new repo), brownfield (existing codebase with convention scan)
- Brownfield convention scanner detects languages, package managers, test frameworks, linters, CI/CD, Docker
- Greenfield `requirements.md` template for agent-driven scaffolding
- Flow 12: Staff Engineer Onboarding (`docs/flows/12-staff-engineer-onboarding.md`)

### Added — AWS Cloud Infrastructure (ADR-009)
- Terraform IaC (`infra/terraform/`) for the full cloud stack:
  - ECR repository for Strands agent Docker images
  - ECS Fargate cluster for headless agent execution
  - S3 bucket for factory artifacts (versioned, KMS-encrypted, public access blocked)
  - Secrets Manager for ALM tokens (GitHub, Asana, GitLab)
  - VPC with public/private subnets, NAT Gateway, security group (egress-only)
  - IAM roles with least-privilege policies (Bedrock, S3, Secrets, CloudWatch)
  - CloudWatch log groups for agent execution and API Gateway
- `infra/terraform/modules/vpc/` — reusable VPC module
- `infra/terraform/factory.tfvars.example` — configuration template
- `scripts/validate-aws-iam.py` — per-service IAM permission validator
- ADR-009: AWS Cloud Infrastructure for Headless Agent Execution

### Added — EventBridge + API Gateway Orchestration
- `infra/terraform/eventbridge.tf` — custom event bus, 3 rules (GitHub/GitLab/Asana), IAM role, 3 ECS RunTask targets with event passthrough
- `infra/terraform/apigateway.tf` — HTTP API Gateway with 3 webhook routes (`POST /webhook/{platform}`), direct EventBridge PutEvents integration, access logging
- Webhook URLs output by Terraform for configuring ALM platform webhooks

### Added — Strands Agent Application Layer
- `infra/docker/agents/registry.py` — Agent Registry: stores agent definitions, creates Strands Agent instances with BedrockModel
- `infra/docker/agents/router.py` — Agent Router: maps EventBridge events to the correct agent (reconnaissance/engineering/reporting)
- `infra/docker/agents/orchestrator.py` — Agent Orchestrator: wires Registry + Router, executes agents, writes results to S3
- `infra/docker/agents/tools.py` — 6 real `@tool`-decorated functions: read_spec, write_artifact, update_github_issue, update_gitlab_issue, update_asana_task, run_shell_command
- `infra/docker/agents/prompts.py` — FDE system prompts for 3 agent roles (Reconnaissance Phase 1, Engineering Phases 2-3, Reporting Phase 4)
- `infra/docker/agents/prompt_registry.py` — Prompt Registry: versioned prompt storage in DynamoDB with SHA-256 hash integrity, context-aware selection by tags
- `infra/docker/agents/task_queue.py` — Task Queue: DynamoDB-backed with DAG dependency resolution, priority ordering, optimistic locking for task claims, automatic promotion of dependent tasks
- `infra/docker/agents/lifecycle.py` — Agent Lifecycle Manager: tracks instances through CREATED → INITIALIZING → RUNNING → COMPLETED/FAILED → DECOMMISSIONED, execution time tracking, active agent count
- `infra/docker/agent_entrypoint.py` — main entrypoint wiring Registry + Router + Orchestrator, 3 execution modes (EventBridge event, direct spec, standby)
- `infra/docker/Dockerfile.strands-agent` — Python 3.12 + Node.js 20, non-root user, strands-agents SDK
- `infra/docker/requirements.txt` — strands-agents>=1.0.0, boto3, pyyaml, requests
- Docker image built and pushed to ECR (`fde-dev-strands-agent:latest`)

### Added — DynamoDB Tables (Terraform)
- `infra/terraform/dynamodb.tf` — 3 DynamoDB tables (PAY_PER_REQUEST):
  - `fde-dev-prompt-registry` (PK: prompt_name, SK: version) — versioned prompts with hash integrity
  - `fde-dev-task-queue` (PK: task_id, GSI: status-created-index) — task queue with dependency DAG
  - `fde-dev-agent-lifecycle` (PK: agent_instance_id, GSI: status-created-index) — agent instance tracking
- IAM policy for ECS task role: DynamoDB read/write access to all 3 tables
- ECS task definition v2: added PROMPT_REGISTRY_TABLE, TASK_QUEUE_TABLE, AGENT_LIFECYCLE_TABLE env vars
- E2E validated against live DynamoDB: prompt versioning + hash integrity, task dependency resolution, full agent lifecycle walk

### Added — E2E Validation and Teardown
- `scripts/validate-e2e-cloud.sh` — validates all 7 cloud resource categories: Terraform outputs, API Gateway webhooks, EventBridge bus/rules/events, S3 read/write, Secrets Manager, ECR repo/images, ECS cluster/task definition
- `scripts/teardown-fde.sh` — two modes: Terraform destroy (preferred) and tag-based cleanup (fallback), with dry-run preview
- E2E validation result: 21 passed, 0 failed, 0 warnings against live AWS account 785640717688

### Added — Documentation
- Flow 13: Cloud Orchestration (`docs/flows/13-cloud-orchestration.md`)
- `docs/corrections-of-error.md` — sequential COE log (8 entries)
- `CHANGELOG.md` — this file

### Added — Data Contract and Platform Templates (ADR-010)
- `docs/design/data-contract-task-input.md` — formal data contract defining required/optional/agent-populated fields, validation rules, platform mapping, agent consumption matrix
- `.github/ISSUE_TEMPLATE/factory-task.yml` — GitHub issue form enforcing the data contract (dropdowns, checkboxes, required fields)
- `.github/pull_request_template.md` — structured PR template with validation checklist
- `.gitlab/issue_templates/factory-task.md` — GitLab issue template with scoped labels
- ADR-010: Data Contract for Task Input — connects data contract to Agent Builder (tech_stack + type drive just-in-time agent provisioning)

### Changed — Enterprise Hooks (v1 → v2)
- `fde-enterprise-backlog` v2.0 — now platform-aware: reads `source:` from spec frontmatter, syncs to originating platform, supports cross-platform linking
- `fde-enterprise-release` v2.0 — creates PR/MR on the correct platform (GitHub or GitLab), updates ALM status across all linked platforms

### Changed — Enterprise Steering
- `.kiro/steering/fde-enterprise.md` — added Factory Dispatcher persona, multi-platform support table, work intake flow, API validation section, cloud deployment context with webhook URLs and agent pipeline

### Changed — Provision Script
- `scripts/provision-workspace.sh` — copies task templates during project onboarding, checks ASANA_ACCESS_TOKEN, adds ALM and cloud setup guidance to "Next Steps"

### Changed — MCP Configuration
- `.kiro/settings/mcp.json` — added Asana MCP server, expanded GitLab autoApprove list

### Changed — Architecture Diagram
- `scripts/generate_architecture_diagram.py` — updated with 14 hooks, multi-platform ALM labels, AWS Cloud Plane branch (ECS Fargate + Bedrock)
- `docs/architecture/autonomous-code-factory.png` — regenerated (3252x1165, 2.79:1 ratio)

### Changed — Design Document
- `docs/architecture/design-document.md` — hook count 13→14, added Cloud Infrastructure/Onboarding Pipeline/Strands Agent/IAM Validator to Components table, added ADR-008 and ADR-009 to Key Design Decisions

### Changed — Adoption Guide
- `docs/guides/fde-adoption-guide.md` — added "Recommended: Automated Onboarding Pipeline" section with three-script flow

### Changed — README
- Quick Start rewritten: pre-flight → validate-deploy → code-factory-setup (was provision-workspace.sh only)
- Hook count badge: 13→14, ADR count: 7→9, flow count: 10→13
- Repo structure: added infra/, agents/, teardown, E2E validation, IAM validator scripts
- Architecture section: added cloud orchestration explanation with link to Flow 13

### Changed — Scripts (Linter Mode + AWS SSO)
- All three onboarding scripts operate as linters — collect all issues, report with remediation, never exit early
- AWS SSO/profile support: `aws_cmd()` helper passes `--profile` to all AWS CLI calls, `get_tf_env()` passes `AWS_PROFILE` to Terraform
- AWS profile stored in manifest (`credentials.aws_profile`, `cloud.aws_tf_profile`)

### Fixed
- COE-001: Hook count inconsistency in design document (13→14)
- COE-002: Design document missing infrastructure components
- COE-003: Adoption guide referenced old onboarding flow
- COE-004: Blogpost missing cloud deployment (intentional — point-in-time publication)
- COE-005: Missing ADR for AWS Cloud Infrastructure (created ADR-009)
- COE-006: Architecture diagram outdated (regenerated with cloud plane)
- COE-007: GitLab EventBridge rule used invalid nested event pattern
- COE-008: Bash arithmetic `((PASS++))` returns exit code 1 when PASS is 0

---

## [3.0.0] — 2026-05-04

### Added
- Autonomous Code Factory pattern (Level 4 autonomy)
- 13 Kiro hooks: DoR gate, adversarial gate, DoD gate, pipeline validation, test immutability, circuit breaker, enterprise backlog, enterprise docs, enterprise release, ship-readiness, alternative exploration, notes consolidation, prompt refinement
- `.kiro/steering/fde.md` — FDE protocol steering with pipeline chain, module boundaries, quality standards
- `.kiro/steering/fde-enterprise.md` — enterprise ALM context steering
- `scripts/provision-workspace.sh` — automated onboarding (--global / --project)
- `scripts/generate_architecture_diagram.py` — ILR-compliant architecture diagram generator
- `scripts/lint_language.py` — violent, trauma, and weasel word detection
- 10 Mermaid feature flow diagrams (`docs/flows/01-10`)
- 7 Architecture Decision Records (ADR-001 through ADR-007)
- Design document (`docs/architecture/design-document.md`)
- Architecture diagram (`docs/architecture/autonomous-code-factory.png`)
- Blogpost (`docs/blogpost-autonomous-code-factory.md`)
- Adoption guide with Next.js and Python microservice walkthroughs
- Blueprint design and hook deploy guide
- Global steerings: agentic-tdd-mandate, adversarial-protocol
- Examples: web-app and data-pipeline workspace templates
- 54 tests: 48 structural E2E + 6 quality threshold
- Factory state dashboard (`~/.kiro/factory-state.md`)
- Cross-session learning via notes system
- Meta-agent for prompt refinement

### Changed
- Renamed from "Dark Factory" to "Autonomous Code Factory"
- Replaced "Director of Architecture" with "Factory Operator" / "Staff Engineer"
- Applied Amazon writing standards: zero violent, trauma, or weasel word violations

---

## [2.0.0] — 2026-04-24

### Added
- Forward Deployed AI Engineers (FDE) design pattern
- Four-phase autonomous engineering protocol (Reconnaissance → Intake → Engineering → Completion)
- Research foundations from 6 peer-reviewed studies
- COE-052 post-mortem analysis with 5 failure modes
- Structured prompt contract (Context + Instruction + Constraints)
- Recipe-aware iteration (Phase 3 sub-phases: 3.a adversarial, 3.b pipeline, 3.c 5W2H, 3.d 5 Whys)
- Engineering level classification (L2/L3/L4)
- Knowledge artifact vs code artifact distinction
- `docs/design/forward-deployed-ai-engineers.md` — full design document with research synthesis

---

## [1.0.0] — 2026-04-24

### Added
- Initial release of the Forward Deployed AI Engineers pattern for Kiro
- Basic steering file for FDE protocol
- README with pattern overview
