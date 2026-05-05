# ADR-011: Multi-Cloud Adapter — Deferred Until Demand

## Status
Accepted

## Date
2026-05-04

## Context
The data contract includes a `target_environment` field (aws / azure / gcp / on-prem) designed to drive a Multi-cloud Adapter using the Strategy Pattern with provider-specific Terraform modules.

### Adversarial Analysis

**Position A — Build the adapter now:**
- The field already exists in the data contract and GitHub issue template
- Building the adapter now prevents lock-in to AWS-specific patterns
- Customers in regulated industries may require multi-cloud from day one

**Position B — Defer until demand exists (selected):**
- Current factory users operate exclusively on AWS (ECS Fargate, Bedrock, DynamoDB, S3, EventBridge)
- No customer has requested Azure or GCP support
- Building an abstraction layer without a second consumer creates untested code
- The Strategy Pattern adapter would add ~500 lines of code with zero test coverage against real cloud APIs
- The `target_environment` field in the data contract is preserved — the adapter can be built when the second cloud provider is needed without breaking the contract

### Cost of Deferral
- If a customer needs Azure, the adapter takes ~2 days to build because the data contract already carries `target_environment`
- The Terraform module structure (`infra/terraform/modules/`) already supports pluggable modules
- No architectural debt is created by deferring

### Cost of Building Now
- ~500 lines of untested abstraction code
- Maintenance burden on every Terraform change (must update N providers)
- False confidence in multi-cloud support that has never been validated against real Azure/GCP APIs

## Decision
Defer the Multi-cloud Adapter until a real customer requires a second cloud provider. The `target_environment` field remains in the data contract as a forward-compatible extension point. No adapter code is written until there is a concrete consumer.

## Trigger to Revisit
- A customer requests Azure or GCP deployment
- The factory is deployed in a regulated environment requiring multi-cloud DR
- `target_environment` values other than "aws" appear in DORA metrics

## Consequences
- The data contract remains stable (no field removal)
- No dead code in the codebase
- The Orchestrator does not reference a Multi-cloud Adapter
- When the adapter is needed, it reads `target_environment` from the same data contract all other components use

## Related
- ADR-009: AWS Cloud Infrastructure
- ADR-010: Data Contract for Task Input
- Design: `docs/design/data-contract-task-input.md`
