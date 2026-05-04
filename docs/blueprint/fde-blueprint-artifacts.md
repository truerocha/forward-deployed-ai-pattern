# FDE V3.0 — Executable Artifacts Specification

> Every artifact below is the EXACT content to be created. No interpretation needed.
> Corrections F2-F7 from Adversarial/Red Team review are embedded.

---

## Corrections Applied

| ID | Issue | Fix |
|----|-------|-----|
| F2 | §0.3 used stateful counters (impossible) | Date-based decay; human-driven reinforcement via feedback.md |
| F3 | §2.6 assumed cross-workspace hook writes | Factory state is human-maintained |
| F4 | §7.2 no Docker timeout | 5-minute timeout; fallback to human on failure |
| F5 | §4 no READY mechanism | YAML frontmatter `status: ready` in spec; DoR gate checks it |
| F6 | §2.5 assumed Kiro cross-workspace primitive | Agent uses standard file tools to write to ~/.kiro/ (filesystem access) |
| F7 | §0.2 no interface validation mechanism | Interface contracts in ~/.kiro/contracts/; agent reads before implementing |
| F5b | §4.3 agent decides WHAT | Changed to "agent PROPOSES spec → human approves" |

---

## Hook Artifacts (9 new hooks)

### fde-test-immutability.kiro.hook
- Event: preToolUse (write)
- Action: askAgent — VETO if writing to @human-approved test file
- Key behavior: If test file has `// @human-approved` marker, ACCESS DENIED

### fde-circuit-breaker.kiro.hook
- Event: postToolUse (shell)
- Action: askAgent — classify error as CODE or ENVIRONMENT
- Key behavior: ENVIRONMENT errors → STOP, never touch code. CODE errors → max 3 attempts same approach, then try different, then rollback

### fde-enterprise-backlog.kiro.hook
- Event: postTaskExecution
- Action: askAgent (PO persona) — update ALM via MCP, create tech-debt issues
- Key behavior: Graceful skip if no MCP configured

### fde-enterprise-docs.kiro.hook
- Event: postTaskExecution
- Action: askAgent (Tech Writer persona) — generate ADR if architectural decision, generate hindsight note, clear working memory
- Key behavior: Notes classified as project-specific or shared (writes to ~/.kiro/notes/shared/ for generic)

### fde-enterprise-release.kiro.hook
- Event: userTriggered
- Action: askAgent (Release Manager persona) — semantic commit, push, open MR via MCP, update ALM
- Key behavior: NEVER merges. Human approves MR.

### fde-ship-readiness.kiro.hook
- Event: userTriggered
- Action: askAgent — run full validation stack (unit, Docker E2E, Playwright, BDD, holdout)
- Key behavior: 5-minute timeout on Docker. Reports SHIP-READY or NOT READY with reasons.

### fde-alternative-exploration.kiro.hook
- Event: userTriggered
- Action: askAgent — generate 2 approaches with trade-offs, await human decision
- Key behavior: Does NOT implement. Presents options. Human chooses.

### fde-notes-consolidate.kiro.hook
- Event: userTriggered
- Action: askAgent — archive notes >90 days (no PINNED), merge duplicates, update README
- Key behavior: Proposes changes, human confirms before execution.

### fde-prompt-refinement.kiro.hook
- Event: userTriggered
- Action: askAgent — analyze feedback.md, suggest hook/steering improvements
- Key behavior: Threshold of 2+ feedback items. Suggestions only, never auto-modifies.

---

## Steering Artifacts (2 global)

### ~/.kiro/steering/agentic-tdd-mandate.md
- Inclusion: auto (loaded in EVERY interaction)
- Content: Shift-left testing, halting condition, anti-lazy-mock, test immutability rules

### ~/.kiro/steering/adversarial-protocol.md
- Inclusion: auto (loaded in EVERY interaction)
- Content: 3-phase protocol (Builder → Attacker → Handoff), mandatory for L3+ tasks

---

## MCP Configuration (.kiro/settings/mcp.json)

Template with GitHub + GitLab servers. Credentials via ${env:VAR} references. autoApprove for read-only operations.

---

## Spec READY Mechanism

Specs use YAML frontmatter:
```yaml
---
status: ready    # draft | review | ready | in_progress | shipped
issue: "#123"
level: L3
---
```

DoR gate checks `status: ready` before allowing execution. If not ready, agent reports and waits.

---

## Error Signal (MR Rejected)

MR rejected → Human writes feedback → Human updates spec → Human marks ready → Agent re-executes.
NOT automated. Human is the error signal.

---

## Interface Contracts (Inter-Workspace)

Location: `~/.kiro/contracts/<project-name>/`
Format: OpenAPI spec, TypeScript type definitions, or Protocol Buffer definitions.
Maintained by: Human (when APIs change).
Consumed by: Agent in dependent workspace reads contract before implementing against it.
