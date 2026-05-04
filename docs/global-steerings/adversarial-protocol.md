---
inclusion: auto
---

# Adversarial Protocol (Universal Law)

For any task involving architecture decisions (L3+), execute in 3 phases:

## Phase 1: The Builder
- Analyze scope using 5W2H
- Extract constraints from the spec
- Design the solution

## Phase 2: The Attacker (MANDATORY)
- You CANNOT agree with Phase 1 on first review
- Find at least 2 flaws: race conditions, single points of failure, I/O bottlenecks, security gaps, scalability limits
- For each flaw: state the attack vector and the impact

## Phase 3: The Handoff
- Refactor the design to address the attacks from Phase 2
- Save constraints to .kiro/specs/WORKING_MEMORY.md
- Only THEN proceed to implementation

If you skip Phase 2, the adversarial gate hook will catch you on the first write.
