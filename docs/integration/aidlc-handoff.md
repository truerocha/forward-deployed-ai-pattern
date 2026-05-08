# AI-DLC → Factory Handoff Integration Guide

> Activity 5.02 — How AI-DLC SharedState artifacts flow into the Autonomous Code Factory.

---

## Overview

The AI-DLC (AI Development Lifecycle) system produces **SharedState artifacts** — structured JSON documents that describe tasks, acceptance criteria, dependencies, and context. The factory's `AIDLCAdapter` reads these artifacts from S3 and converts them into the internal `FactorySpec` format consumed by the orchestrator.

This integration is **one-directional**: AI-DLC → Factory. The factory does not write back to AI-DLC's S3 prefix.

---

## Architecture

```
┌─────────────┐         ┌──────────────────┐         ┌─────────────────┐
│   AI-DLC    │  write   │   S3 Bucket      │  read    │  FDE Factory    │
│  Pipeline   │ ───────► │  shared-state/   │ ◄─────── │  AIDLCAdapter   │
└─────────────┘         └──────────────────┘         └─────────────────┘
                                                              │
                                                              ▼
                                                     ┌─────────────────┐
                                                     │  Orchestrator   │
                                                     │  (FactorySpec)  │
                                                     └─────────────────┘
```

---

## S3 Prefix Convention

AI-DLC artifacts must be stored under a predictable S3 prefix:

```
s3://{bucket}/{prefix}/{project_id}/shared-state/
├── task-{uuid-1}.json
├── task-{uuid-2}.json
├── task-{uuid-3}.json
└── manifest.json          (optional — lists all task IDs)
```

### Naming Rules

| Element | Format | Example |
|---------|--------|---------|
| Bucket | Org-specific | `aidlc-artifacts-prod` |
| Prefix | Configurable | `shared-state` |
| Project ID | Factory project ID | `PROJ-123` |
| Task file | `task-{uuid}.json` | `task-a1b2c3d4.json` |
| Manifest | `manifest.json` | `manifest.json` |

---

## Schema Versions

### v1.0 — Original Format

```json
{
  "schema_version": "1.0",
  "shared_state": {
    "task_id": "TASK-001",
    "description": "Implement user authentication flow",
    "user_value": "As a user, I want to log in securely so that my data is protected",
    "acceptance_criteria": "User can log in with email and password",
    "dependencies": ["auth-service", "user-db"],
    "priority": "high",
    "tags": ["security", "auth"]
  }
}
```

**Notes:**
- `acceptance_criteria` is a single string in v1.0
- `user_value` may be in `description` or `objective` fields as fallback

### v1.1 — Extended Format

```json
{
  "schema_version": "1.1",
  "shared_state": {
    "task_id": "TASK-002",
    "user_story": "As a developer, I want automated test generation",
    "user_value": "Reduce manual test writing time by 80%",
    "acceptance_criteria": [
      {"description": "Unit tests generated for all public methods", "priority": "must"},
      {"description": "Test coverage above 80%", "priority": "should"},
      {"description": "Tests pass on first run", "priority": "must"}
    ],
    "dependencies": ["test-framework", "code-parser"],
    "priority": "medium",
    "tags": ["testing", "automation"],
    "technical_context": {
      "language": "python",
      "framework": "pytest",
      "existing_coverage": 45
    },
    "constraints": ["No external API calls in tests", "Must run in < 30s"]
  }
}
```

**Notes:**
- `acceptance_criteria` is a structured array with `description` and optional `priority`
- `technical_context` provides implementation hints
- `constraints` lists hard requirements

---

## Error Handling

### Unsupported Schema Version

If an artifact has a `schema_version` not in `{1.0, 1.1}`, the adapter raises `AIDLCSchemaError` with a clear message:

```
AIDLCSchemaError: Unsupported AI-DLC schema version '2.0'.
Supported versions: ['1.0', '1.1'].
Please update the AI-DLC adapter or downgrade the artifact schema.
```

**Resolution:** Either update the adapter to support the new version, or ask the AI-DLC team to produce artifacts in a supported version.

### Missing Schema Version

If `schema_version` is missing from the artifact, the adapter raises `AIDLCSchemaError` with version `<missing>`.

### S3 Access Errors

- **NoSuchKey**: Logged as warning, artifact skipped (returns None)
- **AccessDenied**: Logged as error, artifact skipped
- **JSON parse error**: Logged as error, artifact skipped

The adapter is resilient — individual artifact failures do not block processing of other artifacts.

### Feature Flag Disabled

If `ENABLE_AIDLC_ADAPTER=false` (default), calling `fetch_and_convert()` raises `AIDLCAdapterDisabledError` with instructions to enable.

---

## Feature Flag Activation

### 1. Set the Environment Variable

In your ECS task definition (Terraform):

```hcl
{ name = "ENABLE_AIDLC_ADAPTER", value = "true" }
```

Or for testing via CLI override:

```bash
aws ecs run-task --overrides '{
  "containerOverrides": [{
    "name": "orchestrator",
    "environment": [{"name": "ENABLE_AIDLC_ADAPTER", "value": "true"}]
  }]
}'
```

### 2. Configure S3 Access

Ensure the ECS task role has read access to the AI-DLC bucket:

```json
{
  "Effect": "Allow",
  "Action": ["s3:GetObject", "s3:ListBucket"],
  "Resource": [
    "arn:aws:s3:::aidlc-artifacts-prod",
    "arn:aws:s3:::aidlc-artifacts-prod/*"
  ]
}
```

### 3. Configure the Adapter

The adapter is instantiated by the orchestrator with project-specific configuration:

```python
from src.integrations.aidlc import AIDLCAdapter

adapter = AIDLCAdapter(
    project_id="PROJ-123",
    s3_bucket="aidlc-artifacts-prod",
    s3_prefix="shared-state",
)

specs = adapter.fetch_and_convert()
```

---

## Conversion Mapping

| AI-DLC Field | Factory FactorySpec Field | Notes |
|--------------|--------------------------|-------|
| `task_id` / `id` | `task_id` | Falls back to generated ID |
| `user_value` / `description` / `objective` | `user_value` | Priority order for fallback |
| `acceptance_criteria` | `acceptance_criteria` | String→list in v1.0, array in v1.1 |
| `dependencies`, `priority`, `tags` | `context` | Bundled into context dict |
| `technical_context` (v1.1) | `context.technical_context` | Implementation hints |
| `constraints` (v1.1) | `context.constraints` | Hard requirements |

---

## Monitoring

The adapter logs at these levels:

| Level | What |
|-------|------|
| `INFO` | Successful batch conversion (count + project) |
| `WARNING` | Feature flag disabled, missing artifacts |
| `ERROR` | S3 access failures, JSON parse errors |
| `DEBUG` | Artifact listing counts, individual conversions |

CloudWatch log group: `/ecs/fde-orchestrator`

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `AIDLCAdapterDisabledError` | Feature flag off | Set `ENABLE_AIDLC_ADAPTER=true` |
| `AIDLCSchemaError` | Version mismatch | Update adapter or artifact version |
| Empty specs list | No artifacts in S3 | Check S3 prefix and permissions |
| `AccessDenied` in logs | IAM policy missing | Add S3 read permissions to task role |
