# ADR-012: Over-Engineering Mitigations and Architectural Gap Closures

## Status
Accepted

## Date
2026-05-04

## Context
After comparing the Code Factory architecture against the AWS DevAx AI-SDLC framework ("From Friction to Flow", 2025), six items were identified:

- 3 over-engineering risks requiring mitigation
- 3 architectural gaps requiring closure

This ADR documents the structured adversarial reasoning applied to each decision. Each item follows the protocol:

1. **Proposed change** states what to do
2. **Counter-position** presents the strongest reason not to do it
3. **Resolution** documents the final decision with evidence
4. **Trigger to revisit** defines when to re-evaluate

---

## Decision 1: LLM Constraint Extraction — Default Off (Opt-In)

### Proposed Change
Make the LLM-based constraint extraction pass opt-in rather than default. The rule-based pass (regex) handles version pins, latency thresholds, auth mandates, encryption requirements, and dependency exclusions at zero cost and sub-millisecond latency.

### Counter-Position
The rule-based pass only catches structured patterns. Prose constraints like "the system must gracefully degrade under network partition" require semantic understanding that regex cannot provide.

### Resolution
The counter-position is valid for nuanced prose. However:

- The GitHub issue template uses structured fields (checkboxes, dropdowns) that produce regex-friendly output. Prose constraints appear only in free-text fields.
- LLM pass adds ~2-5s latency and ~$0.01/task. For 50 tasks/day, that is $0.50/day — negligible cost but measurable latency on every task.
- LLM pass is available via three opt-in mechanisms: constructor flag, environment variable (`CONSTRAINT_LLM_ENABLED=true`), or per-task field (`enable_llm_extraction: true`).
- The DORA metrics collector records `used_llm` in the `constraint_extraction_time` metric for data-driven evaluation.

**Decision**: Default off. Opt-in per task or globally.

### Trigger to Revisit
- DORA metrics show >20% of tasks have constraints that rule-based extraction misses
- A constraint violation occurs that rule-based extraction should have caught
- L4 tasks consistently require manual constraint entry

### Implementation
- `constraint_extractor.py`: `__init__` accepts `llm_enabled: bool = False`
- `extract()` checks three opt-in sources before invoking LLM
- Added `import os` for environment variable check

---

## Decision 2: Fast Path for Simple Tasks

### Proposed Change
Skip constraint extraction entirely for bugfix and documentation tasks that have empty `constraints` and `related_docs` fields.

### Counter-Position
This creates a bypass. A developer could file a feature as a "bugfix" to skip the constraint gate. Even bugfixes can violate constraints.

### Resolution
- The fast path only activates when BOTH conditions are true: task type is bugfix/documentation AND constraints+related_docs are empty.
- Feature and infrastructure tasks NEVER qualify for fast path regardless of field emptiness.
- The type field comes from the issue template dropdown, not free text. Misclassification requires deliberate action.
- DORA metrics record task type with outcomes. If bugfix failure rate exceeds feature failure rate, the fast path is suspect.

**Decision**: Fast path enabled for bugfix/documentation with empty constraints. Feature/infrastructure always go through full extraction.

### Trigger to Revisit
- Bugfix change failure rate exceeds feature change failure rate
- A bugfix causes a constraint violation that extraction would have caught
- More than 30% of tasks are filed as "bugfix" (potential gaming)

### Implementation
- `orchestrator.py`: Added `_is_fast_path()` static method
- `handle_event()` checks fast path before running extraction

---

## Decision 3: Multi-Cloud Adapter — Deferred

See ADR-011 for the full analysis. Summary: defer until a customer requires a second cloud provider. The `target_environment` field remains in the data contract as a forward-compatible extension point.

---

## Decision 4: Factory Health Report (DORA Dashboard)

### Proposed Change
Add a `generate_factory_report()` method that computes all metrics over a time window and produces a structured JSON report with DORA performance level classification (Elite/High/Medium/Low).

### Counter-Position
A JSON file in S3 is not a dashboard. Without a presentation layer (CloudWatch, Grafana, Slack), this is unused data.

### Resolution
- The report is the data layer, not the presentation layer. CloudWatch dashboards, Grafana, and Slack integrations all consume JSON.
- The S3 report enables serverless analytics: Athena can query reports directly.
- The DORA level classification provides immediate value — the Reporting Agent can include it in ALM comments.
- Presentation layer is a separate concern: add when the factory has enough data (after ~30 tasks).

**Decision**: Build the report generator now. Defer the presentation layer until 30+ tasks have been processed.

### Trigger to Revisit
- Factory has processed 30+ tasks and no presentation layer exists
- Staff Engineer requests a visual dashboard
- DORA level drops below "High" and nobody notices

### Implementation
- `dora_metrics.py`: Added `generate_factory_report()`, `_within_window()`, `_humanize_ms()`
- Report persisted to `s3://{bucket}/reports/factory-health/{timestamp}.json`

---

## Decision 5: PR Diff Review Gate

### Proposed Change
Add a PR diff review gate that scans the git diff for secrets, debug code, sensitive files, and excessively large changes.

### Counter-Position
This duplicates what GitHub Advanced Security and pre-commit hooks already do. The Adversarial Gate already runs before every write.

### Resolution
- The Adversarial Gate operates at the individual write level. The PR diff review operates at the aggregate level (the complete changeset).
- GitHub Advanced Security is not always available (free-tier repos, self-hosted GitLab).
- The gate catches agent-specific issues: debug prints, breakpoints, excessively large changes indicating the agent went off-track.
- This is defense in depth, not duplication.

**Decision**: Build the PR diff review gate as the final outer loop gate.

### Trigger to Revisit
- If all target repos have equivalent SAST, consider making this gate optional
- If the gate produces >50% false positives, tune the patterns

### Implementation
- `pipeline_safety.py`: `review_diff()` with secret patterns, debug patterns, size checks
- Secrets are hard rejections; debug code and size are warnings

---

## Decision 6: Automatic Rollback

### Proposed Change
When the Circuit Breaker exhausts all retries (3 attempts), automatically rollback the feature branch to its pre-agent checkpoint using `git reset --hard`.

### Counter-Position
`git reset --hard` is destructive. Partial commits from the agent may contain valuable progress. Force push to remote is dangerous.

### Resolution
- The agent works on isolated feature branches (never main/master). The rollback refuses to operate on main/master.
- Partial commits from a pipeline that encountered 3 consecutive errors are not trustworthy. A clean rollback to the checkpoint is safer than cherry-picking from an inconsistent state.
- The rollback does NOT force push. It only resets the local branch. The remote retains history.
- The checkpoint is recorded BEFORE the agent starts via `record_branch_checkpoint()`.

**Decision**: Build automatic rollback with checkpoint mechanism. Local reset only, no force push.

### Trigger to Revisit
- If agents start making valuable partial progress, consider `git revert` instead of `git reset --hard`
- If remote branches need cleanup, add an optional force-push flag (requires explicit human approval)

### Implementation
- `pipeline_safety.py`: `record_branch_checkpoint()` and `rollback_to_checkpoint()`
- Refuses main/master, logs commits reverted, cleans untracked files

---

## Consequences

### Over-Engineering Mitigations
1. LLM extraction is opt-in — saves ~2-5s latency and ~$0.01/task on the default path
2. Fast path skips extraction for simple bugfixes — reduces pipeline overhead for ~60% of tasks
3. Multi-cloud adapter deferred — eliminates ~500 lines of untested code

### Gap Closures
4. Factory Health Report provides consumable DORA metrics with performance level classification
5. PR Diff Review Gate adds defense-in-depth for the aggregate changeset
6. Automatic Rollback ensures pipelines that encounter errors leave a clean workspace

### Measurement
All decisions have explicit triggers to revisit. The DORA metrics collector records the data needed to evaluate each trigger. After 30 days of operation, this ADR should be reviewed against actual metrics.

## Related
- ADR-010: Data Contract for Task Input
- ADR-011: Multi-Cloud Adapter Deferred
- ADR-013: Enterprise-Grade Autonomy and Observability
- Design: `docs/design/data-contract-task-input.md`
