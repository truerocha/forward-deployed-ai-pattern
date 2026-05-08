"""
Vector Store — Embedding-Based Code Knowledge Search (Activity 3.03).

Manages vector embeddings for code knowledge entries using Bedrock Titan
Embeddings for vectorization. Stores vectors in DynamoDB with cosine
similarity search over stored embeddings.

This is the interim implementation before Bedrock Knowledge Base integration
(Activity 3.16). It provides the same interface so the migration is seamless.

Methods:
  - index(text, metadata): Embed text and store with metadata
  - search(query, top_k): Find most similar entries by cosine similarity
  - delete(entry_id): Remove an entry from the store

DynamoDB key schema:
  PK: project_id
  SK: "vector#{entry_id}"

Ref: docs/design/fde-core-brain-development.md Section 3 (Knowledge Plane)
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Bedrock Titan Embeddings model
_DEFAULT_EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"

# Embedding dimension for Titan v2
_EMBEDDING_DIMENSION = 1024

# Maximum text length for embedding (Titan limit)
_MAX_TEXT_LENGTH = 8192


@dataclass
class VectorEntry:
    """A single vector entry in the store."""

    entry_id: str
    text: str
    embedding: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()


@dataclass
class SearchResult:
    """A single search result with relevance score."""

    entry_id: str
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


class VectorStore:
    """
    Manages vector embeddings for code knowledge entries.

    Uses Bedrock Titan Embeddings for vectorization and DynamoDB for storage.
    Performs cosine similarity search over stored embeddings.

    Usage:
        store = VectorStore(project_id="my-repo")
        entry_id = store.index(
            text="This module handles OAuth2 authentication",
            metadata={"module_path": "src/auth/oauth.py", "type": "description"}
        )
        results = store.search("authentication flow", top_k=5)
        store.delete(entry_id)
    """

    def __init__(
        self,
        project_id: str,
        knowledge_table: str | None = None,
        embedding_model: str | None = None,
    ):
        self._project_id = project_id
        self._knowledge_table = knowledge_table or os.environ.get(
            "KNOWLEDGE_TABLE", "fde-knowledge"
        )
        self._embedding_model = embedding_model or os.environ.get(
            "EMBEDDING_MODEL_ID", _DEFAULT_EMBEDDING_MODEL
        )
        self._dynamodb = boto3.resource("dynamodb")
        self._bedrock = boto3.client("bedrock-runtime")

        # In-memory cache for search (loaded lazily)
        self._cache: list[VectorEntry] | None = None
        self._cache_loaded_at: float = 0.0

    def index(self, text: str, metadata: dict[str, Any] | None = None) -> str:
        """
        Embed text and store it with metadata.

        Args:
            text: The text content to embed and index.
            metadata: Optional metadata dict (module_path, type, etc.).

        Returns:
            The entry_id of the stored vector.

        Raises:
            ValueError: If text is empty or exceeds maximum length.
        """
        if not text.strip():
            raise ValueError("Cannot index empty text")

        # Truncate if too long
        truncated_text = text[:_MAX_TEXT_LENGTH]

        # Generate a deterministic ID based on content + project
        entry_id = self._generate_entry_id(truncated_text, metadata)

        # Get embedding from Bedrock
        embedding = self._embed_text(truncated_text)
        if not embedding:
            logger.warning("Failed to generate embedding, skipping index")
            return ""

        entry = VectorEntry(
            entry_id=entry_id,
            text=truncated_text,
            embedding=embedding,
            metadata=metadata or {},
        )

        # Persist to DynamoDB
        self._persist_entry(entry)

        # Invalidate cache
        self._cache = None

        return entry_id

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """
        Find the most similar entries by cosine similarity.

        Args:
            query: The search query text.
            top_k: Number of top results to return.

        Returns:
            List of SearchResult ordered by descending similarity score.
        """
        if not query.strip():
            return []

        # Embed the query
        query_embedding = self._embed_text(query)
        if not query_embedding:
            return []

        # Load all vectors (from cache or DynamoDB)
        entries = self._load_all_entries()
        if not entries:
            return []

        # Compute cosine similarity against all entries
        scored: list[tuple[float, VectorEntry]] = []
        for entry in entries:
            if entry.embedding:
                score = self._cosine_similarity(query_embedding, entry.embedding)
                scored.append((score, entry))

        # Sort by score descending and take top_k
        scored.sort(key=lambda x: x[0], reverse=True)
        top_results = scored[:top_k]

        return [
            SearchResult(
                entry_id=entry.entry_id,
                text=entry.text,
                score=round(score, 4),
                metadata=entry.metadata,
            )
            for score, entry in top_results
        ]

    def delete(self, entry_id: str) -> bool:
        """
        Remove an entry from the vector store.

        Args:
            entry_id: The ID of the entry to delete.

        Returns:
            True if deletion succeeded, False otherwise.
        """
        table = self._dynamodb.Table(self._knowledge_table)
        try:
            table.delete_item(
                Key={
                    "project_id": self._project_id,
                    "sk": f"vector#{entry_id}",
                }
            )
            # Invalidate cache
            self._cache = None
            return True
        except ClientError as e:
            logger.warning("Failed to delete vector entry %s: %s", entry_id, e)
            return False

    def get_entry(self, entry_id: str) -> VectorEntry | None:
        """
        Retrieve a specific vector entry by ID.

        Args:
            entry_id: The entry identifier.

        Returns:
            VectorEntry or None if not found.
        """
        table = self._dynamodb.Table(self._knowledge_table)
        try:
            response = table.get_item(
                Key={
                    "project_id": self._project_id,
                    "sk": f"vector#{entry_id}",
                }
            )
            item = response.get("Item")
            if not item:
                return None

            return VectorEntry(
                entry_id=item["entry_id"],
                text=item.get("text", ""),
                embedding=json.loads(item.get("embedding", "[]")),
                metadata=json.loads(item.get("metadata", "{}")),
                created_at=item.get("created_at", ""),
            )
        except ClientError as e:
            logger.warning("Failed to get vector entry %s: %s", entry_id, e)
            return None

    def count(self) -> int:
        """Return the number of indexed entries for this project."""
        entries = self._load_all_entries()
        return len(entries)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _embed_text(self, text: str) -> list[float]:
        """Generate an embedding vector using Bedrock Titan Embeddings."""
        try:
            response = self._bedrock.invoke_model(
                modelId=self._embedding_model,
                contentType="application/json",
                accept="application/json",
                body=json.dumps({
                    "inputText": text,
                    "dimensions": _EMBEDDING_DIMENSION,
                    "normalize": True,
                }),
            )
            response_body = json.loads(response["body"].read())
            embedding = response_body.get("embedding", [])
            return embedding
        except ClientError as e:
            logger.warning("Embedding generation failed: %s", e)
            return []

    def _persist_entry(self, entry: VectorEntry) -> None:
        """Store a vector entry in DynamoDB."""
        table = self._dynamodb.Table(self._knowledge_table)
        try:
            table.put_item(
                Item={
                    "project_id": self._project_id,
                    "sk": f"vector#{entry.entry_id}",
                    "entry_id": entry.entry_id,
                    "text": entry.text,
                    "embedding": json.dumps(entry.embedding),
                    "metadata": json.dumps(entry.metadata),
                    "created_at": entry.created_at,
                }
            )
        except ClientError as e:
            logger.warning("Failed to persist vector entry %s: %s", entry.entry_id, e)

    def _load_all_entries(self) -> list[VectorEntry]:
        """Load all vector entries from DynamoDB (with caching)."""
        # Use cache if fresh (within 60 seconds)
        if self._cache is not None and (time.time() - self._cache_loaded_at) < 60:
            return self._cache

        table = self._dynamodb.Table(self._knowledge_table)
        entries: list[VectorEntry] = []

        try:
            response = table.query(
                KeyConditionExpression=(
                    boto3.dynamodb.conditions.Key("project_id").eq(self._project_id)
                    & boto3.dynamodb.conditions.Key("sk").begins_with("vector#")
                )
            )

            for item in response.get("Items", []):
                entries.append(self._item_to_entry(item))

            # Handle pagination
            while "LastEvaluatedKey" in response:
                response = table.query(
                    KeyConditionExpression=(
                        boto3.dynamodb.conditions.Key("project_id").eq(self._project_id)
                        & boto3.dynamodb.conditions.Key("sk").begins_with("vector#")
                    ),
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                for item in response.get("Items", []):
                    entries.append(self._item_to_entry(item))

        except ClientError as e:
            logger.warning("Failed to load vector entries: %s", e)

        self._cache = entries
        self._cache_loaded_at = time.time()
        return entries

    def _item_to_entry(self, item: dict[str, Any]) -> VectorEntry:
        """Convert a DynamoDB item to a VectorEntry."""
        return VectorEntry(
            entry_id=item.get("entry_id", ""),
            text=item.get("text", ""),
            embedding=json.loads(item.get("embedding", "[]")),
            metadata=json.loads(item.get("metadata", "{}")),
            created_at=item.get("created_at", ""),
        )

    @staticmethod
    def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
        """
        Compute cosine similarity between two vectors.

        Returns a value between -1.0 and 1.0 (1.0 = identical direction).
        """
        if len(vec_a) != len(vec_b) or not vec_a:
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
        magnitude_a = math.sqrt(sum(a * a for a in vec_a))
        magnitude_b = math.sqrt(sum(b * b for b in vec_b))

        if magnitude_a == 0.0 or magnitude_b == 0.0:
            return 0.0

        return dot_product / (magnitude_a * magnitude_b)

    @staticmethod
    def _generate_entry_id(text: str, metadata: dict[str, Any] | None) -> str:
        """Generate a deterministic entry ID from content."""
        content_key = text + json.dumps(metadata or {}, sort_keys=True)
        content_hash = hashlib.sha256(content_key.encode()).hexdigest()[:16]
        return f"vec-{content_hash}"
