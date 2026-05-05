# Plane 4: Data

> Diagram: `docs/architecture/planes/04-data-plane.png`
> Components: Router, Task Queue, Artifact Storage, EventBridge
> ADRs: ADR-009, ADR-010

## Purpose

The Data Plane manages the flow of structured data through the factory. It routes events from ALM platforms, queues tasks with dependency resolution, and stores all artifacts (specs, results, reports, metrics) in versioned S3 storage.

## Components

| Component | Module | Owned State | Responsibility |
|-----------|--------|-------------|----------------|
| Router | `router.py` | RoutingDecision + data_contract | Receives EventBridge events, extracts canonical data contract from platform payloads, determines which agent handles the task |
| Task Queue | `task_queue.py` | DynamoDB table (task_id, status, priority, depends_on) | Priority-ordered queue with DAG dependency resolution. Optimistic locking for task claims. Automatic promotion when dependencies complete. |
| Artifact Storage | S3 bucket | Specs, results, reports, metrics | Versioned, KMS-encrypted, public-access-blocked. Partitioned by `projects/{task_id}/` for isolation. |
| EventBridge | `eventbridge.tf` | Custom event bus + 3 rules | Routes ALM webhook events to ECS Fargate tasks. Input transformer passes event payload as container environment variable. |

## Data Contract

The data contract is the single source of truth for what an agent needs. Every component in the factory reads from it:

| Consumer | Fields Read |
|----------|-------------|
| Router | source, type (for routing decision) |
| Constraint Extractor | constraints, related_docs, tech_stack |
| Agent Builder | tech_stack, type, constraints (extracted) |
| Autonomy Resolution | type, level, autonomy_level (override) |
| Scope Boundaries | acceptance_criteria, tech_stack, description |
| Task Queue | task_id, status, depends_on, priority |
| DORA Metrics | tech_stack (for domain segmentation) |

## Task Lifecycle

```
PENDING → READY → IN_PROGRESS → COMPLETED
                              → BLOCKED (dependency not met)
```

- A task is READY when all `depends_on` tasks are COMPLETED
- Priority ordering: P0 > P1 > P2 > P3 (within READY tasks)
- Optimistic locking prevents double-claiming

## Storage Layout

```
s3://{bucket}/
  projects/{task_id}/
    spec.md
    results/{agent}-result.md
    extraction/constraint-report.json
  reports/factory-health/{timestamp}.json
  metrics/{date}/{metric_type}/{metric_id}.json
```

## Interfaces

| From | To | Data |
|------|-----|------|
| ALM Webhooks | EventBridge | Platform-specific event payload |
| EventBridge | Router (via ECS) | Structured event with source, detail-type, detail |
| Router | Task Queue | Enqueue with data contract fields |
| Router | Orchestrator | RoutingDecision with data_contract dict |
| All agents | S3 | Artifacts written via `write_artifact` tool |

## Related Artifacts

- ADR-009: AWS Cloud Infrastructure
- ADR-010: Data Contract for Task Input
- Design: `docs/design/data-contract-task-input.md`
- Terraform: `infra/terraform/eventbridge.tf`, `dynamodb.tf`
