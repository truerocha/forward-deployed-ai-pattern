# Design Document: Autonomous Code Factory

> Forward Deployed Engineer — GenAI powered by Kiro
> Version: 3.1
> Date: 2026-05-07

## Executive Summary

This document describes the design of the Autonomous Code Factory, a system that enables a Staff Engineer to manage multiple software projects simultaneously by delegating implementation to AI agents governed by structured specifications, quality gates, and automated validation.

## Problem Statement

Standard AI-assisted development follows a reactive cycle: the human writes prompts, reviews generated code line-by-line, and manually coordinates between the IDE, ALM systems, CI/CD pipelines, and documentation. This approach does not scale beyond one project and produces locally correct changes that cascade into system-level issues.

## Requirements

### Functional Requirements

| No. | Role | Use Case | Priority |
|-----|------|----------|----------|
| 1.1 | Staff Engineer | Write specs in NLSpec format and mark as ready for execution | P0 |
| 1.2 | Staff Engineer | Approve test contracts before implementation begins | P0 |
| 1.3 | Staff Engineer | Trigger ship-readiness validation (Docker, E2E, holdout) | P0 |
| 1.4 | Staff Engineer | Trigger release (semantic commit, MR, ALM update) | P0 |
| 2.1 | Agent | Execute specs following the 4-phase protocol (Recon, Intake, Engineering, Completion) | P0 |
| 2.2 | Agent | Generate tests from spec scenarios before writing production code | P0 |
| 2.3 | Agent | Classify errors as CODE or ENVIRONMENT before modifying source | P0 |
| 2.4 | Agent | Generate hindsight notes after task completion | P1 |
| 2.5 | Agent | Sync progress to ALM via MCP | P1 |
| 3.1 | Factory | Support 3+ workspaces operating in parallel | P0 |
| 3.2 | Factory | Inherit global laws and credentials across all workspaces | P0 |
| 3.3 | Factory | Share cross-project knowledge via notes | P1 |
| 3.4 | Factory | Provide observability via Factory Health Report | P2 |

### Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Onboarding time for new project | Under 10 minutes |
| Hook validation overhead per write | Under 5 seconds |
| Ship-readiness Docker timeout | 5 minutes maximum |
| Note archival threshold | 90 days without PINNED tag |
| Meta-agent suggestion threshold | 2+ feedback items |
| Language compliance | Zero violent, trauma, or weasel words |

## Architecture

See `docs/architecture/autonomous-code-factory.png` for the system diagram.

See `docs/architecture/reference-architecture.png` for the full AWS reference architecture (all services, data flows, and integration points).

### Diagrams

| Diagram | Scope | Generator |
|---------|-------|-----------|
| [Reference Architecture](reference-architecture.png) | All AWS services, end-to-end data flow | `scripts/generate_reference_architecture.py` |
| [Autonomous Code Factory](autonomous-code-factory.png) | Logical spine (7-step pipeline) | `scripts/generate_architecture_diagram.py` |
| [Hero Overview](planes/00-hero-overview.png) | 5 planes as blocks | `scripts/generate_plane_diagrams.py` |
| [VSM Plane](planes/01-vsm-plane.png) | Git, ALM, isolation, delivery | `scripts/generate_plane_diagrams.py` |
| [FDE Plane](planes/02-fde-plane.png) | Autonomy, builder, pipeline | `scripts/generate_plane_diagrams.py` |
| [Context Plane](planes/03-context-plane.png) | Constraints, prompts, scope | `scripts/generate_plane_diagrams.py` |
| [Data Plane](planes/04-data-plane.png) | Router, queue, storage, events | `scripts/generate_plane_diagrams.py` |
| [Control Plane](planes/05-control-plane.png) | SDLC, DORA, safety, failure modes | `scripts/generate_plane_diagrams.py` |

### Components

| Component | Owned State | Responsibility |
|-----------|-------------|----------------|
| Spec Control Plane | `.kiro/specs/` | Stores work items, acceptance criteria, holdout scenarios |
| Hook Engine | `.kiro/hooks/` (17 hooks) | Gates execution at preToolUse, postToolUse, preTask, postTask, userTriggered |
| Steering Context | `.kiro/steering/` + `~/.kiro/steering/` | Provides project-specific and universal context to the agent |
| Notes System | `.kiro/notes/` + `~/.kiro/notes/shared/` | Persists cross-session knowledge with verification status |
| Meta System | `.kiro/meta/` | Stores human feedback and prompt refinement history |
| MCP Integration | `.kiro/settings/mcp.json` | Connects to GitHub, GitLab, Asana for ALM operations |
| Task Templates | `docs/templates/` | Portable task schemas for GitHub Projects, Asana, GitLab Ultimate |
| ALM Validation | `scripts/validate-alm-api.sh` | Pre-flight API connectivity checks for all platforms |
| Onboarding Pipeline | `scripts/pre-flight-fde.sh` → `validate-deploy-fde.sh` → `code-factory-setup.sh` | Three-script E2E onboarding with linter mode |
| Cloud Infrastructure | `infra/terraform/` | Terraform IaC for ECR, ECS Fargate, Bedrock, S3, Secrets Manager, VPC |
| Strands Agent | `infra/docker/` | Headless agent container for ECS Fargate execution |
| Agent Orchestrator | `infra/docker/agents/orchestrator.py` | Full pipeline: Router → Scope → Autonomy → Gates → Plan → Execute |
| Agent Router | `infra/docker/agents/router.py` | Maps EventBridge events to data contracts |
| Agent Registry | `infra/docker/agents/registry.py` | Stores agent definitions, creates Strands Agent instances |
| Agent Builder | `infra/docker/agents/agent_builder.py` | Just-in-time agent provisioning from data contract |
| Constraint Extractor | `infra/docker/agents/constraint_extractor.py` | Two-pass constraint extraction (rule-based + opt-in LLM) |
| Scope Boundaries | `infra/docker/agents/scope_boundaries.py` | Rejects out-of-scope tasks, computes confidence level |
| Autonomy | `infra/docker/agents/autonomy.py` | Computes L1-L5 autonomy level, resolves pipeline gates |
| Execution Plan | `infra/docker/agents/execution_plan.py` | Resumable milestone tracking with filesystem persistence |
| SDLC Gates | `infra/docker/agents/sdlc_gates.py` | Inner loop (lint+typecheck+test+build) and outer loop gates with remediation |
| Pipeline Safety | `infra/docker/agents/pipeline_safety.py` | PR diff review (pattern + LLM), automatic rollback |
| DORA Metrics | `infra/docker/agents/dora_metrics.py` | 4 DORA + 5 factory metrics, domain segmentation, health report |
| Failure Modes | `infra/docker/agents/failure_modes.py` | Classifies WHY tasks fail (FM-01 through FM-99) |
| Project Isolation | `infra/docker/agents/project_isolation.py` | SaaS-kernel per-task isolation (S3, workspace, branch, correlation) |
| Prompt Registry | `infra/docker/agents/prompt_registry.py` | Versioned prompt storage with SHA-256 hash integrity |
| Task Queue | `infra/docker/agents/task_queue.py` | DynamoDB-backed DAG dependency resolution |
| Agent Lifecycle | `infra/docker/agents/lifecycle.py` | Instance tracking through CREATED → RUNNING → COMPLETED |
| Agent Tools | `infra/docker/agents/tools.py` | 8 @tool functions including observability (read_factory_metrics, read_factory_health) |
| Agent Prompts | `infra/docker/agents/prompts.py` | FDE system prompts for 3 agent roles |
| Doc Gardening | `infra/docker/agents/doc_gardening.py` | Automated documentation drift detection (5 checks) |
| Golden Principles | `infra/docker/agents/golden_principles.py` | Mechanical code quality invariants (5 principles) |
| Repo Onboarding Agent | `infra/docker/agents/onboarding/` (13 modules), `catalogs/{owner}/{repo}/catalog.db` (S3) | Phase 0: Scans repository structure (Magika + tree-sitter), infers patterns (Haiku), persists SQLite catalog, generates project-specific FDE steering |
| IAM Validator | `scripts/validate-aws-iam.py` | Per-service AWS IAM permission checks |
| Provision Script | `scripts/provision-workspace.sh` | Legacy manual onboarding (--global / --project) |

### Information Flow

| From | To | Data |
|------|----|------|
| Staff Engineer | Spec Control Plane | NLSpec with BDD scenarios |
| Spec Control Plane | Hook Engine (DoR) | Spec readiness check |
| Hook Engine | Agent | Gate decisions (proceed/block/modify) |
| Agent | CI/CD | Code push to feature branch |
| CI/CD | Hook Engine (Circuit Breaker) | Build/test results |
| Agent | Notes System | Hindsight notes |
| Agent | MCP Integration | ALM updates, MR creation |
| Meta System | Hook Engine | Prompt improvement suggestions |
| Staff Engineer | Repo Onboarding Agent | Trigger onboarding (EventBridge/hook) |
| Repo Onboarding Agent | S3 Artifacts | SQLite catalog + steering draft |
| Repo Onboarding Agent | FDE Intake (Phase 2) | tech_stack, level_patterns, module_context |

## Key Design Decisions

See `docs/adr/` for detailed Architecture Decision Records:
- ADR-001: Synaptic Engineering Foundation
- ADR-002: Spec as Control Plane
- ADR-003: Agentic TDD as Halting Condition
- ADR-004: Circuit Breaker for Error Classification
- ADR-005: Multi-Workspace Factory Topology
- ADR-006: Enterprise ALM Integration via MCP
- ADR-007: Cross-Session Learning via Notes
- ADR-008: Multi-Platform Project Tooling (GitHub Projects, Asana, GitLab Ultimate)
- ADR-009: AWS Cloud Infrastructure for Headless Agent Execution
- ADR-010: Data Contract for Task Input
- ADR-011: Multi-Cloud Adapter YAGNI
- ADR-012: Adversarial Review — Over-Engineering and Gaps
- ADR-013: Enterprise-Grade Autonomy and Observability
- ADR-014: Secret Isolation and DAG Parallelism
- ADR-015: Repo Onboarding Agent — Phase 0 Codebase Reasoning
- ADR-016: Ephemeral Catalog and Data Residency for Regulated Environments
- ADR-017: React Portal for Factory Observability UX

## Testing Design

| Scope | Command | Coverage |
|-------|---------|----------|
| Protocol E2E | `python3 -m pytest tests/test_fde_e2e_protocol.py` | All 17 hooks, steerings, design doc coherence |
| Quality Threshold | `python3 -m pytest tests/test_fde_quality_threshold.py` | Bare vs FDE response quality comparison |
| Pipeline Data Travel | `python3 -m pytest tests/test_pipeline_data_travel.py` | 7 cross-module contract tests (E1→E5 data flows) |
| Orchestrator E2E | `python3 -m pytest tests/test_orchestrator_e2e.py` | Full pipeline wiring with real EventBridge events |
| Execution Plans | `python3 -m pytest tests/test_execution_plans.py` | Resumable milestone tracking, filesystem persistence |
| Doc Gardening | `python3 -m pytest tests/test_doc_gardening.py` | Automated drift detection (5 checks) |
| Golden Principles | `python3 -m pytest tests/test_golden_principles.py` | Mechanical code quality invariants |
| Lint Remediation | `python3 -m pytest tests/test_lint_remediation.py` | Custom linters with remediation messages |
| PR LLM Review | `python3 -m pytest tests/test_pr_llm_review.py` | Agent-to-agent PR review (pattern + LLM) |
| Observability Tools | `python3 -m pytest tests/test_observability_tools.py` | Factory metrics and health report tools |
| Autonomy Level | `python3 -m pytest tests/test_autonomy_level.py` | L1-L5 autonomy computation |
| Failure Modes | `python3 -m pytest tests/test_failure_mode_taxonomy.py` | FM-01 through FM-99 classification |
| DORA Metrics | `python3 -m pytest tests/test_domain_segmented_metrics.py` | 4 DORA + 5 factory metrics |
| Scope Boundaries | `python3 -m pytest tests/test_scope_boundaries.py` | Out-of-scope rejection, confidence levels |
| Language Lint | `python3 scripts/lint_language.py` | Violent, trauma, weasel word detection |
| Full Suite | `python3 -m pytest tests/ -v` | All 171 tests across 15 test files |

## Open Questions

1. How to handle inter-workspace dependency validation at scale (currently manual via interface contracts)
2. ~~When to introduce Strands SDK for parallel agent orchestration~~ — **Resolved**: Strands SDK deployed in `infra/docker/agents/` (2026-05-05). Agent registry, builder, and orchestrator use Strands Agent instances.
3. How to measure ROI of the factory compared to traditional development
4. When to promote `fde-doc-gardening` from `userTriggered` to `postTaskExecution` (COE-012 recurrence suggests now)

## References

- Blueprint: `docs/blueprint/fde-blueprint-design.md`
- Adoption Guide: `docs/guides/fde-adoption-guide.md`
- Hook Deploy Guide: `docs/blueprint/fde-hooks-deploy-guide.md`
