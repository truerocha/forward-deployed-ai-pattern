# Changelog

All notable changes to the Forward Deployed Engineer pattern are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
