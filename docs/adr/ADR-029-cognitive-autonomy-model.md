# ADR-029: Cognitive Autonomy Model — Decoupled Capability + Authority

## Status

Accepted

## Date

2026-05-13

## Context

The factory uses a single "autonomy level" (L1-L5) that conflates two orthogonal
concerns: HOW MUCH reasoning power to apply (capability) and WHAT the factory is
ALLOWED to do with the output (authority). This creates a death spiral:

```
High CFR → Anti-Instability Loop reduces autonomy level
  → Fewer agents deployed (capability reduced)
  → Worse output quality (less verification, no adversarial review)
  → More failures → Higher CFR → Even lower autonomy
  → Factory permanently stuck at L2/L3
```

Evidence from GH-94 (cognitive-wafr#94):
- Issue labeled `factory/level:L4` (complex orchestrator with 6 dependencies)
- Factory operated at L3 (downgraded by static classifier)
- Only 4/8 milestones completed (no adversarial, no architect, no fidelity)
- `static-gates` CI check FAILED (quality issues not caught pre-PR)
- Result: incomplete, low-quality PR that requires human rework

Root cause: the factory was UNDER-RESOURCED because the autonomy system reduced
capability when it should have only reduced authority.

## Decision

Replace the single L1-L5 autonomy level with two orthogonal axes:

### Axis 1: Capability Depth (0.0-1.0)

Determines HOW the factory executes — squad size, model tier, verification rigor.

Computed from cognitive signals:
- Risk Engine score (primary)
- Dependency/blocking count (integration complexity)
- ICRL failure history (domain difficulty)
- Synapse signals (decomposition cost, catalog confidence, interface depth)
- CFR history (RAISES floor — more failures = need MORE capability)

**Key rule: Capability NEVER decreases on failure.**

| Depth | Squad | Model | Verification | Topology |
|-------|-------|-------|-------------|----------|
| 0.0-0.3 | 2 | fast | linter | sequential |
| 0.3-0.5 | 4 | standard | linter+types | sequential |
| 0.5-0.7 | 6 | reasoning | full suite | tree |
| 0.7-1.0 | 8 | deep | full+MCTS | debate |

### Axis 2: Delivery Authority (earned)

Determines WHAT the factory is allowed to do with the output.

Computed from trust signals (POST-execution):
- PR Reviewer verdict + Branch Evaluation score
- CFR history + Trust score + Consecutive successes

**Key rule: Authority is EARNED by output quality.**

| Authority | Condition | Action |
|-----------|-----------|--------|
| auto_merge | CFR<10% + trust>80% + 3+ successes | Squash merge |
| ready_for_review | L1 approve + L2>=6.0 | Human reviews |
| blocked | CFR>30% OR override | Escalate |

### Anti-Instability Loop Change

Before: CFR up → autonomy down → fewer agents (death spiral)
After: CFR up → authority down + capability floor UP (recovery spiral)

## Consequences

### Positive
- Breaks the death spiral
- Enables L4/L5 organically (earned by quality)
- GH-94 fixed: 6 deps → depth 0.6+ → full squad → all milestones
- Cost-efficient: simple tasks still get depth 0.2

### Negative
- Two axes slightly harder to explain
- Legacy compatibility shim needed
- Cold-start relies on Risk Engine only

## References

- ADR-013: Enterprise-Grade Autonomy (superseded for capability axis)
- ADR-022: Risk Inference Engine (primary capability signal)
- ADR-027: Review Feedback Loop (ICRL failure history)
- ADR-028: PR Reviewer Agent (L1 authority signal)
- [DORA 2025](https://dora.dev/research/2025/dora-report/)
