# ADR-033: Brown-Field Elevation & DDD Design Phase

## Status
Accepted

## Date
2026-05-15

## Context

FDE's Conductor (ADR-020) currently goes from task intake directly to code generation. This works for simple tasks but creates problems for:

1. **Brown-field modifications** — The coder agent modifies existing code without a formal understanding of the domain model, leading to architectural drift and coupling violations.
2. **Complex green-field features** — Without explicit domain modeling, the coder agent makes implicit design decisions that are never validated by the architect or adversarial agents.

The AI-DLC methodology (awslabs/aidlc-workflows) explicitly includes Domain Design and Logical Design phases between requirements and code generation. Our FDE pipeline should offer the same capability as an opt-in extension.

## Decision

Add two optional Conductor steps that activate based on `fde-profile.json`:

### Step 0: Brown-Field Elevation (when `extensions.brown-field-elevation = true`)

**Purpose**: Reverse-engineer existing code into a semantic model before modifying it.

**Agent**: `architect` with `model_tier: reasoning`

**Inputs**: Files identified during Phase 1 Reconnaissance

**Outputs**: `aidlc-docs/design-artifacts/elevation-model.md`

**Content**:
```markdown
# Elevation Model — {bounded_context_name}

## Static Model
| Component | Responsibility | Dependencies |
|-----------|---------------|--------------|
| ... | ... | ... |

## Dynamic Model
### Flow: {primary_use_case}
1. {Component A} receives {trigger}
2. {Component A} calls {Component B}.{method}
3. ...

## Boundary Map
| File | Bounded Context | Layer |
|------|----------------|-------|
| ... | ... | domain/application/infrastructure |

## Change Impact Assessment
- Components affected: [list]
- Coupling risk: low/medium/high
- Suggested approach: [extend/refactor/replace]
```

**Activation logic**:
- Always runs when `brown-field-elevation = true` AND the task modifies existing files
- Skipped for pure green-field tasks (no existing files in scope)
- Output is cached — subsequent tasks in the same bounded context reuse it

### Step 1: DDD Design Phase (when `extensions.ddd-design-phase = true`)

**Purpose**: Produce explicit domain and logical design before code generation.

**Agent**: `architect` with `model_tier: reasoning`

**Inputs**: Task intake contract + elevation model (if available)

**Outputs**:
- `aidlc-docs/design-artifacts/domain-model.md`
- `aidlc-docs/design-artifacts/logical-design.md`

**Domain Model Content**:
```markdown
# Domain Model — {unit_name}

## Aggregates
### {AggregateName}
- Root entity: {EntityName}
- Value objects: [list]
- Domain events: [list]
- Invariants: [list]

## Repositories
| Repository | Aggregate | Operations |
|-----------|-----------|-----------|
| ... | ... | find, save, delete |

## Domain Services
| Service | Responsibility | Collaborators |
|---------|---------------|--------------|
| ... | ... | ... |
```

**Logical Design Content**:
```markdown
# Logical Design — {unit_name}

## Architecture Decisions
### ADR: {decision_title}
- Context: {why this decision is needed}
- Decision: {what we chose}
- Consequences: {tradeoffs}

## Pattern Selection
| Pattern | Rationale | AWS Service |
|---------|-----------|-------------|
| CQRS | Separate read/write models for... | DynamoDB + OpenSearch |
| Circuit Breaker | External dependency X is unreliable | Step Functions |

## Service Mapping
| Domain Component | AWS Service | Configuration |
|-----------------|-------------|---------------|
| {Aggregate} | DynamoDB | Single-table, GSI for... |
| {Domain Event} | EventBridge | Bus: factory-events |

## Well-Architected Alignment
| Pillar | Relevant Question | How Addressed |
|--------|------------------|---------------|
| Reliability | REL 3 | Circuit breaker on... |
| Security | SEC 2 | IAM least privilege for... |
```

**Activation logic**:
- Runs when `ddd-design-phase = true`
- Cognitive depth threshold: `conductor.auto-design-threshold` (default 0.5)
  - depth < threshold → skip (simple task, no design needed)
  - depth >= threshold → activate automatically
- Can be forced via task metadata: `"require_design": true`

### Conductor Plan Integration

When both extensions are enabled, the Conductor plan looks like:

```
Step 0: [architect] Elevate existing code (brown-field only)
Step 1: [architect] Domain design
Step 2: [architect] Logical design  
Step 3: [coder] Implement per design (access_list: [0, 1, 2])
Step 4: [reviewer] Verify implementation matches design (access_list: [1, 2, 3])
Step 5: [adversarial] Challenge design + implementation (access_list: all)
```

The coder agent's `access_list` includes the design steps — it MUST reference the domain model and logical design when generating code. The reviewer agent validates conformance.

### Artifact Persistence

Design artifacts are stored in `aidlc-docs/design-artifacts/` and persist across tasks:
- Elevation models are keyed by bounded context (reused until code changes significantly)
- Domain models are keyed by unit name (updated when the unit's scope changes)
- Logical designs are keyed by unit name (updated when architecture decisions change)

A `aidlc-docs/design-artifacts/.index.json` tracks which artifacts exist and their freshness.

## Consequences

### Positive
- Explicit design validation before code generation reduces architectural drift
- Brown-field elevation prevents "blind modification" of existing systems
- Design artifacts serve as documentation (not just throwaway context)
- Aligns with AI-DLC Construction Phase methodology
- Adversarial agent can challenge design decisions, not just code

### Negative
- Adds 1-2 Conductor steps (increases task duration by ~30-60s for reasoning model)
- Design artifacts may become stale if not refreshed
- Requires `reasoning` model tier (higher cost per task)

### Mitigations
- Opt-in only — disabled by default in `fde-profile.json`
- Cognitive depth threshold prevents activation on trivial tasks
- Artifact caching amortizes cost across multiple tasks
- Staleness detection: if source files changed since last elevation, re-run

## Related
- ADR-020 — Conductor Orchestration Pattern
- ADR-029 — Cognitive Autonomy Model (depth calibration)
- ADR-032 — FDE Extension Opt-In System
- AI-DLC Construction Phase (awslabs/aidlc-workflows)
- WAF Serverless Lens — service mapping patterns
