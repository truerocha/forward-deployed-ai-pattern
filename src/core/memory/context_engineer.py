"""
Context Engineer — Per-Task-Type Automatic Context Retrieval (Activity 3.11).

Given a task type and description, automatically retrieves the most
relevant context from multiple sources. Eliminates manual context
gathering by agents.

Task types and their primary context sources:
  - architecture: ADRs, design docs, governance rules
  - testing: Test contracts, coverage data, error patterns
  - security: WAF pillars, compliance rules, threat models
  - implementation: Code patterns, API contracts, dependencies
  - knowledge: Corpus files, documentation, learning history

Context sources:
  - ADRs (for architecture tasks)
  - Test contracts (for testing tasks)
  - Corpus files (for knowledge tasks)
  - Memory (for all tasks via MemoryManager.recall())
  - Knowledge annotations (for module-specific context)

Ref: docs/design/fde-core-brain-development.md Section 3 (Wave 3)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import boto3
from botocore.exceptions import ClientError

from src.core.memory.memory_manager import MemoryManager

logger = logging.getLogger(__name__)

VALID_TASK_TYPES = frozenset({
    "architecture", "testing", "security", "implementation", "knowledge"
})

# Mapping of task types to relevant memory types for recall
_TASK_MEMORY_TYPES: dict[str, list[str]] = {
    "architecture": ["decision", "adr"],
    "testing": ["error_pattern", "outcome"],
    "security": ["decision", "error_pattern"],
    "implementation": ["decision", "outcome", "learning"],
    "knowledge": ["learning", "adr", "decision"],
}

# Mapping of task types to knowledge annotation tags
_TASK_ANNOTATION_TAGS: dict[str, list[str]] = {
    "architecture": ["architecture", "design", "governance"],
    "testing": ["testing", "quality", "contracts"],
    "security": ["security", "compliance", "waf"],
    "implementation": ["implementation", "api", "data-plane"],
    "knowledge": ["knowledge", "documentation", "corpus"],
}


@dataclass
class TaskContext:
    """Assembled context for a specific task."""

    task_type: str
    task_description: str
    relevant_adrs: list[dict[str, Any]] = field(default_factory=list)
    relevant_memory: list[dict[str, Any]] = field(default_factory=list)
    relevant_docs: list[dict[str, Any]] = field(default_factory=list)
    relevant_annotations: list[dict[str, Any]] = field(default_factory=list)
    context_sources_used: list[str] = field(default_factory=list)
    retrieval_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for agent consumption."""
        return {
            "task_type": self.task_type,
            "task_description": self.task_description,
            "relevant_adrs": self.relevant_adrs,
            "relevant_memory": self.relevant_memory,
            "relevant_docs": self.relevant_docs,
            "relevant_annotations": self.relevant_annotations,
            "context_sources_used": self.context_sources_used,
            "retrieval_metadata": self.retrieval_metadata,
        }


class ContextEngineer:
    """
    Per-task-type automatic context retrieval.

    Given a task type and description, retrieves the most relevant
    context from ADRs, memory, knowledge annotations, and documents.

    Usage:
        ce = ContextEngineer(
            project_id="my-repo",
            memory_table="fde-dev-memory",
            knowledge_table="fde-knowledge",
        )
        context = ce.get_context_for_task("architecture", "Design caching layer")
        # context.relevant_adrs, context.relevant_memory, context.relevant_docs
    """

    def __init__(
        self,
        project_id: str,
        memory_table: str | None = None,
        knowledge_table: str | None = None,
    ):
        self._project_id = project_id or os.environ.get("PROJECT_ID", "global")
        self._memory_table = memory_table or os.environ.get(
            "MEMORY_TABLE", "fde-dev-memory"
        )
        self._knowledge_table = knowledge_table or os.environ.get(
            "KNOWLEDGE_TABLE", "fde-knowledge"
        )
        self._dynamodb = boto3.resource("dynamodb")
        self._memory_manager = MemoryManager(
            project_id=self._project_id,
            memory_table=self._memory_table,
        )

    def get_context_for_task(
        self,
        task_type: str,
        task_description: str,
    ) -> TaskContext:
        """
        Retrieve the most relevant context for a given task.

        Automatically determines which context sources to query based
        on the task type and uses the task description for relevance
        matching.

        Args:
            task_type: One of: architecture, testing, security, implementation, knowledge.
            task_description: Natural language description of the task.

        Returns:
            TaskContext with assembled relevant context.

        Raises:
            ValueError: If task_type is not valid.
        """
        if task_type not in VALID_TASK_TYPES:
            raise ValueError(
                f"Invalid task_type '{task_type}'. Must be one of: {sorted(VALID_TASK_TYPES)}"
            )

        context = TaskContext(
            task_type=task_type,
            task_description=task_description,
        )

        # Always retrieve relevant memory
        self._retrieve_memory(context)

        # Task-type-specific retrieval
        if task_type == "architecture":
            self._retrieve_adrs(context)
            self._retrieve_annotations(context, tags=["architecture", "design"])
        elif task_type == "testing":
            self._retrieve_annotations(context, tags=["testing", "contracts"])
            self._retrieve_test_context(context)
        elif task_type == "security":
            self._retrieve_adrs(context)
            self._retrieve_annotations(context, tags=["security", "compliance"])
        elif task_type == "implementation":
            self._retrieve_annotations(context, tags=["implementation", "api"])
            self._retrieve_adrs(context)
        elif task_type == "knowledge":
            self._retrieve_annotations(context, tags=["knowledge", "documentation"])
            self._retrieve_corpus_docs(context)

        context.retrieval_metadata = {
            "adrs_found": len(context.relevant_adrs),
            "memories_found": len(context.relevant_memory),
            "docs_found": len(context.relevant_docs),
            "annotations_found": len(context.relevant_annotations),
            "sources_queried": len(context.context_sources_used),
        }

        logger.info(
            "Context assembled: task_type=%s adrs=%d memory=%d docs=%d annotations=%d",
            task_type,
            len(context.relevant_adrs),
            len(context.relevant_memory),
            len(context.relevant_docs),
            len(context.relevant_annotations),
        )
        return context

    # ------------------------------------------------------------------
    # Private retrieval methods
    # ------------------------------------------------------------------

    def _retrieve_memory(self, context: TaskContext) -> None:
        """Retrieve relevant memories using MemoryManager.recall()."""
        memory_types = _TASK_MEMORY_TYPES.get(context.task_type, [])

        try:
            # First, recall with no type filter for broad relevance
            all_results = self._memory_manager.recall(
                query=context.task_description,
                limit=5,
            )

            # Then recall with specific memory types
            for mtype in memory_types:
                typed_results = self._memory_manager.recall(
                    query=context.task_description,
                    memory_type=mtype,
                    limit=3,
                )
                all_results.extend(typed_results)

            # Deduplicate by memory_id
            seen_ids: set[str] = set()
            for memory in all_results:
                if memory.memory_id not in seen_ids:
                    seen_ids.add(memory.memory_id)
                    context.relevant_memory.append({
                        "memory_id": memory.memory_id,
                        "type": memory.memory_type,
                        "content": memory.content,
                        "metadata": memory.metadata,
                    })

            context.context_sources_used.append("memory")
        except Exception as e:
            logger.warning("Failed to retrieve memory context: %s", e)

    def _retrieve_adrs(self, context: TaskContext) -> None:
        """Retrieve relevant ADRs from knowledge annotations."""
        table = self._dynamodb.Table(self._knowledge_table)

        try:
            response = table.query(
                KeyConditionExpression="project_id = :pid AND begins_with(sk, :prefix)",
                ExpressionAttributeValues={
                    ":pid": self._project_id,
                    ":prefix": "annotation#",
                },
            )

            query_keywords = set(context.task_description.lower().split())
            adr_refs: set[str] = set()

            for item in response.get("Items", []):
                data = json.loads(item.get("data", "{}"))
                governing_artifacts = data.get("governing_artifacts", [])

                # Check if this annotation is relevant to the task
                module_path = data.get("module_path", "")
                tags = data.get("tags", [])
                combined_text = f"{module_path} {' '.join(tags)}".lower()
                combined_words = set(combined_text.split())

                if query_keywords & combined_words:
                    for artifact in governing_artifacts:
                        if artifact.startswith("ADR-"):
                            adr_refs.add(artifact)

            for adr_ref in sorted(adr_refs):
                context.relevant_adrs.append({
                    "adr_id": adr_ref,
                    "source": "knowledge_annotations",
                })

            context.context_sources_used.append("adrs")
        except ClientError as e:
            logger.warning("Failed to retrieve ADR context: %s", e)

    def _retrieve_annotations(self, context: TaskContext, tags: list[str]) -> None:
        """Retrieve knowledge annotations matching given tags."""
        table = self._dynamodb.Table(self._knowledge_table)

        try:
            response = table.query(
                KeyConditionExpression="project_id = :pid AND begins_with(sk, :prefix)",
                ExpressionAttributeValues={
                    ":pid": self._project_id,
                    ":prefix": "annotation#",
                },
            )

            tag_set = set(tags)
            for item in response.get("Items", []):
                data = json.loads(item.get("data", "{}"))
                item_tags = set(data.get("tags", []))

                if tag_set & item_tags:
                    context.relevant_annotations.append({
                        "module_path": data.get("module_path", ""),
                        "governing_artifacts": data.get("governing_artifacts", []),
                        "confidence": data.get("confidence", 0.0),
                        "tags": data.get("tags", []),
                    })

            context.context_sources_used.append("annotations")
        except ClientError as e:
            logger.warning("Failed to retrieve annotation context: %s", e)

    def _retrieve_test_context(self, context: TaskContext) -> None:
        """Retrieve test-specific context (error patterns, outcomes)."""
        try:
            error_patterns = self._memory_manager.recall(
                query=context.task_description,
                memory_type="error_pattern",
                limit=5,
            )
            for pattern in error_patterns:
                context.relevant_docs.append({
                    "type": "error_pattern",
                    "content": pattern.content,
                    "metadata": pattern.metadata,
                })

            outcomes = self._memory_manager.recall(
                query=context.task_description,
                memory_type="outcome",
                limit=3,
            )
            for outcome in outcomes:
                context.relevant_docs.append({
                    "type": "test_outcome",
                    "content": outcome.content,
                    "metadata": outcome.metadata,
                })

            context.context_sources_used.append("test_context")
        except Exception as e:
            logger.warning("Failed to retrieve test context: %s", e)

    def _retrieve_corpus_docs(self, context: TaskContext) -> None:
        """Retrieve corpus/documentation context for knowledge tasks."""
        try:
            learnings = self._memory_manager.recall(
                query=context.task_description,
                memory_type="learning",
                limit=5,
            )
            for learning in learnings:
                context.relevant_docs.append({
                    "type": "learning",
                    "content": learning.content,
                    "metadata": learning.metadata,
                })

            adrs = self._memory_manager.recall(
                query=context.task_description,
                memory_type="adr",
                limit=3,
            )
            for adr in adrs:
                context.relevant_docs.append({
                    "type": "adr_memory",
                    "content": adr.content,
                    "metadata": adr.metadata,
                })

            context.context_sources_used.append("corpus")
        except Exception as e:
            logger.warning("Failed to retrieve corpus context: %s", e)
