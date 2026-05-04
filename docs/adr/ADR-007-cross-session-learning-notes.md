# ADR-007: Cross-Session Learning via Hindsight Notes

## Status
Accepted

## Context
Each agent session starts from zero context. Insights discovered in one task (error patterns, architectural decisions, tool conventions) are lost when the session ends. The CCA paper (Wong et al., 2026) demonstrated that persistent notes reduce iteration turns by 5% and improve resolve rate by 1.4%.

## Decision
This design implements a note-taking system with:
- Structured format: YAML frontmatter (id, title, verification status, date) + Context + Insight + Anti-patterns
- Two scopes: project-specific (`.kiro/notes/project/`) and cross-project (`~/.kiro/notes/shared/`)
- Verification status: TESTED (from PASS tasks) or UNTESTED (from PARTIAL tasks)
- Date-based decay: notes older than 90 days without PINNED tag are archived by consolidation hook
- Adversarial gate includes a question about note applicability when prior notes are used

## Consequences
- Knowledge accumulates across sessions instead of being rediscovered
- Generic insights benefit all projects (shared notes)
- Decay prevents unbounded accumulation (90-day archival)
- Anti-patterns section in each note prevents misapplication to wrong contexts
