# ADR-030: Cognitive Router — Dual-Path Dispatch Architecture

> Status: **Accepted**
> Date: 2026-05-13
> Deciders: Staff SWE (rocand)
> Supersedes: ADR-021 static `execution_mode` variable for routing
> Related: ADR-019 (Agentic Squad Architecture), ADR-020 (Conductor), ADR-021 (Two-Way Door), ADR-029 (Cognitive Autonomy)

## Context

ADR-021 introduced a static `execution_mode` Terraform variable that routes ALL tasks to either monolith or distributed execution. This binary switch has limitations:

1. **No per-task intelligence** — A simple label change (L1, 2 files) gets the same execution path as a complex architecture task (L5, 8 dependencies). Either all tasks get the overhead of distributed orchestration, or none do.

2. **Single point of failure risk** — If we route everything through the orchestrator (distributed mode), a bug in the orchestrator blocks ALL tasks. If we stay on monolith, complex tasks are under-resourced.

3. **No graceful degradation** — The static switch requires a Terraform apply to change. If distributed mode has issues at 2am, recovery requires human intervention.

4. **Wasted cost** — Simple tasks (depth < 0.5) don't benefit from squad orchestration. Running them through the orchestrator adds ~30s cold start + Bedrock plan generation ($0.02) for no quality improvement.

The `cognitive_autonomy.py` module already computes capability depth from cognitive signals (dependency count, blocking count, ICRL failures, CFR history). This computation should happen at routing time, not after the task is already running.

## Decision

Enhance the `webhook_ingest` Lambda from a simple DynamoDB writer into a **Cognitive Router** that computes depth per-task and emits dispatch events. Implement a **dual-path architecture** where the monolith always starts as a fallback, eliminating single-point-of-failure risk.

### Architecture

```
EventBridge ALM rule fires on issue.labeled
  │
  ├─ Target 1: webhook_ingest Lambda (ENHANCED, ~200ms)
  │   ├─ Writes task_queue (status: DISPATCHED, target_mode, depth)
  │   ├─ Computes depth from: issue body + labels + metrics (100ms timeout)
  │   ├─ Emits: fde.internal/task.dispatched {target_mode, depth, task_id}
  │   └─ If Lambda fails → task stays READY (monolith fallback)
  │
  ├─ Target 2: ECS monolith (ALWAYS starts, 30s cold start)
  │   ├─ Checks task_queue: if status=DISPATCHED → exit (Lambda handled it)
  │   └─ If status=READY → Lambda failed → run as fallback
  │
  └─ EventBridge dispatch rules (from fde.internal/task.dispatched):
      ├─ Rule: target_mode=distributed → ECS orchestrator task def
      └─ Rule: target_mode=monolith → CloudWatch log (observability only)
```

### Key Properties

1. **Zero single point of failure** — Lambda failure = monolith handles it (slightly less optimal but functional). Lambda success = correct routing.
2. **Per-task intelligence** — Each task gets depth-appropriate execution. Simple tasks stay on monolith (fast, cheap). Complex tasks get the full squad.
3. **Self-healing** — No human intervention needed. Monolith always starts and checks status.
4. **Graceful degradation** — Metrics unavailable? Metadata-only depth. Lambda fails? Monolith fallback. Orchestrator fails? Monolith already running.
5. **No double cold-start for simple tasks** — Monolith starts directly from the ALM rule. No orchestrator overhead for depth < 0.5.
6. **Observable** — Every routing decision is logged with depth, signals, and target_mode.

### Depth Computation (at Lambda time)

The Lambda computes depth from signals available in the webhook payload:

| Signal | Source | Weight |
|--------|--------|--------|
| `factory/level:L1-L5` label | Issue labels | Primary (L5 → 0.85) |
| Dependency count | Issue body parsing | Floor raiser (≥6 → 0.7) |
| Blocking count | Issue body parsing | Floor raiser (≥3 → 0.7) |
| `factory/order:NN` label | Issue labels | Secondary (≥8 → 0.5) |
| CFR history | DynamoDB metrics (100ms timeout) | Floor raiser (>0.30 → 0.8) |
| ICRL failure count | DynamoDB metrics (100ms timeout) | Floor raiser (≥3 → 0.8) |

If DynamoDB metrics are unavailable (timeout, error), the Lambda falls back to metadata-only computation. This guarantees completion within ~200ms regardless of DynamoDB availability.

### Routing Decision

```
depth >= 0.5 → target_mode = "distributed" → orchestrator handles
depth <  0.5 → target_mode = "monolith"    → monolith handles (already running)
```

## Alternatives Considered

### A: Lambda calls ecs.run_task() directly (Risk 1)

Lambda computes depth, then calls `ecs.run_task()` with the appropriate task definition.

**Rejected** — ECS RunTask API takes 2-5s. If throttled or slow, Lambda times out. The task_queue record was written but no ECS task starts. Decoupling via EventBridge event emission eliminates this risk entirely.

### B: Keep static execution_mode, add canary percentage

Add `execution_mode = "canary"` with a percentage split.

**Rejected** — Still doesn't use per-task signals. A random 20% of simple tasks would get expensive distributed execution for no benefit. Cognitive routing is strictly better.

### C: DynamoDB Streams trigger for routing

Write task to DynamoDB, let a DynamoDB Stream trigger a routing Lambda.

**Rejected** — Adds latency (DynamoDB Streams have 1-4s propagation delay). The webhook_ingest Lambda already has the full payload — routing there is faster and simpler.

## Consequences

### Positive

- **Eliminates static execution_mode** — No more Terraform apply to change routing. Each task is routed by its own cognitive signals.
- **Zero SPOF** — Monolith always starts. Lambda failure is invisible to the user.
- **Cost optimization** — Simple tasks (majority) skip orchestrator overhead entirely.
- **Observable** — CloudWatch logs capture every routing decision with full signal breakdown.
- **Backward compatible** — `COGNITIVE_ROUTING_ENABLED=false` reverts to original behavior (all tasks READY, monolith handles).

### Negative

- **Monolith must check task_queue on startup** — Requires a code change in `agent_entrypoint.py` to check status and exit if DISPATCHED. (Planned for next session.)
- **Two EventBridge hops for distributed** — ALM rule → Lambda → dispatch event → orchestrator. Adds ~1s total latency vs direct EventBridge → ECS. Acceptable for complex tasks that take 5-15 minutes.
- **Metrics table dependency** — Lambda reads from the distributed metrics table. If the table doesn't exist (fresh deploy), falls back gracefully to metadata-only.

### Migration Path

1. ✅ Deploy enhanced Lambda with `COGNITIVE_ROUTING_ENABLED=true`
2. ✅ Deploy cognitive_router.tf EventBridge rules
3. ✅ Update eventbridge.tf to always target monolith (dual-path)
4. 🔲 Update `agent_entrypoint.py` to check DISPATCHED status and exit
5. 🔲 Set `execution_mode = "distributed"` in factory.tfvars
6. 🔲 Monitor routing decisions in CloudWatch for 1 week
7. 🔲 Remove `execution_mode` variable (fully cognitive-driven)

### Risks

| Risk | Mitigation |
|------|------------|
| Lambda bug blocks all routing | Monolith always starts as fallback (dual-path) |
| Depth computation inaccurate | Conservative: metadata-only still routes correctly for labeled tasks |
| Metrics table stale | 100ms timeout + fallback to metadata-only |
| Orchestrator task def missing | Both always deployed by Terraform |
| Double execution (monolith + orchestrator) | Monolith checks DISPATCHED status and exits |


---

## Status Update: Single-Path Formalization (2026-05-17)

> Status: **Evolved** — Dual-path superseded by single-path + event-driven retry

### What Changed

The dual-path architecture (Target 2: monolith always-on) has been formalized into a
**single-path architecture** with event-driven retry. The `ecs_failure_handler` Lambda
provides equivalent resilience to the always-on monolith, without the cost and complexity
of running two containers per task.

### Updated Architecture (distributed mode)

```
EventBridge ALM rule fires on issue.labeled
  │
  └─ Target: webhook_ingest Lambda (cognitive router, ~200ms)
      ├─ Writes task_queue (status: DISPATCHED, target_mode, depth)
      ├─ Computes depth from: issue body + labels + metrics
      ├─ Emits: fde.internal/task.dispatched {target_mode, depth, task_id}
      └─ If Lambda fails → task stays READY → pull-based fallback claims it

EventBridge dispatch rules (from fde.internal/task.dispatched):
  ├─ Rule: target_mode=distributed → ECS strands-agent (TASK_ID in env)
  ├─ Rule: target_mode=monolith → ECS strands-agent (TASK_ID in env)
  └─ DLQ: failed target invocations → ecs_failure_handler reprocesses

ECS Task Failure:
  └─ ecs_failure_handler Lambda → retry up to 3x via re-dispatch event
```

### Migration Checklist (updated)

1. ✅ Deploy enhanced Lambda with `COGNITIVE_ROUTING_ENABLED=true`
2. ✅ Deploy cognitive_router.tf EventBridge rules
3. ✅ ~~Update eventbridge.tf to always target monolith (dual-path)~~ → Conditional (monolith mode only)
4. ✅ Update `agent_entrypoint.py` to check DISPATCHED status and exit (+ TASK_ID fast path)
5. ✅ Set `execution_mode = "distributed"` in factory.tfvars
6. ✅ Add `dispatch_monolith_ecs` target for depth < 0.5 tasks
7. ✅ Add `ecs_failure_handler` with retry (replaces always-on monolith resilience)
8. 🔲 Monitor for 1 week — confirm zero stuck tasks without dual-path
9. 🔲 Remove `execution_mode` variable entirely (fully cognitive-driven)

### Rollback

Set `execution_mode = "monolith"` in factory.tfvars and `terraform apply`.
This re-enables the ALM rule → ECS targets (dual-path) and the `_should_defer_to_orchestrator()`
check prevents duplicate execution.

### Cost Impact

- Before: 2 ECS tasks per ALM event (monolith cold start + dispatch container) = ~$0.04/task wasted
- After: 1 ECS task per ALM event (only dispatch container) = $0.00 waste
- At 50 tasks/day: ~$2/day savings ($60/month)

### Well-Architected Alignment

| Pillar | Question | How Addressed |
|--------|----------|---------------|
| COST 7 | Right-size resources | Eliminated wasted monolith cold starts |
| REL 9 | Fault isolation | Retry handler + DLQ + pull-based fallback = 3 layers |
| REL 11 | Withstand failures | ecs_failure_handler retries transient infra failures (max 3x) |
| OPS 8 | Observability | dispatch_monolith CloudWatch log + DLQ alarm retained |
