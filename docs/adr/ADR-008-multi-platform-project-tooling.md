# ADR-008: Multi-Platform Project Tooling — GitHub Projects, Asana, GitLab Ultimate

## Status
Accepted

## Date
2026-05-04

## Context
The Autonomous Code Factory needs to integrate with three ALM platforms to support diverse enterprise environments:
- **GitHub Projects** — native for open-source and GitHub-centric teams
- **Asana** — common in product-led organizations for cross-functional planning
- **GitLab Ultimate** — enterprise self-hosted with built-in CI/CD and boards

ADR-006 established the principle of ALM integration via MCP. This ADR extends it with:
1. A portable task template that works across all three platforms
2. API validation scripts to verify connectivity before automation
3. A trigger mechanism: when a human moves a backlog item to "In Progress", the Code Factory agent pipeline starts

## Decision

### 1. Portable Task Template
A canonical task schema defines the minimum fields required regardless of platform. Each platform adapter maps its native fields to this schema.

```yaml
# Canonical Task Schema
id: string           # Platform-native ID (GH-123, ASANA-456, GL-789)
title: string        # One-line summary
description: string  # Full description / acceptance criteria
status: string       # backlog | in-progress | in-review | done | blocked
priority: string     # P0 | P1 | P2 | P3
labels: string[]     # Tags / labels
assignee: string     # Human owner
spec_path: string    # Path to .kiro/specs/ file (if exists)
source: string       # github | asana | gitlab
```

### 2. Platform Adapters
Each platform has an MCP server and a field mapping:

| Canonical Field | GitHub Projects | Asana | GitLab Ultimate |
|----------------|----------------|-------|-----------------|
| id | `issue.number` | `task.gid` | `issue.iid` |
| title | `issue.title` | `task.name` | `issue.title` |
| description | `issue.body` | `task.notes` | `issue.description` |
| status | Project field "Status" | Section name | Board list label |
| priority | Label `P0`-`P3` | Custom field "Priority" | Label `priority::*` |
| labels | `issue.labels` | `task.tags` | `issue.labels` |
| assignee | `issue.assignees[0]` | `task.assignee` | `issue.assignees[0]` |
| spec_path | Body contains `spec: path` | Custom field or notes | Description contains `spec: path` |
| source | `"github"` | `"asana"` | `"gitlab"` |

### 3. Trigger Mechanism — "In Progress" Starts the Factory
The flow is:
1. Human moves item to "In Progress" on the board
2. A polling hook or webhook detects the status change
3. The agent receives the task context and begins the FDE protocol (Phase 1 → 2 → 3 → 4)

Since Kiro hooks are IDE-local (not webhook receivers), the trigger is implemented as:
- A **userTriggered hook** (`fde-work-intake`) that the human fires after moving the item
- The hook reads the current board state via MCP, finds "In Progress" items, and starts the pipeline
- Future: a CI/CD webhook can call Kiro CLI to automate this fully

### 4. API Validation
A validation script checks connectivity to each configured platform before the factory operates. This prevents silent failures during task execution.

## Consequences
- All three platforms use the same task template — specs are portable
- The agent can read from any platform and write status updates back
- Graceful degradation: if a platform MCP is disabled, the agent skips it
- The human trigger ensures the human decides WHAT enters the pipeline
- API validation runs as a pre-flight check, not during task execution

## Related
- ADR-006: Enterprise ALM Integration via MCP
- Flow: 01-work-intake.md
- Hook: fde-enterprise-backlog.kiro.hook
