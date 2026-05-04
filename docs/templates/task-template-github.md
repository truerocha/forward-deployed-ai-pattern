# Task Template — GitHub Issues

> Portable task template for the Autonomous Code Factory.
> Copy this into a new GitHub Issue to create a factory-ready work item.

## Title
<!-- One-line summary: [type] Brief description -->

## Description
<!-- What needs to change and why. Include acceptance criteria. -->

## Factory Metadata
<!-- The agent reads these fields to configure the FDE pipeline. -->

```yaml
platform: github
priority: P1          # P0 (critical) | P1 (high) | P2 (medium) | P3 (low)
level: L3             # L2 (targeted fix) | L3 (cross-module) | L4 (architectural)
spec: .kiro/specs/    # Path to spec file (agent creates if blank)
```

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2
- [ ] All existing tests pass
- [ ] Pipeline validation passes (upstream + downstream)

## Labels
<!-- Apply these labels on the GitHub Issue -->
- `factory-ready` — Item is ready for agent pickup
- `P1` — Priority level
- `L3` — Engineering level

## Board Status Mapping
| Board Column | Factory Status | Agent Action |
|-------------|---------------|--------------|
| Backlog | `backlog` | No action |
| In Progress | `in-progress` | Agent starts FDE protocol |
| In Review | `in-review` | Human reviews MR |
| Done | `done` | Human closes after merge |
| Blocked | `blocked` | Agent stops, reports blocker |

## Notes
- Move to "In Progress" to signal the agent to start
- The agent will create a spec file if `spec:` is blank
- The agent will open a PR and move the item to "In Review" when done
- The agent NEVER closes issues — human closes after merge
