# Corrections of Error — Autonomous Code Factory

> Log of corrections applied to the factory template.
> Ordered newest first — most recent correction at the top.
> Each entry documents what was wrong, what was fixed, and why.

---

## COE-017: React Portal shipped without ADR, DDR update, or architecture diagram update

- **Date**: 2026-05-07
- **Severity**: Governance (P1 — architectural boundary crossed without decision record)
- **Found in**: commit `31ef9cf` (feat(portal): import React portal with rail navigation, structured reasoning API, and WCAG accessibility)
- **Scope of change**: 37 files, +2964/-349 lines. Introduces an entirely new technology stack (React + TypeScript + Vite + Tailwind + i18n) and a new API endpoint (`GET /status/tasks/{task_id}/reasoning`).
- **Description**: The React portal represents a **new architectural plane** — a user-facing rendering layer that consumes the Data Plane (DynamoDB task_queue) via Lambda API Gateway. This is the E6 edge in the FDE pipeline chain (JSON artifacts → Portal renderers → User sees the review). The commit shipped with:
  - ✅ A design document (`docs/design/portal_design_doc.md`) — thorough, 11 sections
  - ✅ An import plan (`docs/design/import_portal_plan.md`)
  - ✅ Cloud inventory update (`docs/cloud-inventory.md`)
  - ❌ **No ADR** — The decision to introduce React + Vite + Tailwind (breaking the "zero dependencies" principle from the original dashboard) is not recorded. The design doc mentions ADR-011 (YAGNI) but contradicts it by introducing npm, node_modules, and a build pipeline.
  - ❌ **No DDR update** — The design-document.md Components table doesn't list the Portal, its API endpoints, or its data flow. The Information Flow table doesn't show DynamoDB → Lambda → Portal → User.
  - ❌ **No architecture diagram update** — The reference architecture diagram doesn't show the Portal as a consumer of the dashboard Lambda. The plane diagrams don't reflect the new rendering layer.
  - ❌ **No flow diagram** — No `docs/flows/15-portal-reasoning.md` exists for the structured reasoning flow.
  - ❌ **No CHANGELOG entry** — The feat is not in CHANGELOG.md.
- **Architectural decisions that need ADR documentation**:
  1. **Why React over zero-dependency ES modules?** — The original dashboard (`infra/dashboard/index.html`) was explicitly designed as zero-dependency per ADR-011 and SEC 6. The portal introduces `package.json` with 15+ dependencies (react, react-dom, vite, tailwindcss, lucide-react, i18next, etc.). What changed? What's the supply chain risk mitigation?
  2. **Dual dashboard coexistence** — Both `infra/dashboard/` (zero-dep, deployed to CloudFront) and `infra/portal-src/` (React, requires build) now exist. Which is canonical? What's the migration path? When does the old one get removed?
  3. **i18n architecture** — The portal supports en-US, pt-BR, es. This is the first multi-language artifact in the factory. What's the translation governance? Who maintains translations?
  4. **Structured reasoning API** — `GET /status/tasks/{task_id}/reasoning` exposes the full chain-of-thought timeline. What data classification applies? Is this safe to expose without authentication? (The design doc acknowledges "No authentication on dashboard" as a known limitation.)
  5. **WCAG POUR compliance claim** — The commit message claims WCAG accessibility. What level (A, AA, AAA)? Was it validated with assistive technology? Or is it aspirational?
- **Impact on existing architecture**:
  - The orchestrator (`orchestrator.py`) was modified to emit richer events with structured metadata (`phase`, `gate_name`, `gate_result`, `criteria`, `context`, `autonomy_level`, `confidence`). This changes the E4 edge contract (orchestrator → task_queue → Lambda → Portal).
  - The `task_queue.py` was modified with `append_task_event()` accepting new kwargs. This is a data contract change that affects all consumers.
  - The dashboard Lambda (`index.py`) gained a new route handler (`_handle_reasoning()`). This is an API surface expansion.
- **Root cause**: Feature was developed with a design document (good) but without the governance artifacts that make the decision traceable and reversible. The design doc is excellent for "how" but doesn't answer "why this approach over alternatives" — that's what the ADR is for.
- **Prevention**:
  - DoD gate must check: if a feat introduces a new technology (new `package.json`, new language, new framework), an ADR is mandatory.
  - The `fde-enterprise-docs` hook should detect new `package.json` files and flag for ADR.
  - Architecture diagram regeneration should be part of the ship-readiness gate when new planes/edges are introduced.
- **Well-Architected alignment**:
  - OPS 3 (know your workload) — New rendering plane not documented in architecture
  - OPS 10 (manage knowledge) — Decision rationale not captured
  - SEC 6 (protect compute) — Supply chain risk from npm dependencies not assessed in ADR
  - REL 8 (design for recovery) — No rollback plan documented if React portal fails
  - COST 1 (practice cloud financial management) — Build pipeline cost (Vite build, CI time) not assessed

## COE-016: Multi-project orchestration shipped without ADR or flow diagram

- **Date**: 2026-05-07
- **Severity**: Governance (P2 — concurrency model undocumented)
- **Found in**: commit `7e1eb7b` (feat(factory): multi-project orchestration — registry, concurrency guard, dashboard filter)
- **Scope of change**: 5 files, +272/-2 lines. Introduces a new module (`project_registry.py`) and modifies two critical pipeline components (`orchestrator.py`, `task_queue.py`).
- **Description**: Multi-project orchestration introduces three capabilities that fundamentally change how the factory operates at scale:
  - **P0 — Project Registry** (`infra/docker/agents/project_registry.py`): A singleton registry mapping repos to configuration (default_branch, tech_stack, max_concurrent_tasks, priority_boost, steering_context). Loaded from `FACTORY_PROJECTS` env var (JSON) or auto-registers unknown repos with defaults.
  - **P1 — Concurrency Guard** (`task_queue.py` + `orchestrator.py`): `count_active_tasks_for_repo()` queries DynamoDB for IN_PROGRESS/RUNNING tasks per repo. `check_concurrency(repo, max)` gates new task execution. Default: 2 concurrent tasks per repo.
  - **P2 — Dashboard Project Filter**: Server-side `?repo=owner/repo` filtering on `/status/tasks`. Client-side project selector dropdown.
  
  The commit references "Design ref: ADR-005 (Multi-Workspace Factory Topology)" but ADR-005 describes workspace-level isolation (separate `.kiro/` directories), NOT runtime concurrency control within a shared ECS cluster. These are different architectural concerns:
  - ADR-005: How workspaces are isolated on the filesystem
  - This feature: How tasks are throttled at runtime to prevent merge conflicts
  
  **What needs an ADR**:
  1. **Concurrency model** — The guard uses DynamoDB `count_active_tasks_for_repo()` which is eventually consistent. Two tasks could pass the guard simultaneously if they query DynamoDB within the same consistency window. Is this acceptable? What's the blast radius of a race condition (two agents editing the same repo simultaneously)?
  2. **Singleton lifecycle** — `ProjectRegistry` uses a module-level singleton (`_registry`). In ECS Fargate, each task is a separate container, so the singleton is per-container. But if the factory moves to Lambda or long-running ECS services, the singleton could become stale. What's the invalidation strategy?
  3. **Auto-registration semantics** — Unknown repos get auto-registered with `max_concurrent_tasks=2`. This means ANY repo that sends a webhook gets factory capacity. Is this intentional? What prevents a malicious webhook from consuming all factory capacity?
  4. **Priority boost** — `priority_boost` field exists in `ProjectConfig` but is never consumed by the orchestrator. Is this dead code or future work? If future work, what's the scheduling algorithm?
  5. **Configuration source** — `FACTORY_PROJECTS` is a JSON env var. For 50+ projects, this becomes unwieldy. What's the scaling path? DynamoDB table? S3 config file? SSM Parameter Store?
  
  **What needs a flow diagram**:
  - The concurrency guard is a new gate in the pipeline that can return `"queued"` status. This is a new pipeline state that doesn't exist in any current flow diagram. The orchestrator can now return 4 statuses: `skipped`, `rejected`, `queued`, `completed/partial/error`. The `queued` state has no retry mechanism documented — who picks up queued tasks when a slot opens?
  
- **Impact on existing architecture**:
  - `orchestrator.py` now imports `project_registry.get_registry()` — new dependency
  - `task_queue.py` gained `check_concurrency()` and `count_active_tasks_for_repo()` — new DynamoDB queries
  - Dashboard Lambda gained `_extract_projects()` and `?repo=` filter — new API behavior
  - The `queued` status is a new terminal state that the DAG resolution (ADR-014) doesn't handle — queued tasks don't trigger downstream dependencies
  
- **Unanswered questions (Red Team)**:
  1. **What happens to queued tasks?** — The orchestrator returns `"queued"` but nothing re-triggers the task when a slot opens. Is the expectation that EventBridge retries? ECS task retries? Manual re-trigger? This is a **liveness gap** — tasks can be permanently queued.
  2. **DynamoDB consistency** — `count_active_tasks_for_repo()` presumably uses a Scan or Query. Is it using ConsistentRead? If not, two tasks could pass the guard simultaneously.
  3. **What if max_concurrent_tasks=0?** — The guard checks `current < max_concurrent`. If max is 0, no tasks can ever run. Is there validation?
  4. **Container restart** — If the ECS task crashes mid-execution, the task stays IN_PROGRESS in DynamoDB. The concurrency guard counts it as active. Who cleans up stuck tasks? Is there a TTL?
  
- **Root cause**: Feature built incrementally (P0 → P1 → P2) within a single session without pausing to write the ADR. The commit message is well-structured (documents all three phases) but the architectural decisions are embedded in code comments, not in a traceable ADR.
- **Prevention**:
  - Any feature that introduces a new pipeline state (like `queued`) must have a flow diagram showing the state machine.
  - Any feature that introduces concurrency control must have an ADR documenting the consistency model and failure modes.
  - The DoD gate should check: if a feat modifies `orchestrator.py` (the pipeline spine), an ADR is mandatory.
- **Well-Architected alignment**:
  - REL 1 (manage service quotas) — Concurrency limits are quotas; their behavior under load is undocumented
  - REL 5 (design interactions to prevent failures) — Race condition in DynamoDB eventual consistency not addressed
  - REL 9 (plan for recovery) — No recovery path for permanently queued tasks
  - OPS 5 (reduce defects) — Dead code (`priority_boost`) creates confusion
  - OPS 8 (respond to events) — `queued` state has no event-driven retry mechanism

## COE-015: Five systemic agent fixes shipped without individual COE entries

- **Date**: 2026-05-07
- **Severity**: Process
- **Found in**: commit `1a2af15` (fix(agent): 5 systemic fixes for workspace delivery pipeline)
- **Description**: Five distinct fixes were bundled into a single commit without individual COE entries: (1) workspace setup failures, (2) task_id correlation with webhook_ingest, (3) stage update emission, (4) Bedrock inference profile migration, (5) DashboardCallback removal. Each represents a different failure mode that should be individually documented for pattern recognition.
- **Fix**: Documenting as a batch COE. Individual root causes: (1) clone/branch/push sequence not atomic, (2) correlation ID not propagated from ingest to orchestrator, (3) stage events not emitted at correct lifecycle points, (4) legacy model ID used instead of inference profile, (5) non-callable object passed to Agent constructor.
- **Root cause**: Pressure to ship quickly led to bundling unrelated fixes. Each fix addresses a different module boundary (E1: webhook→router, E2: router→orchestrator, E3: orchestrator→workspace, E4: workspace→bedrock, E5: agent→dashboard).
- **Prevention**: One fix per commit. Each fix gets its own COE entry. The circuit breaker hook should enforce this.
- **Well-Architected alignment**: OPS 5 (reduce defects), OPS 8 (respond to events)

## COE-014: Bedrock inference profile fix shipped without model migration documentation

- **Date**: 2026-05-07
- **Severity**: Infrastructure
- **Found in**: commit `22a80a8` (fix(bedrock): use inference profile (us. prefix) + add Converse/ConverseStream IAM)
- **Description**: The Bedrock model was migrated from direct model ID (`anthropic.claude-3-haiku-20240307-v1:0`) to inference profile (`us.anthropic.claude-haiku-4-5-20251001-v1:0`) without documenting the migration rationale, IAM policy changes (Converse + ConverseStream), or the `us.` prefix requirement for cross-region inference profiles.
- **Fix**: CHANGELOG entry exists (under "Changed — Bedrock Model"). Missing: explicit IAM policy documentation in deployment guide.
- **Root cause**: Infrastructure change treated as a simple version bump rather than an architectural decision affecting IAM, cost, and availability.
- **Prevention**: Model changes should be treated as infrastructure changes requiring deployment guide updates.
- **Well-Architected alignment**: SEC 3 (manage permissions), COST 1 (practice cloud financial management)

## COE-013: EventBridge InputTransformer fix required 3 commits to resolve

- **Date**: 2026-05-06 / 2026-05-07
- **Severity**: Process (multi-commit fix pattern)
- **Found in**: commits `72c8c9d`, `2ba6959`, `c40a075`, `0b5618f`
- **Description**: The EventBridge→ECS silent failure (COE-011) required 4 separate fix commits to fully resolve: (1) InputTransformer + Docker platform, (2) labels array in reconstructed event, (3) fetch issue body from GitHub API, (4) onboarding agent IAM + InputTransformer quotes. Each commit fixed a symptom discovered only after the previous fix was deployed.
- **Fix**: All 4 fixes are now deployed and working (proven by task `03b21106`). COE-011 documents the root cause.
- **Root cause**: The "symptom chasing" anti-pattern (COE-052). Each fix was deployed without verifying the full data path end-to-end. The flat env var pattern was correct, but downstream consumers (router, agent) had additional assumptions about event shape.
- **Prevention**: After any EventBridge fix, run the full `scripts/validate-webhook-eventbridge.sh` isolation script before declaring fixed. Verify at the consumer, not just the producer.
- **Well-Architected alignment**: OPS 8 (respond to events), REL 5 (design interactions to prevent failures)

## COE-012: README and design document counts drifted again (systemic recurrence)

- **Date**: 2026-05-07
- **Severity**: Documentation (systemic)
- **Found in**: README.md, docs/architecture/design-document.md
- **Description**: Despite COE-010 creating the doc-gardening agent, counts drifted again: ADRs (13→16), flows (13→14), hooks (14→17 in structure, 16→17 in table), tests (54→171). The `> Generate: python3 scripts/generate_reference_architecture.py` line in the README hero section was disconnected from the solution narrative — it's an implementation detail that belongs in the DDR, not the user-facing README.
- **Fix**: Updated all counts in README (badges, structure, Documentation Index). Removed stale generate script callout from hero section. Added missing `fde-repo-onboard` hook to table. Updated Code to Docs cross-reference.
- **Root cause**: The doc-gardening agent exists but is `userTriggered` — it doesn't run automatically on feat/fix commits. The DoD gate doesn't enforce count consistency.
- **Prevention**: Consider promoting doc-gardening to `postTaskExecution` trigger. At minimum, run before every release.
- **Well-Architected alignment**: OPS 3 (know your workload), OPS 10 (manage knowledge)

## COE-011: Webhook delivered (HTTP 200) but no ECS task ran — InputTransformer + ECS silent failure

- **Date**: 2026-05-06 / 2026-05-07
- **Severity**: Infrastructure (production pipeline blocked)
- **Found in**: `infra/terraform/eventbridge.tf` — InputTransformer template, `infra/docker/Dockerfile.strands-agent` — platform mismatch
- **Description**: GitHub webhook delivered successfully (HTTP 200) but no ECS task was triggered. The full pipeline (API Gateway → EventBridge → Rule Match) was working correctly. Two root causes were identified through systematic data-plane investigation:
  1. **InputTransformer produces invalid ECS RunTask overrides**: The template `"value": "{\"source\":\"<source>\",\"detail-type\":\"<detailType>\",\"detail\":<detail>}"` injects a raw JSON object (`<detail>`) into a string value without escaping. ECS RunTask silently rejects the malformed overrides JSON — no task is created, no error is surfaced. EventBridge reports no FailedInvocations metric (or metrics are severely delayed on custom buses).
  2. **Docker image built for wrong platform**: Image was built on Apple Silicon (arm64) but ECS Fargate requires linux/amd64. Error: `CannotPullContainerError: image Manifest does not contain descriptor matching platform 'linux/amd64'`.
- **Fix**:
  1. Changed InputTransformer to extract **individual scalar fields** as separate environment variables (EVENT_SOURCE, EVENT_ACTION, EVENT_LABEL, EVENT_ISSUE_NUMBER, EVENT_ISSUE_TITLE, EVENT_REPO). No complex JSON in string values.
  2. Updated `agent_entrypoint.py` to reconstruct the event from flat env vars when EVENTBRIDGE_EVENT is not set.
  3. Rebuilt Docker image with `--platform linux/amd64` and pushed to ECR.
  4. Added `eventbridge-observability.tf` with catch-all logging rule for permanent bus visibility.
- **Root cause**: EventBridge InputTransformer with ECS targets silently fails when the template produces invalid JSON for the RunTask `overrides` parameter. No error is returned, no metric is emitted, no task is created. The only way to detect this is to add a separate CloudWatch Logs target to the same rule and verify the rule matches independently of the ECS target.
- **Prevention**: 
  - Never embed JSON objects (`<variable>` without quotes) inside string values in InputTransformer templates for ECS targets.
  - Use flat scalar env vars pattern for ECS container overrides.
  - Always build Docker images with `--platform linux/amd64` for Fargate.
  - The catch-all logging rule provides permanent observability on the bus.
- **Proven in production**: Task `03b21106` (2026-05-07T02:20:40Z) — started by `events-rule/fde-dev-github-factory-r`, agent initialized, event reconstructed from flat env vars, router processed successfully.
- **Well-Architected alignment**: OPS 6 (telemetry), OPS 8 (respond to events), REL 9 (fault isolation)

## COE-010: Systemic doc-drift pattern resolved with automated detection

- **Date**: 2026-05-05
- **Severity**: Process (systemic)
- **Found in**: COE-001 through COE-006 (6 of 9 entries were "doc was outdated")
- **Description**: Documentation drift from code was the most repeated failure pattern. README badge counts, ADR counts, flow counts, and design-document component tables all drifted without detection.
- **Fix**: Created `infra/docker/agents/doc_gardening.py` with 5 automated checks and `fde-doc-gardening` hook (userTriggered). The agent can now detect drift on demand.
- **Root cause**: No automated mechanism to compare documented state against filesystem state. Manual checking doesn't scale.
- **Prevention**: Run `fde-doc-gardening` hook before releases. Future: trigger on `postTaskExecution` for continuous validation.

## COE-009: Data contract shipped without ADR, CHANGELOG, or architecture update

- **Date**: 2026-05-04
- **Severity**: Governance
- **Found in**: commit `13146d3` (feat(contract): data contract)
- **Description**: The data contract was committed without ADR, CHANGELOG update, design document update, or Agent Builder integration design.
- **Fix**: Created ADR-010, updated CHANGELOG, design document ADR list, README ADR count. Added Agent Builder integration to ADR-010.
- **Root cause**: Committed without running the documentation checklist. DoD gate was not applied.

## COE-008: Bash arithmetic `((PASS++))` returns exit code 1 when PASS is 0

- **Date**: 2026-05-04
- **Severity**: Script (cosmetic)
- **Found in**: `scripts/validate-e2e-cloud.sh`
- **Description**: `((PASS++))` when PASS=0 evaluates `((0))` which is falsy in bash (exit code 1). Combined with `&&`/`||` chains, this caused both success and non-success branches to run.
- **Fix**: Changed to `PASS=$((PASS + 1))` which always returns exit code 0.
- **Root cause**: Bash arithmetic treats 0 as falsy, unlike most languages.

## COE-007: GitLab EventBridge rule used invalid nested event pattern

- **Date**: 2026-05-04
- **Severity**: Infrastructure (Terraform apply issue)
- **Found in**: `infra/terraform/eventbridge.tf`
- **Description**: The GitLab EventBridge rule used a nested object pattern (`labels[].title`) which EventBridge does not support. EventBridge patterns only match on simple key-value pairs, not nested array-of-objects. This caused `terraform apply` to return `InvalidEventPatternException`.
- **Fix**: Flattened the event pattern to match on `detail.action = ["update"]` instead of nested `detail.labels[].title`.
- **Root cause**: EventBridge event pattern syntax was assumed to support JSON path-like nested matching, which it does not.
- **Impact**: 49 of 51 resources created successfully. Only the GitLab rule and its ECS target were affected. Second apply created the remaining 2.

## COE-006: Architecture diagram outdated — missing cloud plane and 14 hooks

- **Date**: 2026-05-04
- **Severity**: Documentation / Visual
- **Found in**: `docs/architecture/autonomous-code-factory.png`, `scripts/generate_architecture_diagram.py`
- **Description**: The architecture diagram showed 13 hooks, single-platform ALM (GitHub only), and no AWS cloud infrastructure. The diagram did not reflect the multi-platform ALM (GitHub Projects, Asana, GitLab), the 14th hook (`fde-work-intake`), or the AWS Cloud Plane (ECS Fargate, Bedrock, ECR, Secrets Manager).
- **Fix**: Updated `scripts/generate_architecture_diagram.py` with multi-platform labels, 14 hooks, AWS Cloud Plane branch. Regenerated PNG.
- **Root cause**: Diagram was generated before multi-platform ALM and AWS cloud infrastructure were added.

## COE-005: Missing ADR for AWS Cloud Infrastructure

- **Date**: 2026-05-04
- **Severity**: Governance
- **Found in**: `docs/adr/`
- **Description**: The AWS cloud infrastructure (Terraform IaC, ECR, ECS Fargate, Bedrock, Secrets Manager) was built without a corresponding Architecture Decision Record.
- **Fix**: Created ADR-009.
- **Root cause**: Infrastructure was built incrementally across multiple sessions without pausing to write the ADR.

## COE-004: Blogpost missing cloud deployment capability

- **Date**: 2026-05-04
- **Severity**: Documentation
- **Found in**: `docs/blogpost-autonomous-code-factory.md`
- **Description**: Blogpost described only local factory operations. The AWS cloud deployment capability was not mentioned.
- **Fix**: Not applied — blogpost is a point-in-time publication. Cloud deployment covered in subsequent updates.
- **Root cause**: Blogpost was published before cloud infrastructure was added. Expected behavior, not a defect.

## COE-003: Adoption guide referenced old onboarding flow

- **Date**: 2026-05-04
- **Severity**: Documentation
- **Found in**: `docs/guides/fde-adoption-guide.md`
- **Description**: Step 1 still showed `provision-workspace.sh --global` as the primary onboarding path. The new three-script pipeline was not mentioned.
- **Fix**: Added new "Recommended: Automated Onboarding" section before the manual steps.
- **Root cause**: Adoption guide was written before the onboarding pipeline was built.

## COE-002: Design document missing new infrastructure components

- **Date**: 2026-05-04
- **Severity**: Documentation
- **Found in**: `docs/architecture/design-document.md`
- **Description**: Components table did not include the onboarding scripts, the Terraform IaC, or the Strands agent Docker image.
- **Fix**: Added Cloud Infrastructure, Onboarding Pipeline, and Strands Agent to the Components table.
- **Root cause**: Infrastructure layer was built after the design document was last updated.

## COE-001: Hook count inconsistency in design document

- **Date**: 2026-05-04
- **Severity**: Documentation
- **Found in**: `docs/architecture/design-document.md`
- **Description**: Design document referenced "13 hooks" in the Components table, but the actual count is 14 after adding `fde-work-intake`.
- **Fix**: Updated Components table to reference 14 hooks.
- **Root cause**: Hook was added to `.kiro/hooks/` without updating the design document count.
