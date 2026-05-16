"""
A2A Cross-Workflow Memory Manager — DynamoDB fde-{env}-memory Integration.

Provides persistent memory across workflow executions, enabling agents to
learn from past decisions and outcomes. This bridges the gap between the
ephemeral WorkflowContext (TTL 7 days) and long-term project knowledge.

DynamoDB Table: fde-{env}-memory
  PK: project_id (String)
  SK: memory_key (String)

Memory Key Patterns:
  - "workflow#outcome#{workflow_id}" — Final outcome of a completed workflow
  - "workflow#pattern#{topic_hash}" — Recurring patterns for similar topics
  - "feedback#recurring#{category}" — Frequently recurring review criticisms
  - "agent#performance#{agent_name}" — Agent performance metrics over time

Design:
  - Writes happen ONLY at workflow completion (not during execution)
  - Reads happen at workflow START (inject relevant memory into context)
  - Memory entries have a freshness score (decays over time)
  - Maximum 5 memory entries injected per workflow (token budget)
  - Uses the SAME DynamoDB schema as the existing fde-{env}-memory table

Ref: ADR-034 (A2A Protocol), ADR-007 (Cross-Session Learning Notes),
     fde-ai-squad-composition.md §3.2 (Memory table schema)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from src.core.a2a.contracts import (
    FinalReport,
    RawContent,
    ReviewFeedback,
    WorkflowContext,
)

logger = logging.getLogger(__name__)

# DynamoDB client config
_DDB_CONFIG = Config(
    connect_timeout=5,
    read_timeout=10,
    retries={"max_attempts": 3, "mode": "adaptive"},
)

# Memory injection limits
MAX_MEMORY_ENTRIES_PER_WORKFLOW = 5
MEMORY_ENTRY_MAX_CHARS = 2000
MEMORY_TTL_DAYS = 90


class WorkflowMemoryManager:
    """Manages cross-workflow memory in the fde-{env}-memory DynamoDB table.

    This class enables the A2A orchestrator to:
      1. RECALL: Load relevant past outcomes before starting a new workflow
      2. STORE: Persist workflow outcomes for future reference
      3. LEARN: Track recurring feedback patterns to improve first-pass quality

    The memory table uses the existing schema:
      PK = project_id (String) — identifies the project/repo
      SK = memory_key (String) — identifies the memory entry type + ID

    Usage:
        memory = WorkflowMemoryManager(project_id="my-project")

        # At workflow start — recall relevant memories
        memories = memory.recall_relevant(topic="pagination API")

        # At workflow completion — store outcome
        memory.store_workflow_outcome(context)
    """

    def __init__(
        self,
        project_id: str | None = None,
        table_name: str | None = None,
        region: str | None = None,
    ):
        """Initialize the memory manager.

        Args:
            project_id: Project identifier (DynamoDB PK). Defaults to
                        PROJECT_ID env var or "default".
            table_name: DynamoDB table name. Defaults to fde-{env}-memory.
            region: AWS region. Defaults to AWS_REGION env var.
        """
        self._project_id = project_id or os.environ.get("PROJECT_ID", "default")
        env = os.environ.get("ENVIRONMENT", "dev")
        self._table_name = table_name or os.environ.get(
            "MEMORY_TABLE", f"fde-{env}-memory"
        )
        self._region = region or os.environ.get("AWS_REGION", "us-east-1")
        self._dynamodb = boto3.resource(
            "dynamodb", region_name=self._region, config=_DDB_CONFIG
        )
        self._table = self._dynamodb.Table(self._table_name)

    def recall_relevant(
        self,
        topic: str,
        max_entries: int = MAX_MEMORY_ENTRIES_PER_WORKFLOW,
    ) -> list[dict[str, Any]]:
        """Recall relevant memories for a new workflow.

        Queries the memory table for entries related to the given topic.
        Returns the most recent and relevant memories, up to max_entries.

        This is called at workflow START to inject historical context.

        Args:
            topic: The workflow topic/prompt (used for relevance matching).
            max_entries: Maximum memory entries to return.

        Returns:
            List of memory entry dicts with keys:
              - memory_key: The SK value
              - memory_type: "outcome" | "pattern" | "feedback"
              - content: The memory content (truncated to budget)
              - created_at: When the memory was stored
              - relevance: Why this memory was selected
        """
        memories: list[dict[str, Any]] = []

        # Strategy 1: Check for recurring feedback patterns
        feedback_memories = self._query_feedback_patterns(max_entries=2)
        memories.extend(feedback_memories)

        # Strategy 2: Check for similar topic outcomes (hash-based)
        topic_hash = self._compute_topic_hash(topic)
        topic_memories = self._query_topic_patterns(topic_hash, max_entries=2)
        memories.extend(topic_memories)

        # Strategy 3: Most recent workflow outcomes (general learning)
        if len(memories) < max_entries:
            remaining = max_entries - len(memories)
            recent_memories = self._query_recent_outcomes(max_entries=remaining)
            memories.extend(recent_memories)

        # Enforce budget
        memories = memories[:max_entries]

        if memories:
            logger.info(
                "Recalled %d memories for topic '%s' (project=%s)",
                len(memories), topic[:50], self._project_id,
            )
        else:
            logger.debug(
                "No relevant memories found for topic '%s' (project=%s)",
                topic[:50], self._project_id,
            )

        return memories

    def store_workflow_outcome(
        self,
        context: WorkflowContext,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Store a completed workflow's outcome for future reference.

        Called at workflow COMPLETION. Extracts key learnings:
          - Final quality score (from review feedback)
          - Number of review iterations needed
          - Recurring criticism categories
          - Topic pattern for similarity matching

        Args:
            context: The completed WorkflowContext.
            metadata: Optional additional metadata.

        Returns:
            True if stored successfully.
        """
        now = datetime.now(timezone.utc).isoformat()
        ttl = int(time.time()) + (MEMORY_TTL_DAYS * 24 * 60 * 60)

        # Build outcome summary
        outcome = self._build_outcome_summary(context)

        try:
            # Store workflow outcome
            self._table.put_item(
                Item={
                    "project_id": self._project_id,
                    "memory_key": f"workflow#outcome#{context.workflow_id}",
                    "content": json.dumps(outcome, default=str),
                    "memory_type": "outcome",
                    "topic_hash": self._compute_topic_hash(context.user_input),
                    "created_at": now,
                    "ttl": ttl,
                    "metadata": json.dumps(metadata or {}, default=str),
                }
            )

            # Update recurring feedback patterns
            if context.feedback and context.feedback.criticisms:
                self._update_feedback_patterns(context.feedback, now, ttl)

            # Store topic pattern for similarity matching
            self._store_topic_pattern(context, outcome, now, ttl)

            logger.info(
                "Stored workflow outcome: project=%s workflow=%s score=%.2f attempts=%d",
                self._project_id,
                context.workflow_id,
                outcome.get("quality_score", 0),
                outcome.get("review_attempts", 0),
            )
            return True

        except ClientError as e:
            logger.error(
                "Failed to store workflow outcome: project=%s workflow=%s error=%s",
                self._project_id, context.workflow_id,
                e.response["Error"]["Message"],
            )
            return False

    def _build_outcome_summary(self, context: WorkflowContext) -> dict[str, Any]:
        """Build a concise outcome summary from a completed workflow context.

        Extracts only the fields needed for future memory recall.
        Does NOT store full report content (too large for memory budget).
        """
        outcome: dict[str, Any] = {
            "workflow_id": context.workflow_id,
            "topic": context.user_input[:200],
            "review_attempts": context.review_attempts,
            "quality_score": 0.0,
            "verdict": "UNKNOWN",
            "criticism_categories": [],
            "total_duration_s": context.execution_metrics.get("total_duration_s", 0),
            "completed_at": context.updated_at,
        }

        if context.feedback:
            outcome["quality_score"] = context.feedback.quality_score
            outcome["verdict"] = context.feedback.verdict.value
            outcome["criticism_categories"] = list(set(
                c.categoria for c in context.feedback.criticisms
            ))

        if context.report:
            outcome["artifacts_count"] = len(context.report.artifacts)
            outcome["report_title"] = context.report.title[:100]

        return outcome

    def _update_feedback_patterns(
        self,
        feedback: ReviewFeedback,
        now: str,
        ttl: int,
    ) -> None:
        """Track recurring feedback criticism categories.

        Increments a counter for each criticism category seen.
        This helps future workflows anticipate common issues.
        """
        categories_seen: set[str] = set()
        for criticism in feedback.criticisms:
            cat = criticism.categoria
            if cat in categories_seen:
                continue
            categories_seen.add(cat)

            try:
                self._table.update_item(
                    Key={
                        "project_id": self._project_id,
                        "memory_key": f"feedback#recurring#{cat}",
                    },
                    UpdateExpression=(
                        "SET occurrence_count = if_not_exists(occurrence_count, :zero) + :one, "
                        "last_seen = :now, "
                        "memory_type = :type, "
                        "ttl = :ttl, "
                        "last_example = :example"
                    ),
                    ExpressionAttributeValues={
                        ":zero": 0,
                        ":one": 1,
                        ":now": now,
                        ":type": "feedback",
                        ":ttl": ttl,
                        ":example": criticism.descricao[:200],
                    },
                )
            except ClientError:
                pass  # Non-critical — don't fail the workflow for memory updates

    def _store_topic_pattern(
        self,
        context: WorkflowContext,
        outcome: dict[str, Any],
        now: str,
        ttl: int,
    ) -> None:
        """Store a topic pattern for similarity-based recall."""
        topic_hash = self._compute_topic_hash(context.user_input)

        try:
            self._table.put_item(
                Item={
                    "project_id": self._project_id,
                    "memory_key": f"workflow#pattern#{topic_hash}",
                    "content": json.dumps(outcome, default=str),
                    "memory_type": "pattern",
                    "topic_hash": topic_hash,
                    "topic_preview": context.user_input[:100],
                    "created_at": now,
                    "ttl": ttl,
                }
            )
        except ClientError:
            pass  # Non-critical

    def _query_feedback_patterns(self, max_entries: int = 2) -> list[dict[str, Any]]:
        """Query recurring feedback patterns (most frequent criticism categories)."""
        try:
            response = self._table.query(
                KeyConditionExpression="project_id = :pid AND begins_with(memory_key, :prefix)",
                ExpressionAttributeValues={
                    ":pid": self._project_id,
                    ":prefix": "feedback#recurring#",
                },
                Limit=max_entries,
                ScanIndexForward=False,
            )

            return [
                {
                    "memory_key": item["memory_key"],
                    "memory_type": "feedback",
                    "content": (
                        f"Recurring criticism: {item['memory_key'].split('#')[-1]} "
                        f"(seen {item.get('occurrence_count', 0)} times). "
                        f"Example: {item.get('last_example', 'N/A')}"
                    ),
                    "created_at": item.get("last_seen", ""),
                    "relevance": "recurring_pattern",
                }
                for item in response.get("Items", [])
                if item.get("occurrence_count", 0) >= 2
            ]

        except ClientError as e:
            logger.debug("Failed to query feedback patterns: %s", str(e)[:100])
            return []

    def _query_topic_patterns(
        self, topic_hash: str, max_entries: int = 2
    ) -> list[dict[str, Any]]:
        """Query past outcomes for similar topics (hash-based matching)."""
        try:
            response = self._table.get_item(
                Key={
                    "project_id": self._project_id,
                    "memory_key": f"workflow#pattern#{topic_hash}",
                }
            )

            item = response.get("Item")
            if not item:
                return []

            content = json.loads(item.get("content", "{}"))
            return [
                {
                    "memory_key": item["memory_key"],
                    "memory_type": "pattern",
                    "content": (
                        f"Similar past workflow: '{content.get('report_title', 'N/A')}'. "
                        f"Score: {content.get('quality_score', 0):.2f}, "
                        f"Attempts: {content.get('review_attempts', 0)}, "
                        f"Issues: {', '.join(content.get('criticism_categories', []))}"
                    ),
                    "created_at": item.get("created_at", ""),
                    "relevance": "similar_topic",
                }
            ]

        except (ClientError, json.JSONDecodeError) as e:
            logger.debug("Failed to query topic patterns: %s", str(e)[:100])
            return []

    def _query_recent_outcomes(self, max_entries: int = 2) -> list[dict[str, Any]]:
        """Query most recent workflow outcomes for general learning."""
        try:
            response = self._table.query(
                KeyConditionExpression="project_id = :pid AND begins_with(memory_key, :prefix)",
                ExpressionAttributeValues={
                    ":pid": self._project_id,
                    ":prefix": "workflow#outcome#",
                },
                Limit=max_entries,
                ScanIndexForward=False,
            )

            results = []
            for item in response.get("Items", []):
                try:
                    content = json.loads(item.get("content", "{}"))
                    results.append({
                        "memory_key": item["memory_key"],
                        "memory_type": "outcome",
                        "content": (
                            f"Past workflow '{content.get('report_title', 'N/A')}': "
                            f"score={content.get('quality_score', 0):.2f}, "
                            f"attempts={content.get('review_attempts', 0)}, "
                            f"duration={content.get('total_duration_s', 0):.0f}s"
                        ),
                        "created_at": item.get("created_at", ""),
                        "relevance": "recent_outcome",
                    })
                except (json.JSONDecodeError, KeyError):
                    continue

            return results

        except ClientError as e:
            logger.debug("Failed to query recent outcomes: %s", str(e)[:100])
            return []

    @staticmethod
    def _compute_topic_hash(topic: str) -> str:
        """Compute a stable hash for topic similarity matching.

        Uses first 100 chars normalized (lowercase, stripped) to group
        similar topics together.

        Args:
            topic: The workflow topic/prompt.

        Returns:
            8-char hex hash of the normalized topic prefix.
        """
        normalized = topic[:100].lower().strip()
        return hashlib.sha256(normalized.encode()).hexdigest()[:8]

    def format_memories_for_prompt(
        self,
        memories: list[dict[str, Any]],
        max_chars: int = MEMORY_ENTRY_MAX_CHARS,
    ) -> str:
        """Format recalled memories as a prompt injection string.

        This string is prepended to the workflow's user_input to give
        agents awareness of past outcomes without modifying the
        WorkflowContext schema.

        Args:
            memories: List of memory entries from recall_relevant().
            max_chars: Maximum total characters for the memory block.

        Returns:
            Formatted string ready for prompt injection, or empty string
            if no memories are available.
        """
        if not memories:
            return ""

        lines = ["[MEMORY — Past workflow learnings for this project]"]
        current_size = len(lines[0])

        for mem in memories:
            entry = f"- [{mem.get('relevance', 'general')}] {mem.get('content', '')}"
            if current_size + len(entry) > max_chars:
                break
            lines.append(entry)
            current_size += len(entry)

        lines.append("[/MEMORY]")
        return "\n".join(lines)
