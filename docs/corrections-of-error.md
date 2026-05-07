# Corrections of Error — Autonomous Code Factory

> Log of corrections applied to the factory template.
> Ordered newest first — most recent correction at the top.
> Each entry documents what was wrong, what was fixed, and why.

---

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
