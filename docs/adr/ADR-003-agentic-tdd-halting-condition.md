# ADR-003: Agentic TDD as Halting Condition

## Status
Accepted

## Context
AI agents generating code without a defined stopping criterion produce scope creep, over-engineering, and hallucinated features. The agent needs a mathematical halting condition: a clear, testable definition of "done."

## Decision
This design adopts Agentic TDD (Test-Driven Development) where:
1. Tests are generated FROM spec scenarios BEFORE production code (shift-left)
2. The human approves the tests (the halting condition is human-validated)
3. The agent's sole implementation objective is to make the approved tests pass
4. Approved tests are immutable — the agent cannot modify them (enforced by preToolUse VETO hook)

## Consequences
- The agent cannot over-engineer — its scope is bounded by the test contract
- Lazy mocking of core business rules is prohibited (Anti-SPOF 1)
- The human reviews test contracts (faster than reviewing implementation code)
- If tests are wrong, the implementation will be wrong — spec quality matters
