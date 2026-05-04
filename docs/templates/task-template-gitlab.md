# Task Template — GitLab Issues (Ultimate)

> Portable task template for the Autonomous Code Factory.
> Copy this into a new GitLab Issue to create a factory-ready work item.

## Title
<!-- One-line summary: [type] Brief description -->

## Description
<!-- What needs to change and why. Include acceptance criteria. -->

### Factory Metadata
<!-- The agent reads these fields to configure the FDE pipeline. -->

```yaml
platform: gitlab
priority: P1          # P0 (critical) | P1 (high) | P2 (medium) | P3 (low)
level: L3             # L2 (targeted fix) | L3 (cross-module) | L4 (architectural)
spec: .kiro/specs/    # Path to spec file (agent creates if blank)
```

### Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2
- [ ] All existing tests pass
- [ ] Pipeline validation passes (upstream + downstream)

## Labels
<!-- Apply these labels on the GitLab Issue -->
- `factory-ready` — Item is ready for agent pickup
- `priority::P1` — Priority level (scoped label)
- `level::L3` — Engineering level (scoped label)

## Board List Mapping
| Board List | Factory Status | Agent Action |
|-----------|---------------|--------------|
| Open (Backlog) | `backlog` | No action |
| In Progress | `in-progress` | Agent starts FDE protocol |
| In Review | `in-review` | Human reviews MR |
| Closed (Done) | `done` | Human closes after merge |
| Blocked | `blocked` | Agent stops, reports blocker |

## GitLab Ultimate Features Used
| Feature | Purpose |
|---------|---------|
| Issue Boards | Visual status tracking |
| Scoped Labels | `priority::*`, `level::*` for filtering |
| Merge Request Approvals | Human gate before merge |
| Pipeline Status | CI/CD integration for ship-readiness |
| Epics | Group related factory items |
| Iterations | Sprint-level planning |

## Notes
- Move to "In Progress" list on the board to signal the agent to start
- The agent will create a spec file if `spec:` is blank
- The agent will open an MR and move the issue to "In Review" when done
- The agent NEVER closes issues or merges MRs — human approves outcomes
- Use `/label ~factory-ready` quick action to mark items
