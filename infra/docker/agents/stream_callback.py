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
    agent_role: str = "fde-pipeline"
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

        # Handle tool input delta (captures what the tool is doing)
        tool_delta = (
            event.get("contentBlockDelta", {})
            .get("delta", {})
            .get("toolUse", {})
        )
        if tool_delta and "input" in tool_delta:
            self._handle_tool_input(tool_delta["input"])

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
        """Handle a tool invocation event with contextual observability.

        Emits what the agent is DOING, not just which tool it called.
        This provides the same baseline observability regardless of which
        container (monolith or distributed) is executing.

        Observability tiers:
          MILESTONE: Always emit with full context (file writes, git ops, tests)
          CONTEXT: Emit with file path/description (file reads, searches)
          AGGREGATE: Count silently, emit summary every 10 (shell commands)
        """
        self._tool_count += 1
        tool_name = tool_use.get("name", "unknown")
        tool_input = tool_use.get("toolUseId", "")

        # Track current tool for input parsing
        self._last_tool_name = tool_name
        self._tool_input_acc = ""
        self._tool_context_emitted = False

        # -- MILESTONE tools: always emit with context --
        milestone_tools = {
            "create_pull_request", "create_github_pull_request",
            "create_gitlab_merge_request", "git_push", "git_commit",
            "human_input", "create_branch", "run_tests", "pytest",
        }
        if tool_name in milestone_tools:
            self._flush_aggregate()
            self._buffer.append({"type": "tool", "msg": f"\u25B6 {tool_name}"})
            self._maybe_flush()
            return

        # -- CONTEXT tools: emit with what's being accessed --
        context_tools = {
            "write_file": "Writing",
            "str_replace": "Editing",
            "fs_write": "Creating",
            "read_file": "Reading",
            "readCode": "Analyzing",
            "grep_search": "Searching",
            "file_search": "Finding",
            "list_directory": "Exploring",
        }
        if tool_name in context_tools:
            action = context_tools[tool_name]
            if not hasattr(self, "_context_count"):
                self._context_count = 0
                self._last_context_action = ""
            self._context_count += 1
            self._last_context_action = action

            # Emit summary every 5 context operations
            if self._context_count % 5 == 0:
                self._flush_aggregate()
                self._buffer.append({
                    "type": "info",
                    "msg": f"{action} files ({self._context_count} ops so far)...",
                })
                self._maybe_flush()
            return

        # -- AGGREGATE tools: count silently, summarize periodically --
        if not hasattr(self, "_low_signal_count"):
            self._low_signal_count = 0
        self._low_signal_count += 1

        # Emit summary every 10 low-signal calls
        if self._low_signal_count % 10 == 0:
            self._buffer.append({
                "type": "info",
                "msg": f"Executing ({self._low_signal_count} shell operations)...",
            })
            self._maybe_flush()

    def _flush_aggregate(self) -> None:
        """Flush any pending aggregate counts as a summary before a milestone."""
        if hasattr(self, "_low_signal_count") and self._low_signal_count > 0:
            if self._low_signal_count >= 3:
                self._buffer.append({
                    "type": "info",
                    "msg": f"Completed {self._low_signal_count} shell operations",
                })
            self._low_signal_count = 0
        if hasattr(self, "_context_count") and self._context_count > 0:
            action = getattr(self, "_last_context_action", "Processing")
            if self._context_count >= 3:
                self._buffer.append({
                    "type": "info",
                    "msg": f"{action}: {self._context_count} file operations completed",
                })
            self._context_count = 0

    def _handle_tool_input(self, input_chunk: str) -> None:
        """Accumulate tool input (no-op for shell commands).

        Shell command input arrives as partial JSON chunks that cannot be
        reliably parsed for filenames. The _handle_tool_start already provides
        aggregate observability ("Executing N shell operations...").

        COE: Previous attempts to extract filenames from partial chunks produced
        truncated messages ("Reading: enrichm"). The streaming SDK delivers input
        in unpredictable chunk sizes — classification is only reliable after the
        full input is available, which doesn't happen until tool completion.
        """
        # No-op: shell command classification removed (unreliable on partial chunks)
        pass

    @staticmethod
    def _classify_shell_command(partial_input: str) -> str:
        """Classify a shell command into a human-readable action."""
        inp = partial_input.lower()

        # Git operations
        if "git commit" in inp:
            return "Committing changes..."
        if "git add" in inp:
            return "Staging files..."
        if "git diff" in inp:
            return "Reviewing changes..."
        if "git status" in inp:
            return "Checking workspace status..."

        # Test operations
        if "pytest" in inp or "python -m pytest" in inp:
            return "Running tests..."
        if "npm test" in inp or "npm run test" in inp:
            return "Running tests..."

        # Build/install
        if "pip install" in inp:
            return "Installing dependencies..."
        if "npm install" in inp:
            return "Installing dependencies..."

        # File operations via shell
        if "cat " in inp or "head " in inp:
            for token in partial_input.split():
                if "/" in token and not token.startswith("-"):
                    path = token.strip("'\"").split("/")[-1]
                    if path and len(path) > 2:
                        return f"Reading: {path}"
                    break
        if "mkdir" in inp:
            return "Creating directory..."

        # Lint/format
        if "ruff" in inp or "black" in inp or "flake8" in inp:
            return "Linting code..."
        if "prettier" in inp or "eslint" in inp:
            return "Formatting code..."

        return ""

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
        """Write buffered events to DynamoDB with agent_role as phase."""
        if not self._buffer:
            return

        # Write each buffered event with phase=agent_role for correct labeling
        for event in self._buffer:
            try:
                task_queue.append_task_event(
                    self.task_id,
                    event.get("type", "info"),
                    event.get("msg", ""),
                    phase=self.agent_role,
                )
            except Exception as e:
                logger.warning("Failed to write callback event: %s", e)

        self._buffer.clear()
        self._last_flush = time.time()
