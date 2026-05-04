# ADR-002: Spec as Control Plane (NLSpec Pattern)

## Status
Accepted

## Context
Traditional AI-assisted development uses chat prompts as the primary interface. This leads to context degradation across sessions, scope ambiguity, and no auditable record of intent. The StrongDM Attractor project demonstrated that natural language specifications can serve as the control instrument for autonomous code generation.

## Decision
This design adopts the Spec as Control Plane pattern. Every unit of work entering the factory must be expressed as a structured spec in `.kiro/specs/` with:
- YAML frontmatter (status, issue reference, engineering level)
- NLSpec format (Context, Narrative, Acceptance Criteria in BDD, Constraints, Definition of Done)
- Holdout scenarios (30% of acceptance criteria reserved for ship-readiness validation)

The agent cannot begin execution without `status: ready` in the frontmatter.

## Consequences
- Spec quality becomes the primary bottleneck (by design — this is the StrongDM insight)
- The human invests more time writing specs and less time reviewing code
- Holdout scenarios prevent the agent from gaming its own tests
- Specs serve as auditable records of intent for every change
