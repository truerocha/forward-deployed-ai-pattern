# ADR-034: Knowledge Graph as FDE Reconnaissance Layer

> **Status**: Proposed
> **Date**: 2026-05-15
> **Author**: Staff SWE (rocand) + Kiro FDE Protocol
> **Supersedes**: None
> **Related**: ADR-019, ADR-020, ADR-024, ADR-029
> **Pattern Source**: Code Intelligence Knowledge Graph pattern (open-source prior art)

## Context

FDE Phase 1 (Reconnaissance) relies on static edge tables and file reading.
Code intelligence knowledge graphs precompute relational intelligence at index
time — call chains, imports, clusters, execution flows — exposed via MCP tools.

## Decision

Integrate seven capabilities into the FDE pipeline, inspired by the knowledge
graph pattern for codebase understanding.

## Feature 1: Typed Pipeline Phase DAG Runner

Replace linear orchestrator with typed DAG. Phases declare deps explicitly.
Kahn's topological sort validates at startup. Only declared deps visible.

Phase DAG: route → extract_constraints → [scope, autonomy] → risk →
execution_plan → [dispatch, gates] → safety → completion

## Feature 2: Knowledge Graph as Reconnaissance Layer

Add a code intelligence MCP server. Phase 1 becomes graph queries:
- impact analysis (blast radius)
- symbol context (360-degree view)
- semantic query (process-grouped search)
- detect_changes (pre-commit scope check)

## Feature 3: Staleness-Aware Hooks

PostToolUse: detect when writes invalidate reconnaissance.
PreToolUse: suggest graph queries over raw file reading.
Compare HEAD against last indexed commit.

## Feature 4: Machine-Readable DoD

7 dimensions: Correctness, Architecture, Contracts, Scope Match,
Knowledge Validation, Pipeline Testing, Not-Done Signals.
Machine-checkable "Not Done" signals block completion.

## Feature 5: Compound Review Agents

6 specialized reviewers triggered by change surface:
waf-corpus-guardian, pipeline-edge-reviewer, portal-rendering-reviewer,
security-reviewer, performance-reviewer, cross-pattern-consistency.

## Feature 6: Tiered Evidence Resolution

4 tiers inspired by type-resolution systems in code intelligence tools:
Tier 0 (Explicit, 0.90-1.00), Tier 0b (Composite, 0.75-0.89),
Tier 1 (Inferred, 0.50-0.74), Tier 2 (Transitive, 0.30-0.49).
Fixpoint loop for chain resolution. Conservative: missed > misleading.

## Feature 7: Process Detection as Pipeline Tracing

Structured traces per review run. Each step records module, edge,
input/output counts, duration. Validate against baseline traces.
Funnel ratio detects amplification bugs.

## Implementation Plan

Phase A (2d): F2 + F3 | Phase B (3d): F4 + F5
Phase C (5d): F7 + F6 | Phase D (5d): F1

## References

- docs/internal/knowledge-graph-pattern/ (internal reference material)
- fde-design-swe-sinapses.md
- ADR-019: Agentic Squad Architecture
- ADR-020: Conductor Orchestration Pattern
- ADR-024: SWE Synapses Cognitive Architecture
