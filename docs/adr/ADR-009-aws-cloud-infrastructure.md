# ADR-009: AWS Cloud Infrastructure for Headless Agent Execution

## Status
Accepted

## Date
2026-05-04

## Context
The Autonomous Code Factory initially operated entirely on the Staff Engineer's local machine via Kiro IDE. This creates a dependency on the local machine being available and running. For enterprise adoption, the factory needs to run headless — agents executing tasks on cloud infrastructure without requiring the Staff Engineer's machine to be online.

Additionally, the onboarding process required manual steps that were error-prone. A structured pipeline was needed to validate prerequisites, collect configuration, and deploy infrastructure automatically.

## Decision

### Cloud Infrastructure (Terraform IaC)
The factory deploys to AWS using Terraform with these components:

| Component | AWS Service | Purpose |
|-----------|------------|---------|
| Agent Runtime | ECS Fargate | Headless agent execution (no local machine needed) |
| Agent Image | ECR | Container registry for Strands agent Docker images |
| LLM Inference | Amazon Bedrock | Foundation model access for agent reasoning |
| Agent Orchestration | AgentCore Runtime (optional) | Multi-agent coordination |
| Artifact Storage | S3 | Factory specs, notes, reports, completion artifacts |
| Credential Storage | Secrets Manager | ALM tokens (GitHub, Asana, GitLab) |
| Observability | CloudWatch Logs | Agent execution logs |
| Networking | VPC + NAT Gateway | Private subnets for ECS tasks with outbound access |

### Onboarding Pipeline (Three Scripts)
1. `pre-flight-fde.sh` — Validates tools, credentials (including AWS SSO/profile), IAM permissions, collects project config
2. `validate-deploy-fde.sh` — Validates four planes: Control (Kiro), Data (ALM APIs), FDE (MCP/hooks), Cloud (AWS)
3. `code-factory-setup.sh` — Deploys everything: global infra, per-project workspaces, AWS cloud (Terraform + Docker + Secrets)

### AWS Authentication
Scripts support AWS SSO, named profiles, and environment variables. The profile is stored in the manifest and passed to all `aws` CLI and `terraform` calls.

### Linter Mode
All scripts collect all issues and report with remediation instructions, rather than failing on the first error.

## Consequences
- Factory can run headless on AWS — no dependency on local machine
- Terraform IaC makes infrastructure reproducible and version-controlled
- Cloud deployment is opt-in — local-only mode remains the default
- Human confirms before any AWS resource creation
- Secrets never stored in code — ALM tokens go to Secrets Manager

## Related
- ADR-006: Enterprise ALM Integration via MCP
- ADR-008: Multi-Platform Project Tooling
- Flow: `docs/flows/12-staff-engineer-onboarding.md`
- COE-005: Missing ADR documented in corrections-of-error.md
