# Plane 1: Version Source Management

> Diagram: `docs/architecture/planes/01-vsm-plane.png`
> Components: Project Isolation, ALM Platforms, Delivery (PR/MR)
> ADRs: ADR-006, ADR-008, ADR-011

## Purpose

The Version Source Management (VSM) Plane manages where code lives and how it flows between the Staff Engineer and the Code Factory. It provides three guarantees:

1. Every task runs in an isolated namespace (zero cross-project interference)
2. Every code change lives on a feature branch (main is never touched)
3. Every delivery goes through a PR/MR that the human approves

## Components

| Component | Module | Owned State | Responsibility |
|-----------|--------|-------------|----------------|
| Project Isolation | `project_isolation.py` | ProjectContext (frozen dataclass) | Creates isolated S3 prefix, workspace dir, branch name, correlation ID per task |
| ALM Platforms | `router.py` (extraction) | Data contract fields | Extracts canonical data contract from GitHub issue forms, GitLab scoped labels, Asana custom fields |
| Delivery | Orchestrator + MCP tools | PR/MR metadata | Opens PR/MR on the correct platform with structured body, syncs status back to ALM |

## Interfaces

| From | To | Data Transferred |
|------|-----|-----------------|
| Staff Engineer | ALM Platform | Task created with issue template fields |
| ALM Platform | Router | EventBridge event with platform-specific payload |
| Router | Project Isolation | Data contract dict → ProjectContext |
| Project Isolation | All downstream | Scoped S3 keys, workspace path, branch name |
| Orchestrator | ALM Platform | PR opened, status comment posted |

## Isolation Boundaries

| Boundary | Mechanism | Enforcement |
|----------|-----------|-------------|
| Process | Each EventBridge event spawns a new ECS Fargate task | Terraform: `task_count = 1` per event |
| Filesystem | `/tmp/workspace/{task_id}` | `project_isolation.scoped_workspace()` |
| Storage | `s3://{bucket}/projects/{task_id}/...` | `project_isolation.scoped_s3_key()` |
| Git | Branch `fde/{task_id}/{sanitized-title}` | `project_isolation.create_project_context()` |
| Memory | Transient agent definitions scoped to task_id | Agent Builder registers `{role}-{task_id}` |
| Tracing | Unique `correlation_id` per task | `COR-{uuid}` in ProjectContext |

## Governance Rules

- The factory NEVER works on main or master branches
- The factory NEVER merges PRs — the human approves and merges
- The factory NEVER modifies issue priority or assignment
- The factory NEVER closes issues — the human closes after merge
- Cross-platform references are linked through comments (Asana task → GitHub PR)

## Supported Platforms

| Platform | Event Source | Template | Status |
|----------|-------------|----------|--------|
| GitHub Projects | `fde.github.webhook` | `.github/ISSUE_TEMPLATE/factory-task.yml` | Active |
| GitLab Ultimate | `fde.gitlab.webhook` | `.gitlab/issue_templates/factory-task.md` | Available (token required) |
| Asana | `fde.asana.webhook` | Custom fields mapped to contract | Available (token required) |
| Direct (CLI/Kiro) | `fde.direct` | Spec file with frontmatter | Active |

## Related Artifacts

- ADR-006: Enterprise ALM Integration
- ADR-008: Multi-Platform Project Tooling
- Flow 11: Multi-Platform Work Intake
- Schema: `docs/templates/canonical-task-schema.yaml`
