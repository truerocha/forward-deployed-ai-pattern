# ADR-005: Multi-Workspace Factory Topology

## Status
Accepted

## Context
The Staff Engineer manages 3+ projects simultaneously. Each project is a separate codebase with its own architecture, test infrastructure, and quality standards. The factory must support parallel operation without cross-contamination.

## Decision
This design adopts a distributed topology where:
- Each project is a separate Kiro workspace with its own `.kiro/` directory
- Global laws (`~/.kiro/steering/`) are inherited by all workspaces via auto inclusion
- Global credentials (`~/.kiro/settings/mcp.json`) are shared across workspaces
- Cross-project knowledge flows through `~/.kiro/notes/shared/` (filesystem-based, not Kiro-native)
- Factory state (`~/.kiro/factory-state.md`) is human-maintained
- New projects are onboarded via `scripts/provision-workspace.sh --project`

## Consequences
- Workspaces are isolated — one project's hooks and specs do not affect another
- Global steerings enforce universal laws (TDD mandate, adversarial protocol) across all projects
- Cross-workspace knowledge sharing relies on filesystem access, not a Kiro-native primitive
- Factory state requires human maintenance (future: Strands coordinator agent)
