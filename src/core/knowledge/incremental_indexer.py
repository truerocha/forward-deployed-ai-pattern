"""
Incremental Indexer — Re-indexes only changed files in the Code Knowledge Base.

Instead of re-scanning the entire workspace on every PR merge, this module
accepts a list of changed file paths (from git diff or PR file list) and
updates only those entries in the call graph, description, and vector stores.

Integration:
  - Triggered by EventBridge on PR merge (via Lambda or ECS task)
  - Reads changed file list from the event payload
  - Delegates to CallGraphExtractor (single file), DescriptionGenerator,
    and VectorStore for the actual indexing work
  - Idempotent: re-running on the same files produces the same result

Source: AI-DLC Gap Analysis (Gap 1: Code Knowledge Base)
  "Re-index on every PR merge. Staleness window: max 1 PR behind."

Feature flag: INCREMENTAL_INDEX_ENABLED (default: true)
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("fde.knowledge.incremental_indexer")

_INDEXABLE_EXTENSIONS = {".py"}
_EXCLUDED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox", ".pytest_cache"}


@dataclass
class IndexResult:
    """Result of an incremental indexing operation."""

    files_processed: int = 0
    files_skipped: int = 0
    files_deleted: int = 0
    call_graphs_updated: int = 0
    descriptions_updated: int = 0
    vectors_updated: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0
    triggered_at: str = ""

    def __post_init__(self):
        if not self.triggered_at:
            self.triggered_at = datetime.now(timezone.utc).isoformat()

    @property
    def success(self) -> bool:
        return len(self.errors) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "files_processed": self.files_processed,
            "files_skipped": self.files_skipped,
            "files_deleted": self.files_deleted,
            "call_graphs_updated": self.call_graphs_updated,
            "descriptions_updated": self.descriptions_updated,
            "vectors_updated": self.vectors_updated,
            "errors": self.errors,
            "duration_ms": self.duration_ms,
            "triggered_at": self.triggered_at,
            "success": self.success,
        }


class IncrementalIndexer:
    """Re-indexes only changed files in the Code Knowledge Base.

    Usage:
        indexer = IncrementalIndexer(
            project_id="my-repo",
            workspace_path="/mnt/efs/workspaces/my-repo",
        )
        result = indexer.index_changed_files(
            changed_files=["src/auth/oauth.py", "src/auth/jwt.py"],
            deleted_files=["src/auth/legacy.py"],
        )
    """

    def __init__(
        self,
        project_id: str,
        workspace_path: str,
        knowledge_table: str | None = None,
        generate_descriptions: bool = True,
        update_vectors: bool = True,
    ):
        self._project_id = project_id
        self._workspace_path = Path(workspace_path)
        self._knowledge_table = knowledge_table or os.environ.get("KNOWLEDGE_TABLE", "fde-knowledge")
        self._generate_descriptions = generate_descriptions
        self._update_vectors = update_vectors
        self._enabled = os.environ.get("INCREMENTAL_INDEX_ENABLED", "true").lower() == "true"

    @property
    def enabled(self) -> bool:
        return self._enabled

    def index_changed_files(
        self,
        changed_files: list[str],
        deleted_files: list[str] | None = None,
    ) -> IndexResult:
        """Index a specific set of changed files.

        Args:
            changed_files: Relative file paths that were added or modified.
            deleted_files: Relative file paths that were deleted.

        Returns:
            IndexResult with counts of what was updated.
        """
        if not self._enabled:
            return IndexResult(errors=["Incremental indexing disabled"])

        start = time.time()
        result = IndexResult()
        deleted = deleted_files or []

        from .call_graph_extractor import CallGraphExtractor

        extractor = CallGraphExtractor(
            project_id=self._project_id,
            workspace_path=str(self._workspace_path),
            knowledge_table=self._knowledge_table,
        )

        for file_path in changed_files:
            if not self._should_index(file_path):
                result.files_skipped += 1
                continue

            abs_path = self._workspace_path / file_path
            if not abs_path.exists():
                result.files_skipped += 1
                continue

            try:
                graph = extractor.extract_module(abs_path)
                if graph:
                    extractor.persist_all([graph])
                    result.call_graphs_updated += 1

                    if self._generate_descriptions:
                        result.descriptions_updated += self._update_description(graph.to_dict())

                    if self._update_vectors:
                        result.vectors_updated += self._update_vector(file_path, graph.to_dict())

                result.files_processed += 1

            except Exception as e:
                error_msg = f"Failed to index {file_path}: {type(e).__name__}: {str(e)[:100]}"
                result.errors.append(error_msg)
                logger.warning(error_msg)

        for file_path in deleted:
            if not self._should_index(file_path):
                continue
            try:
                self._remove_from_index(file_path)
                result.files_deleted += 1
            except Exception as e:
                error_msg = f"Failed to remove {file_path}: {type(e).__name__}: {str(e)[:100]}"
                result.errors.append(error_msg)
                logger.warning(error_msg)

        result.duration_ms = int((time.time() - start) * 1000)

        logger.info(
            "Incremental index: project=%s processed=%d skipped=%d deleted=%d errors=%d duration=%dms",
            self._project_id, result.files_processed, result.files_skipped,
            result.files_deleted, len(result.errors), result.duration_ms,
        )
        return result

    def index_from_git_diff(self, base_ref: str = "HEAD~1", head_ref: str = "HEAD") -> IndexResult:
        """Index files changed between two git refs.

        Args:
            base_ref: The base git ref (e.g., "main~1", a commit SHA).
            head_ref: The head git ref (e.g., "HEAD", "main").

        Returns:
            IndexResult with counts of what was updated.
        """
        import subprocess

        try:
            diff_output = subprocess.run(
                ["git", "diff", "--name-status", base_ref, head_ref],
                capture_output=True, text=True, timeout=30,
                cwd=str(self._workspace_path),
            )
            if diff_output.returncode != 0:
                return IndexResult(errors=[f"git diff failed: {diff_output.stderr[:200]}"])
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            return IndexResult(errors=[f"git diff error: {e}"])

        changed_files: list[str] = []
        deleted_files: list[str] = []

        for line in diff_output.stdout.strip().splitlines():
            if not line:
                continue
            parts = line.split("\t", 1)
            if len(parts) < 2:
                continue
            status, file_path = parts[0], parts[1]

            if status.startswith("D"):
                deleted_files.append(file_path)
            elif status.startswith(("A", "M", "R")):
                if "\t" in file_path:
                    file_path = file_path.split("\t")[-1]
                changed_files.append(file_path)

        if not changed_files and not deleted_files:
            return IndexResult()

        return self.index_changed_files(changed_files, deleted_files)

    def _should_index(self, file_path: str) -> bool:
        """Determine if a file should be indexed."""
        path = Path(file_path)
        if path.suffix not in _INDEXABLE_EXTENSIONS:
            return False
        for part in path.parts:
            if part in _EXCLUDED_DIRS:
                return False
        return True

    def _update_description(self, graph_data: dict[str, Any]) -> int:
        """Generate and persist a business description. Returns 1 if updated."""
        from .description_generator import DescriptionGenerator

        try:
            generator = DescriptionGenerator(
                project_id=self._project_id,
                workspace_path=str(self._workspace_path),
                knowledge_table=self._knowledge_table,
            )
            description = generator.generate_single_description(graph_data)
            return 1 if description else 0
        except Exception as e:
            logger.debug("Description generation skipped: %s", e)
            return 0

    def _update_vector(self, file_path: str, graph_data: dict[str, Any]) -> int:
        """Update the vector embedding for a module. Returns 1 if updated."""
        from .vector_store import VectorStore

        try:
            store = VectorStore(
                project_id=self._project_id,
                knowledge_table=self._knowledge_table,
            )

            functions = graph_data.get("functions", [])
            classes = graph_data.get("classes", [])
            module_path = graph_data.get("module_path", file_path)

            text_parts = [
                f"Module: {module_path}",
                f"Functions: {', '.join(functions[:20])}" if functions else "",
                f"Classes: {', '.join(classes[:10])}" if classes else "",
            ]
            text = "\n".join(p for p in text_parts if p)

            if not text.strip():
                return 0

            entry_id = store.index(
                text=text,
                metadata={
                    "module_path": module_path,
                    "type": "call_graph_summary",
                    "function_count": len(functions),
                    "class_count": len(classes),
                },
            )
            return 1 if entry_id else 0

        except Exception as e:
            logger.debug("Vector update skipped for %s: %s", file_path, e)
            return 0

    def _remove_from_index(self, file_path: str) -> None:
        """Remove a deleted file from all knowledge stores."""
        import boto3
        from botocore.exceptions import ClientError

        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(self._knowledge_table)

        try:
            table.delete_item(Key={"project_id": self._project_id, "sk": f"callgraph#{file_path}"})
        except ClientError:
            pass

        try:
            table.delete_item(Key={"project_id": self._project_id, "sk": f"description#{file_path}"})
        except ClientError:
            pass

        logger.debug("Removed index entries for deleted file: %s", file_path)
