# Plane 2: FDE (Forward Deployed Engineer)

> Diagram: `docs/architecture/planes/02-fde-plane.png`
> Components: Autonomy Resolution, Agent Builder, Pipeline Execution
> ADRs: ADR-010, ADR-013

## Purpose

The FDE Plane provisions and executes specialized AI agents for each task. It transforms a data contract into a running pipeline of agents that produce code, tests, and documentation. The plane adapts its behavior based on the task's autonomy level — running fewer gates for high-confidence tasks and more checkpoints for complex ones.

## Components

| Component | Module | Owned State | Responsibility |
|-----------|--------|-------------|----------------|
| Autonomy Resolution | `autonomy.py` | AutonomyResult (level, checkpoints, fast_path) | Computes autonomy level from data contract (type + level), resolves which gates and checkpoints apply |
| Agent Builder | `agent_builder.py` | Transient AgentDefinitions | Queries Prompt Registry by tech_stack, injects constraints into prompts, selects tool set, registers task-scoped agents |
| Pipeline Execution | `orchestrator.py` | Pipeline state (current stage, results) | Executes agents sequentially (Recon → Engineering → Reporting), passes output between stages |

## Autonomy Levels

| Level | Name | Human Checkpoints | Gate Behavior |
|-------|------|-------------------|---------------|
| L2 | Collaborator | After recon, after engineering, PR review | Full outer loop |
| L3 | Consultant | After recon, PR review | Full outer loop |
| L4 | Approver | PR review only | Full outer loop |
| L5 | Observer | None | Adversarial gate skipped, fast path eligible |

## Agent Specialization

The Agent Builder provisions agents using three inputs from the data contract:

1. **tech_stack** → Queries Prompt Registry for context-matched prompts (tags: `["python", "fastapi"]`)
2. **type** → Determines pipeline phases (bugfix skips recon, documentation skips engineering)
3. **constraints** → Injected as a structured block into the agent's system prompt

If the Prompt Registry has no match for the tech_stack, the Agent Builder falls back to the base prompts in `prompts.py`.

## Pipeline Phases

| Phase | Agent Role | Tools | Output |
|-------|-----------|-------|--------|
| 1. Reconnaissance | `reconnaissance-{task_id}` | read_spec, run_shell_command | Context + Instruction contract |
| 2-3. Engineering | `engineering-{task_id}` | read_spec, write_artifact, run_shell_command, ALM tools | Code + tests on feature branch |
| 4. Reporting | `reporting-{task_id}` | write_artifact, ALM tools | Completion report, ALM status update |

## Cloud Execution

When deployed headless (ECS Fargate), the pipeline runs identically but without Kiro hooks. The Orchestrator receives events from EventBridge and executes the same agent sequence. Bedrock provides LLM inference.

## Interfaces

| From | To | Data |
|------|-----|------|
| Data Plane (Router) | Autonomy Resolution | Data contract dict |
| Autonomy Resolution | Agent Builder | AutonomyResult + PipelineGates |
| Context Plane (Constraint Extractor) | Agent Builder | ExtractionResult with constraints |
| Agent Builder | Pipeline Execution | Ordered list of agent names |
| Pipeline Execution | Control Plane (DORA) | Stage durations, outcomes |

## Related Artifacts

- ADR-010: Data Contract for Task Input
- ADR-013: Enterprise-Grade Autonomy
- Design: `docs/design/data-contract-task-input.md`
- Scope: `docs/design/scope-boundaries.md`
