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

    Implements __call__(**kwargs) to match the Strands SDK callback interface.
    The SDK calls this with kwargs containing:
    - reasoningText: model's chain-of-thought reasoning
    - data: text content chunks
    - complete: whether this is the final chunk
    - event: raw model stream event (tool invocations in contentBlockStart)

    Captures:
    - Tool invocations (tool name from contentBlockStart events)
    - Key reasoning markers (## headers, decisions, errors)
    - Phase transitions (Phase 3.a, 3.b, etc.)

    Does NOT capture:
    - Every text token (too noisy, too expensive)
    - Full tool outputs (too large)
    - Raw reasoning text (security: may reference code or secrets)
    """

    task_id: str
    _buffer: list = field(default_factory=list, init=False)
    _last_flush: float = field(default=0.0, init=False)
    _tool_count: int = field(default=0, init=False)
    _text_accumulator: str = field(default="", init=False)

    def __call__(self, **kwargs) -> None:
        """Strands SDK callback entry point.

        Routes incoming events to appropriate handlers based on kwargs content.
        """
        reasoning_text = kwargs.get("reasoningText", "")
        data = kwargs.get("data", "")
        complete = kwargs.get("complete", False)
        event = kwargs.get("event", {})

        # Handle tool invocation start
        tool_use = (
            event.get("contentBlockStart", {})
            .get("start", {})
            .get("toolUse")
        )
        if tool_use:
            self._handle_tool_start(tool_use)

        # Handle reasoning text (model's thinking — summarize, don't expose raw)
        if reasoning_text:
            self._handle_reasoning(reasoning_text)

        # Handle text data (agent's output — capture structural markers)
        if data:
            self._handle_text(data)

        # On completion, flush any remaining buffer
        if complete:
            self._handle_complete()

    def _handle_tool_start(self, tool_use: dict) -> None:
        """Handle a tool invocation event.

        Filters low-value tool calls (shell commands, file reads) and only
        surfaces meaningful tool usage to the dashboard. Aggregates routine
        operations into periodic summary events.

        Signal vs Noise:
          HIGH signal: create_pull_request, run_tests, bedrock_invoke, git_push
          LOW signal: run_shell_command, read_file, write_file, list_directory, str_replace

        Low-signal tools are counted but not individually emitted.
        A summary is emitted every 10 low-signal calls.
        """
        self._tool_count += 1
        tool_name = tool_use.get("name", "unknown")

        # High-signal tools — always emit
        high_signal_tools = {
            "create_pull_request", "create_github_pull_request",
            "create_gitlab_merge_request", "run_tests", "pytest",
            "bedrock_invoke", "converse", "git_push", "git_commit",
            "human_input", "create_branch",
        }

        if tool_name in high_signal_tools:
            summary = f"\u25B6 {tool_name}"
            self._buffer.append({"type": "tool", "msg": summary[:200]})
            self._maybe_flush()
            return

        # Low-signal tools — aggregate into periodic summaries
        if not hasattr(self, "_low_signal_count"):
            self._low_signal_count = 0
        self._low_signal_count += 1

        # Emit summary every 10 low-signal calls
        if self._low_signal_count % 10 == 0:
            summary = f"Processing ({self._low_signal_count} operations)..."
            self._buffer.append({"type": "info", "msg": summary})
            self._maybe_flush()

    def _handle_reasoning(self, text: str) -> None:
        """Handle reasoning text — capture key decision markers only."""
        # Only capture lines with structural markers (not every thinking token)
        markers = [
            "decision:", "conclusion:", "approach:", "risk:", "gate:",
            "result:", "finding:", "recommendation:", "implementation:",
            "analysis:", "strategy:", "plan:", "summary:",
        ]
        for marker in markers:
            if marker in text.lower():
                line = text.strip()[:200]
                if line and len(line) > 15:
                    self._buffer.append({"type": "agent", "msg": f"💭 {line}"})
                    self._maybe_flush()
                break

    def _handle_text(self, data: str) -> None:
        """Handle text output — capture structural markers."""
        self._text_accumulator += data

        # Capture markdown headers (## Phase 3.b, ## Key Metrics, etc.)
        if "\n" in self._text_accumulator:
            lines = self._text_accumulator.split("\n")
            self._text_accumulator = lines[-1]  # Keep incomplete last line

            for line in lines[:-1]:
                stripped = line.strip()
                if stripped.startswith("## ") or stripped.startswith("### "):
                    self._buffer.append({"type": "agent", "msg": stripped[:150]})
                    self._maybe_flush()
                elif stripped.startswith("# "):
                    self._buffer.append({"type": "agent", "msg": stripped[:150]})
                    self._maybe_flush()
                elif any(m in stripped for m in [
                    "✅", "❌", "COMPLETE", "FAILED", "BLOCKED", "PASS", "ERROR",
                    "⚠️", "🔍", "📋", "⚙️", "🧪", "📊", "🎉",
                    "Created file", "Modified file", "Committed",
                ]):
                    if len(stripped) > 10:
                        self._buffer.append({"type": "agent", "msg": stripped[:150]})
                        self._maybe_flush()
                elif stripped.startswith("- **") or stripped.startswith("* **"):
                    # Capture bold list items (key findings, recommendations)
                    if len(stripped) > 20:
                        self._buffer.append({"type": "agent", "msg": stripped[:150]})
                        self._maybe_flush()

    def _handle_complete(self) -> None:
        """Handle completion — flush remaining buffer."""
        # Process any remaining accumulated text
        if self._text_accumulator.strip():
            stripped = self._text_accumulator.strip()
            if stripped.startswith("## ") or stripped.startswith("### "):
                self._buffer.append({"type": "agent", "msg": stripped[:150]})
            self._text_accumulator = ""

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
            try:
                task_queue.append_task_event(
                    self.task_id,
                    event.get("type", "info"),
                    event.get("msg", ""),
                )
            except Exception as e:
                logger.warning("Failed to write callback event: %s", e)

        self._buffer.clear()
        self._last_flush = time.time()
