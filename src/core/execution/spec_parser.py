"""
Spec Parser — Extracts atomic execution steps from structured spec_content.

Recognizes patterns commonly found in factory task specs:
  - "#### A1. Title\n```bash\ncommand\n```\n**Gate**: validation"
  - "### Part A: Title\n#### Step 1..."
  - Numbered steps with bash blocks and gate markers

Each ExecutionStep is an atomic unit with:
  - id: step identifier (e.g., "A1", "B1")
  - title: human-readable step description
  - commands: list of shell commands to execute
  - gate: validation command (pytest, assertion, file check)
  - depends_on: list of step IDs that must complete first

Design decisions:
  - Parser is deterministic (no LLM) — operates on textual structure
  - Dependency inference: sequential within a Part, independent across Parts
  - Gate extraction: looks for **Gate**: or **Validation**: markers
  - Commands extracted from ```bash blocks within each step section

Ref: Issue #146 (class of failure: multi-step execution without decomposition)
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ExecutionStep:
    """A single atomic execution step parsed from spec_content."""

    id: str
    title: str
    commands: list[str] = field(default_factory=list)
    gate: str = ""
    depends_on: list[str] = field(default_factory=list)
    part: str = ""  # Which Part this belongs to (A, B, C...)

    def has_gate(self) -> bool:
        return bool(self.gate.strip())

    def has_commands(self) -> bool:
        return bool(self.commands)


def parse_execution_steps(spec_content: str) -> list[ExecutionStep]:
    """Parse structured spec into atomic execution steps.

    Recognizes two primary patterns:

    Pattern 1 — Part/Step structure:
        ### Part A: Title
        #### A1. Step Title
        ```bash
        command1
        command2
        ```
        **Gate**: pytest tests/test_something.py -v

    Pattern 2 — Flat numbered steps:
        #### Step 1: Title
        ```bash
        command
        ```
        **Gate**: validation command

    Dependencies are inferred:
      - Within a Part: sequential (A2 depends on A1, A3 depends on A2)
      - Across Parts: independent (B1 does NOT depend on A4)

    Args:
        spec_content: The full spec markdown content.

    Returns:
        List of ExecutionStep objects in execution order.
    """
    if not spec_content:
        return []

    # Try Part/Step pattern first (more structured)
    steps = _parse_part_step_pattern(spec_content)
    if steps:
        logger.info("Parsed %d execution steps (Part/Step pattern)", len(steps))
        return steps

    # Fallback: flat numbered steps
    steps = _parse_flat_step_pattern(spec_content)
    if steps:
        logger.info("Parsed %d execution steps (flat pattern)", len(steps))
        return steps

    logger.debug("No execution steps found in spec_content")
    return []


def _parse_part_step_pattern(spec_content: str) -> list[ExecutionStep]:
    """Parse Part A/B/C with sub-steps A1, A2, B1, etc."""
    steps: list[ExecutionStep] = []

    # Find all Parts: ### Part A: Title or ### Part A — Title
    part_pattern = r"###\s+Part\s+([A-Z])[\s:—\-]+(.+?)(?=\n)"
    part_matches = list(re.finditer(part_pattern, spec_content))

    if not part_matches:
        return []

    for i, part_match in enumerate(part_matches):
        part_letter = part_match.group(1)
        # Get content between this Part header and the next Part (or end)
        start = part_match.end()
        end = part_matches[i + 1].start() if i + 1 < len(part_matches) else len(spec_content)
        part_content = spec_content[start:end]

        # Find steps within this Part: #### A1. Title or #### A1: Title
        step_pattern = rf"####\s+({part_letter}\d+)[\.\s:—\-]+(.+?)(?=\n)"
        step_matches = list(re.finditer(step_pattern, part_content))

        prev_step_id = ""
        for j, step_match in enumerate(step_matches):
            step_id = step_match.group(1)
            step_title = step_match.group(2).strip()

            # Get content between this step header and the next step (or end of part)
            s_start = step_match.end()
            s_end = step_matches[j + 1].start() if j + 1 < len(step_matches) else len(part_content)
            step_content = part_content[s_start:s_end]

            commands = _extract_bash_commands(step_content)
            gate = _extract_gate(step_content)

            depends = [prev_step_id] if prev_step_id else []

            steps.append(ExecutionStep(
                id=step_id,
                title=step_title,
                commands=commands,
                gate=gate,
                depends_on=depends,
                part=part_letter,
            ))
            prev_step_id = step_id

    return steps


def _parse_flat_step_pattern(spec_content: str) -> list[ExecutionStep]:
    """Parse flat numbered steps (Step 1, Step 2, etc.)."""
    steps: list[ExecutionStep] = []

    # Pattern: #### Step N: Title or #### N. Title
    step_pattern = r"####\s+(?:Step\s+)?(\d+)[\.\s:—\-]+(.+?)(?=\n)"
    step_matches = list(re.finditer(step_pattern, spec_content))

    if not step_matches:
        return []

    prev_step_id = ""
    for i, match in enumerate(step_matches):
        step_num = match.group(1)
        step_id = f"S{step_num}"
        step_title = match.group(2).strip()

        # Get content between this step and the next
        start = match.end()
        end = step_matches[i + 1].start() if i + 1 < len(step_matches) else len(spec_content)
        step_content = spec_content[start:end]

        commands = _extract_bash_commands(step_content)
        gate = _extract_gate(step_content)

        depends = [prev_step_id] if prev_step_id else []

        steps.append(ExecutionStep(
            id=step_id,
            title=step_title,
            commands=commands,
            gate=gate,
            depends_on=depends,
            part="",
        ))
        prev_step_id = step_id

    return steps


def _extract_bash_commands(content: str) -> list[str]:
    """Extract commands from ```bash code blocks."""
    commands = []
    # Match ```bash ... ``` or ```shell ... ``` or ```sh ... ```
    pattern = r"```(?:bash|shell|sh)\s*\n(.*?)```"
    matches = re.findall(pattern, content, re.DOTALL)

    for block in matches:
        for line in block.strip().split("\n"):
            line = line.strip()
            # Skip empty lines and comments
            if line and not line.startswith("#"):
                commands.append(line)

    return commands


def _extract_gate(content: str) -> str:
    """Extract gate/validation command from step content.

    Recognizes:
      - **Gate**: command
      - **Gate:** command
      - **Validation**: command
      - **Verify**: command
    """
    patterns = [
        r"\*\*Gate\*\*\s*[:：]\s*(.+?)(?:\n|$)",
        r"\*\*Validation\*\*\s*[:：]\s*(.+?)(?:\n|$)",
        r"\*\*Verify\*\*\s*[:：]\s*(.+?)(?:\n|$)",
        r"\*\*Assert\*\*\s*[:：]\s*(.+?)(?:\n|$)",
    ]

    for pattern in patterns:
        match = re.search(pattern, content)
        if match:
            gate_cmd = match.group(1).strip()
            # If gate is wrapped in backticks, extract the command
            backtick_match = re.match(r"`(.+?)`", gate_cmd)
            if backtick_match:
                return backtick_match.group(1)
            return gate_cmd

    # Fallback: look for pytest commands in the content that aren't in bash blocks
    # (sometimes gates are just mentioned inline)
    pytest_match = re.search(r"(pytest\s+\S+.*?)(?:\n|$)", content)
    if pytest_match:
        # Only use if it's NOT inside a bash block (already captured as command)
        cmd = pytest_match.group(1).strip()
        if cmd not in _extract_bash_commands(content):
            return cmd

    return ""
