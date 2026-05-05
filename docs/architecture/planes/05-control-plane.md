# Plane 5: Control

> Diagram: `docs/architecture/planes/05-control-plane.png`
> Components: SDLC Gates, DORA Metrics, Pipeline Safety, Failure Modes
> ADRs: ADR-012, ADR-013

## Purpose

The Control Plane provides governance, observability, and safety for the factory. It enforces quality gates at every stage, measures performance through DORA metrics, classifies why tasks do not complete, and provides automatic rollback when the pipeline encounters repeated errors.

## Components

| Component | Module | Owned State | Responsibility |
|-----------|--------|-------------|----------------|
| SDLC Gates | `sdlc_gates.py` | SDLCReport (gate results, pass/not-pass counts) | Inner loop (lint → test → build) with retry. Outer loop (DoR → Adversarial → Ship-Readiness). |
| DORA Metrics | `dora_metrics.py` | DynamoDB table (metric_id, type, value, dimensions) | Records Lead Time, CFR, MTTR, Deployment Frequency. Domain segmentation by tech_stack. Factory Health Report. |
| Pipeline Safety | `pipeline_safety.py` | DiffReviewResult, RollbackResult | PR diff review (secrets, debug code, size). Automatic rollback to checkpoint on repeated errors. |
| Failure Modes | `failure_modes.py` | FailureModeResult (code, category, recovery) | Classifies WHY tasks do not complete (FM-01 through FM-99). Heuristic rules on execution context. |

## Inner Loop (per-commit)

```
lint → typecheck → unit_test → build
```

- Runs inside the Engineering Agent's execution
- Max 3 retries per gate before the gate result is recorded as not passing
- Commands resolved automatically from tech_stack (Python → ruff/pytest, Go → go vet/go test)

## Outer Loop (per-task)

```
DoR Gate → Constraint Extraction → Adversarial Challenge → Ship-Readiness
```

- Runs at pipeline boundaries
- If any gate does not pass, the pipeline is blocked
- Ship-Readiness validates that all inner + outer gates passed before PR opens

## DORA Performance Levels

| Level | Lead Time | Deploy Frequency | CFR | MTTR |
|-------|-----------|-----------------|-----|------|
| Elite | < 1h | > 1/day | < 5% | < 1h |
| High | < 24h | > 1/week | < 10% | < 24h |
| Medium | < 7d | > 1/month | < 15% | < 7d |
| Low | > 7d | < 1/month | > 15% | > 7d |

The Factory Health Report computes the current DORA level and persists it to S3 for dashboard consumption.

## Failure Mode Taxonomy

| Code | Category | Recovery Action |
|------|----------|-----------------|
| FM-01 | SPEC_AMBIGUITY | Request clarification |
| FM-02 | CONSTRAINT_CONFLICT | Request human resolution |
| FM-03 | TOOL_FAILURE | Retry with backoff |
| FM-05 | COMPLEXITY_EXCEEDED | Decompose into subtasks |
| FM-06 | TEST_REGRESSION | Rollback and retry |
| FM-08 | TIMEOUT | Rollback and report |
| FM-09 | AUTH_FAILURE | Report environment error |
| FM-99 | UNKNOWN | Log full context for review |

## Rollback Mechanism

1. `record_branch_checkpoint()` captures HEAD SHA before agent starts
2. If Circuit Breaker exhausts 3 retries → `rollback_to_checkpoint()`
3. `git reset --hard {checkpoint}` on the feature branch (refuses main/master)
4. `git clean -fd` removes untracked files
5. Task marked with failure mode classification for post-mortem

## Interfaces

| From | To | Data |
|------|-----|------|
| FDE Plane (Pipeline) | SDLC Gates | Workspace path + tech_stack for gate execution |
| SDLC Gates | DORA Metrics | GateResult (timing, attempts, verdict) |
| FDE Plane (Pipeline) | DORA Metrics | Stage durations, task outcomes, tech_stack |
| Pipeline Safety | DORA Metrics | Rollback events, diff review results |
| Failure Modes | DORA Metrics | FailureModeResult dimensions |

## Related Artifacts

- ADR-012: Over-Engineering Mitigations (rollback, PR review decisions)
- ADR-013: Enterprise-Grade Autonomy (failure modes, domain segmentation)
- Design: `docs/design/scope-boundaries.md` (performance targets)
