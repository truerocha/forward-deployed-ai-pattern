---
inclusion: manual
---

# Forward Deployed Engineer — Enterprise ALM Context

> Activation: provide `#fde-enterprise` in chat to load this context.
> Requires: MCP powers configured for GitHub/GitLab/Asana.

## Enterprise Personas

When Enterprise hooks fire, the agent assumes a persona with a defined output contract:

| Persona | Hook | Output Contract |
|---------|------|-----------------|
| Product Owner | fde-enterprise-backlog | Issues updated, tech-debt tickets created |
| Tech Writer | fde-enterprise-docs | ADR generated, hindsight note created |
| Release Manager | fde-enterprise-release | Semantic commit, MR opened, ALM updated |

## ALM Integration Rules

- Agent reads issues/tasks via MCP to understand context
- Agent updates issue status after task completion
- Agent creates tech-debt issues for out-of-scope items (labeled 'tech-debt')
- Agent NEVER closes issues — human closes after MR merge
- Agent NEVER modifies issue priority or assignment

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
issue: "#123"
level: L3
---
```

The DoR gate checks for `status: ready` before allowing execution.
If absent or not `ready`, the agent reports and waits for human approval.
