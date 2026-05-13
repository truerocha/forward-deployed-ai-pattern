# Changelog

All notable changes to the Forward Deployed Engineer pattern are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased] — 2026-05-13

### Added — Review Feedback Loop with ICRL Enhancement (ADR-027)
- `src/core/governance/review_feedback_processor.py` — Core processor that classifies PR review events (full_rework/partial_fix/approval), records metrics across DORA/Trust/Verification/Happy Time systems, updates Risk Engine weights (Bayesian learning from false negatives), emits rework events via EventBridge, and enforces circuit breaker (max 2 rework attempts per task).
- `src/core/memory/icrl_episode_store.py` — In-Context Reinforcement Learning episode storage. Stores structured episodes `(task_context, agent_action, human_reward, correction)` from review feedback. Retrieves relevance-filtered episodes for rework context injection. Generates pattern digests after 10+ episodes accumulate. TTL: 30 days.
- `src/core/governance/verification_reward_gate.py` — Deterministic verification gate providing binary reward signals (Pass/Fail) before PR creation. Runs linter → type-checker → test suite with graceful degradation. Agent gets max 3 inner iterations to achieve all-pass. Replaces estimated rework time with actual measured duration.
- `src/core/orchestration/mcts_planner.py` — Monte Carlo Tree Search planner for rework re-execution. Generates N=3 diverse candidate plans (sequential/parallel/debate topologies), scores each against feedback alignment and structural quality, selects best viable plan. Extends Conductor with multi-trajectory exploration.
- `infra/terraform/lambda/review_feedback/index.py` — Lambda handler processing PR review events from EventBridge. Classifies reviews, resolves task_id from task_queue, records metrics, checks circuit breaker, emits rework events, updates task status.
- `infra/terraform/review_feedback.tf` — Infrastructure: 3 EventBridge rules (pr_review_submitted, pr_rework_comment, task_rework_requested), Lambda function + IAM, ECS target for rework re-execution with feedback context as env vars, CloudWatch alarms for circuit breaker and high rejection rate. Two-way door: `review_feedback_enabled` variable.
- `infra/portal-src/src/components/ReviewFeedbackCard.tsx` — Portal card displaying ICRL feedback loop metrics: classification breakdown, verification gate pass rate, rework rate (5th DORA metric), ICRL episode count, pattern digest status, autonomy adjustments, circuit breaker alerts. Visible to PM/SWE/SRE/Staff personas.
- `docs/adr/ADR-027-review-feedback-loop.md` — Architecture decision record (v2) documenting the review feedback loop design, ICRL enhancement (MCTS, episode history, verification gate, structural uncertainty), conditional autonomy model, execution lock pattern, and research grounding.

### Added — PR Reviewer Agent: Three-Level Review Architecture (ADR-028)
- `infra/docker/agents/fde_pr_reviewer_agent.py` — Independent, isolated PR reviewer agent (Level 1 quality gate). Validates final PR deliverable against original issue spec. Runs in separate ECS task with own ICRL episode store (`icrl_review_episode#` prefix). Reviews 6 dimensions: spec alignment, completeness, security, error handling, test coverage, architecture. Outputs APPROVE/REWORK verdict with structured feedback. Includes DTL Committer decision matrix (`compute_delivery_decision()`).
- `docs/adr/ADR-028-pr-reviewer-agent-three-level-review.md` — Architecture decision record documenting the three-level review model (L1: agent reviewer, L2: branch evaluation, L3: human), isolation guarantees, DTL decision matrix, and autonomy level unlock (L4/L5 now achievable).

### Changed — Conductor Agent Pool (ADR-028)
- `src/core/orchestration/conductor.py` — Added `fde-pr-reviewer-agent` to `_AGENT_CAPABILITIES` with strengths: review, spec-alignment, quality-gate, candid-feedback.

### Changed — Portal Persona Assignments (ADR-027)
- `infra/portal-src/src/components/PersonaFilteredCards.tsx` — Added `ReviewFeedbackCard` to PM, SWE, SRE, and Staff persona views. Imported component and registered in card registry.

### Changed — Task Data Contract Extended (ADR-027)
- `infra/portal-src/src/services/factoryService.ts` — Added optional fields to `Task` interface: `updated_at`, `created_at`, `rework_attempt`, `rework_feedback`, `rework_constraint`, `original_pr_url`. Backward-compatible (all optional).

### Fixed — Portal TypeScript Compilation Errors
- `infra/portal-src/src/components/DoraCard.tsx` — Fixed `Property 'trend' does not exist on type 'unknown'` by adding type assertion `(m as DoraMetricSet)` in `Object.entries()` callback.
- `infra/portal-src/src/mappers/factoryDataMapper.ts` — Fixed `Cannot find name 'AgentStatus'` by adding `AgentStatus` to the import from `../types`.
- `infra/portal-src/src/services/factoryService.ts` — Fixed `Property 'updated_at' does not exist on type 'Task'` by adding the field to the interface.

### Added — Synapse 6 & 7: Transparency and Deterministic Harness (ADR-026)
- `src/core/risk/attp.py` — Agent Thought Transparency Protocol (ATTP): NLA-lite probing of agent hidden reasoning. Includes `AgentThoughtTransparency` dataclass, `probe_agent_transparency()` function, `compute_divergence_score()`, introspection prompt templates, and `ATTPBudget` for cost governance.
- `src/core/orchestration/task_ownership.py` — Atomic task ownership with lock semantics. Prevents MAST taxonomy's #1 failure mode (two agents claiming same work). Includes `AtomicTaskOwnership`, `TaskAssignment`, timeout detection, and goal ancestry computation.
- `src/core/orchestration/goal_ancestry.py` — Goal ancestry tracker: traces every subtask back to original user request. Includes `GoalAncestryTracker`, `GoalAncestryChain`, `GoalAlignmentResult`, and `validate_goal_alignment()` for adversarial gate integration.
- `src/core/orchestration/heartbeat.py` — Heartbeat-aware Conductor for O4-O5 tasks. Implements OpenClaw persistent execution pattern (check, evaluate, probe, act/wait cycle). Includes `HeartbeatAwareConductor`, `HeartbeatConfig`, `HeartbeatState`, and budget governance.
- `.kiro/steering/harness-first.md` — The 1.6% Rule steering: formalizes that new capabilities must be harness infrastructure, not prompt instructions.
- `docs/adr/ADR-025-permission-pipeline-alignment.md` — Superset proof: FDE gate architecture covers all 7 layers of Liu et al.'s permission pipeline plus 10 additional governance mechanisms.
- `docs/adr/ADR-026-synapse-6-7-implementation.md` — Architecture decision record for Synapse 6 and 7 implementation.

### Changed — Risk Engine Extended to 18 Signals
- `src/core/risk/risk_signals.py` — Added `reasoning_divergence` (signal 17, Synapse 6) and `coordination_overhead_ratio` (signal 18, Synapse 7) to `RiskSignals` dataclass.
- `src/core/risk/risk_config.py` — Added weights `w_reasoning_divergence=+1.5` and `w_coordination_overhead_ratio=+1.3` to `SignalWeights`.
- `src/core/risk/inference_engine.py` — Extended signal-to-weight mapping to cover 18 signals in explanation generation.

### Changed — Fidelity Score Extended to 7 Dimensions
- `src/core/brain_sim/fidelity_score.py` — Added `transparency` dimension (weight 0.15). Rebalanced: spec_adherence 0.25 to 0.20, design_quality 0.25 to 0.15. New `_score_transparency()` method measures reasoning consistency, escalation rate, and decision stability from ATTP probes.

### Changed — Adversarial Gate v2.1.0 (Synapse 6+7 Enhanced)
- `.kiro/hooks/fde-adversarial-gate.kiro.hook` — Added question 9 (goal ancestry validation from Synapse 7) and question 10 (transparency probe from Synapse 6).

### Changed — Conductor Agent Pool
- `src/core/orchestration/conductor.py` — Added `swe-tech-writer-agent` to `_AGENT_CAPABILITIES` with strengths: documentation, changelog, adr, readme.

### Changed — Infrastructure
- `infra/terraform/modules/ecs/orchestrator_task_def.tf` — Added env vars: `HEARTBEAT_TOKEN_BUDGET`, `ATTP_PROBE_BUDGET`, `TOTAL_TASK_CEILING`, `HEARTBEAT_ENABLED`.
- `infra/docker/orchestrator_entrypoint.py` — Wired `HeartbeatAwareConductor`, `AtomicTaskOwnership`, `GoalAncestryTracker` into distributed execution path.
- `infra/portal-src/src/types.ts` — Extended Agent interface with transparency/heartbeat fields.
- `infra/portal-src/src/components/BrainSimCard.tsx` — Renders transparency score and heartbeat cycle count.

### Fixed — Static Squad Composition (COE-053)
- `infra/docker/agents/squad_composer.py` — Changed `SQUAD_MODE` default from `"classic"` to `"dynamic"`. Added `swe-tech-writer-agent` to delivery group for medium features and bugfixes.
- `infra/docker/agents/orchestrator.py` — Added `_infer_task_complexity()` method replacing hardcoded `complexity="medium"`. Infers low/medium/high from file count, module breadth, task type, and constraints.

### Fixed — Portal Light Mode Readability
- `infra/portal-src/src/index.css` — Complete theme variable system overhaul. Added semantic variables for surfaces, text tiers, and accent states. Fixed light mode contrast. Resolved dead `dark:` prefix classes.
- `infra/portal-src/index.html` — Added render-blocking FOUC prevention script.
- `infra/portal-src/src/App.tsx` — Theme state initializes from localStorage with system preference fallback. Persists theme choice on change.

---

## [Unreleased] — 2026-05-12

### Added — SWE Synapses Cognitive Architecture (ADR-024)
- `src/core/synapses/__init__.py` — New package implementing five cognitive design principles extracted from peer-reviewed software engineering theory. Each synapse is grounded in academic research, measurable via the Risk Engine, actionable by the Conductor, and observable via the Fidelity Score.
- `src/core/synapses/paradigm_selector.py` — Synapse 3 (Ralph 2013): Selects rational, alternative, or hybrid design paradigm based on organism level, prior success rate, requirement stability, and domain novelty. Generates conductor guidance for topology selection.
- `src/core/synapses/decomposition_cost.py` — Synapse 4 (Homay 2025): Evaluates whether task decomposition is cost-justified using the Fundamental Theorem of Software Engineering. Detects over-decomposition and recommends consolidation when agents share excessive state.
- `src/core/synapses/interface_depth.py` — Synapse 1 (Ousterhout/APOSD): Measures module depth (interface surface vs implementation richness), scores agent instruction quality (WHAT vs HOW), and detects entanglement between agents via SCD field sharing.
- `src/core/synapses/bundle_coherence.py` — Synapse 2 (Wei 2026): Validates that Conductor-generated WorkflowPlans maintain architectural bundle coherence. Enforces empirically-validated co-occurrence rules (multi-agent requires durable context, broad tools require policy approval, recursive requires depth limits).
- `src/core/synapses/epistemic_stance.py` — Synapse 5 (King & Kimble 2004): Decomposes catalog_confidence into four epistemic sub-signals (structural, behavioral, domain, change). Classifies artifact type (code vs knowledge), identifies assumptions to document, and recommends execution approach.
- `src/core/synapses/synapse_engine.py` — Integrated engine orchestrating all five synapses in correct firing order. Produces SynapseAssessment with risk signals, design quality score, conductor guidance, and recommended topology.
- `docs/adr/ADR-024-swe-synapses-cognitive-architecture.md` — Architecture decision record documenting the five synapses, academic grounding, Risk Engine extension, Fidelity Score enhancement, and Conductor integration.

### Changed — Risk Engine Extended to 16 Signals (ADR-024)
- `src/core/risk/risk_signals.py` — Added 3 new signal fields: `interface_depth_ratio` (Synapse 1, protective), `decomposition_cost_ratio` (Synapse 4, risk), `paradigm_fit_score` (Synapse 3, protective). Signal vector extended from 13 to 16 dimensions.
- `src/core/risk/risk_config.py` — Added 3 new weights: `w_interface_depth_ratio` (-1.2), `w_decomposition_cost_ratio` (+1.0), `w_paradigm_fit_score` (-0.8). Weight vector extended from 13 to 16 dimensions.
- `src/core/risk/inference_engine.py` — Extended signal-to-weight mapping in XAI explanation generation to include the 3 new synapse signals.

### Changed — Fidelity Score Enhanced with Design Quality Dimension (ADR-024)
- `src/core/brain_sim/fidelity_score.py` — Added `design_quality` dimension (25% weight) measuring synapse satisfaction. Rebalanced existing dimensions (spec_adherence 25%, reasoning_quality 15%, context_utilization 10%, governance_compliance 15%, user_value_delivery 10%). Backward compatible: returns 0.5 when no synapse assessment is provided.

### Changed — Conductor Integration with SynapseEngine (ADR-024)
- `src/core/orchestration/conductor_integration.py` — `generate_conductor_manifest()` now runs the SynapseEngine pre-plan (determines paradigm, recommended agents, conductor guidance) and post-plan (validates depth and coherence). Synapse assessment metadata stored in manifest for downstream observability. Added `data_contract`, `catalog_metadata`, `prior_success_rate`, and `failure_recurrence` parameters for synapse input.

### Added — Persona-Based Portal UX + DORA Sun Card (PEC Blueprint Ch. 11-12)
- `infra/portal-src/src/components/DoraSunCard.tsx` — Radial health pulse gauge (0-100) with pulsing animation, DORA level badge, 7d projection, per-metric trend arrows, and weakest link identification. Consumes `DoraForecastEngine` output via API.
- `infra/portal-src/src/components/PersonaFilteredCards.tsx` — Role-based card filtering. Each persona (PM/SWE/SRE/Architect/Staff) sees a curated 5-8 card subset. Single source of truth for visibility matrix. Reduces cognitive load per the PEC Blueprint's "Economia de Atenção" principle.
- `infra/portal-src/src/App.tsx` — Wired `PersonaRouter` to `PersonaFilteredCards` with `activePersona` state. Observability view now renders only persona-relevant cards instead of all 13.

### Added — Code Knowledge Base Integration (AI-DLC Gap 1)
- `infra/docker/agents/tools.py` — New `query_code_kb` @tool function exposing the QueryAPI to agents. Supports 5 search modes: semantic, function, callers, callees, module. Added to RECON_TOOLS and ENGINEERING_TOOLS.
- `src/core/knowledge/incremental_indexer.py` — Re-indexes only changed files (from git diff or PR file list). Delegates to CallGraphExtractor, DescriptionGenerator, and VectorStore. Idempotent. Feature flag: INCREMENTAL_INDEX_ENABLED.
- `src/core/knowledge/query_api.py` — Upgraded `search_by_description()` from vector-only-with-keyword-fallback to true hybrid search: 0.6 × vector_similarity + 0.4 × keyword_overlap. Both paths always run; results merged by module_path.

### Added — DORA Forecast Engine (PEC Blueprint Ch. 11)
- `src/core/metrics/dora_forecast.py` — Predictive DORA metrics engine using EWMA (Exponential Weighted Moving Average) projection. Computes trend direction (improving/stable/degrading) per metric, projects DORA levels at T+7d and T+30d, identifies the "weakest link" metric, integrates with Risk Inference Engine for risk-adjusted CFR, and emits a health pulse (0-100) for the portal "DORA Sun" visualization.
- `tests/test_dora_forecast.py` — 33 tests covering EWMA computation, trend classification, level classification, weakest link identification, health pulse, risk integration, serialization, and 3 end-to-end scenarios (Elite/degrading/recovering teams).

### Added — Risk Inference Engine (ADR-022, PEC Blueprint Ch. 1-2)
- `src/core/risk/__init__.py` — New package implementing the PEC Blueprint's Bayesian Risk Inference Engine. Calculates P(Failure|Context) before agent execution using 13 normalized signals, sigmoid activation, and SHAP-like explanations.
- `src/core/risk/risk_config.py` — Knowledge artifact defining thresholds (τ_warn=0.08, τ_escalate=0.15, τ_block=0.40), signal weights, and Recursive Optimizer parameters (learning rate, weight decay, clamping).
- `src/core/risk/risk_signals.py` — Contextual Encoder extracting 13 risk signals from data contract, DORA metrics, failure history, and onboarding catalog. Signals span historical (CFR, recurrence, hotspots), complexity (files, cyclomatic, dependencies, cross-module), DORA trends (lead time, deploy frequency), organism level, and protective factors (test coverage, prior success, catalog confidence).
- `src/core/risk/inference_engine.py` — Core engine: weighted sum → sigmoid → classification → XAI explanation. Includes Recursive Optimizer (gradient descent on prediction errors) for self-improving weights after task outcomes.
- `tests/test_risk_inference_engine.py` — 33 tests covering signal extraction, inference scoring, threshold classification, explanation generation, recursive optimizer, serialization, and 3 end-to-end PEC Blueprint scenarios.
- `docs/adr/ADR-022-risk-inference-engine.md` — Architecture decision record documenting the Bayesian risk scoring approach, signal taxonomy, threshold calibration, and Well-Architected alignment.

### Changed — Design Document Updates for Risk Engine
- `docs/architecture/design-document.md` — Added Risk Inference Engine to Components table, Testing Design table, ADR references, and resolved Open Question #5.

---

## [Previous] — 2026-05-11

### Added — Conductor Orchestration Pattern (ADR-020)
- `src/core/orchestration/conductor.py` — New Conductor engine implementing the RL Conductor pattern (Nielsen et al., ICLR 2026, arXiv:2512.04388v5). Generates dynamic WorkflowPlans with focused subtask instructions, communication topologies (access lists), task-difficulty adaptivity via organism ladder, and bounded recursive self-referential scaling (max depth 2).
- `src/core/orchestration/conductor_integration.py` — Integration layer bridging Conductor with DistributedOrchestrator. Feature flag `CONDUCTOR_ENABLED` (default true for O3+ tasks). Handles recursive refinement loop, manifest conversion, and subtask env injection.
- `docs/design/conductor-orchestration-pattern.md` — Design document mapping the paper's concepts to FDE implementation: topology types (sequential, parallel, tree, debate, recursive), agent capability matching, confidence-based recursion, and integration with DistributedOrchestrator.
- `docs/adr/ADR-020-conductor-orchestration-pattern.md` — Architecture decision record documenting the choice of LLM-generated plans over static topology libraries or full RL training.
- `src/core/orchestration/__init__.py` — Updated exports to include Conductor, WorkflowPlan, WorkflowStep, TopologyType, should_use_conductor, generate_conductor_manifest, execute_with_conductor.

### Added — Orchestrator Container for Distributed Execution
- `infra/docker/Dockerfile.orchestrator` — New container image for the distributed orchestrator. Clones workspace via EFS, dispatches agent tasks via ECS RunTask, monitors completion, and triggers delivery.
- `infra/terraform/distributed-infra.tf` — ECS task definition for orchestrator container with EFS mount, IAM permissions for RunTask dispatch.

### Added — Two-Way Door Execution Mode Switch (ADR-021)
- `infra/terraform/eventbridge.tf` — `execution_mode` variable (`monolith` | `distributed`) switches EventBridge target between strands-agent and orchestrator task definitions. Rollback in <30s via `terraform apply`.
- `docs/adr/ADR-021-two-way-door-distributed-execution.md` — Architecture decision record documenting the two-way door mechanism, alternatives rejected, and consequences.

### Added — Explainability Layer for Pipeline Reasoning
- `infra/docker/agents/explainability.py` — Reasoning rail that captures and structures agent decision points (why this approach, what alternatives considered, confidence level). Emits structured events to DynamoDB for portal visibility.

### Added — ConductorPlanCard Portal Component
- `infra/portal-src/src/components/ConductorPlanCard.tsx` — Visualizes Conductor-generated WorkflowPlans: topology graph, agent assignments, subtask instructions, and execution progress.

### Changed — Agent Runner Conductor Integration
- `src/core/orchestration/agent_runner.py` — `_build_system_prompt()` now reads `AGENT_SUBTASK` env var for Conductor-generated focused instructions (falls back to generic role prompt when absent). `_load_scd_context()` now respects `AGENT_ACCESS_LIST` env var for communication topology enforcement (falls back to loading all previous stages when absent). Both changes are backward-compatible.

### Changed — Stream Callback Tool Noise Filter
- `infra/docker/agents/stream_callback.py` — Added signal/noise classification for tool calls. Low-signal tools aggregated into summaries; high-signal tools emit full events. Reduces DynamoDB write volume and improves portal readability.

### Changed — Factory Data Mapper (Timeline + DORA Empty State)
- `infra/portal-src/src/mappers/factoryDataMapper.ts` — Client-side noise filter for timeline events. DORA metrics empty state handling (shows placeholder when no completed tasks exist). Aggregates consecutive same-type tool calls.

### Changed — Portal Delivery Badge
- `infra/portal-src/src/App.tsx` — Replaced cryptic "NO PR" amber badge with clear delivery status indicators: "Delivered", "Pending Push", "Push Failed (retry)". Tooltip shows failure reason when applicable.

### Changed — EventBridge Execution Mode Routing
- `infra/terraform/eventbridge.tf` — Conditional target selection based on `execution_mode` variable. Both task definition ARNs referenced; only the active one receives events.

### Fixed — PII Removal from Tracked Files
- Removed all hardcoded account IDs, profile names, and email addresses from tracked files. Replaced with environment variable references and placeholders.

### Fixed — AWS_PROFILE Default for SSO Auth
- `infra/terraform/providers.tf` — Removed hardcoded profile name. Uses `AWS_PROFILE` environment variable (defaults to `profile-rocand` for SSO authentication when not set).

### Fixed — Push Stale Ref on Re-Worked Tasks (COE-021)
- `infra/docker/agents/workspace_setup.py` — Added `_fetch_remote_branch()` before push, `_find_existing_pr()` + `_update_pr()` for re-worked tasks. Hybrid safe push strategy handles all retry scenarios.

### Fixed — Portal Timeline Noise (COE-022)
- `infra/docker/agents/stream_callback.py` — Tool-call noise filter with signal/noise classification.
- `infra/portal-src/src/mappers/factoryDataMapper.ts` — Client-side noise filter + aggregation.
- `infra/portal-src/src/App.tsx` — Renamed "Chain of Thought" → "Pipeline Activity".

### Fixed — Cryptic 'NO PR' Badge
- `infra/portal-src/src/App.tsx` — Replaced raw "NO PR" badge with meaningful delivery status that distinguishes between "not yet pushed", "push failed", and "delivered".

### Added — Shell Command Context Parsing
- `infra/docker/agents/stream_callback.py` — `_handle_tool_input()` captures `contentBlockDelta` tool input and classifies shell commands into human-readable actions (git commit → "Committing changes...", pytest → "Running tests...", cat file.py → "Reading: file.py").

### Changed — Agent Role Labels in Timeline
- `infra/docker/agents/stream_callback.py` — Added `agent_role` field to DashboardCallback. Events now carry `phase=agent_role` so the portal shows the correct agent name instead of generic "fde-pipeline".
- `infra/docker/agents/orchestrator.py` — Passes `agent_role` when creating DashboardCallback instances.

### Changed — Portal Polling Interval
- `infra/portal-src/src/App.tsx` — Reduced polling from 15s to 5s to match stream_callback flush interval. Portal updates within ~5-10s without manual refresh.

### Fixed — DORA Lead Time Accuracy (COE-023)
- `infra/docker/agents/task_queue.py` — `update_task_stage()` sets `started_at = if_not_exists(started_at, :now)` idempotently. `complete_task()` calculates `duration_ms = now - started_at`.
- `infra/terraform/lambda/dashboard_status/index.py` — `_compute_elapsed()` uses `started_at` instead of `created_at`.

### Fixed — Push Force Fallback for Re-Worked Tasks
- `infra/docker/agents/workspace_setup.py` — Fallback from `--force-with-lease` to `--force` when the remote branch has divergent history from a previous pipeline run.

### Security
- Removed all hardcoded AWS account IDs, profile names, and email addresses from source-controlled files.
- Added `docs/example/` and `cloud-inventory.md` to `.gitignore` to prevent accidental PII commits.
- `AWS_PROFILE` sourced from environment variable instead of hardcoded in Terraform provider configuration.

---

## [Previous] — 2026-05-08

### Fixed — COE-020: ECS Platform Mismatch + Multi-Model Infra + EventBridge Drift
- `Makefile` — Added `docker-build`, `docker-build-adot`, `docker-build-onboarding`, `docker-push-all`, `docker-deploy` targets. All enforce `--platform linux/amd64` for Fargate compatibility. ECR URL resolved from Terraform outputs.
- `infra/terraform/variables.tf` — Added `bedrock_model_reasoning` (Claude Sonnet 4), `bedrock_model_standard` (Claude Sonnet 4.5), `bedrock_model_fast` (Claude Haiku 4.5) as first-class infrastructure parameters.
- `infra/terraform/main.tf` — Strands agent task definition now passes `BEDROCK_MODEL_REASONING`, `BEDROCK_MODEL_STANDARD`, `BEDROCK_MODEL_FAST` env vars to the container.
- `infra/terraform/distributed-infra.tf` — Passes model tier variables through to ECS module.
- `infra/terraform/modules/ecs/agent_task_def.tf` — Squad agent task definition includes all 3 model tier env vars.
- `infra/terraform/dashboard-cdn.tf` — CloudFront: added `ordered_cache_behavior` for `/assets/*` (1-year immutable cache), reduced default TTL to 60s, added SPA fallback (403/404 → index.html).
- `scripts/deploy-dashboard.sh` — Added `--build` flag for source rebuild before deploy. Separated S3 uploads: index.html (no-cache), assets (immutable), images (24h cache).
- Docker images rebuilt for `linux/amd64` and pushed to ECR. ADOT sidecar rebuilt from official AWS public ECR image.
- EventBridge targets (GitHub, GitLab, Asana) updated from task definition revision `:11` → `:12`.

### Added — Portal Observability Data Mapper
- `infra/portal-src/src/mappers/factoryDataMapper.ts` — New mapper module with 5 functions: `mapDoraMetrics()`, `mapCostMetrics()`, `mapGateHistory()`, `mapLiveTimeline()`, `mapSquadExecution()`. Transforms raw `/status/tasks` API response into component prop shapes.
- `infra/portal-src/src/App.tsx` — Observability view now passes real API data to DoraCard, CostCard, GateHistoryCard, LiveTimeline, SquadExecutionCard via mapper functions.
- `infra/portal-src/src/services/factoryService.ts` — Added `agents` field to `DashboardData` interface (matches Lambda response).
- `infra/dashboard/` — Rebuilt with fresh Vite output containing mapper code.

### Fixed — COE-019: Observability Pipeline (StatusSync + Portal + OTEL)
- `infra/docker/agents/orchestrator.py` — Integrated `StatusSync` (was dead code) to post structured comments to GitHub issues on pipeline complete/fail. Added rebase-retry when push fails with stale ref. Emits `append_task_event(type="error")` on PR delivery failure. Emits gate events (constraint extraction, DoR, adversarial) and stage start/complete events to DynamoDB for portal visibility.
- `infra/docker/agents/stream_callback.py` — Expanded `DashboardCallback` reasoning markers (5→13 keywords), text markers (emojis, file ops, bold items, `#` headers), matching CloudWatch log visibility in the portal.
- `infra/terraform/lambda/dashboard_status/index.py` — Derives `completed_no_delivery` status for tasks that completed without a PR. Exposes `pr_error` field in API response.
- `infra/portal-src/src/App.tsx` — Amber badge "NO PR" for `completed_no_delivery` status. Push failure indicator with tooltip.
- `infra/portal-src/src/services/factoryService.ts` — Added `pr_error` field to `Task` interface.
- `docs/corrections-of-error.md` — COE-019 documented with 3 root causes, 5 fixes, Well-Architected alignment.

### Added — OTEL Distributed Tracing (ADOT Sidecar)
- `infra/docker/agent_entrypoint.py` — `_init_telemetry()` initializes Strands SDK OTEL (agent/cycle/tool spans). No-op when `OTEL_EXPORTER_OTLP_ENDPOINT` is unset.
- `infra/docker/requirements.txt` — Added `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`, `opentelemetry-instrumentation-botocore`.
- `infra/terraform/main.tf` — ADOT collector sidecar container (non-essential) in ECS task definition. OTEL env vars (`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES`, `OTEL_SEMCONV_STABILITY_OPT_IN`). X-Ray write IAM policy for task role.
- Architecture: Strands agent → localhost:4318 → ADOT sidecar → AWS X-Ray. Automatic spans for agent invocations, reasoning cycles, and tool calls.

---

## [Unreleased] — 2026-05-07

### Added — Branch Evaluation Agent (ADR-018)
- `infra/docker/agents/branch_evaluation/` — 7-module evaluation engine: artifact classifier (9 types, prefix/suffix matching), scoring engine (7 dimensions, weighted aggregate, veto rules, auto-merge eligibility), code evaluator (D1 structural, D2 convention, D3 backward compat, D5 test coverage, D7 documentation), domain evaluator (D4 alignment, D6 adversarial resilience), report renderer (markdown PR comment + JSON artifact), merge handler (auto-merge + issue-to-DONE via GitHub REST + GraphQL).
- `infra/docker/agents/branch_evaluation/branch_evaluator.py` — Core orchestrator: git diff → classify → evaluate all 7 dimensions → produce verdict → render reports. Entry point for CLI and ECS execution.
- `infra/docker/agents/branch_evaluation/pipeline_graph.py` — Regression surface mapping: `find_tests_for_module()`, `find_consumers()`, `find_affected_edges()`, `find_contract_tests()`, `compute_regression_surface()`. Maps changed files to pipeline edges E1-E6.
- `scripts/evaluate_branch.py` — CLI entrypoint: `python3 scripts/evaluate_branch.py --base main --head feature/GH-42`. Exits 0 (merge eligible) or 1 (blocked). Supports --verbose, --quiet, --level, --output, --pr-comment.
- `.github/workflows/evaluate-branch.yml` — GitHub Action on `pull_request` (opened/synchronize/reopened). Steps: checkout → setup python → run evaluation → post PR comment (idempotent update) → set check status → auto-merge for score >= 8.0 + L1/L2.
- `.kiro/hooks/fde-branch-eval.kiro.hook` — `userTriggered` hook for local branch evaluation via Kiro agent.
- `infra/portal-src/src/components/BranchEvaluationCard.tsx` — Portal component: 7-dimension score bars, verdict badge, merge eligibility, veto warnings. Integrated into Gates view (`#gates`). i18n: en-US, pt-BR, es.
- `docs/adr/ADR-018-branch-evaluation-agent.md` — Architecture decision: deterministic scoring, no LLM in scoring path, auto-merge for L1/L2 with score >= 8.0.

### Added — Agent Brain → Portal CoT Bridge
- `infra/docker/agents/stream_callback.py` — Rewrote `DashboardCallback` to implement Strands SDK `__call__(**kwargs)` interface. Captures tool invocations (from `contentBlockStart` events), reasoning markers (decision/conclusion/approach keywords), and structural text (## headers, ✅/❌ markers). Batches writes (max 1/5s, max 10/buffer) to avoid DynamoDB write amplification.
- `infra/docker/agents/registry.py` — `create_agent()` now accepts optional `callback_handler` kwarg, passes to Strands `Agent()` constructor.
- `infra/docker/agents/orchestrator.py` — Creates `DashboardCallback(task_id)` before each agent execution, wiring the brain→portal bridge.
- Data flow: Agent brain (Bedrock stream) → DashboardCallback → DynamoDB events → Lambda `/status/tasks/{id}/reasoning` → Portal Reasoning view (15s polling).

### Added — Agent Identity Labeling + PR Attribution
- `infra/docker/agents/workspace_setup.py` — Git author now uses `FDE_AGENT_NAME`/`FDE_AGENT_EMAIL` env vars with issue number tag (e.g., `FDE Agent [GH-42]`) for commit traceability.
- `infra/docker/agents/orchestrator.py` — PR body includes Attribution section: agent as hands-on author, codebase owner as reviewer via CODEOWNERS, task ID for correlation.
- Configurable via env vars: `FDE_AGENT_NAME`, `FDE_AGENT_EMAIL` (defaults preserved for backward compatibility).

### Added — ADR-017: React Portal for Factory Observability UX
- `docs/adr/ADR-017-react-portal-observability-ux.md` — Documents the decision to adopt React + Vite + Tailwind for the portal layer. Partially supersedes ADR-011 (YAGNI) for the observability layer only. Covers: technology choices, data classification for exposed events, i18n governance (Ops team maintains, en-US/pt-BR/es), WCAG 2.1 AA compliance, supply chain risk mitigation.

### Added — Concurrency Guard Hardening (COE-016)
- `infra/docker/agents/task_queue.py` — `reap_stuck_tasks(max_age_minutes=60)`: marks orphaned IN_PROGRESS tasks as FAILED after 60min without update. `retry_queued_tasks(repo)`: finds tasks blocked by concurrency guard that are now eligible. `check_concurrency()`: fail-safe for `max_concurrent_tasks <= 0`. `complete_task()`: calls reap + retry on completion to close liveness gap.
- `infra/docker/agents/project_registry.py` — `FACTORY_ALLOW_AUTO_REGISTER` env var (default: true) gates auto-registration. `FACTORY_ALLOWED_ORGS` (comma-separated) restricts to specific GitHub/GitLab organizations. Unknown repos from non-allowed orgs get `max_concurrent_tasks=1`.
- `infra/docker/agents/orchestrator.py` — Calls `reap_stuck_tasks()` before every concurrency check, emits event if tasks were reaped.

### Fixed — Documentation Governance Debt (COE-012 through COE-017)
- `README.md` — Fixed stale counts: hooks 16→17, ADRs 13→17, flows 13→14, tests 54→171. Removed disconnected `> Generate: python3 scripts/generate_reference_architecture.py` from hero section. Added `fde-repo-onboard` to hook table. Expanded Code to Docs cross-reference. Expanded Repo Structure tests section (2→14 files).
- `docs/corrections-of-error.md` — Added COE-012 (doc drift recurrence), COE-013 (EventBridge multi-commit fix), COE-014 (Bedrock migration), COE-015 (bundled fixes), COE-016 (multi-project orchestration governance), COE-017 (React portal governance).
- `docs/architecture/design-document.md` — Bumped to v3.1 (2026-05-07). Testing Design expanded (3→16 entries). Hook count 16→17. Open Question #2 resolved (Strands SDK deployed). Added ADR-017 to Key Design Decisions.

---

## [Unreleased] — 2026-05-06

### Added — EventBridge Observability (COE-011)
- `infra/terraform/eventbridge-observability.tf` — Catch-all logging rule (all events → CloudWatch Logs), FailedInvocations alarm, API Gateway 4xx/5xx alarms, CloudWatch Log resource policy for EventBridge delivery.
- `scripts/validate-webhook-eventbridge.sh` — Three-test isolation script for webhook→ECS path validation.

### Fixed — EventBridge → ECS Pipeline (COE-011)
- `infra/terraform/eventbridge.tf` — InputTransformer changed from broken single-JSON-string pattern to flat scalar env vars (EVENT_SOURCE, EVENT_ACTION, EVENT_LABEL, EVENT_ISSUE_NUMBER, EVENT_ISSUE_TITLE, EVENT_REPO). Root cause: ECS RunTask silently rejects overrides with unescaped JSON objects in string values.
- `infra/docker/agent_entrypoint.py` — Added flat env var reconstruction mode: when EVENT_SOURCE+EVENT_ACTION are set, reconstructs the event object from individual env vars. Maintains backward compatibility with EVENTBRIDGE_EVENT and TASK_SPEC modes.
- `infra/docker/Dockerfile.strands-agent` — Rebuilt with `--platform linux/amd64` for ECS Fargate compatibility (was arm64 from Apple Silicon build).
- `docs/corrections-of-error.md` — COE-011: Full root cause analysis with production evidence (task 03b21106).

### Added — Repo Onboarding Agent (Phase 0, ADR-015)
- `infra/docker/agents/onboarding/` — Phase 0 codebase reasoning brain (13 modules). Sequential pipeline: Trigger Handler → Repo Cloner → File Scanner (Magika) → AST Extractor (tree-sitter) → Convention Detector → Pattern Inferrer (Claude Haiku) → Catalog Writer (SQLite) → Steering Generator → S3 Persister.
- `infra/docker/agents/onboarding/pipeline.py` — Orchestrates all 9 stages sequentially with observability, failure reporting, and incremental re-scan support.
- `infra/docker/agents/onboarding/trigger_handler.py` — Event reception, input validation (URL allowlist, UUID format), mode detection (cloud vs local), incremental skip check.
- `infra/docker/agents/onboarding/repo_cloner.py` — Git clone with ADR-014 credential isolation (fetch-use-discard via GIT_ASKPASS). Supports GitHub, GitLab, Bitbucket.
- `infra/docker/agents/onboarding/file_scanner.py` — Magika-based content classification for every file. Detects generated code, skips binaries >1MB, respects skip directories.
- `infra/docker/agents/onboarding/ast_extractor.py` — tree-sitter AST parsing for Python, JS/TS, Go, Java, Rust, HCL. Extracts module signatures, import graphs, dependency edges.
- `infra/docker/agents/onboarding/convention_detector.py` — Detects 60+ project conventions (package managers, test frameworks, linters, CI/CD, IaC, containers).
- `infra/docker/agents/onboarding/pattern_inferrer.py` — Claude Haiku (Bedrock) inference for pipeline chain, module boundaries, tech stack, and engineering level patterns. Cost-capped at $0.01/run.
- `infra/docker/agents/onboarding/catalog_writer.py` — SQLite persistence (9 tables per REQ-4.1) + catalog query interface for FDE intake integration (get_tech_stack, get_suggested_level, get_module_context).
- `infra/docker/agents/onboarding/steering_generator.py` — Generates project-specific `.kiro/steering/fde.md` from catalog data with unified diff on re-scan.
- `infra/docker/agents/onboarding/s3_persister.py` — Uploads catalog + steering draft + diff to S3 (cloud mode only).
- `infra/docker/agents/onboarding/observability.py` — Structured JSON logging, CloudWatch metrics (fde/onboarding namespace), failure report generation.
- `infra/docker/Dockerfile.onboarding-agent` — Python 3.12 slim + gh CLI + Magika + tree-sitter grammars.
- `infra/docker/requirements-onboarding.txt` — magika>=0.5.0, tree-sitter>=0.21.0, tree-sitter-languages>=1.10.0, networkx>=3.2, boto3>=1.35.0.
- `infra/terraform/onboarding.tf` — ECS task definition (1 vCPU / 2GB), IAM role (least privilege: S3, Secrets, Bedrock, CloudWatch), EventBridge rule, CloudWatch alarms (stage P99 latency, total duration budget).
- `.kiro/hooks/fde-repo-onboard.kiro.hook` — userTriggered hook for local mode onboarding.
- `docs/adr/ADR-015-repo-onboarding-phase-zero.md` — Architecture decision: hybrid deterministic scan + lightweight LLM.
- `docs/flows/14-repo-onboarding.md` — Phase 0 flow diagram with Mermaid (9 stages + incremental re-scan).

### Added — Ephemeral Catalog for Regulated Environments (ADR-016, SEC 7-10)
- `docs/adr/ADR-016-ephemeral-catalog-data-residency.md` — Data residency architecture: three persistence modes (cloud/local/ephemeral), customer-controlled encryption via KMS, TTL-based auto-destruction, audit sidecar without data exposure.

### Added — Operational Tooling and Observability
- `scripts/validate-e2e-cloud.sh` — Full infrastructure health check (11 checks). Single command validates factory readiness.
- `scripts/deploy-dashboard.sh` — Automated dashboard deployment with config injection from terraform outputs.
- `scripts/setup-fde-client.sh` — One-command FDE client setup for any project (hooks + ALM integration).
- `scripts/setup-alm-integration.sh` — Platform-agnostic ALM setup (`--platform github|gitlab|asana`).
- `scripts/bootstrap-fde-workspace.sh` — Installs minimal FDE hooks into any target workspace.
- `infra/docker/agents/status_sync.py` — Posts structured progress comments to GitHub issues during pipeline execution.
- `infra/dashboard/index.html` — Agentic UX dashboard (Cyber-Industrial theme, chain-of-thought log, light/dark mode, ProServe logo).
- `infra/terraform/dashboard.tf` — Dashboard status Lambda + API Gateway route (`GET /status/tasks`).
- `infra/terraform/dashboard-cdn.tf` — CloudFront distribution + OAC for dashboard static hosting.
- `infra/terraform/lambda/dashboard_status/index.py` — Lambda reading DynamoDB task_queue for dashboard metrics.
- `docs/guides/staff-engineer-post-deploy.md` — Complete post-deploy operations guide.
- `docs/corrections-of-error-cloudfront-kms.md` — COE: CloudFront OAC + SSE-KMS access denied root cause and fix.

### Changed — Bedrock Model (Legacy → Active)
- Migrated from `anthropic.claude-3-haiku-20240307-v1:0` (LEGACY) to `us.anthropic.claude-haiku-4-5-20251001-v1:0` (ACTIVE inference profile).

### Changed — Security Cleanup
- Removed all hardcoded account IDs, endpoint URLs, and profile names from active code and docs.
- Dashboard API URL injected at deploy time via `<meta>` tag.
- Dockerfile: added non-root user, suppressed ONNX Runtime warning.

### Infrastructure Deployed
- 9 new resources added to existing stack (ECR onboarding repo, ECS task def, IAM role, EventBridge rule, CloudWatch alarms, dashboard Lambda, CloudFront distribution).
- Docker images pushed: `fde-dev-onboarding-agent:latest`, `fde-dev-strands-agent:latest`.
- Dashboard live via CloudFront. Status API responding at `/status/tasks`.

### Changed — Dependencies (Repo Onboarding Agent)
- `infra/docker/requirements.txt` — Added magika, tree-sitter, tree-sitter-languages, networkx to shared dependencies.

### Added — Dead-Letter Handler and Observability (ADR-014, OPS 6 + OPS 8)
- `infra/terraform/lambda/dead_letter/index.py` — Dead-letter Lambda handler for permanently failed DAG fan-out invocations. Extracts failed task metadata from SQS messages, publishes structured alerts to SNS, marks tasks as `DEAD_LETTER` in DynamoDB for visibility.
- `infra/terraform/observability.tf` — Full observability layer: SNS topic (`fde-dev-pipeline-alerts`), SQS dead-letter queue (`fde-dev-dag-fanout-dlq`), dead-letter Lambda with IAM role, SQS→Lambda event source mapping, 6 CloudWatch alarms (fan-out errors, dead-letter invocations, fan-out throttles, DynamoDB read/write throttles, fan-out duration approaching timeout).
- `docs/guides/deployment-setup.md` — AWS deployment prerequisites guide: SSO profile configuration, session authentication, Terraform variables, init/plan/apply commands, common errors and fixes, teardown, post-deploy steps.
- CloudWatch alarms route to SNS topic for operator notification (email subscription supported).

### Changed — DAG Fan-Out On-Failure Destination (ADR-014)
- `infra/terraform/dag_fanout.tf` — Added `destination_config.on_failure` pointing to SQS dead-letter queue. Added `sqs:SendMessage` permission to fan-out Lambda IAM policy. Failed batches (after DynamoDB Stream's 3 retries) now route to SQS → dead-letter Lambda → SNS alert.

### Changed — README Documentation Index
- `README.md` — Added [AWS Deployment Setup](docs/guides/deployment-setup.md) and [Auth Setup](docs/guides/auth-setup.md) to the Documentation Index table.

### Infrastructure Deployed
- Stack applied to AWS account (us-east-1): 74 resources total (4 added, 3 changed, 1 destroyed in final apply).
- SNS email subscription created (pending confirmation).

---

## [Unreleased] — 2026-05-05

### Added — E2E Pipeline Data Travel Validation
- `tests/test_pipeline_data_travel.py` — 7 cross-module contract tests validating data flows across: Scope Check → Autonomy → Gate Resolution → Execution Plan → SDLC Gates (with enrichment). Proves module interfaces are compatible.
- `tests/test_orchestrator_e2e.py` — 3 E2E tests calling `orchestrator.handle_event()` with real EventBridge events. Proves the Orchestrator ACTUALLY wires scope check, autonomy, gate resolution, and execution plan tracking in production code.
- Resolves the "Node-scoped verification" anti-pattern (COE-052): modules are now validated as a composed system, not just in isolation.

### Changed — Orchestrator Wiring (v2 → v3)
- `infra/docker/agents/orchestrator.py` — `handle_event()` now wires the full pipeline:
  1. Scope Check (`check_scope()`) rejects out-of-scope tasks before any work starts
  2. Autonomy Level (`compute_autonomy_level()`) determines supervision level
  3. Gate Resolution (`resolve_pipeline_gates(level, confidence)`) determines which gates to run
  4. Execution Plan (`create_plan()` / `load_plan()` / `resume_from_plan()`) enables resumable execution
  5. Milestone tracking persists progress to disk after each gate completion
- New imports: `autonomy`, `execution_plan`, `scope_boundaries`
- New constructor parameter: `plans_dir` (filesystem path for execution plan persistence)
- New method: `_execute_pipeline_with_plan()` tracks inner loop gates as milestones
- Backward compatible: `handle_spec()` path unchanged

### Added — Agent-to-Agent PR Review (Task 5)
- `review_pr_with_llm()` in `pipeline_safety.py` — LLM-powered PR review that evaluates diffs against spec and constraints. Returns structured `PRReviewResult` with approved/concerns/suggestions
- `PRReviewResult` dataclass with `to_dict()` serialization
- Opt-in via `PR_REVIEW_LLM_ENABLED=true` env var (same pattern as constraint extraction)
- `_build_review_prompt()` — structured prompt with diff truncation (8000 char limit)
- `_parse_review_response()` — handles clean JSON, markdown code blocks, and invalid responses gracefully
- `_invoke_bedrock()` — same Bedrock invocation pattern as Constraint Extractor
- `tests/test_pr_llm_review.py` — 12 BDD scenarios covering opt-in behavior, response parsing, prompt construction, and dataclass serialization

### Added — Observability Accessible to Agent (Task 6)
- `read_factory_metrics` @tool in `tools.py` — returns DORA metrics for a specific task_id as JSON (read-only)
- `read_factory_health` @tool in `tools.py` — returns Factory Health Report as JSON (read-only, configurable window_days)
- Both tools added to `REPORTING_TOOLS` list (Reporting Agent only, not Engineering Agent)
- `tests/test_observability_tools.py` — 7 BDD scenarios validating tool registration, read-only separation, signatures, and callability

### Added — Execution Plans with Progress Tracking (Task 1)
- `infra/docker/agents/execution_plan.py` — Resumable pipeline execution with `ExecutionPlan` dataclass, milestone tracking (pending → in_progress → completed/skipped), append-only progress and decision logs, filesystem persistence (save/load/plan_exists), and `resume_from_plan()` that finds the first non-completed milestone
- `tests/test_execution_plans.py` — 15 BDD scenarios covering: plan creation, milestone progression, interruption/resume cycle (the core value prop), persistence roundtrip, corrupted file handling, and decision logging
- Source: OpenAI PLANS.md Cookbook — enables L3/L4 tasks to resume from interruption point

### Added — Doc-Gardening Agent (Task 2)
- `infra/docker/agents/doc_gardening.py` — Documentation drift detection with function registry pattern. 5 built-in checks: hook count badge, ADR count, flow count, design-document components, CHANGELOG freshness
- `.kiro/hooks/fde-doc-gardening.kiro.hook` — userTriggered hook to scan for documentation drift
- `tests/test_doc_gardening.py` — 12 BDD scenarios validating drift detection for all check types, registry extensibility, and crash resilience
- Resolves COE pattern: 6 of 9 entries were "doc was outdated"

### Added — Golden Principles + Garbage Collection (Task 4)
- `docs/design/golden-principles.md` — 5 mechanical code quality invariants (GP-01 through GP-05) with rule, rationale, detection logic, and remediation for each
- `infra/docker/agents/golden_principles.py` — Principle validation engine with `@register_principle` decorator pattern. Checks: max file size (500 lines), no print() in production, module docstrings, no import *, max function length (50 lines)
- `.kiro/hooks/fde-golden-principles.kiro.hook` — userTriggered hook to validate code against structural invariants
- `tests/test_golden_principles.py` — 13 BDD scenarios validating all 5 principles (positive + negative cases) plus integration and registry tests

### Added — Custom Linters with Remediation Messages (Task 3)
- `REMEDIATION_MAP` in `sdlc_gates.py` — 20 error code → remediation instruction mappings covering Python (ruff/flake8), TypeScript/JavaScript (eslint), Go (staticcheck), and Terraform (fmt)
- `_enrich_lint_output()` in `sdlc_gates.py` — post-processes raw lint output, appending actionable fix instructions after each recognized error line
- `check_lint()` now returns enriched errors so the agent sees remediation hints in the inner loop retry
- `tests/test_lint_remediation.py` — 12 BDD scenarios validating enrichment for Python, TypeScript, Go, multi-error, unknown codes, and edge cases

### Added — Minimal Gates for L5 High-Confidence Tasks (Task 7)
- `resolve_pipeline_gates()` in `autonomy.py` now accepts optional `confidence_level` parameter
- L5 tasks with `confidence_level == "high"` skip `dor_gate` and `ship_readiness` (inner loop gates provide sufficient validation)
- L5 tasks with any other confidence level retain standard L5 behavior (backward compatible)
- L4 and below are unaffected regardless of confidence level
- 5 new BDD scenarios in `tests/test_autonomy_level.py` (class `TestMinimalGatesL5`)

### Changed — Sprint 1 Throughput Improvements
- Source: OpenAI Harness Engineering ("custom lints with remediation instructions") + Ralph Loop ("corrections are cheap, waiting is expensive")
- Impact: Inner loop first-pass rate improvement (Task 3) + reduced latency for high-confidence L5 tasks (Task 7)

---

## [Unreleased] — 2026-05-04

### Added — Authentication and Data Journey Validation
- `docs/guides/auth-setup.md` — Step-by-step token creation guide for GitHub (PAT classic, scopes `repo` + `project`), GitLab (PAT, scope `api`, expiry check), and Asana (PAT, inherited permissions). Includes progressive configuration, token rotation, cloud deployment (Secrets Manager), and troubleshooting.
- `examples/web-app/test_data_journey.py` — 13 integration tests validating the full data contract flow per platform (GitHub, GitLab, Asana). Each test covers: Router extraction → Constraint detection → Scope check → Autonomy computation → Routing decision.
- `scripts/validate-alm-api.sh` — Extended GitLab validation: PAT self-introspection (`GET /personal_access_tokens/self`), scope verification (`api` required), and token expiry check.

### Added — Enterprise-Grade Autonomy and Observability (ADR-013)
- `infra/docker/agents/autonomy.py` — Autonomy Level computation (L1-L5) with pipeline gate adaptation. Computes level from data contract (type + level), supports human override, resolves which gates and checkpoints to apply per task.
- `infra/docker/agents/failure_modes.py` — Failure Mode Taxonomy (FM-01 through FM-99). Classifies WHY tasks do not complete using heuristic rules on execution context signals. Integrates with DORA metrics as dimensions.
- `infra/docker/agents/scope_boundaries.py` — Scope Boundary Enforcement. Rejects tasks outside factory capability (no acceptance criteria, no tech_stack, forbidden actions like production deploy or PR merge). Computes confidence level (high/medium/low) from available signals.
- `docs/design/scope-boundaries.md` — Formal scope boundaries document defining in-scope capabilities, out-of-scope items, performance targets per autonomy level, and confidence scoring.
- `tests/test_autonomy_level.py` — 10 BDD scenarios for autonomy computation and pipeline adaptation
- `tests/test_failure_mode_taxonomy.py` — 8 BDD scenarios for failure classification
- `tests/test_domain_segmented_metrics.py` — 5 BDD scenarios for tech_stack segmentation
- `tests/test_scope_boundaries.py` — 8 BDD scenarios for scope enforcement
- ADR-013: Enterprise-Grade Autonomy, Failure Classification, and Scope Boundaries

### Added — Constraint Extractor and Agent Builder (ADR-010)
- `infra/docker/agents/constraint_extractor.py` — Two-pass constraint extraction (rule-based regex + opt-in LLM). Extracts version pins, latency thresholds, auth mandates, encryption requirements, dependency exclusions. DoR Gate validates extracted constraints against tech_stack.
- `infra/docker/agents/agent_builder.py` — Just-in-time agent provisioning from data contract. Queries Prompt Registry by tech_stack context tags, injects extracted constraints into agent prompts, selects tool set by task type.
- `infra/docker/agents/project_isolation.py` — SaaS-kernel project isolation. Each task gets isolated S3 prefix, workspace directory, git branch, and correlation ID. Zero cross-project interference.
- `infra/docker/agents/sdlc_gates.py` — Inner loop (lint → typecheck → unit-test → build) and outer loop (DoR → Constraint Extraction → Adversarial → Ship-Readiness) gate enforcement with retry logic and timing.
- `infra/docker/agents/pipeline_safety.py` — PR Diff Review Gate (secret scanning, debug code detection, size checks) + Automatic Rollback (checkpoint + git reset to known-good state on feature branches).
- `infra/docker/agents/dora_metrics.py` — DORA Metrics Collector with 4 core metrics (Lead Time, Deployment Frequency, Change Failure Rate, MTTR) + 5 factory metrics. Domain segmentation by tech_stack. Factory Health Report with DORA level classification (Elite/High/Medium/Low).

### Added — Over-Engineering Mitigations (ADR-012)
- LLM constraint extraction is opt-in (default off). Enable via env var, constructor flag, or per-task field.
- Fast path for bugfix/documentation tasks with empty constraints — skips extraction entirely.
- ADR-011: Multi-Cloud Adapter deferred until customer demand. `target_environment` preserved in data contract.
- ADR-012: Over-Engineering Mitigations and Gap Closures (6 decisions with adversarial analysis)

### Changed — Router (v1 → v2)
- `infra/docker/agents/router.py` — Now extracts the full canonical data contract from platform-specific event payloads (GitHub issue form sections, GitLab scoped labels, Asana custom fields). `RoutingDecision` carries `data_contract` dict.

### Changed — Orchestrator (v1 → v2)
- `infra/docker/agents/orchestrator.py` — Full pipeline: Router → Constraint Extraction → DoR Gate → Agent Builder → Execute. Fast path for simple tasks. Writes extraction reports to S3 for audit trail.

### Changed — Entrypoint
- `infra/docker/agent_entrypoint.py` — Wires Constraint Extractor (with optional LLM) + Agent Builder into the Orchestrator.

### Changed — DynamoDB (Terraform)
- `infra/terraform/dynamodb.tf` — Added `fde-dev-dora-metrics` table with GSIs for task_id and metric_type queries.
- `infra/terraform/main.tf` — Added DORA_METRICS_TABLE env var to ECS task definition, added DynamoDB access to IAM policy.

### Changed — Data Contract Design
- `docs/design/data-contract-task-input.md` — Updated Agent Consumption Matrix with new components (Constraint Extractor, DoR Gate, Agent Builder). Added Pipeline Flow diagram showing the full InProgress event sequence.

### Added — Multi-Platform ALM Integration (ADR-008)
- Portable task templates for GitHub Projects, Asana, and GitLab Ultimate (`docs/templates/task-template-*.md`)
- Canonical task schema (`docs/templates/canonical-task-schema.yaml`) — platform-agnostic format all adapters map to
- `fde-work-intake` hook (14th hook) — scans ALM boards for "In Progress" items, creates specs, starts pipeline
- Asana MCP server added to `.kiro/settings/mcp.json`
- GitLab MCP server expanded with issue operations in autoApprove list
- `scripts/validate-alm-api.sh` — pre-flight API connectivity checks for all three platforms
- Flow 11: Multi-Platform Work Intake (`docs/flows/11-multi-platform-intake.md`)
- ADR-008: Multi-Platform Project Tooling

### Added — Staff Engineer Onboarding Pipeline (ADR-009)
- `scripts/pre-flight-fde.sh` — validates machine tools, credentials (including AWS SSO/profile), IAM permissions, collects project config interactively
- `scripts/validate-deploy-fde.sh` — validates four planes: Control (Kiro), Data (ALM APIs), FDE (MCP/hooks), Cloud (AWS)
- `scripts/code-factory-setup.sh` — deploys everything: global infra, per-project workspaces, optional AWS cloud
- Three project modes: experiment (local-only), greenfield (new repo), brownfield (existing codebase with convention scan)
- Brownfield convention scanner detects languages, package managers, test frameworks, linters, CI/CD, Docker
- Greenfield `requirements.md` template for agent-driven scaffolding
- Flow 12: Staff Engineer Onboarding (`docs/flows/12-staff-engineer-onboarding.md`)

### Added — AWS Cloud Infrastructure (ADR-009)
- Terraform IaC (`infra/terraform/`) for the full cloud stack:
  - ECR repository for Strands agent Docker images
  - ECS Fargate cluster for headless agent execution
  - S3 bucket for factory artifacts (versioned, KMS-encrypted, public access blocked)
  - Secrets Manager for ALM tokens (GitHub, Asana, GitLab)
  - VPC with public/private subnets, NAT Gateway, security group (egress-only)
  - IAM roles with least-privilege policies (Bedrock, S3, Secrets, CloudWatch)
  - CloudWatch log groups for agent execution and API Gateway
- `infra/terraform/modules/vpc/` — reusable VPC module
- `infra/terraform/factory.tfvars.example` — configuration template
- `scripts/validate-aws-iam.py` — per-service IAM permission validator
- ADR-009: AWS Cloud Infrastructure for Headless Agent Execution

### Added — EventBridge + API Gateway Orchestration
- `infra/terraform/eventbridge.tf` — custom event bus, 3 rules (GitHub/GitLab/Asana), IAM role, 3 ECS RunTask targets with event passthrough
- `infra/terraform/apigateway.tf` — HTTP API Gateway with 3 webhook routes (`POST /webhook/{platform}`), direct EventBridge PutEvents integration, access logging
- Webhook URLs output by Terraform for configuring ALM platform webhooks

### Added — Strands Agent Application Layer
- `infra/docker/agents/registry.py` — Agent Registry: stores agent definitions, creates Strands Agent instances with BedrockModel
- `infra/docker/agents/router.py` — Agent Router: maps EventBridge events to the correct agent (reconnaissance/engineering/reporting)
- `infra/docker/agents/orchestrator.py` — Agent Orchestrator: wires Registry + Router, executes agents, writes results to S3
- `infra/docker/agents/tools.py` — 6 real `@tool`-decorated functions: read_spec, write_artifact, update_github_issue, update_gitlab_issue, update_asana_task, run_shell_command
- `infra/docker/agents/prompts.py` — FDE system prompts for 3 agent roles (Reconnaissance Phase 1, Engineering Phases 2-3, Reporting Phase 4)
- `infra/docker/agents/prompt_registry.py` — Prompt Registry: versioned prompt storage in DynamoDB with SHA-256 hash integrity, context-aware selection by tags
- `infra/docker/agents/task_queue.py` — Task Queue: DynamoDB-backed with DAG dependency resolution, priority ordering, optimistic locking for task claims, automatic promotion of dependent tasks
- `infra/docker/agents/lifecycle.py` — Agent Lifecycle Manager: tracks instances through CREATED → INITIALIZING → RUNNING → COMPLETED/FAILED → DECOMMISSIONED, execution time tracking, active agent count
- `infra/docker/agent_entrypoint.py` — main entrypoint wiring Registry + Router + Orchestrator, 3 execution modes (EventBridge event, direct spec, standby)
- `infra/docker/Dockerfile.strands-agent` — Python 3.12 + Node.js 20, non-root user, strands-agents SDK
- `infra/docker/requirements.txt` — strands-agents>=1.0.0, boto3, pyyaml, requests
- Docker image built and pushed to ECR (`fde-dev-strands-agent:latest`)

### Added — DynamoDB Tables (Terraform)
- `infra/terraform/dynamodb.tf` — 3 DynamoDB tables (PAY_PER_REQUEST):
  - `fde-dev-prompt-registry` (PK: prompt_name, SK: version) — versioned prompts with hash integrity
  - `fde-dev-task-queue` (PK: task_id, GSI: status-created-index) — task queue with dependency DAG
  - `fde-dev-agent-lifecycle` (PK: agent_instance_id, GSI: status-created-index) — agent instance tracking
- IAM policy for ECS task role: DynamoDB read/write access to all 3 tables
- ECS task definition v2: added PROMPT_REGISTRY_TABLE, TASK_QUEUE_TABLE, AGENT_LIFECYCLE_TABLE env vars
- E2E validated against live DynamoDB: prompt versioning + hash integrity, task dependency resolution, full agent lifecycle walk

### Added — E2E Validation and Teardown
- `scripts/validate-e2e-cloud.sh` — validates all 7 cloud resource categories: Terraform outputs, API Gateway webhooks, EventBridge bus/rules/events, S3 read/write, Secrets Manager, ECR repo/images, ECS cluster/task definition
- `scripts/teardown-fde.sh` — two modes: Terraform destroy (preferred) and tag-based cleanup (fallback), with dry-run preview
- E2E validation result: 21 passed, 0 failed, 0 warnings against live AWS account

### Added — Documentation
- Flow 13: Cloud Orchestration (`docs/flows/13-cloud-orchestration.md`)
- `docs/corrections-of-error.md` — sequential COE log (8 entries)
- `CHANGELOG.md` — this file

### Added — Data Contract and Platform Templates (ADR-010)
- `docs/design/data-contract-task-input.md` — formal data contract defining required/optional/agent-populated fields, validation rules, platform mapping, agent consumption matrix
- `.github/ISSUE_TEMPLATE/factory-task.yml` — GitHub issue form enforcing the data contract (dropdowns, checkboxes, required fields)
- `.github/pull_request_template.md` — structured PR template with validation checklist
- `.gitlab/issue_templates/factory-task.md` — GitLab issue template with scoped labels
- ADR-010: Data Contract for Task Input — connects data contract to Agent Builder (tech_stack + type drive just-in-time agent provisioning)

### Changed — Enterprise Hooks (v1 → v2)
- `fde-enterprise-backlog` v2.0 — now platform-aware: reads `source:` from spec frontmatter, syncs to originating platform, supports cross-platform linking
- `fde-enterprise-release` v2.0 — creates PR/MR on the correct platform (GitHub or GitLab), updates ALM status across all linked platforms

### Changed — Enterprise Steering
- `.kiro/steering/fde-enterprise.md` — added Factory Dispatcher persona, multi-platform support table, work intake flow, API validation section, cloud deployment context with webhook URLs and agent pipeline

### Changed — Provision Script
- `scripts/provision-workspace.sh` — copies task templates during project onboarding, checks ASANA_ACCESS_TOKEN, adds ALM and cloud setup guidance to "Next Steps"

### Changed — MCP Configuration
- `.kiro/settings/mcp.json` — added Asana MCP server, expanded GitLab autoApprove list

### Changed — Architecture Diagram
- `scripts/generate_architecture_diagram.py` — updated with 14 hooks, multi-platform ALM labels, AWS Cloud Plane branch (ECS Fargate + Bedrock)
- `docs/architecture/autonomous-code-factory.png` — regenerated (3252x1165, 2.79:1 ratio)

### Changed — Design Document
- `docs/architecture/design-document.md` — hook count 13→14, added Cloud Infrastructure/Onboarding Pipeline/Strands Agent/IAM Validator to Components table, added ADR-008 and ADR-009 to Key Design Decisions

### Changed — Adoption Guide
- `docs/guides/fde-adoption-guide.md` — added "Recommended: Automated Onboarding Pipeline" section with three-script flow

### Changed — README
- Quick Start rewritten: pre-flight → validate-deploy → code-factory-setup (was provision-workspace.sh only)
- Hook count badge: 13→14, ADR count: 7→9, flow count: 10→13
- Repo structure: added infra/, agents/, teardown, E2E validation, IAM validator scripts
- Architecture section: added cloud orchestration explanation with link to Flow 13

### Changed — Scripts (Linter Mode + AWS SSO)
- All three onboarding scripts operate as linters — collect all issues, report with remediation, never exit early
- AWS SSO/profile support: `aws_cmd()` helper passes `--profile` to all AWS CLI calls, `get_tf_env()` passes `AWS_PROFILE` to Terraform
- AWS profile stored in manifest (`credentials.aws_profile`, `cloud.aws_tf_profile`)

### Fixed
- COE-001: Hook count inconsistency in design document (13→14)
- COE-002: Design document missing infrastructure components
- COE-003: Adoption guide referenced old onboarding flow
- COE-004: Blogpost missing cloud deployment (intentional — point-in-time publication)
- COE-005: Missing ADR for AWS Cloud Infrastructure (created ADR-009)
- COE-006: Architecture diagram outdated (regenerated with cloud plane)
- COE-007: GitLab EventBridge rule used invalid nested event pattern
- COE-008: Bash arithmetic `((PASS++))` returns exit code 1 when PASS is 0

---

## [3.0.0] — 2026-05-04

### Added
- Autonomous Code Factory pattern (Level 4 autonomy)
- 13 Kiro hooks: DoR gate, adversarial gate, DoD gate, pipeline validation, test immutability, circuit breaker, enterprise backlog, enterprise docs, enterprise release, ship-readiness, alternative exploration, notes consolidation, prompt refinement
- `.kiro/steering/fde.md` — FDE protocol steering with pipeline chain, module boundaries, quality standards
- `.kiro/steering/fde-enterprise.md` — enterprise ALM context steering
- `scripts/provision-workspace.sh` — automated onboarding (--global / --project)
- `scripts/generate_architecture_diagram.py` — ILR-compliant architecture diagram generator
- `scripts/lint_language.py` — violent, trauma, and weasel word detection
- 10 Mermaid feature flow diagrams (`docs/flows/01-10`)
- 7 Architecture Decision Records (ADR-001 through ADR-007)
- Design document (`docs/architecture/design-document.md`)
- Architecture diagram (`docs/architecture/autonomous-code-factory.png`)
- Blogpost (`docs/blogpost-autonomous-code-factory.md`)
- Adoption guide with Next.js and Python microservice walkthroughs
- Blueprint design and hook deploy guide
- Global steerings: agentic-tdd-mandate, adversarial-protocol
- Examples: web-app and data-pipeline workspace templates
- 54 tests: 48 structural E2E + 6 quality threshold
- Factory state dashboard (`~/.kiro/factory-state.md`)
- Cross-session learning via notes system
- Meta-agent for prompt refinement

### Changed
- Renamed from "Dark Factory" to "Autonomous Code Factory"
- Replaced "Director of Architecture" with "Factory Operator" / "Staff Engineer"
- Applied Amazon writing standards: zero violent, trauma, or weasel word violations

---

## [2.0.0] — 2026-04-24

### Added
- Forward Deployed AI Engineers (FDE) design pattern
- Four-phase autonomous engineering protocol (Reconnaissance → Intake → Engineering → Completion)
- Research foundations from 6 peer-reviewed studies
- COE-052 post-mortem analysis with 5 failure modes
- Structured prompt contract (Context + Instruction + Constraints)
- Recipe-aware iteration (Phase 3 sub-phases: 3.a adversarial, 3.b pipeline, 3.c 5W2H, 3.d 5 Whys)
- Engineering level classification (L2/L3/L4)
- Knowledge artifact vs code artifact distinction
- `docs/design/forward-deployed-ai-engineers.md` — full design document with research synthesis

---

## [1.0.0] — 2026-04-24

### Added
- Initial release of the Forward Deployed AI Engineers pattern for Kiro
- Basic steering file for FDE protocol
- README with pattern overview
