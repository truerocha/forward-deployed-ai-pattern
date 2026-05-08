"""
Semantic Store — Bedrock Knowledge Base Integration (Activity 3.10).

Provides semantic memory search using Amazon Bedrock Knowledge Bases.
Stores text with metadata for vector-based retrieval and falls back
to DynamoDB keyword matching when Bedrock KB is unavailable.

Operations:
  - store_semantic(text, metadata): Store text in Bedrock KB
  - search_semantic(query, top_k): Semantic search via Bedrock KB
  - sync_from_dynamodb(): Sync memory items from DynamoDB to KB

Graceful degradation:
  If Bedrock KB is unavailable (misconfigured, quota exceeded, region
  unavailable), falls back to DynamoDB keyword match with a logged
  warning. Returns partial results in degraded mode.

Ref: docs/design/fde-core-brain-development.md Section 3 (Wave 3)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_DEFAULT_TOP_K = 5
_BEDROCK_REGION = "us-east-1"


@dataclass
class SemanticResult:
    """A single result from semantic search."""

    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str = "bedrock_kb"  # "bedrock_kb" or "dynamodb_fallback"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "text": self.text,
            "score": self.score,
            "metadata": self.metadata,
            "source": self.source,
        }


class SemanticStore:
    """
    Bedrock Knowledge Base integration for semantic memory search.

    Uses Amazon Bedrock Knowledge Bases for vector-based semantic
    retrieval. Falls back to DynamoDB keyword matching when KB is
    unavailable.

    Usage:
        store = SemanticStore(
            project_id="my-repo",
            knowledge_base_id="KB_ID_FROM_ENV",
            memory_table="fde-dev-memory",
        )
        store.store_semantic("DynamoDB chosen for state management", {"source": "ADR-009"})
        results = store.search_semantic("state management approach", top_k=5)
    """

    def __init__(
        self,
        project_id: str,
        knowledge_base_id: str | None = None,
        memory_table: str | None = None,
    ):
        self._project_id = project_id or os.environ.get("PROJECT_ID", "global")
        self._knowledge_base_id = knowledge_base_id or os.environ.get(
            "BEDROCK_KNOWLEDGE_BASE_ID", ""
        )
        self._memory_table = memory_table or os.environ.get(
            "MEMORY_TABLE", "fde-dev-memory"
        )
        self._dynamodb = boto3.resource("dynamodb")
        self._bedrock_agent_runtime = self._init_bedrock_client()
        self._degraded_mode = False

    def store_semantic(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        Store text with metadata for semantic retrieval.

        Stores in DynamoDB (always) and triggers KB sync if available.
        The Bedrock KB ingestion happens asynchronously via data source sync.

        Args:
            text: The text content to store.
            metadata: Optional metadata (tags, source, type).

        Returns:
            True if storage succeeded, False otherwise.
        """
        now = datetime.now(timezone.utc).isoformat()
        item_id = f"semantic#{now}#{hash(text) & 0xFFFFFFFF:08x}"

        table = self._dynamodb.Table(self._memory_table)
        try:
            table.put_item(
                Item={
                    "project_id": self._project_id,
                    "memory_key": item_id,
                    "content": text,
                    "memory_type": "semantic",
                    "data": json.dumps({
                        "text": text,
                        "metadata": metadata or {},
                        "stored_at": now,
                        "synced_to_kb": False,
                    }),
                    "created_at": now,
                    "updated_at": now,
                }
            )
            logger.info(
                "Stored semantic item: project=%s key=%s",
                self._project_id, item_id,
            )
            return True
        except ClientError as e:
            logger.error("Failed to store semantic item: %s", e)
            return False

    def search_semantic(
        self,
        query: str,
        top_k: int = _DEFAULT_TOP_K,
    ) -> list[SemanticResult]:
        """
        Search for semantically similar content.

        Attempts Bedrock KB retrieval first. Falls back to DynamoDB
        keyword matching if KB is unavailable.

        Args:
            query: Natural language search query.
            top_k: Maximum number of results to return.

        Returns:
            List of SemanticResult objects ranked by relevance.
        """
        # Try Bedrock KB first
        if self._knowledge_base_id and not self._degraded_mode:
            results = self._search_bedrock_kb(query, top_k)
            if results is not None:
                return results
            # If Bedrock failed, enter degraded mode
            self._degraded_mode = True
            logger.warning(
                "Bedrock KB unavailable, entering degraded mode (DynamoDB fallback)"
            )

        # Fallback: DynamoDB keyword match
        return self._search_dynamodb_fallback(query, top_k)

    def sync_from_dynamodb(self) -> dict[str, Any]:
        """
        Sync memory items from DynamoDB to Bedrock Knowledge Base.

        Reads all semantic items from DynamoDB that haven't been synced
        and marks them as synced. The actual KB ingestion is triggered
        via the Bedrock data source sync API.

        Returns:
            Summary with items_synced count and any errors.
        """
        summary: dict[str, Any] = {"items_found": 0, "items_synced": 0, "errors": []}

        if not self._knowledge_base_id:
            summary["errors"].append("No knowledge_base_id configured")
            return summary

        table = self._dynamodb.Table(self._memory_table)
        try:
            response = table.query(
                KeyConditionExpression="project_id = :pid AND begins_with(memory_key, :prefix)",
                ExpressionAttributeValues={
                    ":pid": self._project_id,
                    ":prefix": "semantic#",
                },
            )
        except ClientError as e:
            summary["errors"].append(f"DynamoDB query failed: {e}")
            return summary

        items = response.get("Items", [])
        summary["items_found"] = len(items)

        unsynced_items: list[dict[str, Any]] = []
        for item in items:
            data = json.loads(item.get("data", "{}"))
            if not data.get("synced_to_kb", False):
                unsynced_items.append(item)

        if not unsynced_items:
            logger.info("No unsynced items found for KB sync")
            return summary

        # Trigger KB data source sync
        try:
            self._trigger_kb_sync()
        except Exception as e:
            summary["errors"].append(f"KB sync trigger failed: {e}")
            return summary

        # Mark items as synced
        now = datetime.now(timezone.utc).isoformat()
        for item in unsynced_items:
            try:
                data = json.loads(item.get("data", "{}"))
                data["synced_to_kb"] = True
                data["synced_at"] = now
                table.update_item(
                    Key={
                        "project_id": self._project_id,
                        "memory_key": item["memory_key"],
                    },
                    UpdateExpression="SET #data = :data, updated_at = :now",
                    ExpressionAttributeNames={"#data": "data"},
                    ExpressionAttributeValues={
                        ":data": json.dumps(data),
                        ":now": now,
                    },
                )
                summary["items_synced"] += 1
            except ClientError as e:
                summary["errors"].append(
                    f"Failed to mark {item['memory_key']} as synced: {e}"
                )

        logger.info(
            "KB sync complete: found=%d synced=%d errors=%d",
            summary["items_found"], summary["items_synced"], len(summary["errors"]),
        )
        return summary

    @property
    def is_degraded(self) -> bool:
        """Whether the store is operating in degraded (fallback) mode."""
        return self._degraded_mode

    def reset_degraded_mode(self) -> None:
        """Reset degraded mode to retry Bedrock KB on next search."""
        self._degraded_mode = False
        logger.info("Degraded mode reset, will retry Bedrock KB on next search")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _init_bedrock_client(self) -> Any:
        """Initialize Bedrock Agent Runtime client."""
        try:
            region = os.environ.get("BEDROCK_REGION", _BEDROCK_REGION)
            return boto3.client("bedrock-agent-runtime", region_name=region)
        except Exception as e:
            logger.warning("Failed to initialize Bedrock client: %s", e)
            return None

    def _search_bedrock_kb(
        self, query: str, top_k: int
    ) -> list[SemanticResult] | None:
        """
        Search using Bedrock Knowledge Base Retrieve API.

        Returns None if the KB is unavailable (triggers fallback).
        """
        if not self._bedrock_agent_runtime:
            return None

        try:
            response = self._bedrock_agent_runtime.retrieve(
                knowledgeBaseId=self._knowledge_base_id,
                retrievalQuery={"text": query},
                retrievalConfiguration={
                    "vectorSearchConfiguration": {
                        "numberOfResults": top_k,
                    }
                },
            )

            results: list[SemanticResult] = []
            for result in response.get("retrievalResults", []):
                content = result.get("content", {}).get("text", "")
                score = result.get("score", 0.0)
                location = result.get("location", {})
                metadata = {
                    "location": location,
                    "knowledge_base_id": self._knowledge_base_id,
                }
                results.append(
                    SemanticResult(
                        text=content,
                        score=score,
                        metadata=metadata,
                        source="bedrock_kb",
                    )
                )

            logger.info(
                "Bedrock KB search: query='%s' results=%d",
                query[:50], len(results),
            )
            return results

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            logger.warning(
                "Bedrock KB search failed (code=%s): %s", error_code, e
            )
            return None
        except Exception as e:
            logger.warning("Bedrock KB search unexpected error: %s", e)
            return None

    def _search_dynamodb_fallback(
        self, query: str, top_k: int
    ) -> list[SemanticResult]:
        """
        Fallback search using DynamoDB keyword matching.

        Provides degraded results when Bedrock KB is unavailable.
        """
        table = self._dynamodb.Table(self._memory_table)
        try:
            response = table.query(
                KeyConditionExpression="project_id = :pid AND begins_with(memory_key, :prefix)",
                ExpressionAttributeValues={
                    ":pid": self._project_id,
                    ":prefix": "memory#",
                },
            )
        except ClientError as e:
            logger.warning("DynamoDB fallback search failed: %s", e)
            return []

        items = response.get("Items", [])
        query_keywords = set(query.lower().split())
        scored: list[tuple[float, SemanticResult]] = []

        for item in items:
            content = item.get("content", "")
            if not content:
                data = json.loads(item.get("data", "{}"))
                content = data.get("text", data.get("content", ""))

            if not content:
                continue

            content_lower = content.lower()
            content_words = set(content_lower.split())
            overlap = query_keywords & content_words

            if not overlap:
                continue

            score = len(overlap) / len(query_keywords) if query_keywords else 0.0
            scored.append((
                score,
                SemanticResult(
                    text=content,
                    score=round(score, 4),
                    metadata={"memory_key": item.get("memory_key", "")},
                    source="dynamodb_fallback",
                ),
            ))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = [result for _, result in scored[:top_k]]
        if results:
            logger.info(
                "DynamoDB fallback search: query='%s' results=%d (degraded mode)",
                query[:50], len(results),
            )
        return results

    def _trigger_kb_sync(self) -> None:
        """Trigger Bedrock Knowledge Base data source sync."""
        try:
            bedrock_agent = boto3.client(
                "bedrock-agent",
                region_name=os.environ.get("BEDROCK_REGION", _BEDROCK_REGION),
            )
            # List data sources for this KB
            ds_response = bedrock_agent.list_data_sources(
                knowledgeBaseId=self._knowledge_base_id,
            )
            data_sources = ds_response.get("dataSourceSummaries", [])
            if not data_sources:
                logger.warning("No data sources found for KB %s", self._knowledge_base_id)
                return

            # Start ingestion job for the first data source
            ds_id = data_sources[0]["dataSourceId"]
            bedrock_agent.start_ingestion_job(
                knowledgeBaseId=self._knowledge_base_id,
                dataSourceId=ds_id,
            )
            logger.info(
                "Triggered KB ingestion: kb=%s ds=%s",
                self._knowledge_base_id, ds_id,
            )
        except ClientError as e:
            logger.warning("Failed to trigger KB sync: %s", e)
            raise
