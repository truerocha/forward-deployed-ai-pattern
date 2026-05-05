# ADR-010: Data Contract for Task Input

## Status
Accepted

## Date
2026-05-04

## Context
The Code Factory receives work items from three ALM platforms with different field structures. Agents need a consistent, well-scoped input. Without a formal data contract, agents guess at boundaries and the Agent Builder cannot provision specialized agents.

## Decision

### Formal Data Contract
Every task must conform to a contract with three field categories:
1. **Required** (agent cannot start without): title, description, type, priority, level, source, acceptance_criteria, tech_stack
2. **Optional** (agent uses if present, infers if absent): spec_path, depends_on, repo, constraints, related_docs, target_environment
3. **Agent-populated** (set during execution): task_id, status, assigned_agent, prompt_version, prompt_hash, result

### Platform-Specific Issue Templates
- GitHub: `.github/ISSUE_TEMPLATE/factory-task.yml` (YAML issue form)
- GitLab: `.gitlab/issue_templates/factory-task.md` (markdown with scoped labels)
- Asana: Custom fields mapped to the contract

### Agent Builder Integration
The data contract's `tech_stack` and `type` fields drive just-in-time agent provisioning:
- `tech_stack: [Python, FastAPI]` → Python-specific prompt, FastAPI tools
- `tech_stack: [Terraform, AWS]` → IaC prompt, Terraform tools
- `type: bugfix` → Skip Reconnaissance, diagnostic tools
- `type: infrastructure` → IaC-specialized agent with cloud provider tools

### Validation Gates
- DoR Gate validates required fields before agent starts
- Task Queue validates dependencies and priority ordering
- Lifecycle Manager validates prompt integrity (hash check)

## Consequences
- All agents consume a consistent input regardless of source platform
- Agent Builder provisions specialized agents based on tech_stack and type
- Prompt Registry selects context-appropriate prompts using tech_stack as context tags
- Staff Engineers get structured templates that prevent incomplete submissions
- The data contract is the single source of truth for what an agent needs

## Related
- ADR-008: Multi-Platform Project Tooling
- ADR-009: AWS Cloud Infrastructure
- Design: `docs/design/data-contract-task-input.md`
