# Corrections of Error — Autonomous Code Factory

> Log of corrections applied to the factory template.
> Ordered newest first — most recent correction at the top.
> Each entry documents what was wrong, what was fixed, and why.

---

## COE-023: DORA Lead Time Discrepancy (started_at Race Condition)

- **Date**: 2026-05-11
- **Severity**: Metrics (P3)
- **Found in**: TASK-6693629d showed 1.1h lead time in DORA card but actual execution was ~25 min
- **Root cause**: `claim_task()` sets `started_at` via ConditionExpression (`status = READY`). On re-triggered tasks, the condition fails silently (status already IN_PROGRESS from a previous claim), so `started_at` is never set. The dashboard Lambda falls back to `created_at` (webhook arrival time), inflating the metric.
- **Fixes applied**:
  - `update_task_stage()` now sets `started_at = if_not_exists(started_at, :now)` on every stage update. This is idempotent (first-write-wins), unconditional (no ConditionExpression), and universal (works for both monolith and distributed containers).
  - `complete_task()` calculates `duration_ms = now - started_at` (actual execution time).
  - `_compute_elapsed()` in dashboard Lambda uses `started_at` (falls back to `created_at` only if not set).
- **Files modified**:
  - `infra/docker/agents/task_queue.py` — `update_task_stage`, `claim_task`, `complete_task`
  - `infra/terraform/lambda/dashboard_status/index.py` — `_compute_elapsed`
- **Prevention**: `if_not_exists` pattern ensures `started_at` is always set regardless of task lifecycle path. No race condition possible.

---

## COE-022: Portal Timeline Showing Raw Tool Calls

- **Date**: 2026-05-11
- **Severity**: Observability (P3)
- **Found in**: Portal "Chain of Thought" view showing "Tool #36: run_shell_command" ×50 — raw tool invocations with no signal/noise classification, making the timeline unusable for understanding pipeline reasoning.
- **Root cause**: `DashboardCallback._handle_tool_start()` in `stream_callback.py` emitted every tool call event to DynamoDB without distinguishing high-signal actions (file writes, git operations, test runs) from low-signal noise (shell commands, directory listings, file reads). The portal rendered all events equally, burying meaningful activity under repetitive noise.
- **Fixes applied**:
  - ✅ **stream_callback.py** — Added signal/noise classification. Low-signal tools (run_shell_command, read_file, list_directory) are aggregated into periodic summaries instead of individual events. High-signal tools (write_file, git_commit, run_tests) emit full events.
  - ✅ **factoryDataMapper.ts** — Client-side noise filter removes residual low-signal events from the timeline. Aggregates consecutive tool calls of the same type into "N operations" summaries. Added DORA empty state handling.
  - ✅ **Renamed view** — "Chain of Thought" → "Pipeline Activity" to better reflect the curated content.
- **Files modified**:
  - `infra/docker/agents/stream_callback.py` — Tool classification + aggregation logic
  - `infra/portal-src/src/mappers/factoryDataMapper.ts` — Client-side noise filter + DORA empty state handling
  - `infra/portal-src/src/App.tsx` — View rename + delivery status badge fix
- **Prevention**: Tool classification is now the default — new tools added to the agent must be categorized as signal or noise in the callback configuration.

---

## COE-021: Push Rejected on Re-Worked Tasks (Stale Ref)

- **Date**: 2026-05-11
- **Severity**: Delivery (P2)
- **Found in**: TASK-19d68ad5 (GH-91 task 5) — pipeline completed all 7 agents successfully but `git push --force-with-lease` failed with "stale info" error. The PR was never created despite all code being generated correctly.
- **Root causes** (2 distinct failures):
  1. **workspace_setup didn't fetch remote feature branch before push** — When re-working a task that already has a remote branch, `--force-with-lease` compares against the local ref (which is stale). The remote branch had been updated by a previous pipeline run, but the local workspace never fetched the latest remote state.
  2. **Rebase retry failed due to unstaged changes** — The fallback rebase-and-retry logic (added in COE-019) failed because `swe-dtl-commiter-agent` left unstaged changes in the workspace. `git rebase` refuses to run with a dirty working tree.
- **Fixes applied**:
  - ✅ **`_fetch_remote_branch()`** — New helper fetches the remote feature branch before any push attempt, ensuring `--force-with-lease` has accurate remote ref state.
  - ✅ **`_find_existing_pr()`** — Checks if a PR already exists for the branch (re-worked tasks). If found, updates the existing PR instead of creating a new one.
  - ✅ **`_update_pr()`** — Updates existing PR title/body when re-pushing to an existing branch.
  - ✅ **Hybrid safe push strategy** — Sequence: fetch remote → attempt push → if stale, stash + rebase + pop + retry → if PR exists, update instead of create.
- **Files modified**:
  - `infra/docker/agents/workspace_setup.py` — `_fetch_remote_branch()`, `_find_existing_pr()`, `_update_pr()`, hybrid push logic
- **Prevention**: Hybrid safe push strategy now handles all retry scenarios (fresh push, re-work push, stale ref recovery). The push path is no longer a single-shot operation.

---

## COE-020: ECS platform mismatch (arm64→amd64) + single-model infra + stale EventBridge targets

- **Date**: 2026-05-08
- **Severity**: Infrastructure (P0 — all 14 tasks stuck, zero pipeline throughput for >1 hour)
- **Found in**: ECS task failure logs, ECR image manifest, EventBridge target configuration, Terraform task definition env vars
- **Root causes** (3 distinct failures):
  1. **Docker image built for wrong platform (arm64 on amd64 Fargate)** — The `strands-agent:latest` and `adot-v0.40.0` images in ECR were built on Apple Silicon (arm64) without `--platform linux/amd64`. ECS Fargate requires amd64. Error: `CannotPullContainerError: image Manifest does not contain descriptor matching platform 'linux/amd64'`. This is a recurrence of the same class as COE-011 item 2.
  2. **Single-model infrastructure despite multi-model code** — The `squad_composer.py` code reads `BEDROCK_MODEL_REASONING`, `BEDROCK_MODEL_STANDARD`, `BEDROCK_MODEL_FAST` env vars to route different agent roles to different model tiers. But the Terraform task definitions only passed a single `BEDROCK_MODEL_ID` env var. All agents defaulted to Claude Sonnet 4.5 regardless of role, defeating the cost/capability optimization design.
  3. **EventBridge targets pinned to stale task definition revision** — After updating the task definition to revision `:12`, a targeted `terraform apply` on the task definition alone did NOT update the EventBridge targets. The targets remained pinned to `:11` (the broken revision). New tasks continued launching with the old (broken) image. A full `terraform apply` was required to propagate the revision change to dependent resources.
- **Fixes applied**:
  - ✅ **Rebuilt both images for linux/amd64** — `docker buildx build --platform linux/amd64` for strands-agent and ADOT sidecar. Pushed to ECR.
  - ✅ **Added Makefile automation** — `make docker-build`, `make docker-build-adot`, `make docker-push-all`, `make docker-deploy` all enforce `--platform linux/amd64`. ECR URL resolved from Terraform outputs (no hardcoding).
  - ✅ **Added multi-model tier Terraform variables** — `bedrock_model_reasoning`, `bedrock_model_standard`, `bedrock_model_fast` as first-class infra parameters. Passed to both main task definition and squad agent module.
  - ✅ **Updated ECS task definitions** — Revision `:12` includes `BEDROCK_MODEL_REASONING`, `BEDROCK_MODEL_STANDARD`, `BEDROCK_MODEL_FAST` env vars.
  - ✅ **Full terraform apply** — Updated all 3 EventBridge targets (GitHub, GitLab, Asana) from `:11` → `:12`.
  - ✅ **Reset stuck tasks** — All failed/dead-letter tasks reset to PENDING for retry.
  - ✅ **Verified container starts** — Test ECS task launched, pulled image successfully, ran to exit 0.
- **Files modified**:
  - `Makefile` — Added `docker-build`, `docker-build-adot`, `docker-build-onboarding`, `docker-push-all`, `docker-deploy` targets
  - `infra/terraform/variables.tf` — Added `bedrock_model_reasoning`, `bedrock_model_standard`, `bedrock_model_fast` variables
  - `infra/terraform/main.tf` — Added 3 model tier env vars to strands-agent container definition
  - `infra/terraform/distributed-infra.tf` — Passed model tier vars to ECS module
  - `infra/terraform/modules/ecs/agent_task_def.tf` — Added model tier variables and env vars to squad agent container
  - `infra/terraform/dashboard-cdn.tf` — Improved CloudFront caching (immutable assets, SPA fallback)
  - `scripts/deploy-dashboard.sh` — Added `--build` flag, separated S3 uploads by cache policy
- **Lessons**:
  - **Never use targeted terraform apply for task definitions** — EventBridge targets, DAG fanout Lambda, and other consumers reference the task definition ARN (which includes the revision number). A targeted apply creates a new revision but leaves consumers pointing to the old one. Always do a full apply.
  - **Build automation must enforce platform** — The `--platform linux/amd64` flag must be in the build automation (Makefile), not in developer memory. This is the second time this class of bug occurred (COE-011).
  - **Infra must match code contracts** — When application code reads env vars for configuration, the infrastructure must provide them. The `squad_composer.py` multi-model routing was dead code in production because the env vars were never set.
- **Prevention**:
  - `make docker-build` is now the canonical build path (enforces platform)
  - `make docker-deploy` does build + push + terraform apply (full, not targeted)
  - Model tier variables are in `variables.tf` with sensible defaults — changing models is now a tfvars change, not a code change
- **Well-Architected alignment**:
  - OPS 5 (reduce defects) — Build automation prevents platform mismatch recurrence
  - OPS 8 (respond to events) — Full apply ensures EventBridge targets stay in sync
  - COST 1 (practice cloud financial management) — Multi-model routing enables cost optimization (Haiku for simple tasks, Sonnet for complex)
  - PERF 3 (select the best performing resources) — Right-sized models per agent role
  - REL 5 (design interactions to prevent failures) — Terraform dependency graph must be respected (no targeted apply for shared resources)

---

## COE-019: StatusSync dead code + silent PR delivery failure + no portal visibility

- **Date**: 2026-05-08
- **Severity**: Observability (P1 — pipeline completes but PM has zero visibility)
- **Found in**: TASK-9426ff77 (GH-91 task 5) — pipeline completed all 3 stages but `git push` failed with `stale info`, no PR was created, and the portal showed no error.
- **Root causes** (3 distinct failures):
  1. **`StatusSync` is dead code** — The module `infra/docker/agents/status_sync.py` was written with full GitHub issue comment logic but **never imported or called** by the orchestrator. The PM gets zero visibility on the GitHub issue.
  2. **Silent PR delivery failure** — When `push_and_create_pr()` fails, the orchestrator logged a WARNING but emitted no `append_task_event()` with type="error". The portal's Chain of Thought panel showed nothing about the failure.
  3. **No retry on stale ref** — The push failed because the remote branch had been updated (likely by a previous retry). The orchestrator had no retry-with-rebase logic, so recoverable failures became permanent.
- **Fixes applied**:
  - ✅ **Integrated `StatusSync` into orchestrator** (Step 9.4) — now posts pipeline completion/failure comments to the originating GitHub issue.
  - ✅ **Added `append_task_event(type="error")` on PR delivery failure** — the portal CoT panel now shows the push error with context.
  - ✅ **Added `_attempt_rebase_retry()` method** — when push fails with "stale info", the orchestrator fetches + rebases onto origin/main and retries the push once.
  - ✅ **Dashboard Lambda exposes `completed_no_delivery` status** — tasks that completed without a PR are visually distinct (amber badge, "NO PR" label).
  - ✅ **Portal renders `pr_error` field** — amber warning icon with tooltip showing the push error.
- **Files modified**:
  - `infra/docker/agents/orchestrator.py` — StatusSync integration, rebase retry, error event emission
  - `infra/terraform/lambda/dashboard_status/index.py` — `completed_no_delivery` status derivation, `pr_error` field exposure
  - `infra/portal-src/src/App.tsx` — amber status badge, push failure indicator
  - `infra/portal-src/src/services/factoryService.ts` — `pr_error` field in Task interface
- **Well-Architected alignment**:
  - OPS 6 (telemetry) — Pipeline failures now emit observable events
  - OPS 8 (understand operational health) — Portal distinguishes "completed" from "completed-without-delivery"
  - REL 9 (design for recovery) — Rebase retry recovers from transient stale-ref failures
  - REL 11 (fault isolation) — Push failure no longer silently swallowed

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
