# Scope Boundaries: Autonomous Code Factory

> Status: Active
> Date: 2026-05-04
> ADR: ADR-013
> Enforced by: `infra/docker/agents/scope_boundaries.py`

## In-Scope

The Code Factory handles tasks that meet ALL of the following criteria:

| Capability | Autonomy Level | Confidence Requirement |
|---|---|---|
| Implement features from structured specs | L3-L4 (Consultant/Approver) | High |
| Fix bugs with clear acceptance criteria | L4-L5 (Approver/Observer) | Medium+ |
| Generate documentation (ADRs, reports) | L5 (Observer) | Any |
| Open PRs with tested code | L4 (Approver) | Medium+ |
| Extract constraints from design documents | L5 (Observer) | Any |
| Run quality gates (lint, test, build) | L5 (Observer) | Any |
| Update ALM platforms (comments, status) | L5 (Observer) | Any |
| Create tech-debt issues for out-of-scope items | L5 (Observer) | Any |

## Out-of-Scope

The Code Factory NEVER performs these actions regardless of task content:

| Forbidden Action | Reason | Detection |
|---|---|---|
| Deploy to production | Unacceptable risk for autonomous agent | Regex on description/criteria |
| Merge PRs/MRs | Human must approve outcomes | Regex on description/criteria |
| Close issues | Human closes after MR merge | Regex on description/criteria |
| Modify issue priority/assignment | Organizational governance | Hard-coded rule |
| Force push to any branch | Destructive, irreversible | Regex on description/criteria |
| Delete repositories | Destructive, irreversible | Regex on description/criteria |
| Work on main/master branch | Branch protection | Hard-coded in Project Isolation |
| Tasks without acceptance criteria | No halting condition | DoR Gate validation |
| Tasks without tech_stack | Agent Builder cannot specialize | DoR Gate validation |

## Performance Targets

Performance is measured per autonomy level:

| Metric | L5 (Observer) | L4 (Approver) | L3 (Consultant) |
|---|---|---|---|
| Lead Time (InProgress → PR) | < 30min | < 2h | < 8h |
| Change Failure Rate | < 5% | < 10% | < 15% |
| Inner Loop First-Pass Rate | > 85% | > 75% | > 60% |
| Acceptance Rate (PR merged) | > 90% | > 80% | > 70% |

### DORA Performance Level Classification

| Level | Lead Time | Deploy Frequency | CFR | MTTR |
|---|---|---|---|---|
| Elite | < 1h | > 1/day | < 5% | < 1h |
| High | < 24h | > 1/week | < 10% | < 24h |
| Medium | < 7d | > 1/month | < 15% | < 7d |
| Low | > 7d | < 1/month | > 15% | > 7d |

## Confidence Levels

Each task receives a confidence score based on available signals:

| Signal | Points | Description |
|---|---|---|
| tech_stack has configured tooling | +1 | Inner loop gates can run |
| acceptance_criteria >= 3 items | +1 | Clear halting condition |
| constraints field is present | +1 | Boundaries are explicit |
| related_docs are provided | +1 | Context is available |

| Score | Confidence | Meaning |
|---|---|---|
| 3-4 | High | Factory can execute with high probability of success |
| 2 | Medium | Factory can execute but may need human intervention |
| 0-1 | Low | Factory accepts but warns — higher failure probability |

## Trigger to Revisit

This document should be updated when:
- A new tech_stack is added to the supported set
- A new forbidden action is identified
- Performance targets are consistently missed (review thresholds)
- A task type is added or removed from the factory's capabilities
- DORA metrics show a domain consistently below "Medium" level
