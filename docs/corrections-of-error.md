# Corrections of Error — Autonomous Code Factory

> Sequential log of corrections applied to the factory template.
> Each entry documents what was wrong, what was fixed, and why.

---

## COE-001: Hook count inconsistency in design document

- **Date**: 2026-05-04
- **Severity**: Documentation
- **Found in**: `docs/architecture/design-document.md`
- **Description**: Design document referenced "13 hooks" in the Components table, but the actual count is 14 after adding `fde-work-intake`.
- **Fix**: Updated Components table to reference 14 hooks.
- **Root cause**: Hook was added to `.kiro/hooks/` without updating the design document count.

## COE-002: Design document missing new infrastructure components

- **Date**: 2026-05-04
- **Severity**: Documentation
- **Found in**: `docs/architecture/design-document.md`
- **Description**: Components table did not include the onboarding scripts (`pre-flight-fde.sh`, `validate-deploy-fde.sh`, `code-factory-setup.sh`), the Terraform IaC (`infra/terraform/`), or the Strands agent Docker image (`infra/docker/`).
- **Fix**: Added Cloud Infrastructure, Onboarding Pipeline, and Strands Agent to the Components table.
- **Root cause**: Infrastructure layer was built after the design document was last updated.

## COE-003: Adoption guide referenced old onboarding flow

- **Date**: 2026-05-04
- **Severity**: Documentation
- **Found in**: `docs/guides/fde-adoption-guide.md`
- **Description**: Step 1 still showed `provision-workspace.sh --global` as the primary onboarding path. The new three-script pipeline (`pre-flight-fde.sh` → `validate-deploy-fde.sh` → `code-factory-setup.sh`) was not mentioned.
- **Fix**: Added new "Recommended: Automated Onboarding" section before the manual steps.
- **Root cause**: Adoption guide was written before the onboarding pipeline was built.

## COE-004: Blogpost missing cloud deployment capability

- **Date**: 2026-05-04
- **Severity**: Documentation
- **Found in**: `docs/blogpost-autonomous-code-factory.md`
- **Description**: Blogpost described only local factory operations. The AWS cloud deployment capability (Bedrock, AgentCore, ECS/ECR, Terraform IaC) was not mentioned.
- **Fix**: Not applied — blogpost is a point-in-time publication. Cloud deployment will be covered in a future blogpost or addendum.
- **Root cause**: Blogpost was published before cloud infrastructure was added. This is expected behavior, not a defect.

## COE-005: Missing ADR for AWS Cloud Infrastructure

- **Date**: 2026-05-04
- **Severity**: Governance
- **Found in**: `docs/adr/`
- **Description**: The AWS cloud infrastructure (Terraform IaC, ECR, ECS Fargate, Bedrock, AgentCore, Secrets Manager) was built without a corresponding Architecture Decision Record.
- **Fix**: Created ADR-009.
- **Root cause**: Infrastructure was built incrementally across multiple sessions without pausing to write the ADR.


## COE-006: Architecture diagram outdated — missing cloud plane and 14 hooks

- **Date**: 2026-05-04
- **Severity**: Documentation / Visual
- **Found in**: `docs/architecture/autonomous-code-factory.png`, `scripts/generate_architecture_diagram.py`
- **Description**: The architecture diagram showed 13 hooks, single-platform ALM (GitHub only), and no AWS cloud infrastructure. The diagram did not reflect the multi-platform ALM (GitHub Projects, Asana, GitLab), the 14th hook (`fde-work-intake`), or the AWS Cloud Plane (ECS Fargate, Bedrock, ECR, Secrets Manager).
- **Fix**: Updated `scripts/generate_architecture_diagram.py` with:
  - Work Intake cluster label updated to "GitHub Projects · Asana · GitLab"
  - Agent Execution cluster updated to "14 Hooks"
  - Spec Control Plane label updated to include "Canonical Schema"
  - New Branch C: AWS Cloud Plane with ECS Fargate (Strands Agent) and Bedrock (Inference)
  - Regenerated PNG: 3252×1165 (2.79:1 ratio — passes ILR dimension check)
- **Root cause**: Diagram was generated before multi-platform ALM and AWS cloud infrastructure were added.
- **Validation**: Diagram referenced from 4 locations (README.md, blogpost, design-document.md, generate script) — all paths verified correct.


## COE-007: GitLab EventBridge rule used invalid nested event pattern

- **Date**: 2026-05-04
- **Severity**: Infrastructure (Terraform apply failure)
- **Found in**: `infra/terraform/eventbridge.tf`
- **Description**: The GitLab EventBridge rule used a nested object pattern (`labels[].title`) which EventBridge does not support. EventBridge patterns only match on simple key-value pairs, not nested array-of-objects. This caused `terraform apply` to fail with `InvalidEventPatternException`.
- **Fix**: Flattened the event pattern to match on `detail.action = ["update"]` instead of nested `detail.labels[].title`.
- **Root cause**: EventBridge event pattern syntax was assumed to support JSON path-like nested matching, which it does not.
- **Impact**: 49 of 51 resources created successfully. Only the GitLab rule and its ECS target failed. Second apply created the remaining 2.

## COE-008: Bash arithmetic `((PASS++))` returns exit code 1 when PASS is 0

- **Date**: 2026-05-04
- **Severity**: Script bug (cosmetic)
- **Found in**: `scripts/validate-e2e-cloud.sh`
- **Description**: `((PASS++))` when PASS=0 evaluates `((0))` which is falsy in bash (exit code 1). Combined with `&&`/`||` chains, this caused both success and failure branches to execute.
- **Fix**: Changed to `PASS=$((PASS + 1))` which always returns exit code 0.
- **Root cause**: Bash arithmetic treats 0 as falsy, unlike most languages.


## COE-009: Data contract shipped without ADR, CHANGELOG, or architecture update

- **Date**: 2026-05-04
- **Severity**: Governance
- **Found in**: commit `13146d3` (feat(contract): data contract)
- **Description**: The data contract was committed without ADR, CHANGELOG update, design document update, or Agent Builder integration design.
- **Fix**: Created ADR-010, updated CHANGELOG, design document ADR list, README ADR count. Added Agent Builder integration to ADR-010.
- **Root cause**: Committed without running the documentation checklist. DoD gate was not applied.
