# ADR-020: Conductor Orchestration Pattern

> Status: **Accepted**
> Date: 2026-05-11
> Deciders: Staff SWE (rocand)
> Supersedes: Static squad manifest assignment in distributed_orchestrator.py

## Context

The distributed orchestrator (ADR-019) dispatches agents via static Squad Manifests — fixed sequences of agents with predetermined roles and stages. This works for known task patterns but fails when:

1. Task complexity varies significantly (O1 trivial vs O5 novel)
2. Agent assignment should be capability-matched, not role-fixed
3. Communication between agents should be targeted, not broadcast
4. Failed executions need strategy refinement, not just retries

Nielsen et al. (ICLR 2026, arXiv:2512.04388v5) demonstrate that a small "Conductor" model trained with RL can generate optimal coordination strategies that outperform any individual worker and all manually-designed multi-agent pipelines. Key findings:

- Focused subtask instructions outperform generic role prompts
- Communication topology (who sees what) significantly impacts quality
- Task-adaptive workflow complexity (more steps for harder problems) is optimal
- Recursive self-referential scaling handles novel problems

## Decision

Implement a **Conductor** layer between task intake and the distributed orchestrator that dynamically generates WorkflowPlans based on task complexity, available agents, and knowledge context.

### Architecture

```
Task + Organism Level + Knowledge Context
  -> Conductor (Bedrock reasoning model)
    -> WorkflowPlan (steps + topology + access lists)
      -> DistributedOrchestrator (existing, unchanged)
        -> ECS Agent Tasks
          -> Results
            -> Confidence Assessment
              -> [If low] Recursive Refinement (max depth 2)
```

### Key Properties

1. **Focused Instructions**: Each agent receives a targeted subtask, not a generic role prompt
2. **Communication Topology**: Access lists control which agents see which outputs (via SCD)
3. **Difficulty Adaptivity**: Organism level (O1-O5) drives workflow complexity
4. **Bounded Recursion**: Max 2 recursive refinements before fallback
5. **Graceful Degradation**: Fallback to simple sequential plan if Conductor fails

## Alternatives Considered

### A: Static Topology Library

Pre-define 5-10 workflow templates and select by organism level.

- Pro: No Bedrock call overhead, deterministic
- Con: Cannot adapt to task-specific nuances, no focused instructions
- Con: Requires manual maintenance of templates

### B: Full RL-Trained Conductor (Paper's Approach)

Train a custom 7B model with GRPO on our task distribution.

- Pro: Optimal coordination strategies learned from data
- Con: Requires training infrastructure we don't have
- Con: Training data collection is expensive
- Con: Model maintenance burden

### C: LLM-Generated Plans (Selected)

Use Bedrock reasoning model to generate plans via structured prompting.

- Pro: No training needed, leverages existing Bedrock access
- Pro: Adapts to any task description via natural language
- Pro: Cost is minimal (~$0.02 per plan)
- Con: Not as optimal as RL-trained model
- Con: Depends on prompt quality

## Consequences

### Positive

- Agents receive focused, targeted instructions (better output quality)
- Communication topology prevents context pollution
- Workflow complexity adapts to task difficulty automatically
- Failed executions get strategy refinement, not just retries
- Observable: every plan is logged with rationale

### Negative

- Additional Bedrock call per task (~$0.02, ~200ms latency)
- Conductor prompt must be maintained as agent pool evolves
- Recursive refinement can double execution cost for hard tasks
- Plan parsing adds a failure mode (mitigated by fallback plan)

### Risks

| Risk | Mitigation |
|------|------------|
| Conductor generates invalid plans | Fallback to safe sequential plan |
| Recursive loop burns budget | Hard cap at depth 2 |
| Conductor prompt drifts from agent capabilities | `_AGENT_CAPABILITIES` dict is single source of truth |
| Access lists too restrictive (agent lacks context) | Default fallback includes `["all"]` for validation steps |

## Implementation

- Artifact: `src/core/orchestration/conductor.py`
- Design doc: `docs/design/conductor-orchestration-pattern.md`
- Integration: Called by orchestrator before `execute()`, plan converted via `to_squad_manifest_stages()`
- Feature flag: `CONDUCTOR_ENABLED` (default: true for O3+ tasks)
