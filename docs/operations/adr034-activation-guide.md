# ADR-034 Activation Guide — Knowledge Graph Reconnaissance Layer

> **Date**: 2026-05-15
> **Purpose**: Step-by-step activation and testing of all 7 features from ADR-034.

---

## Prerequisites

- Node.js 18+ installed (for code-intelligence MCP)
- Python 3.11+ (for pipeline modules)
- FDE protocol hooks already configured in `.kiro/hooks/`

---

## Phase A: Enable Features 2, 3, 5 (Knowledge Graph + Hooks)

### Step 1: Index the Repository

```bash
cd /path/to/your-project
npx gitnexus analyze --force
```

Verify: `npx gitnexus list` shows your repo with stats.

### Step 2: Enable Code-Intelligence MCP (Feature 2)

Edit `.kiro/settings/mcp.json` — set `"disabled": false` for `code-intelligence`.

### Step 3: Enable Staleness Hook (Feature 3)

Edit `.kiro/hooks/fde-graph-staleness.kiro.hook` — set `"enabled": true`.

Test: Write any file. Hook fires with staleness check.

### Step 4: Enable Graph-Augmented Search Hook (Feature 3)

Edit `.kiro/hooks/fde-graph-augmented-search.kiro.hook` — set `"enabled": true`.

Test: Read any file. Hook fires suggesting graph queries.

### Step 5: Enable Compound Review Hook (Feature 5)

Edit `.kiro/hooks/fde-compound-review.kiro.hook` — set `"enabled": true`.

Test: Complete a task touching a pipeline module. Review lenses activate.

---

## Phase B: Enable Feature 4 (Machine-Readable DoD v3.0.0)

Already upgraded in `.kiro/hooks/fde-dod-gate.kiro.hook`. Set `"enabled": true`.

Produces 7-dimension compliance matrix with Not-Done signal detection.

---

## Phase C: Implement Features 6, 7

Design docs ready at:
- `docs/design/tiered-evidence-resolution.md` (F6)
- `docs/design/pipeline-process-tracing.md` (F7)

---

## Phase D: Implement Feature 1

Design doc: `docs/design/typed-pipeline-dag-runner.md`

---

## Verification Matrix

| Feature | Test Action | Expected Result |
|---------|------------|-----------------|
| F2 | `list_repos` via MCP | Returns indexed repo |
| F2 | `impact({target: "publish_tree"})` | Returns d=1 callers |
| F3 | Write a file | Staleness hook fires |
| F3 | Read a file | Search augmentation hook fires |
| F4 | Complete a task | 7-dimension DoD matrix |
| F5 | Modify pipeline module | Review lenses triggered |

---

## Rollback

All features independently disableable:
- MCP: `"disabled": true` in mcp.json
- Hooks: `"enabled": false` in any .kiro.hook file
- No existing pipeline behavior modified. All additive.

---

## Hook Inventory After Activation

| Hook | Event | Feature | Status |
|------|-------|---------|--------|
| fde-dor-gate | preTaskExecution | Existing | enabled |
| fde-adversarial-gate | preToolUse | Existing | enabled |
| fde-dod-gate | postTaskExecution | F4 (v3.0.0) | enabled |
| fde-pipeline-validation | postTaskExecution | Existing | enabled |
| fde-graph-staleness | postToolUse (write) | F3 | **new** |
| fde-graph-augmented-search | preToolUse (read) | F3 | **new** |
| fde-compound-review | postTaskExecution | F5 | **new** |
| fde-test-immutability | preToolUse (write) | Existing | enabled |
| fde-circuit-breaker | postToolUse (shell) | Existing | enabled |
| fde-artifact-hygiene-gate | preToolUse (shell) | Existing | enabled |
