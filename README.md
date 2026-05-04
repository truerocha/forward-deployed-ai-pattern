# Forward Deployed Engineer — Autonomous Code Factory

### GenAI powered by Kiro

> From reactive code writer to autonomous engineering partner.
> The Staff Engineer writes specs. The factory ships code.

[![Tests](https://img.shields.io/badge/tests-54%20passed-brightgreen)]()
[![Hooks](https://img.shields.io/badge/hooks-13%20(4%20V2%20%2B%209%20V3)-blue)]()
[![Autonomy Level](https://img.shields.io/badge/level-L4%20Autonomous%20Factory-purple)]()

---

## What Is This?

This repo is a **factory template** for enterprise-grade AI-assisted software development using [Amazon Kiro](https://kiro.dev). It implements the **Autonomous Code Factory pattern** (Level 4 autonomy) where AI agents handle the full development loop — writing, testing, reviewing, and packaging code — while the human engineer operates as **Factory Operator**, writing specs and approving outcomes.

The pattern is built on **Forward Deployed Engineers (FDEs)** — AI agents deployed into a project's specific context: its pipeline architecture, its knowledge artifacts, its quality standards, and its governance boundaries. An FDE is not a general-purpose coding assistant. It is an engineering partner that knows your system.

## The Operating Model

```
Staff Engineer writes spec → Agent generates tests → Human approves tests
  → Agent implements (makes tests green) → Adversarial gate challenges each write
    → CI/CD validates → Ship-readiness (Docker + E2E + holdout scenarios)
      → Agent opens MR → Human approves outcome → Code ships
```

The Staff Engineer:
- **Writes specs** (the control plane — what should exist)
- **Approves test contracts** (the halting condition — when is it done)
- **Approves outcomes** (the MR — does it serve the user)
- **Never writes implementation code**
- **Never reviews diffs line-by-line** (automated gates handle correctness)

## Empirical Results

Same task, same AI agent. Without FDE protocol: **33%** quality score. With FDE protocol: **100%** quality score.

```
FDE wins: 12 criteria  |  Bare wins: 0  |  Ties: 6
Improvement: +67 percentage points
```

## Quick Start

### 1. Global setup (one-time)

```bash
git clone https://github.com/truerocha/forward-deployed-engineer-pattern.git ~/factory-template
cd ~/factory-template
bash scripts/provision-workspace.sh --global
```

### 2. Onboard a project

```bash
cd ~/projects/my-project
bash ~/factory-template/scripts/provision-workspace.sh --project
# Then customize .kiro/steering/fde.md for YOUR project
```

### 3. Activate in Kiro

```
# In Kiro chat:
#fde Execute the spec in .kiro/specs/my-feature.md

# Enable hooks in Agent Hooks panel based on engineering level:
# L2: adversarial-gate + test-immutability + circuit-breaker
# L3: All L2 + dor-gate + dod-gate + pipeline-validation + enterprise hooks
# L4: All L3 + alternative-exploration
```

See [docs/guides/fde-adoption-guide.md](docs/guides/fde-adoption-guide.md) for the full walkthrough.

## Architecture — The Factory Floor

```
~/.kiro/ (GLOBAL — universal laws, shared credentials, cross-project knowledge)
    │
    ├── WORKSPACE A ──── Spec in → Ship-ready MR out
    ├── WORKSPACE B ──── Spec in → Ship-ready MR out
    └── WORKSPACE C ──── Spec in → Ship-ready MR out
```

Each workspace is a **production line** for a specific codebase. The Staff Engineer manages multiple lines simultaneously, routing work and approving outcomes.

### Design Philosophy — Synaptic Engineering

The factory operates on four neuro-inspired principles:

| Principle | Meaning | Implementation |
|-----------|---------|---------------|
| **Neurons** | Every component has rigid input/output contracts | Workspace input = spec, output = MR |
| **Synaptic Cleft** | Context transmission must be clean and minimal | Steerings load only relevant context |
| **Neural Plasticity** | Successful patterns strengthen, unused patterns decay | Notes with verification status + date-based archival |
| **Executive Function** | Human decides WHAT/WHY, agent decides HOW | Spec-driven development, never agent-driven scope |

## The 13 Hooks

| Hook | Event | Purpose | Level |
|------|-------|---------|-------|
| fde-dor-gate | preTaskExecution | Readiness validation | L3+ |
| fde-adversarial-gate | preToolUse (write) | Challenge each write | L2+ |
| fde-dod-gate | postTaskExecution | Conformance validation | L3+ |
| fde-pipeline-validation | postTaskExecution | Pipeline testing + 5W2H + report | L3+ |
| fde-test-immutability | preToolUse (write) | VETO writes to approved tests | L2+ |
| fde-circuit-breaker | postToolUse (shell) | Error classification (code vs environment) | L2+ |
| fde-enterprise-backlog | postTaskExecution | ALM sync (GitHub Issues / Asana) | L3+ |
| fde-enterprise-docs | postTaskExecution | ADR generation + hindsight notes | L3+ |
| fde-enterprise-release | userTriggered | Semantic commit + MR via MCP | L3+ |
| fde-ship-readiness | userTriggered | Docker + E2E + Playwright + holdout | L3+ |
| fde-alternative-exploration | userTriggered | 2 approaches for L4 architectural tasks | L4 |
| fde-notes-consolidate | userTriggered | Archive old notes, merge duplicates | L3+ |
| fde-prompt-refinement | userTriggered | Meta-agent: factory health + prompt improvements | L3+ |

## Repo Structure

```
forward-deployed-engineer-pattern/
├── .kiro/                          # Factory template (copy to your projects)
│   ├── steering/                   # Protocol + enterprise context
│   ├── hooks/                      # 13 hooks (4 V2 + 9 V3)
│   ├── specs/                      # Working memory + holdout templates
│   ├── notes/                      # Cross-session learning structure
│   ├── meta/                       # Human feedback + refinement log
│   └── settings/                   # MCP config template
├── docs/
│   ├── design/                     # V2 design document (research foundations)
│   ├── blueprint/                  # V3 Autonomous Code Factory blueprint + artifacts + deploy guide
│   ├── guides/                     # Adoption guide (onboarding walkthrough)
│   └── global-steerings/           # Templates for ~/.kiro/steering/
├── examples/
│   ├── web-app/                    # Example: FDE for a web application
│   └── data-pipeline/             # Example: FDE for a data pipeline
├── scripts/
│   ├── provision-workspace.sh      # Automated onboarding (--global | --project)
│   └── lint_language.py            # Weasel words / language linter
└── tests/
    ├── test_fde_e2e_protocol.py    # Structural E2E test (48 tests)
    └── test_fde_quality_threshold.py # Quality comparison test (6 tests)
```

## Research Foundations

The pattern is grounded in six peer-reviewed studies:

1. **Esposito et al. (2025)** — 93% of GenAI architecture studies lack formal validation
2. **Vandeputte et al. (2025)** — Verification at all levels, not only unit tests
3. **Shonan Meeting 222 (2025)** — Greenfield doesn't generalize to brownfield
4. **DiCuffa et al. (2025)** — "Context and Instruction" is the most efficient prompt pattern (p<10⁻³²)
5. **Bhandwaldar et al. (2026)** — Agent scaling yields 8.27× mean speedup with 10 agents
6. **Wong et al. (2026)** — Agent scaffolding matters as much as model capability (CCA: 59% on SWE-Bench-Pro)

## Running the Tests

```bash
# All tests
python3 -m pytest tests/ -v

# Structural E2E — validates all artifacts are coherent
python3 -m pytest tests/test_fde_e2e_protocol.py -v

# Quality threshold — compares bare vs FDE responses
python3 -m pytest tests/test_fde_quality_threshold.py -v -s

# Language lint
python3 scripts/lint_language.py docs/design/forward-deployed-ai-engineers.md
```

## CI/CD Integration

The factory integrates with:
- **GitHub Actions** — primary CI
- **GitLab CI Ultimate** — via mirror script
- **MCP Powers** — GitHub, GitLab, Asana for ALM automation

Agents ALWAYS work on feature branches. They NEVER merge, deploy, or modify CI config.

## License

MIT

## Contributing

PRs welcome. If you apply the Forward Deployed Engineer pattern to your project and have results to share, open an issue — we'd love to add your case study.
