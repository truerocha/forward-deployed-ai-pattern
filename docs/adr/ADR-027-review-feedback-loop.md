# ADR-027: Review Feedback Loop — ICRL-Enhanced Closed-Loop Learning

## Status

Accepted (v2 — ICRL Enhancement)

## Date

2026-05-13 (v1), 2026-05-13 (v2 — ICRL)

## Context

The factory operates **open-loop** with respect to human PR reviews. When a human
reviewer submits "changes_requested" or comments "sent back for re-work," the factory
has no mechanism to:

1. **Detect** the rejection signal
2. **Record** it as a DORA Change Failure (CFR is understated)
3. **Learn** from it (Risk Engine weights never update for false negatives)
4. **Re-execute** the pipeline with review feedback as additional context

This means:
- DORA CFR only counts pipeline crashes, not "PR produced but rejected by human"
- Trust metrics (`record_pr_outcome`) are never called — no mechanism reads PR state
- Happy Time rework tracking is never triggered
- The Anti-Instability Loop cannot detect quality degradation from human rejections
- The factory repeats the same mistakes because weights never adjust

### Research Grounding

- **c-CRAB (Code Review Agent Benchmark, arXiv:2603.23448)**: Demonstrates that
  human review feedback is the ground truth for evaluating agent-generated code.
  Our loop uses human reviews as the authoritative signal for weight adjustment.

- **HULA (Human-in-the-Loop Agents, arXiv:2411.12924)**: Establishes that agents
  must incorporate human feedback to refine plans and code iteratively. Our re-trigger
  mechanism implements this pattern at the pipeline level.

- **DORA 2025 Report**: Identifies that AI shifts the bottleneck from writing to
  reviewing code. For every 25% increase in AI adoption, delivery stability drops 7.2%.
  Without measuring human rejections as failures, we cannot detect this instability.

- **ThoughtWorks Technology Radar (2026)**: Adds "rework rate" as a fifth DORA metric.
  Our implementation captures this directly from PR review events.

- **Agentic PR Studies (arXiv:2509.14745, arXiv:2604.24450)**: Show that autonomous
  agents create PRs at scale but acceptance rates vary. Reviewer bot feedback patterns
  must be captured to close the quality loop.

## Decision

Implement a **Review Feedback Loop** that:

1. **Detects** PR review events via a new EventBridge rule matching
   `pull_request_review.submitted` with state `changes_requested`, and
   `issue_comment.created` with re-work signal keywords.

2. **Classifies** the feedback into: full re-work, partial fix, or informational comment.

3. **Records metrics** across all existing metric systems:
   - DORA: `record_change_failure(is_failure=True)` — CFR goes up
   - Trust: `record_pr_outcome(accepted=False)` — trust score drops
   - Verification: `record_review_completed(accepted=False)` — rejection rate tracked
   - Happy Time: `record_rework_time()` — toil increases
   - Net Friction: rejection_rework_hours increases upstream friction

4. **Updates Risk Engine weights** via `update_weights_from_outcome(actual_outcome="failed")`
   — Bayesian learning from false negatives (predicted success, actual rejection).

5. **Re-triggers the pipeline** with review feedback injected as additional context
   constraint, using the Conductor's `refine_plan()` mechanism.

6. **Feeds the Anti-Instability Loop** — PR rejections counted as CFR will trigger
   autonomy reduction when thresholds are breached.

## Architecture

```
GitHub PR Review Event (changes_requested / re-work comment)
  → API Gateway (existing webhook endpoint)
  → EventBridge (new rule: fde.github.webhook / pull_request_review.submitted)
  → Target 1: Review Feedback Lambda (classifies + records metrics)
  → Target 2: Webhook Ingest Lambda (updates task_queue status to REWORK)
  → If full re-work: EventBridge emits fde.internal / task.rework_requested
    → ECS RunTask (re-executes pipeline with feedback context)
```

## Consequences

### Positive
- DORA CFR becomes accurate (includes human rejections, not just pipeline crashes)
- Risk Engine learns from mistakes (weights adjust on false negatives)
- Anti-Instability Loop can detect quality degradation from human feedback
- Factory becomes closed-loop (learns from every rejection)
- Trust metrics reflect actual human confidence in factory outputs
- Happy Time accurately captures rework toil

### Negative
- Additional EventBridge rule + Lambda adds ~$0.50/month infrastructure cost
- Re-trigger mechanism could cause loops if review feedback is ambiguous
  (mitigated by max_rework_attempts=2 circuit breaker)
- Requires GitHub webhook to include `pull_request_review` events
  (must be configured in repository webhook settings)

### Risks
- False positive re-work detection (informational comments misclassified as rejections)
  → Mitigated by keyword classification with confidence threshold
- Re-work loop (agent produces same bad output repeatedly)
  → Mitigated by circuit breaker (max 2 re-work attempts per task)
- Metric inflation (single PR rejection counted multiple times)
  → Mitigated by idempotency key (task_id + pr_id + review_id)

## Well-Architected Alignment

- **OPS 6 (Telemetry)**: Every PR review event is captured and classified
- **REL 2 (Workload Architecture)**: Decoupled detection from re-execution
- **SEC 8 (Incident Management)**: Review rejections treated as quality incidents
- **COST 5 (Resource Optimization)**: Lambda-based, pay-per-invocation
- **PERF 3 (Monitoring)**: CloudWatch metrics for review feedback latency

## V2: ICRL Enhancement — In-Context Reinforcement Learning

### Motivation

V1 implements a reactive feedback loop (detect → record → re-trigger). V2 transforms
this into an **active learning engine** using In-Context Reinforcement Learning (ICRL)
principles. The agent adapts to repository-specific review patterns through trial-and-error
entirely within the prompt window — no retraining or weight fine-tuning required.

### ICRL Techniques Applied

#### 1. MCTS for Multi-Trajectory Rework (Monte Carlo Tree Search)

Instead of linear re-execution (single trajectory), the Conductor generates N=3 diverse
candidate plans for rework. Each is scored against deterministic verification tools
(linter, type-checker). Only the highest-scoring plan proceeds to full execution.

```
Rework event → Conductor.generate_candidate_plans(N=3)
  → For each plan: lightweight_verify(plan) → score
  → Select best-scoring plan → ECS executes → PR
```

#### 2. ICRL Episode History (In-Context Learning from Past Rejections)

Review feedback is stored as structured episodes:
`Episode = (task_context, agent_action, human_reward, correction)`

At rework time, the last 5 relevant episodes for the same repo are injected into
the agent's context window. After 10+ episodes accumulate, a "pattern digest"
(common rejection reasons) replaces individual episodes.

#### 3. Verifiable Tool-Use Rewards (Deterministic Verification Gate)

Before PR creation, the agent runs available verification tools:
`linter → type-checker → test suite` (in order of availability).
Each provides a binary reward signal. Agent gets max 3 inner iterations to achieve
all-pass. Actual execution time replaces the estimated 1800s in Happy Time.

#### 4. Structural Uncertainty Annotations (Precision Escalation)

After code generation, each changed file is analyzed against proxy signals:
- Risk Engine hotspot score
- Module boundary crossing
- Public API modification

Changes exceeding 2/3 signals get annotated in the PR as `[NEEDS_HUMAN_DECISION]`.
Cap at 3 annotations per PR.

### Conditional Autonomy (Replaces Blanket Reduction)

| Classification | Autonomy Impact | Rationale |
|---------------|----------------|-----------|
| `full_rework` | -1 for new tasks, maintain for rework task | Judgment was wrong, but don't suppress rework capability |
| `partial_fix` | Unchanged | Approach was right, execution had gaps |
| Successful rework | +1 | Agent demonstrated learning (positive reinforcement) |
| Circuit breaker trip | -2 | Systemic problem, escalate to Staff Engineer |

### Execution Lock (Prevents Infinite Loops)

- Separate event source (`fde.internal`) — cannot trigger `issue.labeled` rule
- DynamoDB conditional write: `execution_lock#{task_id}#{attempt}`
- No issue re-labeling, no card movement, no circular dependency
- Circuit breaker: max 2 attempts, then escalate

### Data Contract Extension (Additive, Backward-Compatible)

New optional fields on `task_queue` (DynamoDB schemaless — no migration):
- `rework_attempt`: int (default: 0)
- `rework_feedback`: str (default: "")
- `rework_constraint`: str (default: "")
- `original_pr_url`: str (default: "")

Issue template: NO CHANGE. Issue labels: NO CHANGE.

### ICRL-Enhanced Architecture

```
Human rejects PR
  │
  ▼
Review Feedback Lambda (classifies, records metrics)
  │
  ├─ ICRL Episode stored (task_context, action, reward, correction)
  ├─ Conditional Autonomy Decision
  │
  ▼
Execution Lock (DynamoDB conditional write, prevents parallel runs)
  │
  ▼
task.rework_requested → ECS RunTask
  │
  ▼
Conductor with MCTS (generates 3 candidate plans, verifies each)
  │
  ▼
Agent executes with ICRL Episode History in context
  │
  ▼
Verification Reward Gate (linter → type-check → tests, max 3 inner loops)
  │
  ▼
Structural Uncertainty Analysis (annotates high-uncertainty changes)
  │
  ▼
New PR created (old PR closed, annotations guide reviewer)
```

### Maturity Advancement

| Dimension | V1 (Reactive) | V2 (ICRL Adaptive) |
|-----------|--------------|-------------------|
| Learning | Bayesian weight updates only | ICRL episodes + pattern digests + weights |
| Exploration | Single-trajectory retry | MCTS multi-trajectory with verification scoring |
| Verification | Human-only (post-hoc) | Deterministic tools (pre-PR) + Human (post-PR) |
| Escalation | Binary (whole task at one level) | Granular (per-change uncertainty thresholds) |
| Autonomy | Blanket reduction on failure | Conditional by classification |

## References

- [c-CRAB: Code Review Agent Benchmark](https://arxiv.org/abs/2603.23448)
- [HULA: Human-in-the-Loop Agents](https://arxiv.org/abs/2411.12924)
- [DORA 2025 Report](https://dora.dev/research/2025/dora-report/)
- [ThoughtWorks Radar: DORA Metrics + Rework Rate](https://www.thoughtworks.com/radar/techniques/dora-metrics)
- [Agentic PRs in OSS](https://arxiv.org/abs/2604.24450)
- [RepoSearch-R1: MCTS for Repository-Level QA](https://arxiv.org/abs/2505.16339)
- [ICRL: In-Context Reinforcement Learning](https://arxiv.org/abs/2602.17084)
- [Self-Improving Coding Agent](https://arxiv.org/abs/2504.15228)
- ADR-013: Enterprise-Grade Autonomy and Observability
- ADR-018: Branch Evaluation Agent
- ADR-020: Conductor Orchestration Pattern
- ADR-022: Risk Inference Engine
