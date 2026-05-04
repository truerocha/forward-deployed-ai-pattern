# FDE V3.0 — Hook Deployment Guide

> Step-by-step instructions for creating and deploying the 9 new hooks.
> Each hook is specified with its exact JSON content, file path, and activation instructions.
> Engineers can copy-paste each JSON block directly into the target file.

---

## Prerequisites

- Kiro IDE installed and workspace open
- `.kiro/hooks/` directory exists in the workspace
- Existing V2 hooks (4 files) already present:
  - `fde-dor-gate.kiro.hook`
  - `fde-adversarial-gate.kiro.hook`
  - `fde-dod-gate.kiro.hook`
  - `fde-pipeline-validation.kiro.hook`

## Deployment Order

Deploy in this order (dependencies flow top-down):

```
1. fde-test-immutability      (preToolUse — gates test file writes)
2. fde-circuit-breaker         (postToolUse — classifies shell errors)
3. fde-enterprise-backlog      (postTaskExecution — ALM sync)
4. fde-enterprise-docs         (postTaskExecution — ADR + notes)
5. fde-enterprise-release      (userTriggered — commit + MR)
6. fde-ship-readiness          (userTriggered — Docker + E2E + holdout)
7. fde-alternative-exploration (userTriggered — 2 approaches for L4)
8. fde-notes-consolidate       (userTriggered — cleanup notes)
9. fde-prompt-refinement       (userTriggered — meta-agent analysis)
```

---

## Hook 1: fde-test-immutability.kiro.hook

**Purpose**: VETO mechanism. Blocks writes to test files marked `@human-approved`.
**Event**: preToolUse (write)
**SPOF mitigated**: SPOF 1 (Lazy Mocking)
**Engineering level**: L2+

**File**: `.kiro/hooks/fde-test-immutability.kiro.hook`

```json
{
  "enabled": false,
  "name": "FDE Test Immutability Gate",
  "description": "Blocks writes to human-approved test files. The agent must fix production code, never relax approved tests. Enable for L2+ tasks.",
  "version": "1.0.0",
  "when": {
    "type": "preToolUse",
    "toolTypes": ["write"]
  },
  "then": {
    "type": "askAgent",
    "prompt": "FDE TEST IMMUTABILITY GATE\n\nYou are about to write to a file. Check:\n\n1. Is this file a test file? (matches *.test.*, *.spec.*, test_*, *_test.go, *Test.java)\n2. If YES: Does it contain the marker '// @human-approved' or '# @human-approved' at the top?\n3. If APPROVED TEST: ACCESS DENIED. You MUST fix production code to satisfy the test. Do NOT modify assertions, remove test cases, or change expected values.\n4. If test WITHOUT marker: Proceed (not yet approved).\n5. If NOT a test file: Proceed normally.\n\nState: [NOT A TEST | UNAPPROVED TEST - PROCEED | APPROVED TEST - ACCESS DENIED]"
  }
}
```

**Deploy**:
1. Create file `.kiro/hooks/fde-test-immutability.kiro.hook`
2. Paste the JSON above
3. To activate: change `"enabled": false` to `"enabled": true`
4. To mark a test as approved: add `// @human-approved` as the first line of the test file

---

## Hook 2: fde-circuit-breaker.kiro.hook

**Purpose**: Classifies shell errors as CODE or ENVIRONMENT before allowing code changes.
**Event**: postToolUse (shell)
**SPOF mitigated**: SPOF 3 (Token Burner Loop)
**Engineering level**: L2+

**File**: `.kiro/hooks/fde-circuit-breaker.kiro.hook`

```json
{
  "enabled": false,
  "name": "FDE Circuit Breaker",
  "description": "After shell command failure, classifies error as CODE (agent can fix) or ENVIRONMENT (human must fix). Prevents the agent from destroying correct code trying to fix infrastructure problems. Enable for L2+ tasks.",
  "version": "1.0.0",
  "when": {
    "type": "postToolUse",
    "toolTypes": ["shell"]
  },
  "then": {
    "type": "askAgent",
    "prompt": "FDE CIRCUIT BREAKER\n\nA shell command completed. If it SUCCEEDED (exit 0), continue normally.\n\nIf it FAILED:\n1. Read ONLY the last 40 lines of error output.\n2. CLASSIFY:\n   ENVIRONMENT: EADDRINUSE, ECONNREFUSED, timeout, permission denied, EACCES, ENOMEM, disk full, package not found, docker not running, port in use, credential expired, network error\n   CODE: SyntaxError, TypeError, AssertionError, ImportError (project modules), test assertion failed, compilation error\n3. If ENVIRONMENT: STOP. Do NOT touch source code. Report: 'ENVIRONMENT ERROR: [type]. Human action required.'\n4. If CODE: Is this the same error as your previous attempt?\n   Same error, same approach → ABANDON approach, try fundamentally different design.\n   Max 3 attempts per approach. After 3 failed approaches → ROLLBACK and report.\n5. Before fixing: re-read .kiro/specs/WORKING_MEMORY.md to confirm no constraint violations.\n\nState: [SUCCESS | ENVIRONMENT - STOP | CODE - ATTEMPT N/3]"
  }
}
```

**Deploy**:
1. Create file `.kiro/hooks/fde-circuit-breaker.kiro.hook`
2. Paste the JSON above
3. To activate: change `"enabled": false` to `"enabled": true`

---

## Hook 3: fde-enterprise-backlog.kiro.hook

**Purpose**: Syncs task progress to ALM (GitHub Issues / Asana) after task completion.
**Event**: postTaskExecution
**Persona**: Product Owner
**Engineering level**: L3+

**File**: `.kiro/hooks/fde-enterprise-backlog.kiro.hook`

```json
{
  "enabled": false,
  "name": "FDE Enterprise Backlog Sync",
  "description": "After task completion, updates ALM status via MCP and creates tech-debt issues for out-of-scope items discovered during implementation. Skips silently if no MCP configured. Enable for L3+ tasks.",
  "version": "1.0.0",
  "when": {
    "type": "postTaskExecution"
  },
  "then": {
    "type": "askAgent",
    "prompt": "FDE BACKLOG SYNC (Product Owner)\n\n1. ISSUE UPDATE: If spec references an issue (look for 'issue:' in frontmatter), update via MCP:\n   - Tasks remaining → add progress comment\n   - All tasks done → set status 'in-review'\n2. TECH DEBT: If you found out-of-scope items during implementation, create new issues via MCP labeled 'tech-debt'. Do NOT fix them now.\n3. If no MCP configured, skip silently.\n\nOutput: [SYNCED: #X updated | TECH-DEBT: #Y created | NO MCP - SKIPPED]"
  }
}
```

**Deploy**:
1. Create file `.kiro/hooks/fde-enterprise-backlog.kiro.hook`
2. Paste the JSON above
3. Requires: GitHub or GitLab MCP configured in `.kiro/settings/mcp.json`
4. To activate: change `"enabled": false` to `"enabled": true`

---

## Hook 4: fde-enterprise-docs.kiro.hook

**Purpose**: Generates ADR for architectural decisions and hindsight notes for cross-session learning.
**Event**: postTaskExecution
**Persona**: Tech Writer
**Engineering level**: L3+

**File**: `.kiro/hooks/fde-enterprise-docs.kiro.hook`

```json
{
  "enabled": false,
  "name": "FDE Enterprise Docs Generator",
  "description": "After task completion, generates ADR if architectural decisions were made, creates hindsight notes for cross-session learning, and clears working memory. Enable for L3+ tasks.",
  "version": "1.0.0",
  "when": {
    "type": "postTaskExecution"
  },
  "then": {
    "type": "askAgent",
    "prompt": "FDE DOCS (Tech Writer)\n\n1. ADR: Did this task involve an architectural decision (new dependency, pattern, data flow change)?\n   YES → Generate ADR in docs/adr/ with: Status, Context, Decision, Consequences.\n   NO → Skip.\n2. HINDSIGHT NOTE: Write a note capturing what was learned.\n   Project-specific → .kiro/notes/project/\n   Generic (any project) → ~/.kiro/notes/shared/\n   Format: YAML frontmatter (id, title, verification: TESTED|UNTESTED, date) + Context + Insight + Anti-patterns.\n3. Clear .kiro/specs/WORKING_MEMORY.md for next task.\n\nOutput: [ADR: path | NOTE: path | MEMORY CLEARED]"
  }
}
```

**Deploy**:
1. Create file `.kiro/hooks/fde-enterprise-docs.kiro.hook`
2. Paste the JSON above
3. Create directories: `mkdir -p docs/adr .kiro/notes/project`
4. To activate: change `"enabled": false` to `"enabled": true`

---

## Hook 5: fde-enterprise-release.kiro.hook

**Purpose**: Semantic commit, push, and MR creation. Human-triggered only.
**Event**: userTriggered
**Persona**: Release Manager
**Engineering level**: L3+ (L4 for full release)

**File**: `.kiro/hooks/fde-enterprise-release.kiro.hook`

```json
{
  "enabled": false,
  "name": "FDE Enterprise Release Manager",
  "description": "Human-triggered. Performs semantic commit, pushes to feature branch, opens MR/PR via MCP. NEVER merges — human approves the MR. Enable for L3+ tasks.",
  "version": "1.0.0",
  "when": {
    "type": "userTriggered"
  },
  "then": {
    "type": "askAgent",
    "prompt": "FDE RELEASE (Release Manager)\n\n1. PRE-FLIGHT: Verify uncommitted changes exist. Verify NOT on main (create feature branch if needed). Check CI green via MCP if available.\n2. COMMIT: Determine type (feat/fix/refactor/docs/test/chore) and scope from spec. Write semantic commit: <type>(<scope>): <desc>. Body: what and why. Footer: Closes #issue, Spec: path.\n3. PUSH: git push -u origin <branch>.\n4. MR: Create via GitHub/GitLab MCP. Title = commit first line. Body = summary + spec ref + validation results. Assign human as reviewer.\n5. ALM: Update issue to 'in-review', link MR.\n\nNEVER merge. Human approves.\n\nOutput: [RELEASED: PR #X | BLOCKED: reason]"
  }
}
```

**Deploy**:
1. Create file `.kiro/hooks/fde-enterprise-release.kiro.hook`
2. Paste the JSON above
3. Requires: GitHub or GitLab MCP configured
4. To activate: change `"enabled": false` to `"enabled": true`
5. To trigger: Click "FDE Enterprise Release Manager" in Agent Hooks panel, or use Command Palette

---

## Hook 6: fde-ship-readiness.kiro.hook

**Purpose**: Full validation stack — unit tests, Docker E2E, Playwright, BDD, holdout scenarios.
**Event**: userTriggered
**Engineering level**: L3+

**File**: `.kiro/hooks/fde-ship-readiness.kiro.hook`

```json
{
  "enabled": false,
  "name": "FDE Ship-Readiness Validation",
  "description": "Human-triggered. Runs full validation: unit tests, Docker E2E (5min timeout), Playwright, BDD, holdout scenarios. Reports SHIP-READY or NOT READY. Enable for L3+ tasks.",
  "version": "1.0.0",
  "when": {
    "type": "userTriggered"
  },
  "then": {
    "type": "askAgent",
    "prompt": "FDE SHIP-READINESS\n\n1. UNIT TESTS: Run project test suite. ALL must pass.\n2. DOCKER E2E: If docker-compose.test.yml exists, run 'docker compose up -d'. TIMEOUT: 5 minutes max for containers to be healthy. If timeout → report DOCKER TIMEOUT, do NOT retry. Run E2E suite. Then 'docker compose down'.\n3. PLAYWRIGHT: If playwright config exists, run tests. Capture screenshots.\n4. BDD: If .feature files exist, run pytest-bdd or equivalent.\n5. HOLDOUT: If .kiro/specs/holdout/ exists, run those scenarios (agent never saw these during implementation).\n6. REPORT:\n   - Unit: PASS/FAIL (N/M)\n   - Docker: PASS/FAIL/SKIP/TIMEOUT\n   - Playwright: PASS/FAIL/SKIP\n   - BDD: PASS/FAIL/SKIP\n   - Holdout: PASS/FAIL/SKIP\n   - Overall: SHIP-READY or NOT READY (reasons)\n\nOutput: [SHIP-READY | NOT READY: reasons]"
  }
}
```

**Deploy**:
1. Create file `.kiro/hooks/fde-ship-readiness.kiro.hook`
2. Paste the JSON above
3. Optional: Create `.kiro/specs/holdout/` with scenarios the agent should NOT see during implementation
4. Optional: Create `docker-compose.test.yml` for E2E environment
5. To activate: change `"enabled": false` to `"enabled": true`
6. To trigger: Click in Agent Hooks panel after implementation is complete

---

## Hook 7: fde-alternative-exploration.kiro.hook

**Purpose**: Generates 2 alternative approaches for L4 architectural tasks before implementing.
**Event**: userTriggered
**Engineering level**: L4 only

**File**: `.kiro/hooks/fde-alternative-exploration.kiro.hook`

```json
{
  "enabled": false,
  "name": "FDE Alternative Exploration",
  "description": "Human-triggered for L4 tasks. Agent generates 2 distinct approaches with trade-offs. Human chooses before implementation begins. Enable only for L4 architectural tasks.",
  "version": "1.0.0",
  "when": {
    "type": "userTriggered"
  },
  "then": {
    "type": "askAgent",
    "prompt": "FDE ALTERNATIVE EXPLORATION (L4)\n\nGenerate 2 distinct approaches for the current task.\n\nFor each:\n## Approach [A/B]: [Name]\n- Architecture: [design, modules, data flow]\n- Trade-offs: [gains vs losses]\n- Complexity: [estimated LOC, files, dependencies]\n- Risk: [what could go wrong]\n- Constraint alignment: [how it satisfies MUST/MUST NOT]\n\n## Recommendation\nWhich and why? What would change your mind?\n\nDo NOT implement. Present both. Human decides.\n\nOutput: [APPROACHES PRESENTED - AWAITING DECISION]"
  }
}
```

**Deploy**:
1. Create file `.kiro/hooks/fde-alternative-exploration.kiro.hook`
2. Paste the JSON above
3. To activate: change `"enabled": false` to `"enabled": true`
4. To trigger: Click in Agent Hooks panel before starting an L4 task

---

## Hook 8: fde-notes-consolidate.kiro.hook

**Purpose**: Archives old notes, merges duplicates, updates README index.
**Event**: userTriggered
**Engineering level**: Any (maintenance task)

**File**: `.kiro/hooks/fde-notes-consolidate.kiro.hook`

```json
{
  "enabled": false,
  "name": "FDE Notes Consolidation",
  "description": "Human-triggered. Reviews notes, archives >90 days old (without PINNED tag), merges duplicates, updates README. Proposes changes for human confirmation.",
  "version": "1.0.0",
  "when": {
    "type": "userTriggered"
  },
  "then": {
    "type": "askAgent",
    "prompt": "FDE NOTES CONSOLIDATION\n\n1. ARCHIVE: List notes in .kiro/notes/ and ~/.kiro/notes/shared/ with date >90 days that lack [PINNED] in frontmatter. Propose moving to archive/ subdirectory.\n2. DUPLICATES: Identify notes on same topic. Propose merging.\n3. PROMOTION: Check .kiro/meta/feedback.md for patterns marked 'repeatedly useful'. Propose promoting to steering.\n4. README: Regenerate .kiro/notes/README.md with index of active notes.\n\nPropose all changes. Do NOT execute without human confirmation.\n\nOutput: [ARCHIVE: N | MERGE: M | PROMOTE: P | README: updated]"
  }
}
```

**Deploy**:
1. Create file `.kiro/hooks/fde-notes-consolidate.kiro.hook`
2. Paste the JSON above
3. Create: `mkdir -p .kiro/notes/archive`
4. To activate: change `"enabled": false` to `"enabled": true`
5. Recommended frequency: Monthly or after every 20 tasks

---

## Hook 9: fde-prompt-refinement.kiro.hook

**Purpose**: Meta-agent that analyzes factory performance and suggests hook/steering improvements.
**Event**: userTriggered
**Engineering level**: Any (maintenance task)

**File**: `.kiro/hooks/fde-prompt-refinement.kiro.hook`

```json
{
  "enabled": false,
  "name": "FDE Prompt Refinement (Meta-Agent)",
  "description": "Human-triggered. Analyzes completion reports and human feedback to suggest improvements to hook prompts and steerings. Also generates Factory Health Report with aggregated metrics. Threshold: 2+ feedback items required before suggesting changes.",
  "version": "1.0.0",
  "when": {
    "type": "userTriggered"
  },
  "then": {
    "type": "askAgent",
    "prompt": "FDE META-AGENT\n\n1. HEALTH REPORT: Read recent completion reports in .kiro/specs/. Calculate:\n   - Tasks completed (by level)\n   - DoD outcomes (PASS/PARTIAL/BLOCK)\n   - Circuit breaker activations\n   - Notes generated vs consulted\n2. FEEDBACK ANALYSIS: Read .kiro/meta/feedback.md. Identify:\n   - Hooks reported as 'not useful' or 'consistently N/A'\n   - Missing checks reported by human\n   - Steerings reported as 'too verbose' or 'missing context'\n3. SUGGESTIONS: For each pattern (threshold: 2+ items):\n   - What to change (file + section)\n   - Current text\n   - Proposed text\n   - Justification\n   - Risk assessment\n4. SAFETY: Suggestions only. Human applies manually. Never auto-modify hooks.\n\nOutput: [HEALTH REPORT + N SUGGESTIONS | NO CHANGES NEEDED]"
  }
}
```

**Deploy**:
1. Create file `.kiro/hooks/fde-prompt-refinement.kiro.hook`
2. Paste the JSON above
3. Create: `mkdir -p .kiro/meta && touch .kiro/meta/feedback.md`
4. To activate: change `"enabled": false` to `"enabled": true`
5. Recommended frequency: After every 10 tasks or monthly

---

## Activation by Engineering Level

After deploying all 9 hooks, enable them based on the project's engineering level:

| Hook | L1 | L2 | L3 | L4 |
|------|:--:|:--:|:--:|:--:|
| fde-test-immutability | — | ✓ | ✓ | ✓ |
| fde-circuit-breaker | — | ✓ | ✓ | ✓ |
| fde-enterprise-backlog | — | — | ✓ | ✓ |
| fde-enterprise-docs | — | — | ✓ | ✓ |
| fde-enterprise-release | — | — | ✓ | ✓ |
| fde-ship-readiness | — | — | ✓ | ✓ |
| fde-alternative-exploration | — | — | — | ✓ |
| fde-notes-consolidate | — | — | ✓ | ✓ |
| fde-prompt-refinement | — | — | ✓ | ✓ |

**Quick enable for L3** (most common):
```bash
# In each hook file, change "enabled": false to "enabled": true
# Skip: fde-alternative-exploration (L4 only)
```

## Verification

After deploying, verify the hooks are recognized:

1. Open Kiro IDE with the workspace
2. Open the **Agent Hooks** panel in the explorer sidebar
3. Verify all 13 hooks appear (4 V2 + 9 V3)
4. Test: type `#fde test the adversarial gate` in chat
5. The adversarial gate should fire when the agent attempts a write operation
