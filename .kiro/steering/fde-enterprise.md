---
inclusion: manual
---

# Forward Deployed Engineer — Enterprise ALM Context

> Activation: provide `#fde-enterprise` in chat to load this context.
> Requires: MCP powers configured for GitHub/GitLab/Asana.
> Validate: `bash scripts/validate-alm-api.sh --all`

## Enterprise Personas

When Enterprise hooks fire, the agent assumes a persona with a defined output contract:

| Persona | Hook | Output Contract |
|---------|------|-----------------|
| Factory Dispatcher | fde-work-intake | Scans boards, creates specs, starts pipeline |
| Product Owner | fde-enterprise-backlog | Issues updated, tech-debt tickets created |
| Tech Writer | fde-enterprise-docs | ADR generated, hindsight note created |
| Release Manager | fde-enterprise-release | Semantic commit, MR opened, ALM updated |

## Multi-Platform Support

The factory supports three ALM platforms simultaneously. Each platform maps to the canonical task schema defined in `docs/templates/canonical-task-schema.yaml`.

| Platform | MCP Server | Status | Task Templates |
|----------|-----------|--------|---------------|
| GitHub Projects | `@modelcontextprotocol/server-github` | Active | `docs/templates/task-template-github.md` |
| Asana | `asana-mcp-server` | Disabled (enable after token setup) | `docs/templates/task-template-asana.md` |
| GitLab Ultimate | `@modelcontextprotocol/server-gitlab` | Disabled (enable after token setup) | `docs/templates/task-template-gitlab.md` |

## Work Intake Flow — Board to Factory

1. Human creates items on any board using the platform task template
2. Human moves item to "In Progress" on the board
3. Human triggers `fde-work-intake` hook in Kiro
4. Agent scans all configured platforms for "In Progress" items
5. Agent maps items to canonical schema and creates spec files
6. DoR gate validates spec readiness
7. FDE pipeline starts (Phase 1 → 2 → 3 → 4)
8. Agent syncs status back to originating platform via `fde-enterprise-backlog`
9. Agent opens MR/PR and moves item to "In Review" via `fde-enterprise-release`

## ALM Integration Rules

- Agent reads issues/tasks via MCP to understand context
- Agent updates issue status after task completion
- Agent creates tech-debt issues for out-of-scope items (labeled 'tech-debt')
- Agent NEVER closes issues — human closes after MR merge
- Agent NEVER modifies issue priority or assignment
- Agent syncs status to the originating platform (reads 'source:' from spec frontmatter)
- Cross-platform references are linked via comments (e.g., Asana task → GitHub PR)

## Delivery Rules

- Agent ALWAYS works on feature branches (never main)
- Agent pushes with `-u` flag to set tracking
- Agent opens MR/PR via MCP with structured body (summary, spec ref, validation results)
- Agent NEVER merges — human approves outcomes
- Agent NEVER deploys to production

## Spec READY Mechanism

Specs use YAML frontmatter to indicate lifecycle status:

```yaml
---
status: ready
issue: "GH-123"        # or "ASANA-456" or "GL-789"
level: L3
source: github          # github | asana | gitlab
---
```

The DoR gate checks for `status: ready` before allowing execution.
If absent or not `ready`, the agent reports and waits for human approval.

## API Validation

Before enabling enterprise hooks, validate API access:

```bash
bash scripts/validate-alm-api.sh --all
```

Required environment variables:
- `GITHUB_TOKEN` — GitHub PAT with `repo` + `project` scopes
- `ASANA_ACCESS_TOKEN` — Asana Personal Access Token
- `GITLAB_TOKEN` — GitLab PAT with `api` scope
- `GITLAB_URL` — GitLab instance URL (default: gitlab.com)

## Related Artifacts

- ADR: `docs/adr/ADR-006-enterprise-alm-integration.md`
- ADR: `docs/adr/ADR-008-multi-platform-project-tooling.md`
- Flow: `docs/flows/11-multi-platform-intake.md`
- Schema: `docs/templates/canonical-task-schema.yaml`
- Validation: `scripts/validate-alm-api.sh`


## Cloud Deployment Context

When AWS cloud infrastructure is deployed, the factory operates headless via EventBridge orchestration.

### Webhook URLs (from Terraform outputs)

| Platform | Endpoint | Events |
|----------|----------|--------|
| GitHub | `POST /webhook/github` | `issue.labeled` with `factory-ready` |
| GitLab | `POST /webhook/gitlab` | `issue.updated` with action `update` |
| Asana | `POST /webhook/asana` | `task.moved` to In Progress |

### Agent Pipeline (ECS Fargate)

| Agent | FDE Phase | Strands Tools |
|-------|-----------|---------------|
| Reconnaissance | Phase 1 | read_spec, run_shell_command |
| Engineering | Phases 2-3 | read_spec, write_artifact, run_shell_command, ALM update tools |
| Reporting | Phase 4 | write_artifact, ALM update tools |

### Cloud Resources

| Resource | Name Pattern | Purpose |
|----------|-------------|---------|
| EventBridge Bus | `fde-{env}-factory-bus` | Routes ALM events to ECS |
| ECS Cluster | `fde-{env}-cluster` | Runs Strands agent tasks |
| ECR Repository | `fde-{env}-strands-agent` | Agent Docker images |
| S3 Bucket | `fde-{env}-artifacts-{account}` | Specs, results, reports |
| Secrets Manager | `fde-{env}/alm-tokens` | GitHub, Asana, GitLab tokens |

### Validation and Teardown

```bash
bash scripts/validate-e2e-cloud.sh --profile profile-name
bash scripts/teardown-fde.sh --terraform
bash scripts/teardown-fde.sh --dry-run
```

- Flow: `docs/flows/13-cloud-orchestration.md`
- ADR: `docs/adr/ADR-009-aws-cloud-infrastructure.md`
