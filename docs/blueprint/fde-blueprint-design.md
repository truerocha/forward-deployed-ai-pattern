# FDE V3.0 — Autonomous Code Factory Blueprint (Autonomous Code Factory Pattern)

> Status: **design document — pending implementation**
> Date: 2026-05-03
> Role: Staff Engineer as **Director of Architecture** managing a squad of AI agents
> Pattern: Autonomous Code Factory (Level 4 — AI-generated with automated review, human approves outcomes)
> Scope: End-to-end — from ALM intake through agent execution to ship-ready code
> Stack: GitHub Issues + Asana | GitHub Actions + GitLab CI Ultimate (mirror) | Playwright + Docker + pytest + BDD
> Research: IBM Agent Factories (arXiv:2603.25719), Meta CCA (arXiv:2512.10398), StrongDM Attractor (NLSpec), Shapiro 5 Levels

---

## 0. Design Philosophy — Synaptic Engineering

The Autonomous Code Factory operates on a neuro-inspired architecture. Every design decision derives from four foundational principles borrowed from how biological neural networks process, transmit, and consolidate information.

### 0.1 Neurons — Encapsulated Modules with Rigid Interfaces

Every unit in the factory (workspace, agent, spec, hook) is a **neuron**: an encapsulated processing unit with strictly defined inputs and outputs. A neuron does not leak internal state.

| Factory Element | Input Signal | Output Signal |
|----------------|--------------|---------------|
| Workspace | Spec (NLSpec format) | Ship-ready code (MR) |
| Agent (within workspace) | Task + constraints + context | Implementation + completion report |
| Hook | Event + accumulated context | Decision (proceed / block / modify) |
| Spec | User story + scenarios | Decomposed tasks with acceptance criteria |
| Note | Task outcome + insight | Reusable knowledge for future tasks |

**Rule**: If a component cannot define its input and output in one sentence each, decompose it.

### 0.2 Synaptic Cleft — Clean Context Transmission

The gap where information jumps between neurons. Signal quality degrades if the cleft is noisy. Every handoff must be **clean, focused, and minimal**.

- **Context pruning**: Load ONLY relevant context per interaction. Not all steerings, not all notes.
- **Signal-to-noise**: 50 lines of precise context > 500 lines of everything.
- **Handoff contracts**: When work moves between stages, the interface is a defined contract — not a dump.
- **Inter-workspace synapses**: When Workspace A produces an API that Workspace B consumes, the contract (OpenAPI spec, type definitions, interface file) IS the neurotransmitter. Agents validate interface compatibility, not internal implementation.

**Implementation**: Manual steering inclusion, fileMatch for auto-context, Working Memory capped at 30 lines, Notes in structured format, Hooks with focused prompts.

### 0.3 Neural Plasticity — Reinforcement and Decay

The brain strengthens successful connections and weakens unused ones. The factory does the same.

**Reinforcement** (what worked gets stronger):
- Notes from PASS tasks are `[VERIFIED]` — trusted
- Patterns reported by human in feedback.md as "repeatedly useful" are promoted to steering
- Hook prompts that produce useful challenges are preserved (append-only default)

**Decay** (what didn't work fades):
- Notes older than 90 days without `[PINNED]` tag → archived by consolidation hook
- Notes from failed tasks are `[UNVERIFIED]` — suggestions only
- Hook prompts reported as "consistently not applicable" in feedback.md → candidates for removal

**Implementation**: Decay is **date-based**, not counter-based. Notes include a `date` field (ISO format). The consolidation hook (`userTriggered`) runs a shell command that compares file dates against current date and lists candidates for archival. The human reviews and confirms. Reinforcement is **human-driven**: the Staff Engineer writes observations in `.kiro/meta/feedback.md`, and the meta-agent hook reads this file to suggest promotions. No stateful counters exist — all decisions derive from file metadata (dates) and human input (feedback.md).

### 0.4 Executive Function — Human as Prefrontal Cortex

The prefrontal cortex decides which networks to activate and what goal to pursue.

| Human Decides | Agent Decides |
|---------------|---------------|
| WHAT to build (spec) | HOW to implement (code) |
| WHY to build it (value) | HOW to test (from scenarios) |
| WHEN to ship (approve MR) | HOW to fix (within circuit breaker) |
| WHICH connections to strengthen (feedback) | HOW to document (ADR, notes) |

**Rule**: If the human is deciding HOW → factory below Level 4. If the agent is deciding WHAT → factory lost control.

### 0.5 Derived Design Rules

| Rule | Principle | Governs |
|------|-----------|---------|
| Every workspace: defined input (spec) → defined output (MR) | Neurons | §2 Topology |
| Context per-interaction is minimal and relevant | Synaptic Cleft | §3 Intake, §6 Execution |
| Cross-workspace uses interface contracts, not shared state | Synaptic Cleft | §2 Routing |
| Successful patterns promoted; unused patterns decay | Plasticity | §6 Notes, Meta-agent |
| Human: specs + outcomes. Agent: implementation + validation | Executive Function | §1 Operating Model |

---

## 1. Operating Model

### 1.1 The Staff Engineer's Role

The Staff Engineer does NOT write code. The Staff Engineer:
- Writes specs (the control plane)
- Approves test contracts (the halting condition)
- Approves outcomes (the MR)
- Refines the factory (meta-agent feedback)

### 1.2 Autonomy Level

| Level | Description | Human Role | Our Target |
|-------|-------------|-----------|------------|
| L1 | AI-assisted | Human writes, AI suggests | — |
| L2 | AI-generated with human review | Human reviews every diff | — |
| L3 | AI-generated with automated gates | Human reviews exceptions | Brownfield fixes |
| **L4** | **AI-generated, human approves outcomes** | **Human writes specs, approves results** | **Primary mode** |
| L5 | Fully autonomous | Human monitors metrics | Future |

### 1.3 Daily Operating Rhythm

```
09:00  DISPATCH — Write/approve specs for 3 projects
09:30  APPROVE TESTS — Review generated test contracts (not code)
09:45  RELEASE — Agents execute in background
12:00  HARVEST — Review MRs, approve outcomes
14:00  REFINE — Analyze completion reports, update specs
16:00  ARCHITECT — Plan next milestone, write new specs
```

---

## 2. Factory Topology — Multi-Workspace Orchestration

### 2.1 The Factory Floor

The Autonomous Code Factory is a **distributed system** of workspaces. Each workspace is a production line for a specific codebase. The Staff Engineer operates as the factory floor manager.

```
~/.kiro/ (GLOBAL — inherited by ALL workspaces)
├── steering/
│   ├── agentic-tdd-mandate.md (auto)       ← Universal law
│   └── adversarial-protocol.md (auto)      ← Universal law
├── settings/mcp.json                        ← Shared credentials (GitHub, Asana)
├── notes/shared/                            ← Cross-project insights
└── skills/adversarial-planner.md            ← Universal skill

WORKSPACE A: payment-service ──── Status: IN_PROGRESS (TDD, Task 3/5)
WORKSPACE B: analytics-dashboard ── Status: SHIP_READINESS (E2E running)
WORKSPACE C: infra-terraform ───── Status: AWAITING_SPEC
```

### 2.2 Inheritance Model

| Layer | Location | Scope | Examples |
|-------|----------|-------|----------|
| Global laws | `~/.kiro/steering/` (auto) | ALL workspaces, ALL interactions | TDD mandate, adversarial protocol |
| Global credentials | `~/.kiro/settings/mcp.json` | ALL workspaces | GitHub token, Asana token |
| Global knowledge | `~/.kiro/notes/shared/` | ALL workspaces (read) | Error patterns, tool conventions |
| Global skills | `~/.kiro/skills/` | ALL workspaces (on demand) | Adversarial planner |
| Project steering | `.kiro/steering/` (manual) | THIS workspace only | Pipeline chain, régua, module boundaries |
| Project hooks | `.kiro/hooks/` | THIS workspace only | Gates configured for this project's level |
| Project specs | `.kiro/specs/` | THIS workspace only | Active work items |
| Project notes | `.kiro/notes/project/` | THIS workspace only | Architecture decisions, domain knowledge |
| Project MCP | `.kiro/settings/mcp.json` | THIS workspace (overrides global) | Project-specific GitLab instance |

**Precedence**: Workspace overrides global. A project with its own `.kiro/settings/mcp.json` uses that instead of the global one.

### 2.3 Workspace Provisioning (Onboarding a New Project)

```bash
# 1. Clone repo
git clone <repo-url> && cd <repo>

# 2. Initialize factory structure
mkdir -p .kiro/{steering,hooks,specs,notes/project,meta,settings}

# 3. Copy template from factory-template repo (this repo)
cp <factory-template>/.kiro/hooks/*.kiro.hook .kiro/hooks/
cp <factory-template>/.kiro/steering/fde.md .kiro/steering/

# 4. Customize .kiro/steering/fde.md for THIS project:
#    - Pipeline chain (data flow)
#    - Module boundaries (edges)
#    - Régua (quality standards)
#    - Test infrastructure (commands)

# 5. Enable hooks for project's engineering level (L2/L3/L4)

# 6. Open in Kiro — production line operational
```

### 2.4 Work Routing

| Signal | Route To |
|--------|----------|
| GitHub Issue on repo X | Workspace X |
| Asana task in Project Y | Workspace Y |
| Cross-cutting (shared lib) | Workspace that owns the lib; dependents get regression specs |
| New project | Provision new workspace (§2.3) |
| Inter-project dependency | Spec in A references contract from B; agent validates interface |

### 2.5 Cross-Workspace Knowledge Flow

```
Workspace A completes task → generates note
  ├── Project-specific → .kiro/notes/project/ (stays in A)
  └── Generic insight → ~/.kiro/notes/shared/ (available to B, C, ...)
                           │
                           ▼ Next task in B or C
                             └── Agent consults ~/.kiro/notes/shared/
```

**Classification rule**: "If this insight applies ONLY to this project → project notes. If it applies to ANY project → shared notes."

### 2.6 Factory State (Consolidated View)

`~/.kiro/factory-state.md` — updated by each workspace's postTaskExecution hook:

```markdown
# Factory State

| Project | Status | Spec | Progress | Blockers |
|---------|--------|------|----------|----------|
| payment-service | IN_PROGRESS | jwt-refresh.md | 3/5 | None |
| analytics-dashboard | SHIP_READINESS | chart-perf.md | 5/5 | Docker timeout |
| infra-terraform | AWAITING_SPEC | — | 0/0 | Human writing spec |

## Pending Human Actions
- [ ] analytics-dashboard: Approve MR #45
- [ ] infra-terraform: Complete VPC refactor spec
- [ ] payment-service: Review test contract
```

### 2.7 Parallel Execution

| Mode | How | When |
|------|-----|------|
| Kiro IDE (single) | 1 workspace open, switch between | Spec writing, MR review |
| Kiro IDE (multi-window) | Multiple windows, different workspaces | Monitoring |
| Kiro CLI (background) | Separate terminals per workspace | Agents executing while human works |
| Strands (future) | N Kiro CLI orchestrated | Full parallel with coordination |

```bash
# Current model (no AWS):
# Terminal 1:
cd ~/projects/payment-service && kiro cli "#fde Execute Task 3"
# Terminal 2:
cd ~/projects/analytics-dashboard && kiro cli "#fde Ship-readiness"
# Terminal 3 (IDE):
# Human writing spec for infra-terraform
```

### 2.8 Credential Management

| Scope | Location | Security |
|-------|----------|----------|
| Global tokens | `~/.kiro/settings/mcp.json` | References `${env:GITHUB_TOKEN}` etc. |
| Project-specific | `.kiro/settings/mcp.json` | Overrides global for specific GitLab instance |
| Environment vars | `~/.zshrc` / `~/.bashrc` | Source of truth for secrets |
| Never committed | `.gitignore` | All `mcp.json` with credentials are gitignored |

**Rule**: Agents access credentials via env vars in MCP config. They NEVER read `.env` files, credential stores, or secret managers directly.

---

## 3. Work Intake

### 2.1 ALM Sources

| Source | Role | MCP Power |
|--------|------|-----------|
| GitHub Issues | Primary (open-source, public) | `@modelcontextprotocol/server-github` |
| Asana | Primary (internal, enterprise) | Asana MCP server |
| GitLab Issues | Secondary (via mirror) | `@modelcontextprotocol/server-gitlab` |

### 2.2 Work Hierarchy (Global Standard)

```
Milestone (Quarter/Release)
  └── Epic (GitHub Milestone / Asana Project)
       └── Feature (GitHub Issue [type:feature] / Asana Section)
            └── Task (Kiro Spec task)
                 └── Subtask (Single commit)
```

### 2.3 User Story Format (NLSpec-Inspired)

Every Feature entering the factory uses this format:

```markdown
# Feature: [Title]

## Context
- Project: [name]
- Epic: [parent]
- Affected modules: [list]
- Type: [greenfield | brownfield | bugfix | refactor]

## Narrative
As a [role], I want [capability] so that [business value].

## Acceptance Criteria (BDD Scenarios)
GIVEN [precondition]
WHEN [action]
THEN [expected outcome]

## Constraints
- MUST NOT: [what cannot change]
- MUST: [NFRs — performance, security, accessibility]
- OUT OF SCOPE: [excluded]

## Technical Context (brownfield)
- Architecture: [relevant modules]
- Regression risk: [what could break]
- Existing tests: [what must keep passing]

## Definition of Done
- [ ] All acceptance scenarios pass as automated tests
- [ ] Existing test suite passes (zero regressions)
- [ ] CI/CD pipeline green
- [ ] Ship-readiness validated (Docker + E2E)
- [ ] MR opened with semantic commit
```

### 2.4 Intake Flow

```
ALM (Issue/Task)
  → Human writes User Story (NLSpec format)
    → Kiro Spec (.kiro/specs/feature.md)
      → Human marks READY
        → Agent Pipeline Triggered
```

---

## 4. Spec as Control Plane

### 3.1 The StrongDM Insight

"The bottleneck has shifted from implementation speed to spec quality."

The spec is NOT documentation. It is the **control instrument** of the factory. Spec quality = output quality.

### 3.2 Scenarios as Holdout Set

```
Scenarios in Spec
  ├── 70% → Agent-visible (used for TDD)
  └── 30% → Holdout (used only for ship-readiness validation)
```

The holdout prevents the agent from gaming its own tests.

### 3.3 Spec Lifecycle

```
DRAFT → REVIEW → READY → IN_PROGRESS → VALIDATION → SHIPPED
```

---

## 5. Agent Pipeline Triggers

### 4.1 When Agents Are Sensibilized

| Trigger | Event | Action |
|---------|-------|--------|
| Spec READY | Human approves spec | Agent begins (DoR gate fires) |
| Task complete | Agent finishes task | Post-task hooks fire |
| CI failure | Pipeline reports red | Circuit breaker → fix or escalate |
| Ship-readiness | Human triggers | Docker + E2E + holdout |
| Release | Human triggers | Commit + MR + ALM update |

### 4.2 Greenfield Pipeline

```
Spec READY → DoR Gate → Reconnaissance → Scaffold
  → TDD (tests first) → Human approves tests
    → Implementation (make tests green)
      → Adversarial gate on each write
        → DoD Gate → CI/CD → Ship-readiness → Delivery
```

### 4.3 Brownfield Pipeline

```
Issue arrives → Agent reconnaissance → Agent generates Spec
  → Human approves Spec → TDD loop (scoped to fix)
    → CI/CD (ALL existing tests must pass) → Ship-readiness → Delivery
```

---

## 6. Execution

### 5.1 Agentic TDD

- SHIFT-LEFT: Tests before code
- ANTI-LAZY MOCK: Cannot mock core business rule
- TEST IMMUTABILITY: Human-approved tests are frozen
- HALTING: Stop when tests green + constraints satisfied

### 5.2 Working Memory

`.kiro/specs/WORKING_MEMORY.md` — updated at recipe checkpoints, max 30 lines.

### 5.3 Circuit Breaker

```
Error → Read last 40 lines stderr → Classify
  ├── ENVIRONMENT → STOP, report to human
  └── CODE → Fix (max 3 attempts, then different approach, then rollback)
```

### 5.4 Cross-Session Notes

`.kiro/notes/` — hindsight notes with verification status and anti-patterns.

---

## 7. CI/CD Integration

### 6.1 Architecture

```
GitHub (primary) ──→ GitHub Actions (CI)
  │
  └── mirror.sh ──→ GitLab A ──→ GitLab CI Ultimate
                 ──→ GitLab B ──→ GitLab CI Ultimate
```

### 6.2 Agent Rules

- ALWAYS feature branch (never main)
- Reads CI status via MCP
- Fixes CODE errors only (circuit breaker classifies)
- NEVER merges, NEVER deploys, NEVER modifies CI config

### 6.3 Feedback Loop

```
Push → CI runs → GREEN → proceed to ship-readiness
                → RED → Circuit breaker → fix or escalate
```

---

## 8. Ship-Readiness

### 7.1 Validation Stack

```
Layer 1: Unit Tests (pytest/jest) — in CI
Layer 2: Integration (Docker Compose) — agent-triggered
Layer 3: E2E + BDD (Playwright + pytest-bdd) — agent-triggered
Layer 4: Holdout Scenarios (human-written, agent never saw)
Layer 5: Visual Regression (Playwright screenshots) — for UI projects
```

### 7.2 Docker Validation

Agent runs:
1. `docker compose -f docker-compose.test.yml up -d`
2. Wait for health checks
3. Run E2E suite
4. Run holdout scenarios
5. Capture results
6. `docker compose down`
7. Report pass/fail

### 7.3 Playwright/Browser (UI Projects)

MCP or direct Playwright for:
- Navigation flows
- Form submissions
- Visual regression (screenshot comparison)
- Accessibility checks

### 7.4 BDD (Behavioral)

Spec scenarios → Gherkin features → pytest-bdd step definitions → automated validation.

---

## 9. Delivery

### 8.1 Semantic Commit

```
feat(auth): implement JWT refresh rotation

Implements token refresh with 30s grace period for concurrent requests.
Holdout scenarios validated race condition handling.

Closes #123
Spec: .kiro/specs/jwt-refresh.md
Co-authored-by: AI Agent <agent@kiro.dev>
```

### 8.2 MR Structure

- Summary (1-2 sentences)
- Spec reference + Issue link
- Changes per module
- Validation results (tests, E2E, holdout, CI)
- Risks and residuals

### 8.3 ALM Update

- Issue → `in-review` (MR opened)
- Issue → `closed` (MR merged by human)
- Asana → section moved, PR linked

---

## 10. MCP Powers

### 9.1 Required

| Power | Purpose |
|-------|---------|
| GitHub | Issues, PRs, Actions, code search |
| GitLab | MRs, pipelines, wiki |
| Asana | Tasks, projects, status |
| Playwright | Browser E2E, visual validation |

### 9.2 Security Boundaries

| Allowed | Forbidden |
|---------|-----------|
| Read issues, create PRs, push feature branch | Merge to main, deploy, modify CI config |
| Read CI status, create subtasks | Access secrets, modify permissions |
| Run Docker locally, run tests | Push to production, delete branches |

---

## 11. Kiro Artifacts

### 10.1 Hooks (13 total)

| Hook | Event | Purpose |
|------|-------|---------|
| fde-dor-gate | preTaskExecution | Readiness validation |
| fde-adversarial-gate | preToolUse (write) | Challenge each write |
| fde-dod-gate | postTaskExecution | Conformance validation |
| fde-pipeline-validation | postTaskExecution | Pipeline testing + report |
| fde-test-immutability | preToolUse (write) | VETO writes to approved tests |
| fde-circuit-breaker | postToolUse (shell) | Error classification |
| fde-enterprise-backlog | postTaskExecution | ALM sync |
| fde-enterprise-docs | postTaskExecution | ADR + docs |
| fde-enterprise-release | userTriggered | Commit + MR |
| fde-ship-readiness | userTriggered | Docker + E2E + holdout |
| fde-alternative-exploration | userTriggered | 2 approaches for L4 |
| fde-notes-consolidate | userTriggered | Cleanup notes |
| fde-prompt-refinement | userTriggered | Meta-agent analysis |

### 10.2 Steerings

| File | Inclusion | Purpose |
|------|-----------|---------|
| fde.md | manual (#fde) | Core protocol |
| fde-enterprise.md | manual (#fde-enterprise) | Enterprise ALM context |

### 10.3 Global Steerings (~/.kiro/steering/)

| File | Inclusion | Purpose |
|------|-----------|---------|
| agentic-tdd-mandate.md | auto | Anti-lazy-mock, shift-left |
| adversarial-protocol.md | auto | 3-phase adversarial |

---

## 12. AWS Dependencies (Future)

| Component | Purpose | When |
|-----------|---------|------|
| Strands SDK | N agents in parallel (L4) | >3 projects with L4 tasks |
| AgentCore | Persistent memory | Cross-session learning at scale |
| EventBridge | Production anomaly detection | Proactive monitoring |

---

## 13. Risk Register

| Risk | Mitigation |
|------|------------|
| Low spec quality → bad output | Spec review as human gate; holdout catches gaps |
| Agent modifies approved tests | Test immutability VETO hook |
| CI failure loop burns tokens | Circuit breaker; max 3 attempts |
| Agent pushes to main | Hook prohibition + branch protection |
| Mirror breaks | Monitor mirror; agent checks both remotes |
| Holdout leaks to agent | Stored separately; loaded only at ship-readiness |

---

## 14. References

1. Bhandwaldar et al. "Agent Factories for HLS." arXiv:2603.25719, 2026.
2. Wong et al. "Confucius Code Agent." arXiv:2512.10398, 2026.
3. StrongDM/Attractor. NLSpec pattern. 2025-2026.
4. Shapiro. "Five Levels of AI Coding Autonomy." 2025.
5. Esposito et al. "GenAI for Software Architecture." arXiv:2503.13310, 2025.
6. Vandeputte et al. "GenAI-Native Design Principles." arXiv:2508.15411, 2025.
7. DiCuffa et al. "Prompt Patterns in AI-Assisted Code Generation." arXiv:2506.01604, 2025.

---

## 15. Observability & Evaluation

### 15.1 Principle

From §0 (Synaptic Engineering): a neural network without feedback signals cannot learn. The factory without observability cannot improve.

### 15.2 Metrics (Derived, Not Collected)

All metrics are derived from artifacts that already exist (completion reports, ALM data via MCP). No additional data collection infrastructure required.

| Metric | Source | What It Indicates |
|--------|--------|-------------------|
| Tasks completed (by workspace, by level) | Completion reports in .kiro/specs/ | Throughput |
| DoD outcomes (PASS / PARTIAL / BLOCK) | Completion reports | Quality gate effectiveness |
| Circuit breaker activations (CODE vs ENV) | Completion reports | Infrastructure health vs code quality |
| MRs opened vs merged vs rejected | ALM via MCP (GitHub/GitLab) | Delivery effectiveness |
| Holdout scenario pass rate | Ship-readiness reports | True quality (agent never saw these tests) |
| Notes generated vs consulted | .kiro/notes/ file dates | Cross-session learning effectiveness |
| Spec refinement loops | Spec status history (READY → IN_PROGRESS → back to REVIEW) | Spec quality |

### 15.3 Factory Health Report

Generated by the meta-agent hook (fde-prompt-refinement) when human triggers it. The report is **factual** (numbers), not **evaluative** (judgments). The human interprets.

```markdown
# Factory Health Report — [Date Range]

## Throughput
- Workspace A: 5 tasks (3 L3, 2 L2)
- Workspace B: 2 tasks (1 L4, 1 L3)
- Workspace C: 0 tasks (awaiting spec)

## Quality Gates
- DoD PASS: 6/7 (85.7%)
- DoD PARTIAL: 1/7 (14.3%)
- DoD BLOCK: 0/7

## Delivery
- MRs opened: 5
- MRs merged (first attempt): 4 (80%)
- MRs requiring revision: 1

## Holdout Scenarios
- Pass rate: 12/14 (85.7%)
- Failures: [list specific scenarios]

## Circuit Breaker
- CODE errors: 8 (all resolved within 3 attempts)
- ENVIRONMENT errors: 2 (escalated to human)

## Learning
- Notes generated: 4
- Notes consulted: 2 (from previous sessions)
```

### 15.4 Evaluation Cadence

| Frequency | What | Who |
|-----------|------|-----|
| Per-task | Completion report (automatic via pipeline validation hook) | Agent generates, human reads |
| On-demand | Factory Health Report (meta-agent hook, userTriggered) | Human triggers, agent generates |
| Monthly | Trend analysis (compare this month vs last month) | Human reviews health reports |
| Per-milestone | Retrospective (what worked, what didn't, what to change) | Human writes in feedback.md |

---

## 16. Adoption & Operations

### 16.1 Prerequisites

- Kiro IDE or Kiro CLI installed
- Git configured with SSH or HTTPS
- Environment variables set: GITHUB_TOKEN, GITLAB_TOKEN (if using GitLab), ASANA_TOKEN (if using Asana)
- MCP servers installed: `npx -y @modelcontextprotocol/server-github` (test with `npx` first)
- Docker installed (for ship-readiness validation)
- Playwright installed (for UI projects): `npx playwright install`

### 16.2 First-Time Setup (One-Time)

```bash
# 1. Clone the factory template
git clone https://github.com/<org>/forward-deployed-ai-pattern.git ~/factory-template

# 2. Create global steerings
mkdir -p ~/.kiro/steering
cp ~/factory-template/docs/global-steerings/agentic-tdd-mandate.md ~/.kiro/steering/
cp ~/factory-template/docs/global-steerings/adversarial-protocol.md ~/.kiro/steering/

# 3. Create global MCP config
mkdir -p ~/.kiro/settings
# Edit ~/.kiro/settings/mcp.json with your tokens (see §10 MCP Powers)

# 4. Create global notes directory
mkdir -p ~/.kiro/notes/shared

# 5. Create factory state file
touch ~/.kiro/factory-state.md
```

### 16.3 Onboarding a New Project

```bash
# 1. Clone the project repo
git clone <project-repo-url> && cd <project-repo>

# 2. Copy factory structure
cp -r ~/factory-template/.kiro .kiro

# 3. Customize .kiro/steering/fde.md for THIS project
# Replace: pipeline chain, module boundaries, régua, test commands

# 4. Enable hooks for the project's engineering level
# L2: enable adversarial-gate + test-immutability + circuit-breaker
# L3: enable all L2 + dor-gate + dod-gate + pipeline-validation + enterprise hooks
# L4: enable all L3 + alternative-exploration

# 5. Open in Kiro IDE
# Verify: type #fde in chat — agent should respond with project context
```

### 16.4 First Task Walkthrough

```
1. Write a spec in .kiro/specs/my-first-feature.md (use NLSpec format from §3.3)
2. Add frontmatter: status: ready
3. In Kiro chat: "#fde Execute the spec in .kiro/specs/my-first-feature.md"
4. Agent executes: DoR gate → Reconnaissance → TDD → Implementation → DoD gate
5. Review the completion report
6. Trigger ship-readiness: click "fde-ship-readiness" in Agent Hooks panel
7. If SHIP-READY: trigger release: click "fde-enterprise-release"
8. Review the MR in GitHub/GitLab
9. Approve and merge
```
