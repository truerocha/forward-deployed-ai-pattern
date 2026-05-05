# Multi-Platform Work Intake Flow

How work enters the factory from GitHub Projects, Asana, and GitLab Ultimate boards.

```mermaid
flowchart TD
    subgraph Boards["ALM Boards (Human Domain)"]
        GH[GitHub Projects Board]
        AS[Asana Board]
        GL[GitLab Issue Board]
    end

    subgraph Trigger["Trigger (Human Action)"]
        MOVE["Human moves item to\n'In Progress'"]
        FIRE["Human triggers\nfde-work-intake hook"]
    end

    subgraph Intake["Factory Intake (Agent Domain)"]
        SCAN["Scan all configured\nMCP platforms"]
        MAP["Map to canonical\ntask schema"]
        SPEC["Create/locate\nspec file"]
        DOR["DoR Gate validates\nspec readiness"]
    end

    subgraph Pipeline["FDE Pipeline"]
        RECON["Phase 1: Reconnaissance"]
        TASK["Phase 2: Task Intake"]
        ENG["Phase 3: Engineering"]
        COMP["Phase 4: Completion"]
    end

    subgraph Sync["Status Sync (Agent → Board)"]
        UPDATE["Update board status\nvia MCP"]
        MR["Open MR/PR\nvia MCP"]
        REVIEW["Move to 'In Review'\non board"]
    end

    GH --> MOVE
    AS --> MOVE
    GL --> MOVE
    MOVE --> FIRE
    FIRE --> SCAN
    SCAN --> MAP
    MAP --> SPEC
    SPEC --> DOR
    DOR -->|Ready| RECON
    DOR -->|Not Ready| MOVE
    RECON --> TASK
    TASK --> ENG
    ENG --> COMP
    COMP --> UPDATE
    UPDATE --> MR
    MR --> REVIEW
```

## Platform Adapter Mapping

```mermaid
flowchart LR
    subgraph GitHub
        GH_ISSUE[Issue #123] --> GH_MAP["id: GH-123\nsource: github\nstatus: Project field"]
    end

    subgraph Asana
        AS_TASK[Task abc123] --> AS_MAP["id: ASANA-abc123\nsource: asana\nstatus: Section name"]
    end

    subgraph GitLab
        GL_ISSUE[Issue !456] --> GL_MAP["id: GL-456\nsource: gitlab\nstatus: Board list"]
    end

    GH_MAP --> CANONICAL["Canonical Task Schema\n(docs/templates/canonical-task-schema.yaml)"]
    AS_MAP --> CANONICAL
    GL_MAP --> CANONICAL
    CANONICAL --> SPEC[".kiro/specs/{id}-{slug}.md"]
```

## API Validation Pre-Flight

Before enabling the work intake hook, validate API access:

```bash
# Validate all platforms
bash scripts/validate-alm-api.sh --all

# Validate individual platforms
bash scripts/validate-alm-api.sh --github
bash scripts/validate-alm-api.sh --asana
bash scripts/validate-alm-api.sh --gitlab
```

## Environment Variables

| Variable | Platform | Required Scopes |
|----------|----------|----------------|
| `GITHUB_TOKEN` | GitHub | `repo`, `project` |
| `ASANA_ACCESS_TOKEN` | Asana | Full access PAT |
| `GITLAB_TOKEN` | GitLab | `api` scope |
| `GITLAB_URL` | GitLab | N/A (default: gitlab.com) |
| `GITLAB_PROJECT_ID` | GitLab | N/A (project ID for board access) |

## Related
- Hook: [`fde-work-intake`](../../.kiro/hooks/fde-work-intake.kiro.hook)
- Hook: [`fde-enterprise-backlog`](../../.kiro/hooks/fde-enterprise-backlog.kiro.hook)
- ADR: [ADR-008 Multi-Platform Project Tooling](../adr/ADR-008-multi-platform-project-tooling.md)
- Schema: [Canonical Task Schema](../templates/canonical-task-schema.yaml)
- Templates: [GitHub](../templates/task-template-github.md) | [Asana](../templates/task-template-asana.md) | [GitLab](../templates/task-template-gitlab.md)
