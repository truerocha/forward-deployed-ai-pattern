# Changelog

All notable changes to the Forward Deployed Engineer pattern are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased] — 2026-05-04

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
