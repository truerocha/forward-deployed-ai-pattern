# Forward Deployed Engineer: Building an Autonomous Code Factory with Kiro

> The Staff Engineer writes specs. The factory ships code.

## The Opportunity

Software engineering teams using AI coding assistants today operate at Level 2 autonomy: the AI generates code, the human reviews every diff. This model produces a 2-3x productivity gain but does not scale beyond one project. The human remains the bottleneck — reviewing, coordinating, and context-switching between tasks.

The Autonomous Code Factory pattern raises the operating level to Level 4: the AI handles the full development loop (writing, testing, reviewing, packaging), while the human writes specifications and approves outcomes. The human reviews results, not diffs.

Three engineers at StrongDM demonstrated this model in production: 16,000 lines of Rust, 9,500 lines of Go, and 6,700 lines of TypeScript — generated from three Markdown specification files. No human wrote code. No human reviewed code. The humans approved outcomes.

## What Is a Forward Deployed Engineer?

A Forward Deployed Engineer (FDE) is an AI agent deployed into a specific project's context — its pipeline architecture, its knowledge artifacts, its quality standards, and its governance boundaries. It is not a general-purpose coding assistant.

An FDE has:
- **System awareness**: it knows the pipeline chain, module boundaries, and data flow
- **Quality standards**: it measures against the project's quality reference artifacts, not its own judgment
- **Structured interaction**: it follows the Context + Instruction pattern, not ad-hoc prompts
- **Recipe discipline**: it executes a predefined engineering sequence, carrying context across steps

## The Factory Architecture

The Autonomous Code Factory operates on four neuro-inspired principles we call Synaptic Engineering:

**Neurons**: Every component (workspace, agent, spec, hook) has rigid input/output contracts. A workspace receives a spec and produces a merge request. No ambiguity in between.

**Synaptic Cleft**: Context transmission between components is clean and minimal. The agent receives only the relevant context for the current task — not everything the project has ever produced.

**Neural Plasticity**: Successful patterns strengthen over time. The factory accumulates cross-session knowledge through structured hindsight notes. Patterns that appear in three or more successful tasks are promoted to permanent context. Notes older than 90 days without explicit retention are archived.

**Executive Function**: The human decides WHAT to build and WHY. The agent decides HOW to implement and HOW to test. If the human is deciding HOW, the factory is operating below its target level. If the agent is deciding WHAT, the factory has lost control.

## How It Works

The factory operates as a distributed system of Kiro workspaces. Each workspace is a production line for a specific codebase. The Staff Engineer manages multiple lines simultaneously.

### The Daily Rhythm

**Morning (Dispatch)**: The Staff Engineer reviews completion reports from yesterday, approves pending merge requests, and writes specifications for today's work. Each spec uses a structured format with behavioral scenarios in BDD (Given/When/Then) that define acceptance criteria.

**Midday (Execute)**: The agent executes specifications through a four-phase protocol: reconnaissance (understand the system), intake (reformulate the task as a structured contract), engineering (test-driven implementation with adversarial challenge on every write), and completion (validation report).

**Afternoon (Harvest)**: The Staff Engineer triggers ship-readiness validation (Docker E2E, Playwright browser tests, BDD scenarios, and holdout tests the agent never saw during implementation). For validated tasks, the agent creates semantic commits and opens merge requests through MCP integration with GitHub or GitLab.

### The 13 Quality Gates

The factory enforces quality through 13 hooks that fire at specific moments:

- **Before execution starts**: Definition of Ready validates that the spec is complete and the agent has identified applicable quality standards
- **Before every write**: An adversarial gate challenges the agent with eight questions about downstream consumers, parallel paths, root cause analysis, and domain validation
- **After every shell command**: A circuit breaker classifies errors as code issues (agent can fix) or environment issues (human must fix), preventing the agent from destroying correct code while trying to fix an infrastructure problem
- **After task completion**: Definition of Done validates conformance, pipeline validation runs contract tests, and enterprise hooks sync progress to ALM systems
- **On human trigger**: Ship-readiness runs the full validation stack, and the release manager creates the merge request

### Agentic TDD: The Halting Condition

The agent's implementation objective is bounded by a mathematical halting condition: make the approved tests pass while satisfying all constraints.

Tests are generated from spec scenarios before production code exists (shift-left). The human approves the tests — not the implementation. Once approved, tests are immutable: the agent cannot modify them to make the build pass. If tests do not pass, the agent fixes production code.

This prevents scope creep, over-engineering, and hallucinated features. The agent has one goal: green bar.

## Empirical Results

Same task, same AI model. Without the FDE protocol: 33% quality score across 18 evaluation criteria. With the FDE protocol: 100% quality score.

```
FDE wins: 12 criteria  |  Bare wins: 0  |  Ties: 6
Improvement: +67 percentage points
```

The improvement comes from structured context (the agent knows the system before writing code), adversarial challenge (every write is questioned before execution), and pipeline-level validation (testing edges between modules, not individual functions).

## Research Foundations

The pattern draws from six peer-reviewed studies:

1. Esposito et al. (2025) found that 93% of studies on GenAI in software architecture lack formal validation — the gap our Definition of Done gate addresses.
2. Vandeputte et al. (2025) advocate for verification at all levels, not only unit tests — the principle behind our five-layer ship-readiness validation.
3. The Shonan Meeting 222 (2025) reached consensus that greenfield approaches do not generalize to brownfield — our protocol includes a separate brownfield pipeline with mandatory reconnaissance.
4. DiCuffa et al. (2025) demonstrated that the "Context and Instruction" prompt pattern is the most efficient (ANOVA p<10 to the negative 32) — the pattern our structured intake contract implements.
5. Bhandwaldar et al. (2026) showed that scaling from 1 to 10 agents yields 8.27x mean speedup on optimization tasks — informing our alternative exploration hook for architectural decisions.
6. Wong et al. (2026) demonstrated that agent scaffolding matters as much as model capability: a weaker model with strong scaffolding outperformed a stronger model with weak scaffolding (52.7% compared to 52.0% on SWE-Bench-Pro).

## Getting Started

The factory template is open source: [github.com/truerocha/forward-deployed-engineer-pattern](https://github.com/truerocha/forward-deployed-engineer-pattern)

Setup takes 15 minutes:

1. Run the global setup script (one-time): `bash scripts/provision-workspace.sh --global`
2. Onboard your project: `bash scripts/provision-workspace.sh --project`
3. Customize the steering file for your project's architecture
4. Enable hooks for your engineering level (L2 for targeted fixes, L3 for features, L4 for architecture)
5. Write a spec, mark it as ready, and type `#fde` in Kiro chat

The adoption guide includes step-by-step walkthroughs for Next.js applications and Python microservices, a detailed daily operating rhythm for managing three projects in parallel, and 15 troubleshooting scenarios.

## What This Is Not

This is not a replacement for engineering judgment. The human writes the specifications that define what the system does. The human approves the outcomes that determine what ships. The human provides feedback that improves the factory over time.

The factory amplifies the Staff Engineer's capacity — from managing one project with full attention to managing three or more projects by focusing on specifications and outcomes instead of implementation details.

The code is the output. The specification is the product.
