# Forward Deployed Engineer — Autonomous Code Factory

### GenAI powered by Kiro

> From reactive code writer to autonomous engineering partner.
> The Staff Engineer writes specs. The factory ships code.

[![Tests](https://img.shields.io/badge/tests-171%20collected-brightgreen)]()
[![Hooks](https://img.shields.io/badge/hooks-17%20(4%20V2%20%2B%2013%20V3)-blue)]()
[![Autonomy Level](https://img.shields.io/badge/level-L4%20Autonomous%20Factory-purple)]()

---

## What Is This?

This repo is a **factory template** for enterprise-grade AI-assisted software development using [Amazon Kiro](https://kiro.dev). It implements the Autonomous Code Factory pattern (Level 4 autonomy) where AI agents handle the full development loop — writing, testing, reviewing, and packaging code — while the human engineer operates as **Factory Operator**, writing specs and approving outcomes.

The pattern is built on **Forward Deployed Engineers (FDEs)** — AI agents deployed into a project's specific context: its pipeline architecture, its knowledge artifacts, its quality standards, and its governance boundaries. An FDE is not a general-purpose coding assistant. It is an engineering partner that knows your system.

## The Operating Model

```
Staff Engineer writes spec → Agent generates tests → Human approves tests
  → Agent implements (makes tests green) → Adversarial gate challenges each write
    → CI/CD validates → Ship-readiness (Docker + E2E + holdout scenarios)
      → Agent opens MR → Human approves outcome → Code ships
```

The Staff Engineer:
- **Writes specs** (the control plane — what should exist)
- **Approves test contracts** (the halting condition — when is it done)
- **Approves outcomes** (the MR — does it serve the user)
- **Never writes implementation code**
- **Never reviews diffs line-by-line** (automated gates handle correctness)

## Empirical Results

Same task, same AI agent. Without FDE protocol: **33%** quality score. With FDE protocol: **100%** quality score.

```
FDE wins: 12 criteria  |  Bare wins: 0  |  Ties: 6
Improvement: +67 percentage points
```

## Architecture

![Autonomous Code Factory — Hero Overview](docs/architecture/planes/00-hero-overview.png)

The factory is organized into **5 modular planes**, each with its own diagram and design narrative:

| # | Plane | Responsibility | Diagram |
|---|-------|---------------|---------|
| 1 | [Version Source Management](docs/architecture/planes/01-vsm-plane.md) | Git, ALM platforms, project isolation, PR delivery | ![VSM](docs/architecture/planes/01-vsm-plane.png) |
| 2 | [FDE (Forward Deployed Engineer)](docs/architecture/planes/02-fde-plane.md) | Autonomy resolution, agent builder, pipeline execution | ![FDE](docs/architecture/planes/02-fde-plane.png) |
| 3 | [Context](docs/architecture/planes/03-context-plane.md) | Constraint extraction, prompt registry, scope boundaries, learning | ![Context](docs/architecture/planes/03-context-plane.png) |
| 4 | [Data](docs/architecture/planes/04-data-plane.md) | Router, task queue, artifact storage, EventBridge | ![Data](docs/architecture/planes/04-data-plane.png) |
| 5 | [Control](docs/architecture/planes/05-control-plane.md) | SDLC gates, DORA metrics, pipeline safety, failure modes | ![Control](docs/architecture/planes/05-control-plane.png) |

> Full single-diagram view: [docs/architecture/autonomous-code-factory.png](docs/architecture/autonomous-code-factory.png)

### AWS Reference Architecture

![Reference Architecture](docs/architecture/reference-architecture.png)

The complete AWS reference architecture shows all cloud services, data flows, and integration points in a single view. It covers: API Gateway (webhook ingestion), EventBridge (event routing), ECS Fargate (headless agent execution), Amazon Bedrock (LLM inference), DynamoDB (state management), S3 (artifact storage), Lambda (DAG fan-out + dead-letter), CloudWatch/SNS/SQS (observability), CloudFront (dashboard CDN), and Secrets Manager (credential isolation).

**Cloud orchestration (optional):** When deployed to AWS, ALM webhooks flow through API Gateway → EventBridge → ECS Fargate, where a Strands agent container runs the FDE protocol headless using Bedrock for inference. Results are written to S3 and ALM status is updated automatically. See [Cloud Orchestration Flow](docs/flows/13-cloud-orchestration.md).

Each workspace is a **production line** for a specific codebase. The Staff Engineer manages multiple lines simultaneously, routing work and approving outcomes.

```
~/.kiro/ (GLOBAL — universal laws, shared credentials, cross-project knowledge)
    |
    +-- WORKSPACE A ---- Spec in -> Ship-ready MR out
    +-- WORKSPACE B ---- Spec in -> Ship-ready MR out
    +-- WORKSPACE C ---- Spec in -> Ship-ready MR out
```

## Quick Start

### 1. Pre-flight validation

```bash
git clone https://github.com/truerocha/forward-deployed-engineer-pattern.git ~/factory-template
cd ~/factory-template
bash scripts/pre-flight-fde.sh
```

The pre-flight script validates your machine (tools, runtimes, credentials) and collects project configuration interactively. It writes a manifest to `~/.kiro/fde-manifest.json`.

### 2. Validate deployment resources

```bash
bash scripts/validate-deploy-fde.sh
```

Validates three planes:
- **Control Plane**: Kiro steerings, hooks, specs structure
- **Data Plane**: ALM platforms (GitHub Projects / Asana / GitLab Ultimate) API access
- **FDE Plane**: MCP servers, factory template integrity, global laws

### 3. Deploy the Code Factory

```bash
bash scripts/code-factory-setup.sh
```

For each project in your manifest:
- **Greenfield**: initializes repo, creates `requirements.md` template for agents to read
- **Brownfield**: clones repo, scans conventions (languages, test frameworks, linters, CI/CD) so agents match existing patterns
- Provisions workspace with hooks, steerings, MCP config, and task templates
- Enables hooks automatically based on engineering level (L2/L3/L4)
- Writes factory state dashboard to `~/.kiro/factory-state.md`

### 4. Start working

```bash
# Open your project in Kiro IDE
# Move items to "In Progress" on your board (GitHub Projects / Asana / GitLab)
# Trigger the work intake hook, or:
#fde Execute the spec in .kiro/specs/my-feature.md
```

See [docs/guides/fde-adoption-guide.md](docs/guides/fde-adoption-guide.md) for the full walkthrough with Next.js and Python microservice examples.

## The 17 Hooks

| Hook | Event | Purpose | Level |
|------|-------|---------|-------|
| fde-dor-gate | preTaskExecution | Readiness validation | L3+ |
| fde-adversarial-gate | preToolUse (write) | Challenge each write | L2+ |
| fde-dod-gate | postTaskExecution | Conformance validation | L3+ |
| fde-pipeline-validation | postTaskExecution | Pipeline testing + 5W2H + report | L3+ |
| fde-test-immutability | preToolUse (write) | VETO writes to approved tests | L2+ |
| fde-circuit-breaker | postToolUse (shell) | Error classification (code compared to environment) | L2+ |
| fde-enterprise-backlog | postTaskExecution | ALM sync (GitHub / Asana / GitLab) | L3+ |
| fde-enterprise-docs | postTaskExecution | ADR generation + hindsight notes | L3+ |
| fde-enterprise-release | userTriggered | Semantic commit + MR through MCP | L3+ |
| fde-work-intake | userTriggered | Scan boards, create specs, start pipeline | L3+ |
| fde-ship-readiness | userTriggered | Docker + E2E + Playwright + holdout | L3+ |
| fde-alternative-exploration | userTriggered | 2 approaches for L4 architectural tasks | L4 |
| fde-notes-consolidate | userTriggered | Archive old notes, merge duplicates | L3+ |
| fde-prompt-refinement | userTriggered | Meta-agent: factory health + prompt improvements | L3+ |
| fde-doc-gardening | userTriggered | Detect documentation drift from code | L3+ |
| fde-golden-principles | userTriggered | Validate code against structural invariants | L3+ |
| fde-repo-onboard | userTriggered | Phase 0 codebase reasoning (Magika + tree-sitter + Haiku) | L3+ |

## Repo Structure

```
forward-deployed-engineer-pattern/
+-- .kiro/                          # Factory template (copy to your projects)
|   +-- steering/                   # Protocol + enterprise context
|   +-- hooks/                      # 17 hooks (4 V2 + 13 V3)
|   +-- specs/                      # Working memory + holdout templates
|   +-- notes/                      # Cross-session learning structure
|   +-- meta/                       # Human feedback + refinement log
|   +-- settings/                   # MCP config template
+-- docs/
|   +-- architecture/               # System diagram + design document (DDR)
|   +-- adr/                        # 17 Architecture Decision Records
|   +-- flows/                      # 14 Mermaid feature flow diagrams
|   +-- blueprint/                  # V3 blueprint + artifacts + deploy guide
|   +-- design/                     # V2 design document (research foundations)
|   +-- guides/                     # Adoption guide with walkthroughs
|   +-- global-steerings/           # Templates for ~/.kiro/steering/
+-- examples/
|   +-- web-app/                    # Example: FDE for a web application
|   +-- data-pipeline/              # Example: FDE for a data pipeline
+-- scripts/
|   +-- pre-flight-fde.sh          # Step 1: Validate machine + collect config
|   +-- validate-deploy-fde.sh     # Step 2: Validate control/data/FDE planes
|   +-- code-factory-setup.sh      # Step 3: Deploy factory (greenfield + brownfield)
|   +-- provision-workspace.sh     # Legacy: manual onboarding (--global | --project)
|   +-- validate-alm-api.sh        # ALM API connectivity checks
|   +-- validate-aws-iam.py        # AWS IAM permission validator
|   +-- validate-e2e-cloud.sh     # E2E cloud infrastructure validation
|   +-- teardown-fde.sh           # Decommission AWS resources (Terraform or tag-based)
|   +-- generate_architecture_diagram.py
|   +-- generate_reference_architecture.py
|   +-- generate_plane_diagrams.py
|   +-- lint_language.py
+-- infra/
|   +-- terraform/                  # AWS IaC (ECR, ECS, Bedrock, S3, Secrets, VPC)
|   +-- docker/                     # Strands agent container (Dockerfile + entrypoint)
|   |   +-- agents/                 # Agent application layer (registry, router, orchestrator, tools, prompts)
+-- tests/
    +-- test_fde_e2e_protocol.py    # Structural E2E test (48 tests)
    +-- test_fde_quality_threshold.py # Quality comparison test (6 tests)
    +-- test_pipeline_data_travel.py # Cross-module contract tests (7 tests)
    +-- test_orchestrator_e2e.py    # Full pipeline wiring (3 tests)
    +-- test_execution_plans.py    # Resumable milestone tracking (15 tests)
    +-- test_doc_gardening.py      # Documentation drift detection (12 tests)
    +-- test_golden_principles.py  # Code quality invariants (13 tests)
    +-- test_lint_remediation.py   # Custom linters (12 tests)
    +-- test_pr_llm_review.py      # Agent-to-agent PR review (12 tests)
    +-- test_observability_tools.py # Factory metrics tools (7 tests)
    +-- test_autonomy_level.py     # L1-L5 autonomy computation (5 tests)
    +-- test_failure_mode_taxonomy.py # Failure classification
    +-- test_domain_segmented_metrics.py # DORA + factory metrics
    +-- test_scope_boundaries.py   # Out-of-scope rejection
```

## Research Foundations

The pattern draws from six peer-reviewed studies:

1. **Esposito et al. (2025)** — 93% of GenAI architecture studies lack formal validation
2. **Vandeputte et al. (2025)** — Verification at all levels, not only unit tests
3. **Shonan Meeting 222 (2025)** — Greenfield does not generalize to brownfield
4. **DiCuffa et al. (2025)** — "Context and Instruction" is the most efficient prompt pattern (p<10 to the negative 32)
5. **Bhandwaldar et al. (2026)** — Agent scaling yields 8.27x mean speedup with 10 agents
6. **Wong et al. (2026)** — Agent scaffolding matters as much as model capability (CCA: 59% on SWE-Bench-Pro)

## Running the Tests

```bash
python3 -m pytest tests/ -v
python3 scripts/lint_language.py docs/design/forward-deployed-ai-engineers.md
```

## CI/CD Integration

The factory integrates with GitHub Actions and GitLab CI Ultimate (through mirror). Agents work on feature branches. They never merge, deploy, or modify CI config.

---

## Documentation Index

| Document | Purpose | Start Here If... |
|----------|---------|-----------------|
| [Adoption Guide](docs/guides/fde-adoption-guide.md) | Setup + first task walkthrough | You want to start using the factory today |
| [AWS Deployment Setup](docs/guides/deployment-setup.md) | SSO auth, Terraform prerequisites, deploy commands | You want to deploy the cloud infrastructure |
| [Auth Setup](docs/guides/auth-setup.md) | ALM token creation (GitHub, GitLab, Asana) | You need to configure platform API access |
| [Blueprint](docs/blueprint/fde-blueprint-design.md) | Full architecture (16 sections) | You want to understand the design decisions |
| [Hook Deploy Guide](docs/blueprint/fde-hooks-deploy-guide.md) | Exact JSON for all 17 hooks | You want to deploy or customize hooks |
| [Design Document](docs/architecture/design-document.md) | Requirements, components, information flow | You want the formal tech design |
| [Feature Flows](docs/flows/README.md) | 14 Mermaid diagrams | You want to see how each feature works |
| [ADRs](docs/adr/) | 17 Architecture Decision Records | You want to understand why decisions were made |
| [V2 Design Doc](docs/design/forward-deployed-ai-engineers.md) | Research foundations | You want the academic grounding |
| [Blogpost](docs/blogpost-autonomous-code-factory.md) | Public summary | You want to share with your team |

### Code to Docs Cross-Reference

| Code Artifact | Documentation |
|--------------|---------------|
| `.kiro/hooks/fde-adversarial-gate.kiro.hook` | [ADR-003](docs/adr/ADR-003-agentic-tdd-halting-condition.md), [Flow 04](docs/flows/04-adversarial-gate.md) |
| `.kiro/hooks/fde-circuit-breaker.kiro.hook` | [ADR-004](docs/adr/ADR-004-circuit-breaker-error-classification.md), [Flow 05](docs/flows/05-circuit-breaker.md) |
| `.kiro/hooks/fde-test-immutability.kiro.hook` | [ADR-003](docs/adr/ADR-003-agentic-tdd-halting-condition.md), [Flow 03](docs/flows/03-agentic-tdd.md) |
| `.kiro/hooks/fde-enterprise-release.kiro.hook` | [ADR-006](docs/adr/ADR-006-enterprise-alm-integration.md), [Flow 07](docs/flows/07-enterprise-release.md) |
| `.kiro/hooks/fde-ship-readiness.kiro.hook` | [Flow 06](docs/flows/06-ship-readiness.md) |
| `.kiro/hooks/fde-enterprise-docs.kiro.hook` | [ADR-007](docs/adr/ADR-007-cross-session-learning-notes.md), [Flow 08](docs/flows/08-cross-session-learning.md) |
| `.kiro/hooks/fde-prompt-refinement.kiro.hook` | [Flow 09](docs/flows/09-meta-agent.md) |
| `.kiro/hooks/fde-repo-onboard.kiro.hook` | [ADR-015](docs/adr/ADR-015-repo-onboarding-phase-zero.md), [Flow 14](docs/flows/14-repo-onboarding.md) |
| `.kiro/hooks/fde-doc-gardening.kiro.hook` | [COE-010](docs/corrections-of-error.md) |
| `.kiro/hooks/fde-golden-principles.kiro.hook` | [Design: Golden Principles](docs/design/golden-principles.md) |
| `.kiro/steering/fde.md` | [V2 Design Doc](docs/design/forward-deployed-ai-engineers.md), [Blueprint](docs/blueprint/fde-blueprint-design.md) |
| `infra/docker/agents/onboarding/` | [ADR-015](docs/adr/ADR-015-repo-onboarding-phase-zero.md), [ADR-016](docs/adr/ADR-016-ephemeral-catalog-data-residency.md) |
| `infra/docker/agents/orchestrator.py` | [Flow 13](docs/flows/13-cloud-orchestration.md), [Design Document](docs/architecture/design-document.md) |
| `scripts/provision-workspace.sh` | [Adoption Guide](docs/guides/fde-adoption-guide.md) |

---

## License

MIT

## Contributing

PRs welcome. If you apply the Forward Deployed Engineer pattern to your project and have results to share, open an issue.
