# Technical Design Document: Cognitive Autonomy for Agentic Software Factories

## Goal of This Doc

De-risk the architectural shift from static autonomy levels to a cognitive, signal-driven model. Align stakeholders on why the current L1-L5 model creates a structural failure mode (capability-authority conflation) and how decoupling these axes enables self-improving delivery without human degradation.

## Executive Summary

This document proposes a **Cognitive Autonomy Model** that replaces the industry-standard static autonomy classification (L1-L5) with a dual-axis system: **Capability Depth** (computed from Bayesian risk signals) and **Delivery Authority** (earned from output quality). The key innovation is that system failures trigger increased computational investment (more agents, deeper reasoning) rather than capability reduction — transforming the traditional punishment-based feedback loop into a recovery-oriented learning system. This is grounded in In-Context Reinforcement Learning (ICRL) theory and implements a closed-loop Markov Decision Process where the environment's reward signal (human review outcomes) drives adaptive resource allocation without model retraining.

---

## Background

### Industry State of the Art

Autonomous coding agents (GitHub Copilot Workspace, Devin, Factory, Cursor) operate with fixed autonomy models:

| System | Autonomy Model | Failure Response |
|--------|---------------|-----------------|
| GitHub Copilot Agent | Binary (draft PR / auto-merge) | Human reviews everything |
| Devin | Single-session, no memory | Starts fresh each time |
| Factory.ai | Task-level confidence score | Reduces scope on low confidence |
| SWE-Agent | Fixed tool access | No adaptation |

All share a common limitation: **autonomy is a static permission, not a dynamic cognitive signal**. When quality degrades, these systems either stop (binary) or reduce capability (graduated) — neither of which addresses the root cause.

### Our Previous State

The FDE Code Factory used a 5-level autonomy model (Feng et al., 2025):
- L1 (Operator): Human drives everything
- L2 (Collaborator): Human checkpoint at every phase
- L3 (Consultant): Human checkpoint after reconnaissance
- L4 (Approver): Human approves final PR only
- L5 (Observer): Fully autonomous

The Anti-Instability Loop (DORA A11) monitored Change Failure Rate and reduced the level when CFR exceeded thresholds. This created a **death spiral**: reduced level → fewer agents → worse output → higher CFR → further reduction.

Evidence: Issue GH-94 (cognitive-wafr) — labeled `factory/level:L4` (6 dependencies, blocks 4 tasks), factory operated at L3, deployed only 4/8 milestones, no adversarial agent, `static-gates` CI failed. The factory was structurally incapable of producing quality output because the autonomy system denied it the resources to do so.

---

## Problem Statement

The autonomous software factory exhibits a **capability-authority conflation failure** where a single control variable (autonomy level) gates both:

1. **Computational investment** (how many agents, what model tier, what verification depth)
2. **Delivery permission** (whether output can be auto-merged or requires human review)

This conflation produces three pathological behaviors:

1. **Death spiral**: Quality degradation triggers capability reduction, which guarantees further degradation. The system cannot recover without manual intervention.

2. **Permanent L2/L3 trap**: The factory never earns L4/L5 because it's never given the resources to produce L4/L5-quality output. Self-fulfilling prophecy.

3. **Static classification in dynamic environment**: Autonomy is decided once at task intake based on incomplete information. The system discovers complexity during execution but cannot adapt its resource allocation.

---

## Glossary

| Term | Definition |
|------|-----------|
| **Capability Depth** | Continuous value (0.0-1.0) representing computational investment: squad size, model tier, verification rigor. Determined by cognitive signals. Never decreases on failure. |
| **Delivery Authority** | Permission level for output disposition (auto-merge, human review, blocked). Earned by demonstrated output quality. Can decrease on failure. |
| **Cognitive Signal** | Any measurable input that informs resource allocation: risk score, dependency count, ICRL episodes, CFR, trust score, synapse assessments. |
| **ICRL** | In-Context Reinforcement Learning — the model adapts to repository-specific patterns through trial-and-error within the prompt window, without retraining. |
| **Recovery Spiral** | The inverse of a death spiral: failure triggers increased investment → better output → trust earned → authority restored. |
| **Capability Floor** | Minimum capability depth enforced when signals indicate difficulty. Failures RAISE the floor (more resources for harder problems). |

---

## Long-Term Vision

A software factory that:
1. **Self-calibrates** resource allocation per task based on 18+ cognitive signals
2. **Learns from every human review** (positive and negative) via ICRL episodes
3. **Earns autonomy organically** through demonstrated quality (not manual promotion)
4. **Recovers from failure** by investing more (not less) in problematic domains
5. **Operates at L5** for proven task types while maintaining L3 for novel domains — simultaneously, per-task, not per-project

---

## Requirements

### Functional Requirements

| Component | No. | Role | Use Case | Priority |
|-----------|-----|------|----------|----------|
| Cognitive Autonomy Engine | 1.1 | Orchestrator | Compute capability depth from Risk Engine + cognitive signals | P0 |
| Cognitive Autonomy Engine | 1.2 | Orchestrator | Compute delivery authority from trust + CFR + review outcomes | P0 |
| Capability-to-Squad Mapper | 2.1 | Squad Composer | Map depth value to concrete squad composition | P0 |
| Authority Decision Matrix | 3.1 | DTL Committer | Determine merge/review/block based on L1+L2+authority | P0 |
| Anti-Instability Loop v2 | 4.1 | Governance | Reduce authority (not capability) on CFR breach | P1 |
| Anti-Instability Loop v2 | 4.2 | Governance | Raise capability floor on repeated failures | P1 |
| Legacy Compatibility Shim | 5.1 | All consumers | Provide `legacy_autonomy_level` (int 1-5) for downstream code | P1 |

### Non-Functional Requirements

| Requirement | Target | Rationale |
|-------------|--------|-----------|
| Computation latency | < 100ms | Must not add perceptible delay to task intake |
| Signal availability | Graceful degradation | If Risk Engine unavailable, use defaults (depth=0.5) |
| Backward compatibility | 100% | Existing code reading `autonomy_level` must not break |
| Feature flag | `COGNITIVE_AUTONOMY_ENABLED` | Instant rollback without redeployment |
| Cold start | Functional without ICRL history | Risk Engine provides baseline; ICRL enriches over time |

---

## Success Metrics

| Metric | Baseline (Before) | Target (After) | Measurement |
|--------|-------------------|----------------|-------------|
| Milestone completion rate | 50% (4/8 for GH-94) | >90% | task_queue events / total milestones |
| PR rejection rate (human) | Unknown (not measured) | <15% | Review Feedback Loop (ADR-027) |
| Time to L4 authority | Never achieved | <30 days from cold start | First auto-merge event |
| Death spiral incidents | Recurring | Zero | Anti-Instability Loop never reduces capability |
| Squad utilization efficiency | Over-provisioned simple tasks | <$0.05/task for O1-O2 | Cost metrics per depth band |

---

## Assumptions

1. **Risk Engine accuracy**: The 18-signal Bayesian risk score is a reliable proxy for task complexity. Validated by ADR-022 with 33 tests and 3 end-to-end scenarios.
2. **ICRL episode relevance**: Past failures for the same repo predict future difficulty. TTL of 30 days prevents stale signals.
3. **Trust is monotonic within windows**: A project's trust score changes slowly (30-day rolling window). Sudden drops indicate real quality issues, not noise.
4. **Dependency count is available**: The issue template includes `depends_on` and `blocks` fields. If missing, defaults to 0 (conservative: lower depth).
5. **Human review is the ground truth**: When a human approves a PR, the factory's output was correct. When rejected, it was wrong. No ambiguity.

---

## Out of Scope

- Modifying the Risk Engine's signal computation (it already works)
- Changing the Conductor's plan generation logic (it already accepts capability parameters)
- Retraining any model (ICRL operates entirely in-context)
- Multi-tenant authority (authority is per-project, not per-organization)
- Real-time capability adjustment mid-execution (evaluated at intake; future work)

---

## Proposal

### Option A: Patch the Existing L1-L5 Model (Rejected)

Add dependency counting and label reading to `compute_autonomy_level()`. Keep the single-axis model.

**Why rejected**: Treats symptoms. The fundamental conflation of capability and authority remains. Adding more inputs to a broken model does not fix the model.

### Option B: Continuous Single Axis (Rejected)

Replace L1-L5 with a continuous 0.0-1.0 score that still controls both capability and authority.

**Why rejected**: Still conflated. A single axis cannot represent "high capability + low authority" (the correct state for a factory that is trying hard but has not earned trust yet).

### Option C: Dual-Axis Cognitive Model (Selected)

Decouple into two independent axes computed from different signal sources.

**Why selected**: 
- Eliminates the death spiral (capability never decreases)
- Enables organic L5 achievement (authority earned by quality)
- Maps naturally to existing infrastructure (Risk Engine → capability, Review Architecture → authority)
- No new computation needed (reuses existing signals)

---

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    COGNITIVE AUTONOMY ENGINE                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────────────┐      ┌──────────────────────────┐      │
│  │   CAPABILITY DEPTH   │      │   DELIVERY AUTHORITY      │      │
│  │   (How to execute)   │      │   (What to do with output)│      │
│  ├─────────────────────┤      ├──────────────────────────┤      │
│  │ Inputs:              │      │ Inputs:                    │      │
│  │ - Risk Engine score  │      │ - PR Reviewer verdict (L1) │      │
│  │ - Dependency count   │      │ - Branch Eval score (L2)   │      │
│  │ - ICRL failure count │      │ - CFR history              │      │
│  │ - Synapse signals    │      │ - Trust score              │      │
│  │ - CFR (raises floor) │      │ - Consecutive successes    │      │
│  ├─────────────────────┤      ├──────────────────────────┤      │
│  │ Output:              │      │ Output:                    │      │
│  │ - Squad size (2-8)   │      │ - auto_merge               │      │
│  │ - Model tier         │      │ - ready_for_review         │      │
│  │ - Verification level │      │ - blocked                  │      │
│  │ - Topology           │      │                            │      │
│  └─────────────────────┘      └──────────────────────────┘      │
│                                                                   │
│  Rule: Capability NEVER decreases on failure                      │
│  Rule: Authority is EARNED by output quality                      │
│  Rule: Anti-Instability Loop affects AUTHORITY only               │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

### Capability Depth Mapping

| Depth Range | Squad | Model | Verification | Topology | Cost/Task |
|-------------|-------|-------|-------------|----------|-----------|
| 0.0 - 0.3 | 2 agents | fast (Haiku) | linter only | sequential | ~$0.02 |
| 0.3 - 0.5 | 4 agents | standard (Sonnet) | linter + types | sequential | ~$0.08 |
| 0.5 - 0.7 | 6 agents | reasoning (Sonnet) | full suite | tree | ~$0.15 |
| 0.7 - 1.0 | 8 agents | deep (Opus) | full + MCTS | debate | ~$0.30 |

### Authority Earning Conditions

| Authority Level | Required Conditions | Typical Timeline |
|----------------|--------------------|--------------------|
| `blocked` | CFR > 30% OR Staff Engineer override | Immediate on breach |
| `ready_for_review` | Default state; L1 approve + L2 >= 6.0 | Day 1 |
| `auto_merge` | CFR < 10% + Trust > 80% + 3 consecutive successes + L1 approve + L2 >= 8.0 | Week 2-4 |

### Anti-Instability Loop v2

| Trigger | Old Behavior (v1) | New Behavior (v2) |
|---------|-------------------|-------------------|
| CFR > 15% (7-day) | Reduce autonomy level by 1 | Reduce authority to `ready_for_review` + raise capability floor to 0.6 |
| CFR > 30% (3-day) | Reduce autonomy level by 2 | Block authority + raise capability floor to 0.8 + alert Staff Engineer |
| CFR = 0% (30-day) | Eligible for promotion | Authority auto-upgrades to `auto_merge` if trust > 80% |

---

## Testing Design

### Unit Tests

| Test | What It Validates |
|------|-------------------|
| `test_depth_from_risk_score` | Risk score maps correctly to depth bands |
| `test_depth_floor_from_failures` | Past failures raise the floor (never lower) |
| `test_depth_floor_from_cfr` | High CFR raises floor (recovery, not punishment) |
| `test_authority_auto_merge_conditions` | All conditions must be met simultaneously |
| `test_authority_blocked_on_high_cfr` | CFR > 30% blocks regardless of other signals |
| `test_legacy_shim_mapping` | Legacy L1-L5 computed correctly from authority |
| `test_feature_flag_disabled` | Returns safe defaults when flag is off |

### Integration Tests

| Test | What It Validates |
|------|-------------------|
| `test_orchestrator_reads_risk_engine` | End-to-end: Risk Engine → capability → squad composition |
| `test_high_depth_includes_adversarial` | Depth >= 0.5 always includes adversarial agent |
| `test_authority_earned_after_successes` | 3 consecutive approvals → auto_merge unlocked |

---

## Design Details

### Why This Is Novel

No existing autonomous coding system implements this dual-axis model. The state of the art treats autonomy as a permission (binary or graduated) rather than a cognitive signal. Our contribution:

1. **Failure as investment signal**: Every other system reduces capability on failure. We increase it. This is grounded in the ICRL principle that negative rewards should trigger exploration (more diverse strategies), not exploitation (narrower strategies).

2. **Authority earned by output, not assumed by input**: No system we have found determines merge permission based on the actual quality of the specific PR (measured by independent reviewer + deterministic verification). All use static rules (confidence threshold, task type, user setting).

3. **Continuous adaptation without retraining**: The capability depth adapts per-task based on 18+ signals that change in real-time (ICRL episodes accumulate, CFR shifts, trust evolves). No model fine-tuning, no weight updates to the LLM itself — pure in-context adaptation.

4. **Recovery spiral as architectural primitive**: The Anti-Instability Loop v2 is, to our knowledge, the first implementation of a "failure → invest more" feedback loop in an autonomous coding system. All others implement "failure → restrict more."

### Theoretical Grounding

The model maps to a **Partially Observable Markov Decision Process (POMDP)** where:
- **State**: True task complexity (partially observable)
- **Observation**: Risk Engine score + cognitive signals (noisy estimate of state)
- **Action**: Capability depth selection (resource allocation)
- **Reward**: Human review outcome (binary: approve/reject)
- **Policy**: `compute_capability_depth()` — maps observations to actions
- **Belief update**: ICRL episodes refine the observation model over time

The key insight is that the **action space** (capability depth) and the **reward interpretation** (authority) are decoupled. The agent always takes the action that maximizes expected quality (high capability for hard tasks), and the reward determines what happens AFTER the action completes (merge or review).

---

## Rollout Plan

| Phase | Duration | What Changes | Rollback |
|-------|----------|-------------|----------|
| 1. Deploy (current) | Day 0 | Module deployed, feature flag ON | Set `COGNITIVE_AUTONOMY_ENABLED=false` |
| 2. Observe | Days 1-7 | Monitor depth distribution, squad sizes, authority decisions | Same flag |
| 3. Validate | Days 7-14 | Compare milestone completion rate vs baseline | Same flag |
| 4. Earn authority | Days 14-30 | First auto-merge events expected | Reduce trust threshold if needed |
| 5. Steady state | Day 30+ | System self-calibrating | N/A |

---

## Open Questions

1. **Should capability depth be re-evaluated mid-execution?** Currently computed once at intake. If reconnaissance reveals unexpected complexity, should the squad be expanded mid-flight?

2. **Per-repo vs per-task authority?** Currently authority is per-project. Should a project have different authority levels for different task types (bugfix vs feature)?

3. **Cost ceiling**: Should there be a hard cap on capability depth regardless of signals? (e.g., never spend more than $0.50/task even if all signals say maximum depth)

4. **Multi-model selection**: Should the model tier be per-agent (architect gets reasoning, reporter gets fast) rather than uniform across the squad?

---

## References

- ADR-013: Enterprise-Grade Autonomy and Observability
- ADR-022: Risk Inference Engine (18-signal Bayesian scoring)
- ADR-027: Review Feedback Loop (ICRL Enhancement)
- ADR-028: PR Reviewer Agent (Three-Level Review Architecture)
- ADR-029: Cognitive Autonomy Model (this design's ADR)
- Feng et al., 2025: "Human-in-the-Loop Software Development Agents" (arXiv:2411.12924)
- DORA 2025 Report: "Speed without stability is a trap"
- ICRL (arXiv:2602.17084): In-Context Reinforcement Learning
- c-CRAB (arXiv:2603.23448): Code Review Agent Benchmark
- Nielsen et al., ICLR 2026: "Learning to Orchestrate Agents" (Conductor pattern)
- ThoughtWorks Technology Radar 2026: Rework Rate as fifth DORA metric

---

## Doc Data / Change Log

| Version | Author | Status | Comments |
|---------|--------|--------|----------|
| 1.0 | FDE Squad | Draft | Initial design for review |

## Tenets

1. "We will invest MORE computational resources in failing domains, even if it costs more per task, because the alternative (capability reduction) guarantees permanent failure."

2. "We will never auto-merge a PR that has not been independently validated by an agent reviewer AND a deterministic verification gate, even if the human has historically approved everything."

3. "We will treat authority as something earned per-PR by output quality, not something granted per-project by configuration, even if this means the factory operates at 'ready_for_review' for weeks before earning auto-merge."
