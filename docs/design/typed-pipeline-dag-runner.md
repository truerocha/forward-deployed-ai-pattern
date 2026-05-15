# Typed Pipeline Phase DAG Runner — Design Document

> **Status**: Design
> **Date**: 2026-05-15
> **ADR**: ADR-033 Feature 1
> **Synapse Alignment**: Synapse 7 (Harness Primacy — 98.4% infrastructure)

## Problem

Our orchestrator uses a linear pipeline with hidden coupling between phases.
Adding a new phase requires understanding implicit ordering.

## Solution

Replace with a typed DAG where phases declare dependencies explicitly.
Kahn's topological sort validates at startup. Only declared deps visible.

## Phase DAG

```
route → extract_constraints → [scope_boundaries, autonomy_level]
  → risk_assessment → execution_plan → [agent_dispatch, sdlc_gates]
    → pipeline_safety → completion
```

| Phase | Deps | Output Type |
|-------|------|-------------|
| `route` | (root) | DataContract |
| `extract_constraints` | `route` | ConstraintSet |
| `scope_boundaries` | `extract_constraints` | ScopeDecision |
| `autonomy_level` | `extract_constraints` | AutonomyConfig |
| `risk_assessment` | `scope_boundaries`, `autonomy_level` | RiskScore |
| `execution_plan` | `risk_assessment` | WorkflowPlan |
| `agent_dispatch` | `execution_plan` | AgentResults |
| `sdlc_gates` | `agent_dispatch` | GateResults |
| `pipeline_safety` | `sdlc_gates` | SafetyDecision |
| `completion` | `pipeline_safety` | CompletionRecord |

## Key Properties

1. **Explicit data flow**: Only declared deps visible to each phase
2. **Startup validation**: Cycles, missing deps, duplicates caught before execution
3. **Per-phase timing**: Automatic observability without instrumentation
4. **Testability**: Mock only declared deps, not entire upstream chain

## Validation at Startup

- No duplicate phase names
- All declared deps exist
- No cycles (DFS traces concrete path: `A → B → C → A`)
- Reports transitively blocked dependents count

## Migration Path

1. Extract current linear steps into PipelinePhase implementations
2. Declare explicit deps (currently implicit via execution order)
3. Replace sequential calls with `run_pipeline(phases, ctx)`
4. Validate: same behavior, explicit dependency graph
5. Enable observability: per-phase timing automatically available
