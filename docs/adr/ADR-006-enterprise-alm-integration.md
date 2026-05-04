# ADR-006: Enterprise ALM Integration via MCP

## Status
Accepted

## Context
Enterprise development requires traceability between code changes and work items (issues, tasks, epics). Manual synchronization between the IDE and ALM systems (GitHub Issues, Asana, GitLab) creates friction and breaks audit trails.

## Decision
The factory integrates with ALM systems through MCP (Model Context Protocol) powers:
- GitHub MCP for issues, PRs, Actions status
- GitLab MCP for MRs, pipelines (via mirror)
- Asana MCP for tasks, projects, status updates

Three Enterprise hooks automate ALM interaction:
1. **Backlog Sync** (postTaskExecution): Updates issue status, creates tech-debt tickets
2. **Docs Generator** (postTaskExecution): Creates ADRs, generates hindsight notes
3. **Release Manager** (userTriggered): Semantic commit, opens MR, updates ALM

## Consequences
- Agent can read and update ALM systems but NEVER closes issues or merges MRs
- Tech-debt discovered during implementation is captured as new issues (not ignored)
- All hooks degrade gracefully if MCP is not configured (skip silently)
- Credentials are managed via environment variables, never stored in code
