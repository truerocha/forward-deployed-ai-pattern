"""
Stream Callback — Captures agent reasoning events for dashboard visibility.

The Strands SDK supports callback handlers that fire on every tool call
and text chunk. This module provides a DynamoDB-backed callback that
writes condensed reasoning events to the task_queue record so the
dashboard's Chain of Thought panel shows real-time agent activity.

Design decisions:
- Only captures tool calls and key text markers (not every token)
- Batches events to avoid DynamoDB write amplification (max 1 write/5s)
- Truncates messages to 200 chars (DynamoDB item size budget)
- Non-blocking: failures are logged but never stop the agent

Usage:
    from agents.stream_callback import DashboardCallback

    callback = DashboardCallback(task_id="TASK-abc123")
    agent = Agent(callback_handler=callback)
"""

import logging
import time
from dataclasses import dataclass, field

from . import task_queue

logger = logging.getLogger("fde.stream_callback")

# Minimum interval between DynamoDB writes (seconds)
_MIN_WRITE_INTERVAL = 5.0

# Maximum events to buffer before forcing a flush
_MAX_BUFFER_SIZE = 10


@dataclass
class DashboardCallback:
    """Strands callback handler that emits reasoning events to DynamoDB.

    Captures:
    - Tool invocations (tool name + first 100 chars of result)
    - Key reasoning markers (## headers, decisions, errors)
    - Phase transitions (Phase 3.a, 3.b, etc.)

    Does NOT capture:
    - Every text token (too noisy, too expensive)
    - Full tool outputs (too large)
    - Internal chain-of-thought (security: may contain secrets)
    """

    task_id: str
    _buffer: list = field(default_factory=list, init=False)
    _last_flush: float = field(default=0.0, init=False)
    _tool_count: int = field(default=0, init=False)

    def on_tool_start(self, tool_name: str, tool_input: dict) -> None:
        """Called when the agent invokes a tool."""
        self._tool_count += 1
        # Summarize the tool call (don't expose full input — may contain secrets)
        summary = f"Tool #{self._tool_count}: {tool_name}"
        if tool_name == "run_shell_command":
            cmd = tool_input.get("command", "")[:80]
            summary = f"Tool #{self._tool_count}: $ {cmd}"
        elif tool_name in ("update_github_issue", "create_github_pull_request"):
            summary = f"Tool #{self._tool_count}: {tool_name}"
        elif tool_name == "write_artifact":
            name = tool_input.get("artifact_name", "")[:40]
            summary = f"Tool #{self._tool_count}: write_artifact({name})"

        self._buffer.append({"type": "tool", "msg": summary})
        self._maybe_flush()

    def on_tool_end(self, tool_name: str, tool_output: str) -> None:
        """Called when a tool returns its result."""
        # Only capture notable outcomes (pass/fail signals)
        output_lower = (tool_output or "")[:500].lower()
        if "error" in output_lower or "failed" in output_lower:
            self._buffer.append({"type": "error", "msg": f"{tool_name}: {tool_output[:150]}"})
            self._maybe_flush(force=True)
        elif "pass" in output_lower or "success" in output_lower:
            # Summarize test results
            if "test" in tool_name.lower() or "pytest" in output_lower:
                self._buffer.append({"type": "system", "msg": f"Tests: {tool_output[:150]}"})
                self._maybe_flush()

    def on_text_chunk(self, text: str) -> None:
        """Called for each text chunk from the model.

        We only capture structural markers, not every token.
        """
        # Capture markdown headers (## Phase 3.b, ## Key Metrics, etc.)
        if text.startswith("## ") or text.startswith("### "):
            header = text.strip()[:100]
            self._buffer.append({"type": "agent", "msg": header})
            self._maybe_flush()
        # Capture key decision markers
        elif any(marker in text for marker in ["\u2705", "\u274c", "COMPLETE", "FAILED", "BLOCKED"]):
            line = text.strip()[:150]
            if line and len(line) > 10:
                self._buffer.append({"type": "agent", "msg": line})
                self._maybe_flush()

    def on_agent_end(self, result: str) -> None:
        """Called when the agent finishes execution."""
        self._buffer.append({"type": "system", "msg": "Agent execution complete"})
        self._flush()

    def _maybe_flush(self, force: bool = False) -> None:
        """Flush buffer to DynamoDB if enough time has passed or buffer is full."""
        now = time.time()
        elapsed = now - self._last_flush

        if force or elapsed >= _MIN_WRITE_INTERVAL or len(self._buffer) >= _MAX_BUFFER_SIZE:
            self._flush()

    def _flush(self) -> None:
        """Write buffered events to DynamoDB."""
        if not self._buffer:
            return

        # Write each buffered event (append_task_event handles non-blocking)
        for event in self._buffer:
            task_queue.append_task_event(
                self.task_id,
                event.get("type", "info"),
                event.get("msg", ""),
            )

        self._buffer.clear()
        self._last_flush = time.time()
