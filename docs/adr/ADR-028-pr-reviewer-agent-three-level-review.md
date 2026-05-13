# ADR-028: PR Reviewer Agent — Three-Level Review Architecture

## Status

Accepted

## Date

2026-05-13

## Context

The factory operates at L2/L3 autonomy despite having L4/L5 infrastructure because
there is no independent quality gate on the FINAL deliverable. The adversarial gate
runs mid-execution (on individual writes), but no agent validates the assembled PR
against the original issue spec before a human sees it.

This creates a structural bottleneck:
- Human is the FIRST reviewer (not the last resort)
- Every PR requires human attention regardless of quality
- L4 (Approver) and L5 (Observer) are unreachable
- The squad reviews its own work (confirmation bias)
- DORA Lead Time includes human review wait (hours/days)

### Root Cause (5 Whys)

1. Why does the human reject PRs? → PR doesn't match spec or has quality issues.
2. Why doesn't the factory catch this? → No agent validates PR against spec post-implementation.
3. Why not? → Adversarial gate runs mid-execution, not on the final assembled deliverable.
4. Why not? → Architecture assumes "if each step passes gates, the whole is correct."
5. Why is that wrong? → Integration errors exist between steps. The whole is not the sum of parts.

### Research Grounding

- **c-CRAB (arXiv:2603.23448)**: Code review benchmarks show that independent review
  (not self-review) is the ground truth for quality assessment.
- **Agentic PR Studies (arXiv:2604.24450)**: Reviewer bots that are independent from
  the PR author produce higher-quality feedback than self-review.
- **DORA 2025**: The bottleneck shifts from writing to reviewing. An agent reviewer
  that runs in seconds (not hours) eliminates the review bottleneck.
- **ICRL (arXiv:2602.17084)**: The reviewer agent maintains its own episode store,
  learning from its own review decisions independently of implementation patterns.

## Decision

Implement a **three-level review architecture** with an independent `fde-pr-reviewer-agent`:

### Level 1: fde-pr-reviewer-agent (Independent, Isolated)

- Runs as a SEPARATE ECS task (not in the squad's execution context)
- Reads ONLY: original issue spec + PR diff + test results
- Does NOT read: squad reasoning, Conductor plans, intermediate outputs
- Maintains its OWN ICRL episode store (`icrl_review_episode#` prefix)
- Output: APPROVE | REWORK (with structured feedback using GateFeedbackFormatter)
- If REWORK: triggers internal rework loop (squad never exposes bad PR to human)

### Level 2: Branch Evaluation Agent (Automated Scoring)

- Existing workflow (unchanged)
- Multi-dimensional quality score
- If score >= 8.0 AND L4/L5 AND Level 1 approved → auto-merge
- If score >= 6.0 → mark ready for human review
- If score < 6.0 → back to Level 1 with score feedback

### Level 3: Human Reviewer (Last Resort)

- Only sees PRs that Level 1 has already approved
- Focused on: architectural decisions, business logic, annotated uncertainty points
- NOT reviewing: syntax, formatting, error handling (already validated by L1+L2)
- Required only for L2/L3 autonomy or when L1+L2 disagree

### DTL Committer Decision Matrix

| L1 Verdict | L2 Score | Autonomy | Action |
|-----------|----------|----------|--------|
| APPROVE | >= 8.0 | L4/L5 | Auto-merge (squash) |
| APPROVE | >= 6.0 | L3 | Mark ready for human review |
| APPROVE | >= 6.0 | L2 | Assign human reviewer |
| APPROVE | < 6.0 | Any | Back to L1 with "score too low" |
| REWORK | Any | Any | Internal rework loop (human never sees it) |

### Isolation Guarantees

The reviewer agent MUST be isolated because:
- Shared context → anchoring bias (assumes approach is correct because it was "planned")
- Shared reasoning → confirmation bias (fills gaps with agent's intent, not code reality)
- Shared ICRL episodes → groupthink (same learning, same blind spots)
- Shared ECS task → resource contention + shared failure mode

## Architecture

```
Squad completes implementation
  │
  ▼
DTL Committer creates DRAFT PR (not ready for review)
  │
  ▼
Level 1: fde-pr-reviewer-agent (isolated ECS task)
  ├─ Input: issue spec + PR diff + test results
  ├─ Context: own ICRL review episodes (NOT squad episodes)
  ├─ Output: ReviewVerdict (APPROVE/REWORK + structured feedback)
  │
  ├─ If REWORK → emit task.internal_rework (internal loop, max 2)
  │   └─ Squad fixes → new commit → back to Level 1
  │
  ├─ If APPROVE → DTL marks PR "ready for review"
  │
  ▼
Level 2: Branch Evaluation Agent (GitHub Actions)
  ├─ Triggers on: pull_request [opened, synchronize]
  ├─ Scores: multi-dimensional (existing)
  │
  ▼
DTL Committer Decision Matrix
  ├─ L1=APPROVE + L2>=8.0 + L4/L5 → auto-merge
  ├─ L1=APPROVE + L2>=6.0 + L2/L3 → assign human
  ├─ L1=APPROVE + L2<6.0 → back to L1
```

## Consequences

### Positive
- Enables true L4/L5 autonomy (factory can self-approve high-quality PRs)
- Human never sees PRs that the factory's own reviewer rejected (internal rework)
- Reduces human review load by 60-80% (only edge cases reach human)
- DORA Lead Time drops dramatically (agent review = seconds, not hours)
- Independent reviewer catches integration errors the squad misses
- Reviewer learns independently (own ICRL store, own patterns)

### Negative
- Additional ECS task per PR (~$0.02 per review, ~30s execution)
- Adds 30-60s to pipeline before PR is visible to human
- Reviewer agent needs its own prompt engineering and calibration
- Risk of false approvals (reviewer too lenient) or false rejections (too strict)

### Risks
- Reviewer becomes a rubber stamp (always approves) → Mitigated by tracking approval rate; alert if >95%
- Reviewer becomes a blocker (always rejects) → Mitigated by circuit breaker (max 2 internal rework cycles)
- Reviewer and squad develop adversarial relationship → Not possible (reviewer has no memory of squad reasoning)
- Auto-merge introduces regressions → Mitigated by Level 2 score threshold (8.0) + test suite must pass

## Well-Architected Alignment

- **OPS 6 (Telemetry)**: Every review decision logged with structured feedback
- **OPS 8 (Evolve operations)**: Reviewer learns from outcomes via ICRL
- **REL 2 (Workload Architecture)**: Isolated execution prevents cascade failures
- **SEC 8 (Incident Management)**: Bad PRs caught before merge, not after
- **PERF 3 (Monitoring)**: Review latency tracked as a DORA sub-metric
- **COST 5 (Resource Optimization)**: Reduces human review hours (most expensive resource)

## References

- [c-CRAB: Code Review Agent Benchmark](https://arxiv.org/abs/2603.23448)
- [Agentic PRs in OSS](https://arxiv.org/abs/2604.24450)
- [DORA 2025 Report](https://dora.dev/research/2025/dora-report/)
- [ICRL: In-Context Reinforcement Learning](https://arxiv.org/abs/2602.17084)
- ADR-018: Branch Evaluation Agent
- ADR-019: Agentic Squad Architecture
- ADR-027: Review Feedback Loop (ICRL Enhancement)
