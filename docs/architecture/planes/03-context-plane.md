# Plane 3: Context

> Diagram: `docs/architecture/planes/03-context-plane.png`
> Components: Constraint Extractor, Prompt Registry, Scope Boundaries, Cross-Session Learning
> ADRs: ADR-010, ADR-012, ADR-013

## Purpose

The Context Plane provides the knowledge that agents need to execute tasks correctly. It extracts constraints from documents, resolves specialized prompts from the registry, validates tasks against scope boundaries, and accumulates learning across sessions.

## Components

| Component | Module | Owned State | Responsibility |
|-----------|--------|-------------|----------------|
| Constraint Extractor | `constraint_extractor.py` | ExtractionResult (constraints list) | Two-pass extraction: rule-based regex (default) + LLM (opt-in). Produces typed Constraint objects for DoR validation. |
| Prompt Registry | `prompt_registry.py` | DynamoDB table (prompt_name, version, content, hash, tags) | Versioned prompt storage with SHA-256 integrity. Context-aware selection by tech_stack tags. |
| Scope Boundaries | `scope_boundaries.py` | ScopeCheckResult (in_scope, confidence, warnings) | Validates tasks against factory limits. Rejects forbidden actions, computes confidence from available signals. |
| Cross-Session Learning | `.kiro/notes/` + Notes System | Hindsight notes, working memory | Persists insights across sessions. Agents consult shared notes for patterns discovered in previous tasks. |

## Constraint Extraction Flow

```
Data Contract (constraints + related_docs + tech_stack)
  │
  ▼
Pass 1: Rule-Based (regex, <1ms, zero cost)
  ├── Version pins: Python 3.11, Node 20
  ├── Latency thresholds: p99 < 200ms
  ├── Auth mandates: must use OAuth2
  ├── Encryption: AES-256, TLS 1.3
  └── Exclusions: must not use library X
  │
  ▼
Pass 2: LLM-Based (opt-in, ~2-5s, ~$0.01/task)
  └── Nuanced prose constraints
  │
  ▼
Merge + Deduplicate (rule-based takes precedence)
  │
  ▼
DoR Gate Validation (constraints vs tech_stack)
```

## Scope Boundary Signals

| Signal | Points | Description |
|--------|--------|-------------|
| tech_stack has configured tooling | +1 | Inner loop gates can run |
| acceptance_criteria >= 3 items | +1 | Clear halting condition |
| constraints field present | +1 | Boundaries are explicit |
| related_docs provided | +1 | Context is available |

Score >= 2 → high confidence. Score 1 → medium. Score 0 → low.

## Interfaces

| From | To | Data |
|------|-----|------|
| Data Plane (Router) | Constraint Extractor | Data contract (constraints, related_docs, tech_stack) |
| Constraint Extractor | FDE Plane (Agent Builder) | ExtractionResult with typed constraints |
| Prompt Registry | FDE Plane (Agent Builder) | Versioned prompt content + hash |
| Scope Boundaries | Data Plane (DoR Gate) | ScopeCheckResult (accept/reject + confidence) |

## Related Artifacts

- ADR-012: Over-Engineering Mitigations (LLM opt-in decision)
- Design: `docs/design/scope-boundaries.md`
- Flow 08: Cross-Session Learning
