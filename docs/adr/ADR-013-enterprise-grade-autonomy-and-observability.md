# ADR-013: Enterprise-Grade Autonomy, Failure Classification, and Scope Boundaries

## Status
Accepted

## Date
2026-05-04

## Context
Four academic papers were analyzed to identify gaps between the current Code Factory and enterprise-grade requirements:

1. **SWE-AGI** (Zhang et al., Feb 2026): Code reading is the dominant bottleneck; specification-intensive tasks degrade performance
2. **SWE-Bench Pro** (Deng et al., Sep 2025): Enterprise-level long-horizon tasks; failure mode clustering reveals stable error patterns
3. **WhatsCode** (Mao et al., Dec 2025): 25-month industrial deployment; two stable collaboration patterns (one-click 60%, commandeer-revise 40%); acceptance rates vary 9%-100% by domain
4. **Levels of Autonomy** (Feng et al., Jun 2025): Five levels (Operator → Observer); autonomy as deliberate design decision; autonomy certificates

Four gaps were identified:

1. No explicit autonomy level per task
2. No failure mode classification (only "completed" or "not completed")
3. No domain-segmented metrics (acceptance rate by tech_stack)
4. No formal scope boundaries document

## Decisions

### Decision 1: Autonomy Level in Data Contract

New optional field `autonomy_level` (enum: L1-L5) with smart defaults computed from `type` + `level`:

| Level | Name | Human Role | Pipeline Behavior |
|-------|------|-----------|-------------------|
| L2 | Collaborator | Checkpoint at every phase | Full gates + 3 human checkpoints |
| L3 | Consultant | Checkpoint after reconnaissance | Full gates + 2 human checkpoints |
| L4 | Approver | Approves final PR only | Full gates + 1 human checkpoint |
| L5 | Observer | Monitors metrics | Reduced gates, fast path eligible |

The Orchestrator adapts pipeline gates based on autonomy level. Higher autonomy = fewer gates and faster execution. Inner loop gates (lint, test, build) always run regardless of level.

### Decision 2: Failure Mode Taxonomy

When a task does not complete successfully, classify WHY using detectable signals:

| Code | Category | Signal | Recovery |
|------|----------|--------|----------|
| FM-01 | SPEC_AMBIGUITY | 3+ DoR warnings about ambiguity | Request clarification |
| FM-02 | CONSTRAINT_CONFLICT | DoR validation errors present | Request human resolution |
| FM-03 | TOOL_FAILURE | ECONNREFUSED, command not found | Retry with backoff |
| FM-05 | COMPLEXITY_EXCEEDED | 15+ files modified + timeout | Decompose into subtasks |
| FM-06 | TEST_REGRESSION | Tests that passed now do not pass | Rollback and retry |
| FM-07 | DEPENDENCY_MISSING | ModuleNotFoundError, Cannot find module | Report and block |
| FM-08 | TIMEOUT | Execution time >= limit | Rollback and report |
| FM-09 | AUTH_FAILURE | 401/403, token expired | Report environment error |
| FM-99 | UNKNOWN | No pattern matches | Log full context for review |

Classification uses heuristic rules. After 100 tasks, review the taxonomy against real data.

### Decision 3: Domain-Segmented Metrics

All DORA metrics gain a `tech_stack` dimension. This enables per-domain analysis:
- "Python tasks have 92% acceptance rate, Java tasks have 67%"
- "Terraform tasks take 3x longer lead time than Python tasks"

Implementation: add `tech_stack: list[str]` parameter to `record_task_outcome`, `record_lead_time`, and `record_pipeline_stage`. The factory report includes a `domain_breakdown` section.

### Decision 4: Formal Scope Boundaries

Create `docs/design/scope-boundaries.md` as the authoritative document defining what the Code Factory does and does not do. The `scope_boundaries.py` module enforces these boundaries programmatically in the DoR Gate.

Confidence levels (high/medium/low) are computed from available signals: tooling support, acceptance criteria specificity, constraints presence, and related docs availability.

## Consequences

- The data contract gains `autonomy_level` as an optional field with computed defaults
- The Circuit Breaker gains second-level failure classification (FM-01 through FM-99)
- All DORA metrics gain tech_stack segmentation for domain-specific analysis
- A formal scope boundaries document defines the factory's operational limits
- The Orchestrator adapts pipeline behavior based on autonomy level
- 31 BDD scenarios validate all four capabilities

## Related
- ADR-010: Data Contract for Task Input
- ADR-012: Over-Engineering Mitigations
- Design: `docs/design/scope-boundaries.md`
- Implementation: `infra/docker/agents/autonomy.py`, `failure_modes.py`, `scope_boundaries.py`
- Tests: `tests/test_autonomy_level.py`, `test_failure_mode_taxonomy.py`, `test_domain_segmented_metrics.py`, `test_scope_boundaries.py`
