"""
Squad Context — Shared Context Document for multi-agent collaboration.

Instead of RAG or vector stores, the squad uses a structured in-memory
document that each agent reads from and writes to. This avoids:
- Token explosion (each agent only reads relevant sections)
- Context loss (structured sections persist across agent hand-offs)
- Latency (no embedding/retrieval overhead)

The SCD lives in memory for the duration of a single task execution.
It is NOT persisted to DynamoDB or S3 — it's ephemeral by design.

Design ref: ADR-019 (Agentic Squad Architecture)
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("fde.squad_context")

# Maximum chars per section in SCD (controls INPUT to next agents, not OUTPUT)
# This is a SLIDING WINDOW — each agent's full output goes to S3 untruncated.
# Only the SCD summary (passed to subsequent agents) is windowed.
# Strategy: most recent content wins. If section exceeds window, older entries are dropped.
_MAX_SECTION_CHARS = 4000
_MAX_TOTAL_INPUT_CHARS = 12000  # Max total context any single agent receives from SCD

# Sections that each agent role is allowed to READ
_READ_PERMISSIONS: dict[str, list[str]] = {
    "task-intake-eval-agent": [],
    "swe-issue-code-reader-agent": ["task_intake"],
    "swe-code-context-agent": ["task_intake"],
    "swe-architect-agent": ["task_intake", "code_context"],
    "architect-standard-agent": ["task_intake", "code_context", "architecture"],
    "swe-developer-agent": ["task_intake", "architecture", "code_context"],
    "code-ops-agent": ["task_intake", "implementation"],
    "code-sec-agent": ["task_intake", "implementation"],
    "code-rel-agent": ["task_intake", "implementation"],
    "code-perf-agent": ["task_intake", "implementation"],
    "code-cost-agent": ["task_intake", "implementation"],
    "code-sus-agent": ["task_intake", "implementation"],
    "reviewer-security-agent": ["task_intake", "implementation", "waf_review"],
    "swe-code-quality-agent": ["task_intake", "implementation"],
    "swe-adversarial-agent": ["task_intake", "implementation", "quality"],
    "swe-redteam-agent": ["task_intake", "implementation", "waf_review"],
    "fde-code-reasoning": ["task_intake", "code_context", "implementation"],
    "swe-tech-writer-agent": ["task_intake", "implementation", "waf_review", "quality"],
    "swe-dtl-commiter-agent": ["task_intake", "implementation"],
    "reporting-agent": ["task_intake", "implementation", "waf_review", "quality", "delivery"],
}

# Sections that each agent role WRITES to
_WRITE_PERMISSIONS: dict[str, str] = {
    "task-intake-eval-agent": "task_intake",
    "swe-issue-code-reader-agent": "code_context",
    "swe-code-context-agent": "code_context",
    "swe-architect-agent": "architecture",
    "architect-standard-agent": "architecture",
    "swe-developer-agent": "implementation",
    "code-ops-agent": "waf_review",
    "code-sec-agent": "waf_review",
    "code-rel-agent": "waf_review",
    "code-perf-agent": "waf_review",
    "code-cost-agent": "waf_review",
    "code-sus-agent": "waf_review",
    "reviewer-security-agent": "waf_review",
    "swe-code-quality-agent": "quality",
    "swe-adversarial-agent": "quality",
    "swe-redteam-agent": "quality",
    "fde-code-reasoning": "implementation",
    "swe-tech-writer-agent": "delivery",
    "swe-dtl-commiter-agent": "delivery",
    "reporting-agent": "delivery",
}


@dataclass
class SquadContext:
    """Shared Context Document — in-memory, task-scoped.

    Each section is a dict with:
    - agent: which agent wrote it
    - timestamp: when it was written
    - content: the structured output (max _MAX_SECTION_CHARS)
    """

    task_id: str
    sections: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def read_for_agent(self, agent_role: str) -> str:
        """Build the context input for a specific agent based on read permissions.

        Implements SLIDING WINDOW strategy:
        - Each section is capped at _MAX_SECTION_CHARS (most recent content wins)
        - Total input is capped at _MAX_TOTAL_INPUT_CHARS across all sections
        - If total exceeds budget, sections are trimmed proportionally
        - Agent OUTPUT is NEVER capped — only the input context is windowed

        Args:
            agent_role: The agent's role name (e.g., 'swe-developer-agent').

        Returns:
            Formatted context string to prepend to the agent's prompt.
        """
        allowed_sections = _READ_PERMISSIONS.get(agent_role, [])
        if not allowed_sections:
            return ""

        # Collect all section content with per-section window
        section_contents: list[tuple[str, str]] = []
        total_chars = 0

        for section_name in allowed_sections:
            entries = self.sections.get(section_name, [])
            if not entries:
                continue

            # Build section content (most recent entries first for sliding window)
            section_text = ""
            for entry in reversed(entries):
                content = entry.get("content", "")
                agent = entry.get("agent", "unknown")
                chunk = f"**From {agent}:**\n{content}\n"
                if len(section_text) + len(chunk) <= _MAX_SECTION_CHARS:
                    section_text = chunk + section_text  # Prepend to maintain order
                else:
                    # Sliding window: drop older entries, keep most recent
                    break

            if section_text:
                section_contents.append((section_name, section_text))
                total_chars += len(section_text)

        if not section_contents:
            return ""

        # If total exceeds budget, trim from oldest sections first
        if total_chars > _MAX_TOTAL_INPUT_CHARS:
            budget_remaining = _MAX_TOTAL_INPUT_CHARS
            trimmed: list[tuple[str, str]] = []
            for name, text in reversed(section_contents):
                if budget_remaining <= 0:
                    break
                if len(text) <= budget_remaining:
                    trimmed.append((name, text))
                    budget_remaining -= len(text)
                else:
                    trimmed.append((name, text[:budget_remaining] + "\n[...windowed]"))
                    budget_remaining = 0
            section_contents = list(reversed(trimmed))

        # Format output
        parts = ["## Squad Context (from previous agents)\n"]
        for section_name, section_text in section_contents:
            parts.append(f"### {section_name.replace('_', ' ').title()}")
            parts.append(section_text)

        return "\n".join(parts)

    def write_from_agent(self, agent_role: str, content: str) -> None:
        """Write an agent's output summary to its designated SCD section.

        IMPORTANT: This writes a WINDOWED SUMMARY to the SCD for subsequent agents.
        The agent's FULL untruncated output is written to S3 separately by the
        orchestrator (_write_result). The SCD is for inter-agent context passing only.

        Sliding window: if the section already has entries and adding this one
        would exceed _MAX_SECTION_CHARS, the oldest entry is dropped.

        Args:
            agent_role: The agent's role name.
            content: The agent's structured output (will be windowed for SCD).
        """
        section_name = _WRITE_PERMISSIONS.get(agent_role)
        if not section_name:
            logger.warning("Agent %s has no write permission — output discarded", agent_role)
            return

        if section_name not in self.sections:
            self.sections[section_name] = []

        # Window the content for SCD (full output preserved in S3 by orchestrator)
        windowed = content[:_MAX_SECTION_CHARS] if len(content) > _MAX_SECTION_CHARS else content

        self.sections[section_name].append({
            "agent": agent_role,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "content": windowed,
        })

        # Sliding window: if section total exceeds budget, drop oldest entries
        total = sum(len(e.get("content", "")) for e in self.sections[section_name])
        while total > _MAX_SECTION_CHARS * 2 and len(self.sections[section_name]) > 1:
            dropped = self.sections[section_name].pop(0)
            total -= len(dropped.get("content", ""))

        logger.info(
            "SCD write: agent=%s section=%s chars=%d (windowed from %d)",
            agent_role, section_name, len(windowed), len(content),
        )

    def get_summary(self) -> dict:
        """Get a summary of the SCD state (for observability/debugging)."""
        return {
            "task_id": self.task_id,
            "sections": {
                name: {
                    "entries": len(entries),
                    "total_chars": sum(len(e.get("content", "")) for e in entries),
                    "agents": [e.get("agent", "") for e in entries],
                }
                for name, entries in self.sections.items()
            },
            "total_chars": sum(
                sum(len(e.get("content", "")) for e in entries)
                for entries in self.sections.values()
            ),
        }


def create_squad_context(task_id: str) -> SquadContext:
    """Create a new Shared Context Document for a task."""
    ctx = SquadContext(task_id=task_id)
    logger.info("Created Squad Context for task %s", task_id)
    return ctx
