# ADR-038: Execution Readiness Pipeline (ERP)

> Status: **Accepted**
> Date: 2026-05-16
> Deciders: Staff SWE (rocand)
> Related: ADR-030 (Cognitive Router), ADR-020 (Conductor), Issue #146

## Context

Issue #146 exposed a **class of failure**, not an isolated incident. Any task that requires execution of scripts, generation of artifacts, or validation via multi-step gates fails when treated as a standard code generation task. The standard pipeline (reconnaissance → engineering → reporting) assumes the agent generates code, but execution tasks require the agent to **run commands in sequence with validation gates**.

Root cause: the factory has no mechanism to:
1. Classify execution complexity BEFORE dispatch
2. Decompose tasks into atomic sub-steps with gates
3. Execute steps sequentially with per-step timeout and reporting
4. Report granular progress (step A2/A4 vs generic "workspace 14%")

## Decision

Implement an **Execution Readiness Pipeline (ERP)** in three waves. This ADR covers Wave 1 (classification + basic step executor).

### Wave 1 Architecture (Implemented)

```
Webhook → Lambda (classify) → DynamoDB (complexity field) → ECS
                                                              │
                                                              ├─ complexity=simple/standard → Standard Pipeline
                                                              │   (unchanged)
                                                              │
                                                              └─ complexity=execution → ERP Step Executor
                                                                  ├─ Parse spec → ExecutionSteps
                                                                  ├─ For each step:
                                                                  │   ├─ Update DynamoDB stage
                                                                  │   ├─ Execute commands
                                                                  │   ├─ Run gate validation
                                                                  │   └─ If gate fails → STOP
                                                                  └─ Push & PR (if all steps pass)
```

### Classification (Lambda, ~5ms)

Textual regex-based classification at webhook_ingest time:

| Indicator | Pattern | Signal |
|-----------|---------|--------|
| bash_commands | ` ```bash\n ` | Script execution required |
| pytest_execution | `pytest\s+\S+` | Test validation gates |
| artifact_generation | `git add\s+\S+` | Generates and commits files |
| sequential_gates | `**Gate**:` | Explicit gate markers |
| multi_part | `### Part [A-Z]` | Multi-part deliverables |
| script_execution | `python3? scripts/` | Script execution |
| dependency_chain | `A1.*→.*A2` | Sequential dependencies |
| step_numbering | `#### [A-Z]\d+` | Structured step IDs |

Threshold: 3+ indicators → `complexity = "execution"`

### Step Executor (ECS, per-step)

- 15-minute timeout per step (vs 60-min whole-task)
- Gate validation after each step (fail-fast)
- Per-step DynamoDB stage updates (dashboard visibility)
- Graceful fallback: if parser finds 0 steps, standard pipeline continues

### Data Contract (DynamoDB, additive)

New fields on task-queue items (non-breaking):

| Field | Type | Written By | Read By |
|-------|------|-----------|---------|
| complexity | S | Lambda | Orchestrator |
| complexity_indicators | S (JSON) | Lambda | Dashboard |
| current_step | S | Step Executor | Dashboard |
| step_progress | S | Step Executor | Dashboard |
| execution_steps | S (JSON) | Step Executor | Dashboard |

## Alternatives Considered

### A: Classify in the container (entrypoint)

- Pro: Access to repo, can validate scripts exist
- Con: Already spent Fargate compute, too late for routing
- Con: Lambda has the spec_content already — no repo needed for textual classification

### B: Dedicated classification Lambda

- Pro: Separation of concerns
- Con: More infra, more latency, YAGNI for Wave 1
- Con: webhook_ingest already has the payload

### C: LLM-based classification

- Pro: More nuanced understanding
- Con: Adds ~2s + $0.01 per task for a decision that regex handles in 5ms
- Con: Non-deterministic

## Consequences

### Positive

- Tasks like #146 are now decomposed and executed step-by-step
- Dashboard shows "Step A2/A4: generating corpus..." instead of "workspace 14%"
- Gate failures stop execution immediately (no wasted compute)
- Per-step timeout (15min) catches stuck commands faster than 60-min whole-task timeout
- Classification is additive — existing tasks unaffected (complexity defaults to empty/simple)

### Negative

- Parser is regex-based — specs with non-standard structure won't be parsed (fallback to standard pipeline)
- Step executor uses subprocess (shell=True) — same security model as existing agent execution
- No checkpoint/resume in Wave 1 (container restart = start from scratch)

### Future Waves

- **Wave 2**: Checkpoint per-step in DynamoDB, resume from last checkpoint, gate validation per-step
- **Wave 3**: Pre-flight workspace validation, parallel execution of independent steps, auto-decomposition via LLM

## Implementation

| Artifact | Purpose |
|----------|---------|
| `src/core/execution/__init__.py` | Module package |
| `src/core/execution/complexity_classifier.py` | Standalone classifier (for testing/reuse) |
| `src/core/execution/spec_parser.py` | Parses spec_content → ExecutionSteps |
| `src/core/execution/step_executor.py` | Atomic step execution with gates |
| `src/core/execution/erp_integration.py` | Bridges orchestrator ↔ step executor |
| `infra/terraform/lambda/webhook_ingest/index.py` | `_classify_spec_complexity()` + DynamoDB fields |
| `infra/docker/agents/orchestrator.py` | Step 7.7: ERP check before standard pipeline |
