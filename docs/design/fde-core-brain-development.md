# FDE Core Brain Development — Integrated Implementation Plan

> Status: **Ready for Implementation**
> Date: 2026-05-08
> Sources: `fde-brain-simulation-design.md` + `distributed-squad-execution.md` + `benchmarking-fde-analysis.md` + `dora-2025-code-factory-analysis.md`
> Purpose: Single source of truth for the next implementation wave. Converges brain sim + distributed execution + benchmarking gaps + DORA 2025 strategic findings into a deployment-ready plan.
> Governance: Changes require Staff SWE approval.

---

## 1. Executive Summary

This document merges four complementary inputs into a single coherent, deployment-ready implementation plan:

- **Brain Simulation Ecosystem** — elevates FDE from simulation (correct outputs) to emulation (causal mechanism replication) via fidelity scoring, meta-cognition, hierarchical memory, knowledge governance, and perturbation testing.
- **Distributed Squad Execution** — replaces monolithic sequential execution with parallel ECS tasks, DynamoDB-backed shared context, EFS workspace, and per-agent observability.
- **Benchmarking Gap Analysis** — identifies weaknesses and opportunities from comparative analysis against AWS AI-DLC Platform. Scoped as optional add-on integrations, not mandatory dependencies.
- **DORA 2025 Strategic Alignment** — integrates the 7-capability AI model, speed-stability paradox mitigations, user-centric focus gap, and anti-instability feedback loops into the factory's core measurement and governance systems.

### Architectural Principles (Post-Convergence)

1. **The Code Factory is self-contained.** It receives work items from any board (GitHub Projects, GitLab, Asana, Jira) and delivers PRs. No IDE coupling. No external platform dependency.
2. **Kiro is an add-on.** The spec-driven development workflow in Kiro complements the factory by producing well-structured specs. But the factory operates from board items, not from Kiro sessions.
3. **AWS AI-DLC is an add-on.** The inception-phase integration is available for Staff Engineers who want AI-generated requirements/design. It is not in the critical path.
4. **DORA 2025 is the strategic compass.** The 7-capability model defines what "mature" means. The speed-stability paradox defines what we must prevent. User-centric focus defines what we must add.

---

## 2. Implementation Contract — Strict Execution Order

> **This section is the contract.** The engineer follows this index top-to-bottom. Each activity has a sequence number, the exact artifact it creates or modifies, the type of change, and what must be completed before it can start. No activity may begin until its prerequisites show ✅ in the tracking column.

### Wave 1: Distributed Infrastructure + DORA Foundation

| Seq | Activity | Artifact (path) | Change Type | Depends On | Tracking |
|-----|----------|-----------------|-------------|------------|----------|
| 1.01 | Create Terraform EFS module | `infra/terraform/modules/efs/main.tf` | CREATE | Pre-flight checks | ✅ |
| 1.02 | Create EFS security group | `infra/terraform/modules/efs/sg.tf` | CREATE | 1.01 | ✅ |
| 1.03 | Create DynamoDB table: fde-dev-scd | `infra/terraform/modules/dynamodb/scd.tf` | CREATE | Pre-flight checks | ✅ |
| 1.04 | Create DynamoDB table: fde-dev-context-hierarchy | `infra/terraform/modules/dynamodb/context_hierarchy.tf` | CREATE | Pre-flight checks | ✅ |
| 1.05 | Create DynamoDB table: fde-dev-metrics | `infra/terraform/modules/dynamodb/metrics.tf` | CREATE | Pre-flight checks | ✅ |
| 1.06 | Create DynamoDB table: fde-dev-memory | `infra/terraform/modules/dynamodb/memory.tf` | CREATE | Pre-flight checks | ✅ |
| 1.07 | Create DynamoDB table: fde-dev-organism | `infra/terraform/modules/dynamodb/organism.tf` | CREATE | Pre-flight checks | ✅ |
| 1.08 | Create DynamoDB table: fde-dev-knowledge | `infra/terraform/modules/dynamodb/knowledge.tf` | CREATE | Pre-flight checks | ✅ |
| 1.09 | Create parametrized Agent ECS Task Definition | `infra/terraform/modules/ecs/agent_task_def.tf` | CREATE | 1.01, 1.03 | ✅ |
| 1.10 | Create Orchestrator ECS Task Definition | `infra/terraform/modules/ecs/orchestrator_task_def.tf` | CREATE | 1.09 | ✅ |
| 1.11 | Implement distributed_orchestrator.py | `src/core/orchestration/distributed_orchestrator.py` | CREATE | 1.10 | ✅ |
| 1.12 | Implement agent_runner.py | `src/core/orchestration/agent_runner.py` | CREATE | 1.09 | ✅ |
| 1.13 | Implement cost_tracker.py | `src/core/metrics/cost_tracker.py` | CREATE | 1.05 | ✅ |
| 1.14 | Update dora_metrics.py (autonomy_level dimension) | `src/core/metrics/dora_metrics.py` | MODIFY | 1.05 | ✅ |
| 1.15 | Implement verification_metrics.py | `src/core/metrics/verification_metrics.py` | CREATE | 1.05 | ✅ |
| 1.16 | Implement vsm_tracker.py | `src/core/metrics/vsm_tracker.py` | CREATE | 1.05 | ✅ |
| 1.17 | Implement anti_instability_loop.py | `src/core/governance/anti_instability_loop.py` | CREATE | 1.14 | ✅ |
| 1.18 | Create starter profile | `.kiro/profiles/starter.json` | CREATE | None | ✅ |
| 1.19 | Create standard profile | `.kiro/profiles/standard.json` | CREATE | 1.18 | ✅ |
| 1.20 | Create full profile | `.kiro/profiles/full.json` | CREATE | 1.19 | ✅ |
| 1.21 | Write quickstart guide | `docs/quickstart.md` | CREATE | 1.18 | ✅ |
| 1.22 | Write AI stance document (DORA C1 + O15 + O21) | `docs/operations/ai-stance.md` | CREATE | None | ✅ |
| 1.23 | Write feature flags documentation | `docs/feature-flags.md` | CREATE | 1.13-1.17 | ✅ |
| 1.24 | Implement gate_feedback_formatter.py (O19 P0) | `src/core/governance/gate_feedback_formatter.py` | CREATE | None | ✅ |
| 1.25 | Update all hook prompts (structured feedback output) | `.kiro/hooks/*.kiro.hook` | MODIFY | 1.24 | ✅ |
| 1.26 | Implement net_friction_calculator.py (O14) | `src/core/metrics/net_friction_calculator.py` | CREATE | 1.05 | ✅ |
| 1.27 | Implement trust_metrics.py (O17) | `src/core/metrics/trust_metrics.py` | CREATE | 1.05 | ✅ |
| 1.28 | Implement learning_curve_tracker.py (O23) | `src/core/metrics/learning_curve_tracker.py` | CREATE | 1.05 | ✅ |
| 1.29 | Terraform apply + smoke test | `infra/terraform/` (all modules) | DEPLOY | 1.01-1.10 | ✅ |
| 1.30 | Integration test: orchestrator dispatches agent | `tests/integration/test_distributed_orchestration.py` | CREATE | 1.11, 1.12, 1.29 | ✅ |
| 1.31 | Integration test: gate feedback format | `tests/integration/test_gate_feedback.py` | CREATE | 1.24, 1.25 | ✅ |

### Wave 2: Brain Sim Core

| Seq | Activity | Artifact (path) | Change Type | Depends On | Tracking |
|-----|----------|-----------------|-------------|------------|----------|
| 2.01 | Implement fidelity_score.py | `src/core/brain_sim/fidelity_score.py` | CREATE | 1.05 (metrics table) | ✅ |
| 2.02 | Implement emulation_classifier.py | `src/core/brain_sim/emulation_classifier.py` | CREATE | 2.01 | ✅ |
| 2.03 | Implement context_hierarchy.py | `src/core/brain_sim/context_hierarchy.py` | CREATE | 1.04 (context-hierarchy table) | ✅ |
| 2.04 | Implement organism_ladder.py | `src/core/brain_sim/organism_ladder.py` | CREATE | 1.07 (organism table) | ✅ |
| 2.05 | Implement brain_sim_metrics.py | `src/core/brain_sim/brain_sim_metrics.py` | CREATE | 2.01, 2.02 | ✅ |
| 2.06 | Create fde-fidelity-agent prompt | `src/agents/fidelity/prompt.md` | CREATE | 2.01-2.05 | ✅ |
| 2.07 | Create fde-fidelity-agent ECS task def | `infra/terraform/modules/ecs/fidelity_agent_task_def.tf` | CREATE | 2.06, 1.09 | ✅ |
| 2.08 | Implement user_value_validator.py (DORA C6) | `src/core/governance/user_value_validator.py` | CREATE | None | ✅ |
| 2.09 | Update DoR gate hook (user value field) | `.kiro/hooks/fde-dor-gate.kiro.hook` | MODIFY | 2.08 | ✅ |
| 2.10 | Update DoD gate hook (user story completion) | `.kiro/hooks/fde-dod-gate.kiro.hook` | MODIFY | 2.08 | ✅ |
| 2.11 | Integration test: fidelity scoring pipeline | `tests/integration/test_fidelity_pipeline.py` | CREATE | 2.01-2.07 | ✅ |
| 2.12 | Integration test: user value validation | `tests/integration/test_user_value_gates.py` | CREATE | 2.08-2.10 | ✅ |

### Wave 3: Knowledge + Memory + Maturity

| Seq | Activity | Artifact (path) | Change Type | Depends On | Tracking |
|-----|----------|-----------------|-------------|------------|----------|
| 3.01 | Implement call_graph_extractor.py | `src/core/knowledge/call_graph_extractor.py` | CREATE | 1.01 (EFS) | ✅ |
| 3.02 | Implement description_generator.py | `src/core/knowledge/description_generator.py` | CREATE | 3.01 | ✅ |
| 3.03 | Implement vector_store.py | `src/core/knowledge/vector_store.py` | CREATE | 3.02 | ✅ |
| 3.04 | Implement query_api.py | `src/core/knowledge/query_api.py` | CREATE | 3.03 | ✅ |
| 3.05 | Implement knowledge_annotation.py | `src/core/knowledge/knowledge_annotation.py` | CREATE | 1.08 (knowledge table) | ✅ |
| 3.06 | Implement data_quality_scorer.py (DORA C2) | `src/core/knowledge/data_quality_scorer.py` | CREATE | 3.05 | ✅ |
| 3.07 | Implement perturbation_engine.py | `src/core/brain_sim/perturbation_engine.py` | CREATE | 1.01 (EFS) | ☐ |
| 3.08 | Implement behavioral_benchmark.py | `src/core/brain_sim/behavioral_benchmark.py` | CREATE | 1.01 (EFS), 2.01 | ☐ |
| 3.09 | Implement memory_manager.py (DynamoDB backend) | `src/core/memory/memory_manager.py` | CREATE | 1.06 (memory table) | ☐ |
| 3.10 | Implement semantic_store.py (Bedrock KB) | `src/core/memory/semantic_store.py` | CREATE | 3.09, 3.16 | ☐ |
| 3.11 | Implement context_engineer.py | `src/core/memory/context_engineer.py` | CREATE | 3.09, 3.10 | ☐ |
| 3.12 | Create memory migration script | `scripts/migrate_memory.py` | CREATE | 3.09 | ☐ |
| 3.13 | Implement system_maturity_scorer.py (DORA 7-cap) | `src/core/governance/system_maturity_scorer.py` | CREATE | 1.05 (metrics table) | ☐ |
| 3.14 | Implement gate_optimizer.py | `src/core/governance/gate_optimizer.py` | CREATE | 1.05 (metrics table) | ☐ |
| 3.15 | Update repo_onboarding_agent (maturity + archetype) | `src/agents/onboarding/repo_onboarding_agent.py` | MODIFY | 3.13 | ☐ |
| 3.16 | Create Bedrock KB Terraform module | `infra/terraform/modules/bedrock_kb/main.tf` | CREATE | Pre-flight (model access) | ☐ |
| 3.17 | Terraform apply Bedrock KB | `infra/terraform/modules/bedrock_kb/` | DEPLOY | 3.16 | ☐ |
| 3.18 | Run memory migration | `scripts/migrate_memory.py` (execute) | EXECUTE | 3.12, 3.17 | ☐ |
| 3.19 | Implement happy_time_metric.py (O18) | `src/core/metrics/happy_time_metric.py` | CREATE | 1.16 (vsm_tracker) | ☐ |
| 3.20 | Implement unified gate output schema (O20) | All hook prompts + `src/core/governance/gate_output_schema.py` | CREATE+MODIFY | 1.24 | ☐ |
| 3.21 | Write training guide: effective-specs.md (O22) | `docs/training/effective-specs.md` | CREATE | None | ☐ |
| 3.22 | Write training guide: understanding-gates.md (O22) | `docs/training/understanding-gates.md` | CREATE | 1.24 | ☐ |
| 3.23 | Write training: onboarding-checklist.md (O22) | `docs/training/onboarding-checklist.md` | CREATE | 3.21, 3.22 | ☐ |
| 3.24 | Add learning_mode to Squad Manifest schema (O16) | `src/core/orchestration/squad_manifest.py` | MODIFY | 2.06 | ☐ |
| 3.25 | Integration test: knowledge pipeline | `tests/integration/test_knowledge_pipeline.py` | CREATE | 3.01-3.06 | ☐ |
| 3.26 | Integration test: memory recall | `tests/integration/test_memory_recall.py` | CREATE | 3.09-3.11, 3.18 | ☐ |
| 3.27 | Integration test: maturity scoring | `tests/integration/test_maturity_scorer.py` | CREATE | 3.13, 3.15 | ☐ |

### Wave 4: Real-time Infrastructure + Portal

| Seq | Activity | Artifact (path) | Change Type | Depends On | Tracking |
|-----|----------|-----------------|-------------|------------|----------|
| 4.01 | Create API Gateway WebSocket Terraform | `infra/terraform/modules/apigw_ws/main.tf` | CREATE | 1.24 (Wave 1 deployed) | ☐ |
| 4.02 | Implement ws_handler.py (Lambda) | `src/api/ws_handler.py` | CREATE | 4.01 | ☐ |
| 4.03 | Implement human_input_tool.py | `src/tools/human_input_tool.py` | CREATE | 4.02 | ☐ |
| 4.04 | Update autonomy.py (L2/L3 gating for HITL) | `src/core/autonomy.py` | MODIFY | 4.03 | ☐ |
| 4.05 | Implement events.py (streaming event types) | `src/api/events.py` | CREATE | 4.02 | ☐ |
| 4.06 | Terraform apply WebSocket API | `infra/terraform/modules/apigw_ws/` | DEPLOY | 4.01, 4.02 | ☐ |
| 4.07 | Implement Portal: LiveTimeline.tsx | `infra/portal-src/components/LiveTimeline.tsx` | CREATE | 4.05, 4.06 | ☐ |
| 4.08 | Implement Portal: HumanInputCard.tsx | `infra/portal-src/components/HumanInputCard.tsx` | CREATE | 4.03, 4.06 | ☐ |
| 4.09 | Implement Portal: CostCard.tsx | `infra/portal-src/components/CostCard.tsx` | CREATE | 1.13 | ☐ |
| 4.10 | Implement Portal: DoraCard.tsx (per-level) | `infra/portal-src/components/DoraCard.tsx` | CREATE | 1.14 | ☐ |
| 4.11 | Implement Portal: ValueStreamCard.tsx | `infra/portal-src/components/ValueStreamCard.tsx` | CREATE | 1.16 | ☐ |
| 4.12 | Implement Portal: MaturityRadar.tsx | `infra/portal-src/components/MaturityRadar.tsx` | CREATE | 3.13 | ☐ |
| 4.13 | Implement Portal: DataQualityCard.tsx | `infra/portal-src/components/DataQualityCard.tsx` | CREATE | 3.06 | ☐ |
| 4.14 | Implement Portal: SquadExecutionCard.tsx | `infra/portal-src/components/SquadExecutionCard.tsx` | CREATE | 1.11 | ☐ |
| 4.15 | Implement Portal: BrainSimCard.tsx | `infra/portal-src/components/BrainSimCard.tsx` | CREATE | 2.05 | ☐ |
| 4.16 | Implement Portal: GateFeedbackCard.tsx (O19) | `infra/portal-src/components/GateFeedbackCard.tsx` | CREATE | 1.24 | ☐ |
| 4.17 | Implement Portal: NetFrictionCard.tsx (O14) | `infra/portal-src/components/NetFrictionCard.tsx` | CREATE | 1.26 | ☐ |
| 4.18 | Implement Portal: TrustCard.tsx (O17) | `infra/portal-src/components/TrustCard.tsx` | CREATE | 1.27 | ☐ |
| 4.19 | Implement Portal: GateHistoryCard.tsx (O20) | `infra/portal-src/components/GateHistoryCard.tsx` | CREATE | 3.20 | ☐ |
| 4.20 | Implement Portal: PersonaRouter.tsx | `infra/portal-src/components/PersonaRouter.tsx` | CREATE | 4.07-4.19 | ☐ |
| 4.21 | Integration test: WebSocket HITL flow | `tests/integration/test_hitl_websocket.py` | CREATE | 4.03, 4.04, 4.06 | ☐ |
| 4.22 | Integration test: streaming events | `tests/integration/test_streaming_events.py` | CREATE | 4.05, 4.07 | ☐ |
| 4.23 | Portal E2E test: all cards render | `tests/portal/test_portal_cards.py` | CREATE | 4.07-4.20 | ☐ |

### Wave 5: Add-Ons (Independent — Staff Engineer Decision)

| Seq | Activity | Artifact (path) | Change Type | Depends On | Tracking |
|-----|----------|-----------------|-------------|------------|----------|
| 5.01 | Implement aidlc_adapter.py | `src/integrations/aidlc/aidlc_adapter.py` | CREATE | None (reads S3) | ☐ |
| 5.02 | Write AI-DLC integration guide | `docs/integration/aidlc-handoff.md` | CREATE | 5.01 | ☐ |
| 5.03 | Implement atlassian_mcp_proxy.py | `src/integrations/atlassian/atlassian_mcp_proxy.py` | CREATE | None | ☐ |
| 5.04 | Implement Atlassian OAuth auth.py | `src/integrations/atlassian/auth.py` | CREATE | 5.03 | ☐ |
| 5.05 | Create Atlassian Lambda Terraform | `infra/terraform/modules/atlassian/main.tf` | CREATE | 5.03, 5.04 | ☐ |
| 5.06 | Write Atlassian setup guide | `docs/integration/atlassian-setup.md` | CREATE | 5.05 | ☐ |
| 5.07 | Integration test: AI-DLC adapter | `tests/integration/test_aidlc_adapter.py` | CREATE | 5.01 | ☐ |
| 5.08 | Integration test: Atlassian proxy | `tests/integration/test_atlassian_proxy.py` | CREATE | 5.03, 5.04 | ☐ |

### Execution Rules

1. **Sequential within wave**: Activities within a wave execute in sequence number order. No skipping.
2. **Parallel across waves**: Waves 2 and 3 may execute in parallel after Wave 1 completes (1.25 ✅). Wave 4 requires Wave 1 deployed (1.24 ✅). Wave 5 is independent.
3. **No activity starts without prerequisites**: The "Depends On" column is absolute. If a dependency shows ☐, the activity cannot begin.
4. **Each activity produces exactly one artifact**: The "Artifact (path)" column is the deliverable. The activity is not complete until that artifact exists and passes its acceptance criteria (defined in Sections 4-8).
5. **Integration tests gate wave completion**: A wave is not "done" until its integration tests pass. No proceeding to dependent waves without green tests.
6. **DEPLOY activities require Terraform plan review**: Activities marked DEPLOY require `terraform plan` output reviewed by Staff Engineer before `terraform apply`.
7. **MODIFY activities require diff review**: Activities that modify existing files require the engineer to read the current file, understand the change scope, and verify no regression.

---

## 3. Integration Analysis — Conflicts Resolved

### 2.1 Conflict: Orchestrator Role

| Brain Sim (original) | Distributed Squad | **Resolution** |
|---------------------|-------------------|----------------|
| Orchestrator executes fidelity_score + emulation_classifier + context_hierarchy post-task | Orchestrator is a 512MB lightweight dispatcher | **Fidelity computation runs as a dedicated completion-stage agent** (`fde-fidelity-agent`) in the last stage of the Squad Manifest. It reads SCD + test results from DynamoDB, computes scores, writes results back. The orchestrator remains thin. |

### 2.2 Conflict: Agent Builder vs ECS Task Definitions

| Brain Sim (original) | Distributed Squad | **Resolution** |
|---------------------|-------------------|----------------|
| Modifies `agent_builder.py` to accept organism + knowledge annotations | Replaces agent_builder with parametrized ECS RunTask | **Organism classification and knowledge annotations feed into the Squad Manifest** produced by `task-intake-eval-agent`. The manifest includes `organism_level` and `knowledge_context` fields. ECS task definitions consume these as environment variables. No `agent_builder.py` modification needed. |

### 2.3 Conflict: Context Hierarchy Persistence

| Brain Sim (original) | Distributed Squad | **Resolution** |
|---------------------|-------------------|----------------|
| Context Hierarchy persists L3-L5 to S3 | SCD uses DynamoDB; S3 for full outputs only | **Context Hierarchy uses DynamoDB** (table: `fde-dev-context-hierarchy`, PK: `project_id`, SK: `level#item_key`). Consistent with SCD pattern. S3 reserved for large artifacts (>400KB). |

### 2.4 Conflict: Knowledge Annotation vs Code Knowledge Base

| Brain Sim | Distributed Squad (Gap 1) | **Resolution** |
|-----------|--------------------------|----------------|
| Knowledge Annotation Layer: module to governing knowledge artifacts | Code KB: call graph to business descriptions to vector search | **Both coexist as separate concerns in unified catalog.db schema.** Knowledge Annotations answer "what governs this module?" (governance). Code KB answers "what does this code do in business terms?" (navigation). Same `catalog.db`, different tables: `knowledge_annotations` and `code_kb_entries`. Cross-references via `module` foreign key. |

---

## 4. Integration Analysis — Narrative Alignment

### 3.1 Where Brain Sim Logic Executes in Distributed Model

| Component | Execution Model | Rationale |
|-----------|----------------|-----------|
| `fidelity_score.py` | Inside `fde-fidelity-agent` (last stage, fast tier) | Needs test results + SCD. Lightweight computation. |
| `emulation_classifier.py` | Inside `fde-fidelity-agent` (same agent) | Depends on fidelity score. Same context. |
| `context_hierarchy.py` | DynamoDB-backed service, queried by orchestrator at dispatch | Orchestrator queries hierarchy to inject L1-L2 into SCD. |
| `knowledge_annotation.py` | Queried by `task-intake-eval-agent` during manifest creation | Annotations inform knowledge context per agent. |
| `perturbation_engine.py` | Inside `swe-adversarial-agent` or `swe-redteam-agent` | Perturbation is testing — belongs in adversarial agents. |
| `behavioral_benchmark.py` | Inside `fde-fidelity-agent` (post-execution validation) | Behavioral tests validate full pipeline output. |
| `organism_ladder.py` | Queried by `task-intake-eval-agent` during squad composition | Organism level determines squad size. |
| `brain_sim_metrics.py` | Inside `fde-fidelity-agent` (persists after scoring) | Metrics are side-effect of fidelity computation. |

### 3.2 SCD Integration with Context Hierarchy

| Mechanism | Scope | Persistence | Purpose |
|-----------|-------|-------------|---------|
| SCD | Intra-task (single pipeline execution) | DynamoDB, TTL 7 days | Pass context between agents within one task |
| Context Hierarchy | Cross-session (project lifetime) | DynamoDB, no TTL | Retain learned context across tasks and sessions |

**Integration point**: Orchestrator queries Context Hierarchy for L1-L2 items relevant to the task and injects them into SCD `context_enrichment` section before dispatching Stage 1.

### 3.3 Unified Observability Model (DORA-Aligned)

| Section | Cards | Source | DORA Capability |
|---------|-------|--------|-----------------|
| **Factory Health** | DORA 4 metrics (lead time, deploy freq, CFR, MTTR) + CFR per autonomy level + verification throughput | `dora_metrics.py` | C4, C5 |
| **Squad Execution** | Per-agent status, model tier, retry count, stage progress | Distributed Squad | C7 |
| **Brain Simulation** | Fidelity trend, emulation ratio, organism ladder, memory wall, knowledge coverage, perturbation coverage | Brain Sim | C2, C3 |
| **Cost & Efficiency** | Token usage per task, cost per gate, model tier distribution, gate-pass-rate | Bedrock usage metrics | Speed-stability |
| **Value Stream** | Idea→spec→impl→PR→merge→deploy timeline, wait-time identification | VSM integration | C6 |
| **System Maturity** | 7-capability radar chart, amplifier score per repo | DORA model scoring | All 7 |

---

## 5. DORA 2025 Convergence — Speed-Stability Paradox Resolution

> Source: `dora-2025-code-factory-analysis.md` — The central DORA thesis: AI is an amplifier, not a fix.

### 4.1 The Problem DORA Identifies

AI adoption correlates positively with throughput but negatively with stability. Teams that accelerate without governance create instability. The Code Factory's governance layer exists precisely to prevent this — but DORA reveals we must MEASURE the prevention, not just assume it works.

### 4.2 Speed-Stability Controls (Already Active)

| DORA Risk | Code Factory Control | Measurement (NEW) |
|-----------|---------------------|-------------------|
| Increased change volume → more failures | Inner loop gate (lint/test/build before PR) | Gate-pass-rate per autonomy level |
| AI-generated code deployed without review | Adversarial gate challenges every write | Adversarial-rejection-rate trend |
| Speed outpaces testing capacity | Test immutability hook prevents test weakening | Test-coverage-delta per task |
| No error classification when failures occur | Circuit breaker (CODE vs ENVIRONMENT) | Classification accuracy audit (monthly) |
| Instability not measured | DORA metrics collector (CFR + rework tracking) | CFR per autonomy level (NEW dimension) |
| Local optimization hides system-level issues | Pipeline validation (E1→E6 data travel) | Cross-module regression count |

### 4.3 Anti-Instability Feedback Loop (NEW — DORA A11)

When CFR rises above threshold, the factory automatically reduces autonomy level. This is the mechanical implementation of DORA's finding that "speed without stability is a trap."

| Trigger | Action | Reversibility |
|---------|--------|---------------|
| CFR > 15% over 7-day window for a given autonomy level | Reduce autonomy by 1 level (L5→L4, L4→L3) | Auto-restore after 14 days of CFR < 10% |
| CFR > 30% over 3-day window | Reduce autonomy by 2 levels + alert Staff Engineer | Manual restore only (requires review) |
| CFR = 0% over 30-day window at current level | Eligible for autonomy promotion (requires 3 consecutive clean windows) | N/A (promotion, not demotion) |

**Implementation**:

| Component | Location | What It Does |
|-----------|----------|--------------|
| `anti_instability_loop.py` | `src/core/governance/` | Reads CFR from DynamoDB metrics, computes 7-day rolling window per autonomy level, triggers level adjustment |
| DynamoDB: autonomy adjustments | Table `fde-dev-metrics`, SK: `autonomy_adjustment#{timestamp}` | Audit trail of all automatic adjustments |
| CloudWatch alarm | Terraform | Fires when any autonomy level is auto-reduced (visibility for Staff Engineer) |
| Restoration checker | Cron (EventBridge rule, daily) | Checks if 14-day clean window met, proposes restoration |

**Acceptance Criteria**:
- [ ] CFR computed per autonomy level with 7-day rolling window
- [ ] Auto-reduction triggers within 1 hour of threshold breach
- [ ] Audit trail shows reason, old level, new level, CFR data
- [ ] Manual override available (Staff Engineer can force level)
- [ ] Restoration is never automatic for >2-level reductions

### 4.4 CFR Per Autonomy Level Tracking (NEW — DORA A1)

Current `dora_metrics.py` tracks CFR globally. DORA's finding that instability varies by team maturity maps to our autonomy levels. We must correlate.

| Component | Location | What It Does |
|-----------|----------|--------------|
| `dora_metrics.py` update | `src/core/metrics/` | Add `autonomy_level` as dimension to all 4 DORA metrics (lead time, deploy freq, CFR, MTTR) |
| DynamoDB schema | Existing table, new SK pattern: `dora#{metric}#{autonomy_level}#{date}` | Per-level metric storage |
| Portal card update | `infra/portal-src/components/DoraCard.tsx` | Breakdown view: DORA metrics filterable by autonomy level |
| Calibration report | Weekly automated report | Compares CFR across levels. If L5 CFR > L3 CFR, calibration is wrong. |

**Acceptance Criteria**:
- [ ] All 4 DORA metrics tracked per autonomy level
- [ ] Portal shows level-filtered view
- [ ] Weekly calibration report generated automatically
- [ ] Anomaly detection: alert if higher autonomy produces worse stability

### 4.5 Verification Throughput Metric (NEW — DORA A2)

DORA identifies that AI shifts the bottleneck from writing code to verifying/reviewing code. Our branch evaluation agent may become the bottleneck as throughput increases.

| Component | Location | What It Does |
|-----------|----------|--------------|
| `verification_metrics.py` | `src/core/metrics/` | Tracks: time-in-review, review-rejection-rate, evaluation-agent-queue-depth, time-from-PR-to-merge |
| DynamoDB persistence | Existing metrics table, SK: `verification#{metric}#{date}` | Historical tracking |
| Bottleneck alert | CloudWatch | Fires when evaluation-agent-queue-depth > 5 or time-in-review > 2 hours |
| Scaling trigger | EventBridge rule | When queue-depth > 3 for >30min, spawn additional evaluation agent instance |

**Acceptance Criteria**:
- [ ] Time-in-review measured from PR creation to merge/reject decision
- [ ] Queue depth visible in portal
- [ ] Auto-scaling of evaluation capacity when bottleneck detected
- [ ] Historical trend shows whether verification is becoming the constraint

---

## 6. DORA 2025 Convergence — 7-Capability Model Integration

### 5.1 Capability Assessment (Current State)

| # | DORA Capability | Code Factory Status | Gap | Action |
|---|----------------|--------------------:|-----|--------|
| C1 | Clear and communicated AI stance | ✅ STRONG | None | A3: Consolidate into `docs/operations/ai-stance.md` |
| C2 | Healthy data ecosystems | ⚠️ PARTIAL | No quality scoring on knowledge artifacts | A5: Extend catalog.db with quality scores |
| C3 | AI-accessible internal data | ⚠️ PARTIAL | No persistent semantic index | A6: Bedrock KB for cross-session semantic search |
| C4 | Strong version control practices | ✅ STRONG | None | Already exceeds (branch eval, auto-merge) |
| C5 | Working in small batches | ✅ STRONG | None | Already exceeds (execution plans, scope boundaries) |
| C6 | User-centric focus | ❌ GAP | Spec conformance ≠ user value | A4+A12: User value in DoR/DoD gates |
| C7 | Quality internal platforms | ✅ STRONG | None | Already exceeds (18 hooks, 5 planes) |

### 5.2 C6 Resolution: User-Centric Focus in Quality Gates

DORA's most critical finding for us: **"In the absence of user-centric focus, AI adoption can have a NEGATIVE impact on team performance."** We optimize for spec fidelity when we should also optimize for user value delivery.

| Component | Location | What It Does |
|-----------|----------|--------------|
| DoR gate update | `.kiro/hooks/fde-dor-gate.kiro.hook` prompt update | Adds validation: "Does this spec identify the end-user and the value delivered? Reject specs without user context." |
| `user_value_validator.py` | `src/core/governance/` | Parses spec for user story format (As a [user], I want [action], so that [value]). Scores completeness 0-100. |
| DoD gate update | `.kiro/hooks/fde-dod-gate.kiro.hook` prompt update | Adds validation: "Does the implementation serve the stated user need? Is the user story fulfilled, not just the technical spec?" |
| Squad Manifest field | `user_value_statement` (required field) | Every task must carry a user value statement. Intake agent extracts from spec or board item description. |

**Acceptance Criteria**:
- [ ] DoR rejects specs without identifiable user value (score < 40)
- [ ] DoD validates user story completion, not just technical conformance
- [ ] Squad Manifest includes `user_value_statement` for every task
- [ ] Metrics track: user-value-score distribution across tasks

### 5.3 C2 Resolution: Data Ecosystem Quality Scoring

| Component | Location | What It Does |
|-----------|----------|--------------|
| `data_quality_scorer.py` | `src/core/knowledge/` | Scores each knowledge artifact on: freshness (last update), completeness (coverage vs corpus), consistency (cross-reference integrity), accuracy (validated against source of truth) |
| catalog.db extension | `knowledge_quality` table | Stores quality scores per artifact per assessment date |
| Freshness tracker | EventBridge rule (weekly) | Re-scores all knowledge artifacts. Alerts on staleness (>90 days without validation). |
| Portal card | `infra/portal-src/components/DataQualityCard.tsx` | Shows knowledge artifact health: green/yellow/red per artifact |

**Acceptance Criteria**:
- [ ] All 6 knowledge artifact types scored weekly
- [ ] Staleness alert fires for artifacts >90 days without update
- [ ] Quality score visible in portal per artifact
- [ ] Trend shows improvement over time (or flags degradation)

### 5.4 C3 Resolution: Persistent Semantic Index

| Component | Location | What It Does |
|-----------|----------|--------------|
| `memory_manager.py` | `src/core/memory/` | Unified API: `store()`, `recall()`, `consolidate()`, `forget()` |
| Structured memory | DynamoDB table `fde-dev-memory` (PK: `project_id`, SK: `memory_type#timestamp`) | Fast lookup for recent decisions, task outcomes, error patterns |
| Semantic memory | Bedrock Knowledge Base with OpenSearch Serverless vector store | Semantic search over past decisions, ADRs, knowledge artifacts, cross-session context |
| Context engineering | `src/core/memory/context_engineer.py` | Per task-type, retrieves relevant context automatically: ADRs for architecture tasks, test contracts for testing tasks, corpus for knowledge tasks |
| Migration script | `scripts/migrate_memory.py` | Converts existing `cross_session_notes/` to new memory format |

**Acceptance Criteria**:
- [ ] `recall("how did we handle auth in project X?")` returns relevant past decisions in <500ms
- [ ] Context engineering injects relevant ADRs/contracts per task type without manual specification
- [ ] Consolidation runs weekly, merges redundant memories
- [ ] Fallback to DynamoDB-only if Bedrock KB unavailable (degraded, not broken)
- [ ] Existing notes migrated without data loss

### 5.5 System Maturity Scoring (DORA A10)

The factory should predict whether AI will amplify strengths or weaknesses for a given repo. Uses DORA's 7 capabilities as scoring dimensions.

| Component | Location | What It Does |
|-----------|----------|--------------|
| `system_maturity_scorer.py` | `src/core/governance/` | Scores a repo on all 7 DORA capabilities (0-100 each). Produces composite "amplifier readiness" score. |
| Phase 0 integration | `repo_onboarding_agent` update | During onboarding, runs maturity scorer. Score determines initial autonomy level recommendation. |
| Team archetype detection | Inside maturity scorer | Maps repo to one of DORA's 7 team archetypes based on git history (commit frequency, CFR patterns, rework rate). |
| Portal card | `infra/portal-src/components/MaturityRadar.tsx` | 7-axis radar chart showing capability scores per repo |

**Acceptance Criteria**:
- [ ] All 7 capabilities scored during Phase 0 onboarding
- [ ] Composite score maps to recommended autonomy level (score < 40 → max L2, score 40-70 → max L4, score > 70 → L5 eligible)
- [ ] Team archetype identified and logged
- [ ] Radar chart visible in portal per repo

---

## 7. DORA 2025 Convergence — Process Friction Prevention

### 6.1 The "Constrained by Process" Risk

DORA identifies a team archetype "constrained by process" — good capability but friction-heavy. This maps to our T6 threat: 4+ LLM calls per write (adversarial + DoR + DoD + pipeline validation). If governance overhead exceeds the instability it prevents, we become the problem.

**Resolution: Adaptive Gate Frequency**

| Component | Location | What It Does |
|-----------|----------|--------------|
| `gate_optimizer.py` | `src/core/governance/` | Monitors gate-pass-rate per pattern. If a pattern passes adversarial gate >98% over 30 days, marks it as "trusted pattern." |
| Fast path | Orchestrator logic | Trusted patterns at L5 skip adversarial gate (still run DoR + DoD + pipeline). Saves ~$0.01/write and ~3s latency. |
| Trust decay | Weekly cron | If a trusted pattern fails adversarial gate, immediately revoke trust. Require 30 new clean passes to re-trust. |
| Metrics | `time_in_gates` factory metric | Tracks total gate time per task. Alert if gate time > 20% of total task time. |

**Acceptance Criteria**:
- [ ] Gate-pass-rate tracked per pattern category
- [ ] Fast path activated only at L5 with >98% pass rate over 30 days
- [ ] Trust revocation is immediate on first failure
- [ ] Time-in-gates metric visible in portal
- [ ] Net effect: governance overhead < 15% of total task time for mature repos

### 6.2 Starter Profile (Adoption Simplification)

DORA's "quality internal platforms" capability (C7) requires that the platform be ACCESSIBLE, not just powerful. 18 hooks + 5 planes is overwhelming for new users.

| Profile | Hooks Included | Target Audience | DORA Archetype |
|---------|---------------|-----------------|----------------|
| **Starter** (6 hooks) | DoR, adversarial, DoD, pipeline-validation, test-immutability, circuit-breaker | New teams, "foundational challenges" archetype | Teams scoring < 40 on maturity |
| **Standard** (12 hooks) | Starter + fidelity-gate, emulation-check, scope-boundary, concurrency-guard, branch-eval, cost-tracker | Established teams, "balanced but plateaued" archetype | Teams scoring 40-70 |
| **Full** (18 hooks) | Standard + perturbation-reminder, mob-elaboration, alternative-exploration, knowledge-validation, anti-instability, gate-optimizer | High-performing teams, "harmonious high-achievers" archetype | Teams scoring > 70 |

| Component | Location | What It Does |
|-----------|----------|--------------|
| `.kiro/profiles/starter.json` | Profile definition | 6 essential hooks only |
| `.kiro/profiles/standard.json` | Profile definition | 12 hooks for established teams |
| `.kiro/profiles/full.json` | Profile definition | All 18 hooks |
| `make profile LEVEL=starter` | Makefile target | Activates selected profile |
| `docs/quickstart.md` | Documentation | Single-page "deploy in 15 minutes" guide |
| Phase 0 recommendation | `repo_onboarding_agent` | Maturity score → profile recommendation |

**Acceptance Criteria**:
- [ ] New user deploys starter profile in <15 minutes
- [ ] Starter profile passes factory smoke test
- [ ] Upgrade path: starter → standard → full is documented and reversible
- [ ] Phase 0 onboarding recommends profile based on maturity score

---

## 8. DORA 2025 Convergence — Deep Report Insights (142-Page Extraction)

> Source: `dora-2025-code-factory-analysis.md` Parts 9-11 — patterns extracted from full PDF that secondary sources missed.

### 8.1 O19 (P0): Clear Gate Feedback

DORA's #1 correlated platform capability is "clear feedback on tasks." Our gates must not just reject — they must explain WHY and WHAT to fix. "Adversarial gate rejected" is insufficient.

| Component | Location | What It Does |
|-----------|----------|--------------|
| `gate_feedback_formatter.py` | `src/core/governance/` | Transforms raw gate rejection into structured feedback: `{reason, violated_rule, suggestion, reference_artifact, severity}` |
| Gate output schema | All hook prompts updated | Every gate outputs structured JSON with `feedback_message` field (human-readable, actionable) |
| Portal rendering | `infra/portal-src/components/GateFeedbackCard.tsx` | Renders gate rejections with: what failed, why it matters, what to do next, link to relevant doc |
| Feedback quality metric | `src/core/metrics/` addition to existing metrics | Tracks: feedback-clarity-score (LLM-judged), time-to-resolution after rejection, repeat-rejection-rate |

**Acceptance Criteria**:
- [ ] Every gate rejection includes: reason, violated rule, actionable suggestion, reference artifact
- [ ] Portal renders feedback in human-readable format (not raw JSON)
- [ ] Repeat-rejection-rate < 10% (if same issue rejected twice, feedback was unclear)
- [ ] Time-to-resolution after rejection measurable and trending down

### 8.2 O14 (P1): Net Friction Measurement

DORA finding: "Friction doesn't vanish, it moves." Our gates add upstream friction but should reduce downstream friction (fewer incidents, less rework). We must measure NET friction across the full value stream.

| Component | Location | What It Does |
|-----------|----------|--------------|
| `net_friction_calculator.py` | `src/core/metrics/` | Computes: upstream_friction (gate time + rejection rework) vs downstream_friction (incidents + hotfixes + rework). Net = downstream_saved - upstream_cost. |
| Data sources | DynamoDB metrics table | Reads: time-in-gates, rejection-count, CFR, rework-rate, incident-count |
| Portal card | `infra/portal-src/components/NetFrictionCard.tsx` | Shows: "Gates saved X hours of downstream rework this month" with trend |
| Alert | CloudWatch | Fires when net_friction > 0 (gates costing more than they save) for 14-day window |

**Acceptance Criteria**:
- [ ] Net friction computed weekly per project
- [ ] Positive net friction (gates save more than they cost) for all projects at Standard/Full profile
- [ ] Alert fires if gates become net-negative (governance overhead exceeds value)
- [ ] Portal shows ROI of governance in hours saved

### 8.3 O15 (P1): Work Intensification Guardrail

DORA warning: "Perceived capacity gains from AI have invited higher expectations of work output." L5 autonomy means the factory handles more — it does NOT mean humans should take on more tasks.

| Component | Location | What It Does |
|-----------|----------|--------------|
| AI stance update | `docs/operations/ai-stance.md` | Explicit section: "Autonomy levels reduce human toil. They do NOT justify increased workload expectations." |
| Workload metric | `src/core/metrics/` addition | Tracks: tasks-per-developer-per-week. Alert if trending up >20% after autonomy promotion. |
| Governance boundary | DoR gate prompt update | If task volume per developer exceeds threshold, DoR gate warns: "Work intensification detected. Consider redistributing." |

**Acceptance Criteria**:
- [ ] AI stance document explicitly addresses work intensification
- [ ] Workload metric tracked per developer per week
- [ ] Alert fires when workload increases >20% post-autonomy-promotion
- [ ] DoR gate includes work intensification check

### 8.4 O17 (P1): Trust Metrics

DORA finding: 30% report little or no trust in AI-generated code. We must measure trust in factory outputs.

| Component | Location | What It Does |
|-----------|----------|--------------|
| `trust_metrics.py` | `src/core/metrics/` | Tracks: PR-acceptance-rate (factory PRs merged vs rejected), gate-override-rate, manual-intervention-rate, developer-satisfaction-survey (quarterly) |
| DynamoDB persistence | Existing metrics table, SK: `trust#{metric}#{date}` | Historical trust tracking |
| Portal card | `infra/portal-src/components/TrustCard.tsx` | Shows: acceptance rate trend, override frequency, trust score composite |

**Acceptance Criteria**:
- [ ] PR acceptance rate tracked (target: >90%)
- [ ] Gate override rate tracked (target: <5% — overrides should be rare)
- [ ] Quarterly developer satisfaction survey mechanism defined
- [ ] Trust score composite visible in portal

### 8.5 O21 (P1): Continuous AI Positioning

DORA introduces "Continuous AI" — AI as living part of the pipeline, perceiving events, operating autonomously yet collaboratively. Our factory IS this. We must position explicitly.

| Component | Location | What It Does |
|-----------|----------|--------------|
| Architecture documentation update | `docs/architecture/design-document.md` | New section: "Continuous AI Architecture" — maps factory to DORA's evolving mode |
| AI stance alignment | `docs/operations/ai-stance.md` | Section: "The factory operates as Continuous AI per DORA 2025 definition" |

**Acceptance Criteria**:
- [ ] Architecture doc explicitly maps to DORA's Continuous AI concept
- [ ] AI stance references DORA positioning

### 8.6 O23 (P1): Instability Learning Curve Compression

DORA finding: Instability has a LONGER learning curve than throughput (took teams "another year"). Our governance layer compresses this by making instability visible and preventable mechanically.

| Component | Location | What It Does |
|-----------|----------|--------------|
| `learning_curve_tracker.py` | `src/core/metrics/` | Tracks: days-to-stable (from first task to CFR < 10% sustained). Compares across projects. |
| Onboarding benchmark | Phase 0 output | Records initial CFR baseline. Measures time to reach stability threshold. |
| Portal card | Part of MaturityRadar.tsx | Shows: "Time to stability" per project with industry benchmark comparison |

**Acceptance Criteria**:
- [ ] Days-to-stable metric tracked per project
- [ ] Benchmark: factory-assisted projects reach stability in <30 days (vs DORA's "another year")
- [ ] Visible in maturity radar as "stability velocity" dimension

### 8.7 O16 (P2): Skill Development Mode

DORA warning (Matt Beane): "Default AI usage patterns block skill development for most devs." The factory must handle TOIL, not CRAFT.

| Component | Location | What It Does |
|-----------|----------|--------------|
| Learning mode flag | Squad Manifest field: `learning_mode: true/false` | When true, fidelity agent explains reasoning at each step (not just executes) |
| Explanation output | `fde-fidelity-agent` prompt variant | Produces: "I did X because Y. The alternative was Z but it fails because W." |
| Target audience | L1/L2 tasks assigned to junior developers | Intake agent detects junior assignment and suggests learning mode |

**Acceptance Criteria**:
- [ ] Learning mode produces explanation alongside implementation
- [ ] Explanations reference ADRs, patterns, and governance rules
- [ ] Junior developers report improved understanding (quarterly survey)

### 8.8 O18 (P2): "Happy Time" Metric

From Adidas case study: 50% increase in "Happy Time" — more coding, less administrative toil.

| Component | Location | What It Does |
|-----------|----------|--------------|
| `happy_time_metric.py` | `src/core/metrics/` | Tracks: ratio of creative-work-time (spec writing, architecture, code review) vs toil-time (waiting, fixing CI, manual deploys) |
| Data source | VSM tracker timestamps + gate timestamps | Creative = time in Stage 3 (implementation). Toil = time in gates + waiting + rework. |
| Portal card | Part of ValueStreamCard.tsx | Shows: "Happy Time ratio" with trend |

**Acceptance Criteria**:
- [ ] Happy Time ratio computed per task
- [ ] Target: >60% creative time / total time
- [ ] Trend visible in portal
- [ ] Alert if Happy Time drops below 40% for 7-day window

### 8.9 O20 (P2): Cohesive Platform Experience

DORA finding: "Users perceive platform as single entity." Our 18 hooks must feel cohesive, not like 18 separate friction points.

| Component | Location | What It Does |
|-----------|----------|--------------|
| Unified gate UX | All hook prompt outputs | Consistent output format across all gates: `{gate_name, status, feedback, next_action}` |
| Portal: unified gate view | `infra/portal-src/components/GateHistoryCard.tsx` | Single timeline showing all gate interactions for a task (not per-gate silos) |
| Naming convention | All hooks | Consistent naming: `fde-{category}-{action}` (e.g., `fde-quality-dor`, `fde-quality-dod`, `fde-safety-circuit-breaker`) |

**Acceptance Criteria**:
- [ ] All gates produce consistent output schema
- [ ] Portal shows unified gate timeline per task
- [ ] Developer perceives gates as "one system" not "18 separate checks"

### 8.10 O22 (P2): Training Program

From Booking.com case study: Training on effective context provision led to 30% increase in merge requests + higher job satisfaction.

| Component | Location | What It Does |
|-----------|----------|--------------|
| Training guide | `docs/training/effective-specs.md` | How to write specs that the factory executes well. Context provision patterns. |
| Training guide | `docs/training/understanding-gates.md` | What each gate checks, how to pass first time, common rejection patterns. |
| Onboarding checklist | `docs/training/onboarding-checklist.md` | New developer: read these 5 docs, run starter profile, complete 3 L1 tasks. |

**Acceptance Criteria**:
- [ ] Training materials cover: spec writing, gate understanding, context provision
- [ ] New developer completes onboarding in <1 day
- [ ] First-time gate pass rate improves after training (measurable via trust metrics)

---

## 9. Benchmarking Gap Convergence — Core Items (Decoupled from External Platforms)

### 7.1 Cost Visibility

| Component | Location | What It Does |
|-----------|----------|--------------|
| `cost_tracker.py` | `src/core/metrics/` | Intercepts Bedrock `invoke_model` responses, extracts `inputTokens` + `outputTokens`, computes cost per model tier |
| DynamoDB persistence | Existing metrics table, SK: `cost#agent_name#{date}` | Per-agent, per-task cost tracking |
| DORA integration | `dora_metrics.py` update | New metrics: `cost_per_task`, `cost_per_gate`, `model_tier_distribution` |
| Portal card | `infra/portal-src/components/CostCard.tsx` | Cost trend, cost per agent, model tier pie chart |
| Alert threshold | CloudWatch alarm | Fires if cost_per_task > $2.00 (configurable) |
| Gate cost optimization | `gate_optimizer.py` | Tracks cost per gate type. Identifies expensive gates for prompt optimization. |

**Acceptance Criteria**:
- [ ] Every Bedrock call tracked with token count + cost
- [ ] Portal shows cost breakdown per agent per task
- [ ] Alert fires when task exceeds threshold
- [ ] Historical cost trend visible (30-day rolling)
- [ ] Gate cost breakdown identifies optimization targets

### 7.2 Real-time HITL During Execution

| Component | Location | What It Does |
|-----------|----------|--------------|
| `human_input_tool.py` | `src/tools/` | Strands tool: blocks agent, sends question via WebSocket, waits for response (timeout: 5min) |
| WebSocket endpoint | API Gateway WebSocket API + Lambda handler | Real-time bidirectional communication |
| `ws_handler.py` | `src/api/` | Lambda: routes messages between portal and agent containers |
| Portal integration | `infra/portal-src/components/HumanInputCard.tsx` | Real-time notification: "Agent needs input" with inline response form |
| Autonomy gating | `src/core/autonomy.py` update | Tool only available at L2/L3. L4/L5 skip (best-effort inference). L1 always blocks. |
| Timeout behavior | `human_input_tool.py` | L2: abort on timeout. L3: proceed with inference + flag for review. |

**Acceptance Criteria**:
- [ ] Agent at L2 can ask clarifying question and receive answer in <2min
- [ ] Portal shows real-time notification within 1s of agent question
- [ ] Timeout at L3 produces reasonable inference (validated by adversarial gate)
- [ ] No HITL calls at L4/L5 (verified by integration test)
- [ ] WebSocket connection survives agent container restart (reconnect logic)

### 7.3 Streaming Dashboard

| Component | Location | What It Does |
|-----------|----------|--------------|
| WebSocket streaming | Reuses HITL WebSocket infrastructure | Same API Gateway endpoint |
| Event types | `src/api/events.py` | `gate_result`, `milestone_reached`, `agent_started`, `agent_completed`, `error_occurred`, `autonomy_adjusted` |
| Portal integration | `infra/portal-src/components/LiveTimeline.tsx` | Live execution timeline with auto-scroll |
| Reconnection | Portal client logic | Reconnects on disconnect, replays missed events from DynamoDB |

**Acceptance Criteria**:
- [ ] Gate results appear in portal within 2s of completion
- [ ] Timeline shows all stages with real-time progress
- [ ] Reconnection replays missed events correctly
- [ ] Works with 10+ concurrent task executions

### 7.4 Value Stream Mapping Visualization (DORA A7)

| Component | Location | What It Does |
|-----------|----------|--------------|
| `vsm_tracker.py` | `src/core/metrics/` | Tracks timestamps at each stage boundary: idea→spec→intake→implementation→review→PR→merge→deploy |
| Wait-time identification | Inside vsm_tracker | Computes time-in-queue between stages. Identifies where work waits. |
| Portal card | `infra/portal-src/components/ValueStreamCard.tsx` | Horizontal timeline showing flow + wait times. Red highlights for bottlenecks. |
| DORA alignment | Maps to lead time decomposition | Shows which portion of lead time is active work vs waiting |

**Acceptance Criteria**:
- [ ] All stage transitions timestamped
- [ ] Wait-time computed between every stage pair
- [ ] Portal shows flow efficiency (active time / total time)
- [ ] Bottleneck identification: highlights stage with highest wait-time

---

## 10. Add-On Integrations (Optional — Staff Engineer Decision)

> These integrations complement the Code Factory but are NOT in the critical path. The factory operates fully without them. Each is feature-flagged and independently deployable.

### 8.1 ADD-ON: Kiro IDE Integration

**What it provides**: Spec-driven development workflow in the IDE. Produces well-structured specs that feed the factory's intake.

**Relationship to factory**: Kiro produces specs → specs become board items → factory consumes board items. The factory never calls Kiro APIs. Kiro never calls factory APIs. The connection is the board item.

| Component | Location | What It Does |
|-----------|----------|--------------|
| Steering files | `.kiro/steering/` | Guide spec creation in Kiro IDE sessions |
| Hook definitions | `.kiro/hooks/` | Enforce quality during IDE-based development |
| Profile definitions | `.kiro/profiles/` | Starter/standard/full hook configurations |
| Spec templates | `.kiro/specs/` | Structured spec format that maps to factory intake |

**Feature flag**: N/A — Kiro files are passive. They exist in the repo but only activate when a developer uses Kiro IDE. Zero cost if unused.

**Decoupling guarantee**: If Kiro changes its hook API or steering format, only the `.kiro/` directory is affected. No factory source code depends on Kiro runtime.

### 8.2 ADD-ON: AWS AI-DLC Inception Integration

**What it provides**: AI-generated requirements, design documents, and user stories from a raw project description. Feeds the factory's spec intake.

**Relationship to factory**: AI-DLC produces artifacts (S3) → adapter converts to factory spec format → spec becomes board item → factory consumes. One-directional. Factory never depends on AI-DLC availability.

| Component | Location | What It Does |
|-----------|----------|--------------|
| `aidlc_adapter.py` | `src/integrations/aidlc/` | Reads AI-DLC SharedState artifacts from S3 prefix, converts to factory spec format |
| S3 prefix convention | `s3://{bucket}/aidlc-output/{project_id}/` | Where AI-DLC deposits its artifacts |
| Schema validator | Inside adapter | Validates AI-DLC artifact schema version. Rejects unknown versions with clear error. |
| Feature flag | `ENABLE_AIDLC_ADAPTER=false` | Disabled by default. Staff Engineer enables per project. |

**Acceptance Criteria**:
- [ ] Adapter converts AI-DLC SharedState → factory spec in <5s
- [ ] Unknown schema versions rejected with actionable error message
- [ ] Factory operates normally when adapter is disabled (default)
- [ ] No factory module imports from `src/integrations/aidlc/` except the adapter entry point

### 8.3 ADD-ON: Atlassian Integration

**What it provides**: Confluence page reading (specs as input) and Jira issue management (task tracking).

| Component | Location | What It Does |
|-----------|----------|--------------|
| `atlassian_mcp_proxy.py` | `src/integrations/atlassian/` | MCP server wrapping Atlassian REST API (Confluence + Jira) |
| Lambda deployment | Terraform module | Proxy runs as Lambda behind API Gateway |
| OAuth 2.0 (3LO) | `src/integrations/atlassian/auth.py` | Token stored in Secrets Manager, proactive refresh |
| Feature flag | `ENABLE_ATLASSIAN=false` | Disabled by default. Requires OAuth app registration. |

**Acceptance Criteria**:
- [ ] Factory reads Confluence specs as task input when enabled
- [ ] Factory creates/updates Jira issues for task tracking when enabled
- [ ] OAuth token refresh works without human intervention
- [ ] Factory operates normally when Atlassian is disabled (default)

---

## 11. Unified Architecture Diagram (Post-Convergence)

```
UNIFIED FDE PLATFORM (v3 — DORA-Aligned, Add-On Decoupled)

┌─────────────────────────────────────────────────────────────────────────────┐
│ BOARD INTAKE (Any Source)                                                    │
│   GitHub Projects | GitLab Issues | Asana Tasks | Jira (add-on)            │
│   ← Kiro specs (add-on, IDE-produced)                                       │
│   ← AI-DLC artifacts (add-on, S3-deposited)                                │
│   All sources converge to: structured work item with user_value_statement   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ CONTROL PLANE (Orchestrator — 512MB, dispatcher only)                       │
│   1. Receive work item (EventBridge)                                        │
│   2. Query System Maturity Score → validate amplifier readiness             │
│   3. Query Context Hierarchy (DynamoDB) → inject L1-L2 into SCD            │
│   4. Query Organism Ladder (DynamoDB) → determine complexity class          │
│   5. Query Memory Manager (semantic) → inject relevant past decisions       │
│   6. Check Anti-Instability Loop → confirm autonomy level is valid          │
│   7. Dispatch Stage 1: task-intake-eval-agent                               │
│      → Extracts user_value_statement                                        │
│      → Reads organism + knowledge annotations                               │
│      → Produces Squad Manifest                                              │
│   8. Dispatch Stages 2..N per manifest (parallel within stage)              │
│   9. Dispatch Final Stage: fde-fidelity-agent + reporting-agent             │
│  10. Push + Create PR + Update portal + Track cost + Update VSM             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ DATA PLANE                                                                   │
│   DynamoDB Tables:                                                           │
│     fde-dev-scd              — Shared Context Document (intra-task)          │
│     fde-dev-context-hierarchy — Cross-session learned context                │
│     fde-dev-metrics          — DORA metrics + factory metrics + cost         │
│                                (SK patterns: dora#, cost#, verification#,    │
│                                 vsm#, autonomy_adjustment#, maturity#)       │
│     fde-dev-memory           — Structured memory (decisions, outcomes)       │
│     fde-dev-organism         — Organism ladder state                         │
│     fde-dev-knowledge        — Knowledge annotations + quality scores        │
│   Bedrock KB: Semantic Memory (OpenSearch Serverless vector store)           │
│   EFS: /workspaces/{task_id}/{repo}/                                        │
│   S3: Full outputs (>400KB) | Behavioral baselines | Archived metrics       │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ EXECUTION PLANE (Independent ECS Tasks)                                      │
│   Stage 1: Intake → task-intake-eval-agent (user value extraction)          │
│   Stage 2: Context → swe-issue-code-reader + swe-code-context (Code KB)    │
│   Stage 3: Implementation → swe-developer + swe-architect (per manifest)   │
│   Stage 4: Review → code-sec + swe-adversarial (perturbation) + WAF agents │
│   Stage 5: Delivery → swe-tech-writer + swe-dtl-commiter                   │
│   Stage 6: Fidelity → fde-fidelity-agent + reporting-agent                 │
│   Tools: human_input (L2/L3 only) | cost_tracker (all agents)              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ QUALITY PLANE (Brain Simulation + DORA Governance)                           │
│   Fidelity Score Engine | Emulation Classifier | Organism Ladder            │
│   Perturbation Engine | Behavioral Benchmark | Context Hierarchy Manager    │
│   Knowledge Annotation Layer | Code Knowledge Base                          │
│   Memory Manager (DynamoDB + Bedrock KB)                                    │
│   Anti-Instability Loop | Gate Optimizer | User Value Validator             │
│   System Maturity Scorer (7 DORA capabilities)                              │
│   Data Quality Scorer (knowledge artifact health)                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ PORTAL (Unified Dashboard — DORA-Aligned)                                    │
│   [Factory Health + DORA 4 metrics per autonomy level]                      │
│   [Squad Execution — real-time via WebSocket]                               │
│   [Brain Simulation — fidelity + emulation + organism]                      │
│   [Cost & Efficiency — per agent, per gate, per task]                       │
│   [Value Stream — flow + wait times + bottleneck identification]            │
│   [System Maturity — 7-axis radar per repo]                                 │
│   [Data Quality — knowledge artifact health]                                │
│   [Live Timeline + Human Input Card]                                        │
│   [Persona: PM | SWE | SRE | Architect | Staff Engineer]                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ ADD-ON PLANE (Optional, Feature-Flagged, Zero-Cost When Disabled)            │
│   [Kiro IDE] — steering + hooks + profiles (passive, repo-resident)         │
│   [AI-DLC Adapter] — S3 artifact import (ENABLE_AIDLC_ADAPTER=false)       │
│   [Atlassian Proxy] — Confluence + Jira (ENABLE_ATLASSIAN=false)           │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 12. 5W2H — Unified Implementation (Post-Convergence)

| Dimension | Answer |
|-----------|--------|
| **WHAT** | Self-contained Code Factory combining: distributed agent execution (infrastructure) + brain simulation quality measurement (meta-cognition) + DORA 2025 strategic alignment (speed-stability governance, 7-capability scoring, user-centric focus, anti-instability feedback loop, adaptive gate frequency, value stream mapping) + managed semantic memory + real-time HITL + cost visibility + streaming observability. Add-ons (Kiro, AI-DLC, Atlassian) available but not required. |
| **WHY** | DORA 2025 proves: AI without governance creates instability. Distributed execution solves resource exhaustion. Brain simulation solves quality blindness. DORA alignment makes us the reference implementation of the 7-capability model. User-centric focus prevents "moving fast in the wrong direction." Anti-instability loop is the mechanical implementation of DORA's central thesis. |
| **WHO** | Staff SWE (architecture + review + add-on decisions), FDE Squad (core implementation), Platform team (Terraform + WebSocket + DynamoDB), Portal team (React cards + streaming), Metrics team (DORA + cost + VSM). |
| **WHERE** | `src/core/governance/` (anti-instability, gate optimizer, user value, maturity scorer), `src/core/metrics/` (DORA enhanced, cost, VSM, verification), `src/core/memory/` (manager + semantic store + context engineer), `src/core/knowledge/` (data quality scorer), `src/tools/` (human input), `src/api/` (WebSocket), `src/integrations/` (add-ons only), `infra/terraform/` (ECS + DynamoDB + EFS + API GW + Bedrock KB), `infra/portal-src/` (React cards), `.kiro/profiles/` (starter/standard/full). |
| **WHEN** | 5 waves over 8-10 weeks. Wave 1 unblocks all. Waves 2-3 parallel. Wave 4 depends on Wave 1 WebSocket. Wave 5 (add-ons) is independent and optional. |
| **HOW** | Incremental per wave. Feature flags gate all new functionality. Anti-instability loop validates each wave's impact on CFR. Starter profile available from Wave 1. Each wave validates at one organism level. Data travel tests prove E2E integration. |
| **HOW MUCH** | ~$85/month (dev, includes Bedrock KB). ~7500 LOC core (Python + HCL + TSX). ~1200 LOC add-ons (optional). 50-55 context windows for core. Add-ons: +10 CW each if enabled. |

---

## 13. Adversarial Challenge

| Challenge | Honest Answer |
|-----------|---------------|
| "Why not distributed first, brain sim later?" | Distributed without quality measurement scales the problem. 6 agents producing SIMULATION-quality output faster is waste. Fidelity agent in last stage costs <30s, provides feedback loop that makes parallelism valuable. DORA confirms: speed without stability is a trap. |
| "DORA alignment is marketing, not engineering." | Every DORA item maps to a concrete component with acceptance criteria. Anti-instability loop is 4 components. User value validator is 4 components. System maturity scorer is 4 components. No hand-waving. |
| "User-centric focus in DoR/DoD is subjective." | `user_value_validator.py` scores completeness 0-100 based on user story format presence. Score < 40 = reject. Mechanical, not subjective. The CONTENT of user value is subjective; the PRESENCE of user value statement is not. |
| "Anti-instability loop is too aggressive." | Thresholds are configurable. Default (15% CFR over 7 days) is generous — DORA elite performers have <5% CFR. Override available for Staff Engineer. Restoration is automatic after 14 clean days. |
| "Gate optimizer undermines governance." | Only applies to L5 with >98% pass rate over 30 days. One failure revokes trust immediately. Net effect: governance is preserved for risky patterns, reduced for proven-safe patterns. DORA's "constrained by process" archetype is the alternative. |
| "Kiro decoupling breaks our workflow." | It doesn't. Kiro files remain in the repo. Developers using Kiro get the same experience. The change is architectural: factory source code has zero imports from Kiro runtime. The connection is the board item, not an API call. |
| "AI-DLC as add-on means we lose inception." | We never HAD inception. It was a planned feature. Making it an add-on means Staff Engineers who want it can enable it. Those who don't aren't burdened. The factory's core value is construction-to-delivery, not inception. |
| "7500 LOC is too much." | Alternative: implement piecemeal, discover DORA's speed-stability paradox at month 4 when CFR spikes, retrofit anti-instability loop into architecture not designed for it. Integrated design cost < integration debt. Feature flags allow partial deployment. |
| "System maturity scoring during onboarding adds latency." | Runs once per repo (Phase 0). Takes <60s. Determines autonomy level for ALL future tasks. ROI: 60s upfront saves hours of miscalibrated autonomy. |

---

## 14. Red Team — Failure Modes

| Failure Mode | Prob | Impact | Mitigation |
|---|---|---|---|
| Fidelity agent fails → no score | Low | Med | Retry max 3. If all fail, task completes without score (degraded, not blocked). Alert fires. |
| Context Hierarchy stale → wrong context | Med | Med | TTL on L1-L2. Confidence decay on L3-L5. Fresh SCD always included alongside. |
| EFS latency spike → slow agents | Low | High | Provisioned Throughput for prod. Fallback: local clone if >500ms. |
| SCD write conflict → parallel agents | Low | High | Conditional writes (version attr). Manifest enforces section permissions. |
| Organism gate blocks legitimate scaling | Low | Med | Override flag + audit log + weekly review. |
| Code KB index stale → wrong navigation | Med | Med | Re-index on PR merge. Max staleness: 1 PR. Agents verify file exists. |
| Anti-instability loop false positive | Med | Med | 7-day window smooths noise. Manual override available. Alert includes CFR data for human judgment. |
| User value validator too strict | Med | Low | Score threshold configurable (default 40). Bypass available for infrastructure tasks (no end-user). |
| Gate optimizer trusts wrong pattern | Low | High | Immediate trust revocation on first failure. 30-day re-qualification. Audit log of all trust decisions. |
| Bedrock KB unavailable → no semantic search | Low | Med | Fallback to DynamoDB keyword match. Degraded recall, not broken factory. |
| WebSocket disconnect mid-HITL | Med | Med | Client reconnect with replay. Agent waits full timeout. DynamoDB persists pending questions. |
| Cost tracker drift vs AWS billing | Low | Low | Weekly reconciliation against Cost Explorer. Alert if delta >10%. |
| System maturity scorer miscalibrates | Med | Med | Score is recommendation, not enforcement. Staff Engineer can override. Recalibrate monthly. |
| VSM timestamps missing (stage skipped) | Low | Low | Default to "unknown" duration. Don't break flow for missing telemetry. |
| Token explosion (all gates + DORA metrics) | Low | Med | Gate optimizer reduces calls for trusted patterns. Fast-tier for all deterministic gates. Cost alert at $2/task. |

---

## 15. Dependency Graph (Final — 5 Waves)

```
Wave 1: Distributed Infrastructure + DORA Foundation (blocks Waves 2-4)
  ├─ EFS + Security Groups
  ├─ DynamoDB tables: scd, context-hierarchy, metrics, memory, organism, knowledge
  ├─ Agent Task Definition (parametrized)
  ├─ Orchestrator Task Definition
  ├─ distributed_orchestrator.py + agent_runner.py
  ├─ cost_tracker.py (lightweight, no external deps)
  ├─ dora_metrics.py update (autonomy_level dimension)
  ├─ verification_metrics.py (time-in-review, queue-depth)
  ├─ vsm_tracker.py (stage transition timestamps)
  ├─ anti_instability_loop.py (CFR monitoring + auto-adjustment)
  ├─ Starter profile: .kiro/profiles/starter.json
  ├─ Standard profile: .kiro/profiles/standard.json
  ├─ Full profile: .kiro/profiles/full.json
  ├─ docs/quickstart.md
  └─ docs/operations/ai-stance.md (DORA C1)

Wave 2: Brain Sim Core (depends on Wave 1 DynamoDB)
  ├─ fidelity_score.py
  ├─ emulation_classifier.py (depends on fidelity_score)
  ├─ context_hierarchy.py (depends on DynamoDB)
  ├─ organism_ladder.py
  ├─ brain_sim_metrics.py (depends on fidelity + classifier)
  ├─ fde-fidelity-agent prompt + task def
  ├─ user_value_validator.py (DORA C6)
  ├─ DoR gate update (user value field)
  └─ DoD gate update (user story completion)

Wave 3: Knowledge + Memory + Maturity (depends on Wave 1 DynamoDB + EFS)
  ├─ call_graph_extractor.py
  ├─ description_generator.py (depends on extractor)
  ├─ vector_store.py
  ├─ query_api.py (depends on vector_store)
  ├─ knowledge_annotation.py (depends on DynamoDB)
  ├─ data_quality_scorer.py (DORA C2)
  ├─ perturbation_engine.py
  ├─ behavioral_benchmark.py (depends on EFS)
  ├─ memory_manager.py (DynamoDB backend)
  ├─ semantic_store.py (Bedrock KB integration)
  ├─ context_engineer.py (per-task-type context retrieval)
  ├─ migrate_memory.py (one-time migration script)
  ├─ system_maturity_scorer.py (DORA 7-capability scoring)
  ├─ gate_optimizer.py (adaptive gate frequency)
  └─ repo_onboarding_agent update (maturity score + archetype + profile recommendation)

Wave 4: Real-time Infrastructure + Portal (depends on Wave 1 + API Gateway)
  ├─ API Gateway WebSocket API (Terraform)
  ├─ ws_handler.py (Lambda)
  ├─ human_input_tool.py
  ├─ Autonomy gating update (L2/L3 only)
  ├─ Portal: LiveTimeline.tsx (WebSocket streaming)
  ├─ Portal: HumanInputCard.tsx
  ├─ Portal: CostCard.tsx
  ├─ Portal: DoraCard.tsx (per-autonomy-level breakdown)
  ├─ Portal: ValueStreamCard.tsx
  ├─ Portal: MaturityRadar.tsx (7-axis)
  ├─ Portal: DataQualityCard.tsx
  ├─ Portal: Squad Execution cards
  ├─ Portal: Brain Sim cards (depends on Wave 2)
  └─ Portal: Persona routing (PM | SWE | SRE | Architect | Staff)

Wave 5: Add-Ons (INDEPENDENT — parallel with any wave, Staff Engineer decision)
  ├─ aidlc_adapter.py (AI-DLC S3 artifact import)
  ├─ atlassian_mcp_proxy.py (Confluence + Jira)
  ├─ Atlassian Lambda + Terraform
  ├─ Atlassian OAuth auth.py
  ├─ docs/integration/aidlc-handoff.md
  └─ docs/integration/atlassian-setup.md
```

---

## 16. Implementation Readiness Checklist

| Wave | Prerequisites | Ready? | Blocking Issue |
|------|--------------|--------|----------------|
| Wave 1 | AWS account, Terraform state bucket, ECR registry | ✅ | None |
| Wave 2 | Wave 1 DynamoDB tables deployed | ⏳ | Depends on Wave 1 |
| Wave 3 | Wave 1 EFS + DynamoDB, Bedrock KB model access grant | ⏳ | Bedrock KB requires model access approval |
| Wave 4 | Wave 1 + API Gateway WebSocket quota check | ⏳ | WebSocket API requires service quota verification |
| Wave 5 | Independent (Atlassian requires OAuth app registration) | ⏳ | Staff Engineer decision to enable |

### Pre-Flight Checks (Before Wave 1)

- [ ] Terraform state bucket exists and is accessible
- [ ] ECR registry created for agent images
- [ ] DynamoDB on-demand capacity confirmed (no provisioned limits)
- [ ] EFS security group allows ECS task ENIs
- [ ] Bedrock model access granted (Claude Sonnet for reasoning, Haiku for gates)
- [ ] Feature flags documented in `docs/feature-flags.md`
- [ ] Starter profile hooks validated locally
- [ ] Cost alert threshold agreed ($2.00/task default)
- [ ] DORA baseline metrics captured (current CFR, lead time, deploy freq, MTTR)
- [ ] AI stance document reviewed by Staff Engineer

---

## 17. Cost Estimate (Post-Convergence)

| Component | Monthly Cost (Dev) | Monthly Cost (Prod) | Notes |
|-----------|-------------------|--------------------:|-------|
| DynamoDB (on-demand, 6 tables) | $5 | $25 | Low throughput in dev |
| EFS (General Purpose) | $3 | $15 | ~10GB workspace storage |
| ECS Fargate (agents) | $20 | $150 | Spot for dev, on-demand for prod |
| Bedrock (Claude Sonnet — reasoning) | $30 | $200 | ~50 tasks/month dev, ~500 prod |
| Bedrock (Haiku — gates + fidelity) | $5 | $30 | Fast-tier for deterministic gates |
| Bedrock KB (OpenSearch Serverless) | $12 | $12 | Minimum OCU charge |
| API Gateway WebSocket | $2 | $10 | Per-connection + per-message |
| S3 (artifacts + behavioral baselines) | $1 | $5 | Lifecycle policy: 90-day archive |
| CloudWatch (logs + alarms) | $5 | $20 | Log retention: 30 days |
| Secrets Manager | $2 | $5 | Per-secret per-month |
| **Core Total** | **~$85** | **~$472** | |
| Add-on: Atlassian Lambda (if enabled) | +$3 | +$10 | Only when ENABLE_ATLASSIAN=true |
| Add-on: AI-DLC S3 reads (if enabled) | +$1 | +$3 | Only when ENABLE_AIDLC_ADAPTER=true |
| **Total with all add-ons** | **~$89** | **~$485** | |

---

## 18. Success Metrics (DORA-Aligned)

| Metric | Baseline (Current) | Target (Post-Implementation) | Measurement | DORA Alignment |
|--------|--------------------|-----------------------------|-------------|----------------|
| Change Fail Rate (global) | Unknown (not tracked per level) | <10% (L4/L5), <5% (L3) | `dora_metrics.py` per autonomy level | Speed-stability paradox |
| Lead Time (spec → merged PR) | ~45min (sequential) | ~15min (parallel, L4/L5) | VSM tracker | DORA throughput |
| Verification throughput | Unknown | Time-in-review < 30min | `verification_metrics.py` | Bottleneck shift (F5) |
| Cost per task | Unknown | <$2.00 (dev), <$5.00 (prod) | `cost_tracker.py` | Sustainability |
| User value score (DoR) | 0% (not measured) | >80% of specs score ≥ 60 | `user_value_validator.py` | C6 (User-centric focus) |
| Cross-session recall accuracy | ~60% (notes grep) | >90% (semantic search) | Memory recall benchmark | C3 (AI-accessible data) |
| Knowledge artifact freshness | Unknown | 0 artifacts stale >90 days | `data_quality_scorer.py` | C2 (Healthy data ecosystems) |
| System maturity score | Not measured | All onboarded repos scored | `system_maturity_scorer.py` | 7-capability model |
| Gate time / total task time | Unknown | <15% for mature repos (L5) | `gate_optimizer.py` | "Constrained by process" prevention |
| Fidelity score (emulation quality) | Not measured | >0.7 sustained (L4/L5 tasks) | `fde-fidelity-agent` | Brain sim quality |
| Anti-instability interventions | N/A | <2 per month (healthy system) | `anti_instability_loop.py` audit log | Speed-stability governance |
| HITL response time (L2/L3) | N/A (no mid-execution) | <2min (WebSocket) | Portal metrics | Real-time collaboration |
| Adoption time (new user) | ~2 hours (full setup) | <15min (starter profile) | Onboarding timer | C7 (Quality platforms) |
| Flow efficiency (VSM) | Unknown | >60% active time / total time | `vsm_tracker.py` | Value stream visibility |

---

## 19. Migration Path

### From Current State → Wave 1

1. **No breaking changes.** Wave 1 adds infrastructure alongside existing system.
2. Feature flags default to `false`. Existing behavior unchanged until opt-in.
3. Starter profile is a subset of current hooks. No new constraints.
4. Cost tracker is passive (observes, doesn't block).
5. Anti-instability loop starts in "observe-only" mode (logs recommendations, doesn't auto-adjust) for first 30 days.
6. DORA metrics enhancement is additive (new dimension, existing data preserved).

### From Wave 1 → Full Platform

1. Each wave activates via feature flag. Rollback = set flag to `false`.
2. Memory migration is one-time but reversible (old notes preserved in S3 archive).
3. Anti-instability loop transitions from observe-only to active after 30-day baseline.
4. User value validator starts with warning-only mode (logs score, doesn't reject) for 2 weeks.
5. Gate optimizer starts with no trusted patterns (builds trust over 30 days of observation).
6. System maturity scorer runs on next Phase 0 onboarding (doesn't retroactively score existing repos until manually triggered).

### Add-On Activation (Independent of Core Waves)

1. Kiro: Already present in repo. No activation needed. Works when developer uses Kiro IDE.
2. AI-DLC: `ENABLE_AIDLC_ADAPTER=true` + configure S3 prefix. Requires AI-DLC deployed separately.
3. Atlassian: `ENABLE_ATLASSIAN=true` + OAuth app registration + Secrets Manager entry.

---

## 20. Validated Strengths (Confirmed by DORA 2025 + Benchmarking)

| DORA Recommendation | Code Factory Implementation | Validation |
|--------------------|----------------------------|------------|
| "Embrace and fortify safety nets" | 18 hooks (DoR, adversarial, DoD, pipeline, test immutability, circuit breaker) | ✅ Exceeds — DORA recommends rollback; we have 6 layers |
| "Enforce discipline of small batches" | Execution plans with milestones, scope boundaries | ✅ Meets |
| "Invest in internal platform" | 5-plane architecture, 3-script deployment, automated gates | ✅ Exceeds |
| "Clarify and socialize AI policies" | FDE protocol, steering files, hook documentation | ✅ Meets (A3 strengthens) |
| "Strong version control practices" | Branch evaluation, auto-merge rules, never-direct-to-main | ✅ Exceeds |
| "Speed without stability is a trap" | Anti-instability feedback loop (NEW) | ✅ Operationalized |
| "Trust but verify" | Adversarial gate on every write | ✅ Unique differentiator |
| "Bottleneck shifts to verification" | Verification throughput metric + auto-scaling (NEW) | ✅ Addressed |
| "User-centric focus prevents wrong direction" | User value validator in DoR/DoD (NEW) | ✅ Addressed |
| "AI amplifies existing strengths/weaknesses" | System maturity scorer predicts amplification (NEW) | ✅ Addressed |

### Unique Differentiators (No Other Platform Has These)

| Differentiator | What It Does | DORA Backing |
|---------------|--------------|--------------|
| Adversarial challenge on every write | Prevents spec drift mechanically | "Trust but verify" |
| Autonomy spectrum L1-L5 | Adapts governance to team maturity | "Teams vary in maturity" |
| Anti-instability feedback loop | Auto-reduces autonomy when CFR rises | "Speed without stability is a trap" |
| Failure taxonomy (FM-01 to FM-99) | Structured learning from failures | "Learn from failures" |
| Test immutability | Prevents test weakening to pass | No DORA equivalent (we're ahead) |
| Circuit breaker (CODE vs ENVIRONMENT) | Prevents false fixes | No DORA equivalent (we're ahead) |
| Gate optimizer (adaptive frequency) | Prevents "constrained by process" | "Constrained by process" archetype |
| System maturity scorer | Predicts AI amplification direction | "AI is an amplifier" thesis |

---

## 21. Document Governance

| Action | Requires | Approver |
|--------|----------|----------|
| Add new Wave | Staff SWE approval + ADR | Architecture |
| Modify core component scope | Staff SWE approval | Architecture |
| Enable add-on for a project | Staff Engineer decision | Staff Engineer (per-project) |
| Promote add-on to core | Team consensus + DORA impact analysis | Architecture + Product |
| Update cost estimates | Actual usage data (>30 days) | Platform |
| Change feature flag defaults | Production readiness review + 30-day observe data | SRE |
| Modify anti-instability thresholds | CFR data review + Staff Engineer approval | Governance |
| Update DORA capability scoring weights | Quarterly review against DORA publications | Architecture |

---

## 22. Strategic Position (Post-Convergence)

The 2025 DORA Report proves our thesis: AI without governance creates instability. The Code Factory is the only platform that operationalizes all 7 DORA AI Capabilities as automated, measurable controls.

**What we are**: A self-contained construction-to-delivery execution engine with governance-first architecture, DORA-aligned measurement, and brain simulation quality feedback.

**What we are NOT**: An IDE plugin. A platform that requires specific tooling. A system that depends on external AI services for its core loop.

**Add-ons extend, never constrain**: Kiro makes spec creation easier. AI-DLC makes inception possible. Atlassian connects to enterprise ALM. None are required. All are independently valuable.

**The DORA alignment is not marketing**: Every DORA finding maps to a concrete component with acceptance criteria, DynamoDB schema, and portal visualization. The anti-instability loop is the mechanical implementation of DORA's central thesis. The system maturity scorer is the operational form of the 7-capability model. The user value validator closes the one gap DORA says can make AI harmful.

**Bottom line**: DORA proves our thesis. Now we operationalize DORA's thesis — that the right system makes AI an amplifier of strength, not weakness.

---

*End of document. All elements are deployment-ready with feature flags for progressive rollout. No placeholders. No fake implementations. No deferred decisions without explicit ownership and timeline.*
