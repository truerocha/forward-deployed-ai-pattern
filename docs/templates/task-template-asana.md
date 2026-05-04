# Task Template — Asana Tasks

> Portable task template for the Autonomous Code Factory.
> Use this structure when creating Asana tasks for agent pickup.

## Task Name
<!-- One-line summary: [type] Brief description -->

## Task Description (Notes)
<!-- What needs to change and why. Include acceptance criteria. -->

### Factory Metadata
<!-- The agent reads these fields from the task notes. -->

```yaml
platform: asana
priority: P1          # P0 (critical) | P1 (high) | P2 (medium) | P3 (low)
level: L3             # L2 (targeted fix) | L3 (cross-module) | L4 (architectural)
spec: .kiro/specs/    # Path to spec file (agent creates if blank)
repo: owner/repo      # GitHub/GitLab repo for code changes
```

### Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2
- [ ] All existing tests pass
- [ ] Pipeline validation passes (upstream + downstream)

## Custom Fields (Configure in Asana Project)
| Custom Field | Values | Purpose |
|-------------|--------|---------|
| Priority | P0, P1, P2, P3 | Agent reads to determine urgency |
| Engineering Level | L2, L3, L4 | Agent reads to determine hook activation |
| Spec Path | text | Path to .kiro/specs/ file |
| Repository | text | owner/repo for code changes |

## Tags
- `factory-ready` — Item is ready for agent pickup
- `tech-debt` — Created by agent for out-of-scope items

## Section (Board Column) Mapping
| Asana Section | Factory Status | Agent Action |
|--------------|---------------|--------------|
| Backlog | `backlog` | No action |
| In Progress | `in-progress` | Agent starts FDE protocol |
| In Review | `in-review` | Human reviews MR |
| Done | `done` | Human completes after merge |
| Blocked | `blocked` | Agent stops, reports blocker |

## Notes
- Move to "In Progress" section to signal the agent to start
- The agent reads the task notes for factory metadata
- The agent adds comments to the task with progress updates
- The agent moves the task to "In Review" when MR is opened
- The agent NEVER completes tasks — human completes after merge
