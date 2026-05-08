"""
Query API — Unified Code Knowledge Base Interface (Activity 3.04).

Provides a single query interface that combines call graph data, module
descriptions, and vector search to answer questions about the codebase.
This is the primary interface used by agents to understand code context.

Methods:
  - query_module(path): Get full knowledge about a module
  - query_function(name): Find a function across all modules
  - search_by_description(text): Semantic search over module descriptions
  - get_callers(function): Who calls this function?
  - get_callees(function): What does this function call?

Results are ranked by relevance score combining exact matches, call graph
proximity, and vector similarity.

DynamoDB key schema (reads from):
  PK: project_id
  SK: "callgraph#{module_path}" | "description#{module_path}" | "vector#{id}"

Ref: docs/design/fde-core-brain-development.md Section 3 (Knowledge Plane)
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Relevance score weights for combined ranking
_WEIGHT_EXACT_MATCH = 1.0
_WEIGHT_CALL_GRAPH = 0.7
_WEIGHT_VECTOR_SIMILARITY = 0.5
_WEIGHT_DESCRIPTION_MATCH = 0.6

# Default top-k for vector search
_DEFAULT_TOP_K = 10

# Bedrock Titan Embeddings model (for vector search)
_DEFAULT_EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"


@dataclass
class QueryResult:
    """A single result from a knowledge query."""

    module_path: str
    relevance_score: float
    match_type: str  # "exact", "call_graph", "vector", "description"
    description: str = ""
    functions: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    calls_to: list[str] = field(default_factory=list)
    called_by: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModuleKnowledge:
    """Complete knowledge about a single module."""

    module_path: str
    description: str = ""
    functions: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    calls_to: list[str] = field(default_factory=list)
    called_by: list[str] = field(default_factory=list)
    class_hierarchy: dict[str, list[str]] = field(default_factory=dict)
    imports: list[str] = field(default_factory=list)
    line_count: int = 0
    last_updated: str = ""


class QueryAPI:
    """
    Unified query interface for the code knowledge base.

    Combines call graph, descriptions, and vector search to provide
    comprehensive code understanding. Used by agents to determine
    context before making changes.

    Usage:
        api = QueryAPI(project_id="my-repo")
        # Get everything about a module:
        knowledge = api.query_module("src/core/metrics/cost_tracker.py")
        # Find who calls a function:
        callers = api.get_callers("CostTracker.record")
        # Semantic search:
        results = api.search_by_description("authentication handling")
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

    def query_module(self, module_path: str) -> ModuleKnowledge | None:
        """
        Get complete knowledge about a specific module.

        Combines call graph data and description into a unified view.

        Args:
            module_path: Relative path to the module (e.g., "src/core/metrics/cost_tracker.py").

        Returns:
            ModuleKnowledge or None if the module is not indexed.
        """
        table = self._dynamodb.Table(self._knowledge_table)
        knowledge = ModuleKnowledge(module_path=module_path)

        # Fetch call graph
        call_graph = self._get_call_graph(table, module_path)
        if call_graph:
            knowledge.functions = call_graph.get("functions", [])
            knowledge.classes = call_graph.get("classes", [])
            knowledge.calls_to = call_graph.get("calls_to", [])
            knowledge.called_by = call_graph.get("called_by", [])
            knowledge.class_hierarchy = call_graph.get("class_hierarchy", {})
            knowledge.imports = call_graph.get("imports", [])
            knowledge.line_count = call_graph.get("line_count", 0)
            knowledge.last_updated = call_graph.get("extracted_at", "")

        # Fetch description
        description = self._get_description(table, module_path)
        if description:
            knowledge.description = description

        # Return None if we have no data at all
        if not call_graph and not description:
            return None

        return knowledge

    def query_function(self, function_name: str) -> list[QueryResult]:
        """
        Find a function across all indexed modules.

        Searches both top-level functions and class methods.

        Args:
            function_name: Function name to search for (e.g., "record" or
                          "CostTracker.record").

        Returns:
            List of QueryResult for modules containing this function,
            ordered by relevance.
        """
        table = self._dynamodb.Table(self._knowledge_table)
        results: list[QueryResult] = []

        # Query all call graphs for this project
        call_graphs = self._get_all_call_graphs(table)

        for graph_data in call_graphs:
            module_path = graph_data.get("module_path", "")
            functions = graph_data.get("functions", [])

            # Check for exact or partial match
            score = 0.0
            if function_name in functions:
                score = _WEIGHT_EXACT_MATCH
            elif any(function_name in f for f in functions):
                score = _WEIGHT_EXACT_MATCH * 0.8
            elif any(f.endswith(f".{function_name}") for f in functions):
                score = _WEIGHT_EXACT_MATCH * 0.9

            if score > 0:
                description = self._get_description(table, module_path) or ""
                results.append(
                    QueryResult(
                        module_path=module_path,
                        relevance_score=round(score, 4),
                        match_type="exact",
                        description=description,
                        functions=functions,
                        classes=graph_data.get("classes", []),
                        calls_to=graph_data.get("calls_to", []),
                        called_by=graph_data.get("called_by", []),
                    )
                )

        # Sort by relevance
        results.sort(key=lambda r: r.relevance_score, reverse=True)
        return results

    def search_by_description(
        self, text: str, top_k: int = _DEFAULT_TOP_K
    ) -> list[QueryResult]:
        """
        Semantic search over module descriptions using vector similarity.

        Args:
            text: Natural language query describing what you're looking for.
            top_k: Maximum number of results to return.

        Returns:
            List of QueryResult ordered by vector similarity score.
        """
        if not text.strip():
            return []

        # Get query embedding
        query_embedding = self._embed_text(text)
        if not query_embedding:
            # Fall back to keyword matching on descriptions
            return self._keyword_search_descriptions(text, top_k)

        # Search vector entries
        table = self._dynamodb.Table(self._knowledge_table)
        vector_results = self._vector_search(table, query_embedding, top_k)

        results: list[QueryResult] = []
        for entry_id, score, metadata in vector_results:
            module_path = metadata.get("module_path", "")
            if not module_path:
                continue

            description = metadata.get("text", "")
            results.append(
                QueryResult(
                    module_path=module_path,
                    relevance_score=round(score * _WEIGHT_VECTOR_SIMILARITY, 4),
                    match_type="vector",
                    description=description,
                    metadata=metadata,
                )
            )

        return results

    def get_callers(self, function_name: str) -> list[QueryResult]:
        """
        Find all modules that call a given function.

        Args:
            function_name: The function to find callers for.

        Returns:
            List of QueryResult for modules that call this function.
        """
        table = self._dynamodb.Table(self._knowledge_table)
        results: list[QueryResult] = []

        call_graphs = self._get_all_call_graphs(table)

        for graph_data in call_graphs:
            module_path = graph_data.get("module_path", "")
            calls_to = graph_data.get("calls_to", [])

            # Check if this module calls the target function
            if function_name in calls_to or any(
                call.endswith(f".{function_name}") for call in calls_to
            ):
                description = self._get_description(table, module_path) or ""
                results.append(
                    QueryResult(
                        module_path=module_path,
                        relevance_score=_WEIGHT_CALL_GRAPH,
                        match_type="call_graph",
                        description=description,
                        functions=graph_data.get("functions", []),
                        calls_to=calls_to,
                    )
                )

        results.sort(key=lambda r: r.relevance_score, reverse=True)
        return results

    def get_callees(self, function_name: str) -> list[QueryResult]:
        """
        Find all functions/modules called by a given function.

        First locates the module containing the function, then returns
        its calls_to list as results.

        Args:
            function_name: The function to find callees for.

        Returns:
            List of QueryResult for modules called by this function.
        """
        # First find the module containing this function
        function_results = self.query_function(function_name)
        if not function_results:
            return []

        # Get the calls_to from the first (best) match
        source_module = function_results[0]
        table = self._dynamodb.Table(self._knowledge_table)
        results: list[QueryResult] = []

        # For each call target, try to find its module
        call_graphs = self._get_all_call_graphs(table)

        for call_target in source_module.calls_to:
            # Try to find which module defines this function
            for graph_data in call_graphs:
                functions = graph_data.get("functions", [])
                if call_target in functions or any(
                    f.endswith(f".{call_target}") for f in functions
                ):
                    module_path = graph_data["module_path"]
                    description = self._get_description(table, module_path) or ""
                    results.append(
                        QueryResult(
                            module_path=module_path,
                            relevance_score=_WEIGHT_CALL_GRAPH,
                            match_type="call_graph",
                            description=description,
                            functions=functions,
                            metadata={"called_function": call_target},
                        )
                    )
                    break

        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_call_graph(
        self, table: Any, module_path: str
    ) -> dict[str, Any] | None:
        """Fetch a single call graph from DynamoDB."""
        try:
            response = table.get_item(
                Key={
                    "project_id": self._project_id,
                    "sk": f"callgraph#{module_path}",
                }
            )
            item = response.get("Item")
            if not item:
                return None
            return json.loads(item.get("data", "{}"))
        except ClientError as e:
            logger.warning("Failed to get call graph for %s: %s", module_path, e)
            return None

    def _get_description(self, table: Any, module_path: str) -> str | None:
        """Fetch a module description from DynamoDB."""
        try:
            response = table.get_item(
                Key={
                    "project_id": self._project_id,
                    "sk": f"description#{module_path}",
                }
            )
            item = response.get("Item")
            return item.get("description") if item else None
        except ClientError as e:
            logger.warning("Failed to get description for %s: %s", module_path, e)
            return None

    def _get_all_call_graphs(self, table: Any) -> list[dict[str, Any]]:
        """Fetch all call graphs for this project."""
        graphs: list[dict[str, Any]] = []
        try:
            response = table.query(
                KeyConditionExpression=(
                    boto3.dynamodb.conditions.Key("project_id").eq(self._project_id)
                    & boto3.dynamodb.conditions.Key("sk").begins_with("callgraph#")
                )
            )
            for item in response.get("Items", []):
                data = json.loads(item.get("data", "{}"))
                if data:
                    graphs.append(data)

            while "LastEvaluatedKey" in response:
                response = table.query(
                    KeyConditionExpression=(
                        boto3.dynamodb.conditions.Key("project_id").eq(self._project_id)
                        & boto3.dynamodb.conditions.Key("sk").begins_with("callgraph#")
                    ),
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                for item in response.get("Items", []):
                    data = json.loads(item.get("data", "{}"))
                    if data:
                        graphs.append(data)

        except ClientError as e:
            logger.warning("Failed to query call graphs: %s", e)

        return graphs

    def _vector_search(
        self, table: Any, query_embedding: list[float], top_k: int
    ) -> list[tuple[str, float, dict[str, Any]]]:
        """
        Perform vector similarity search over stored embeddings.

        Returns list of (entry_id, score, metadata) tuples.
        """
        entries: list[tuple[str, list[float], dict[str, Any]]] = []

        try:
            response = table.query(
                KeyConditionExpression=(
                    boto3.dynamodb.conditions.Key("project_id").eq(self._project_id)
                    & boto3.dynamodb.conditions.Key("sk").begins_with("vector#")
                )
            )

            for item in response.get("Items", []):
                entry_id = item.get("entry_id", "")
                embedding = json.loads(item.get("embedding", "[]"))
                metadata = json.loads(item.get("metadata", "{}"))
                metadata["text"] = item.get("text", "")
                if embedding:
                    entries.append((entry_id, embedding, metadata))

            while "LastEvaluatedKey" in response:
                response = table.query(
                    KeyConditionExpression=(
                        boto3.dynamodb.conditions.Key("project_id").eq(self._project_id)
                        & boto3.dynamodb.conditions.Key("sk").begins_with("vector#")
                    ),
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                for item in response.get("Items", []):
                    entry_id = item.get("entry_id", "")
                    embedding = json.loads(item.get("embedding", "[]"))
                    metadata = json.loads(item.get("metadata", "{}"))
                    metadata["text"] = item.get("text", "")
                    if embedding:
                        entries.append((entry_id, embedding, metadata))

        except ClientError as e:
            logger.warning("Failed to load vectors for search: %s", e)
            return []

        # Compute cosine similarity
        scored: list[tuple[str, float, dict[str, Any]]] = []
        for entry_id, embedding, metadata in entries:
            score = self._cosine_similarity(query_embedding, embedding)
            scored.append((entry_id, score, metadata))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def _keyword_search_descriptions(
        self, text: str, top_k: int
    ) -> list[QueryResult]:
        """Fallback keyword search when vector search is unavailable."""
        table = self._dynamodb.Table(self._knowledge_table)
        results: list[QueryResult] = []
        keywords = set(text.lower().split())

        try:
            response = table.query(
                KeyConditionExpression=(
                    boto3.dynamodb.conditions.Key("project_id").eq(self._project_id)
                    & boto3.dynamodb.conditions.Key("sk").begins_with("description#")
                )
            )

            for item in response.get("Items", []):
                description = item.get("description", "").lower()
                module_path = item.get("module_path", "")
                # Simple keyword overlap scoring
                matches = sum(1 for kw in keywords if kw in description)
                if matches > 0:
                    score = (matches / len(keywords)) * _WEIGHT_DESCRIPTION_MATCH
                    results.append(
                        QueryResult(
                            module_path=module_path,
                            relevance_score=round(score, 4),
                            match_type="description",
                            description=item.get("description", ""),
                        )
                    )

        except ClientError as e:
            logger.warning("Failed keyword search: %s", e)

        results.sort(key=lambda r: r.relevance_score, reverse=True)
        return results[:top_k]

    def _embed_text(self, text: str) -> list[float]:
        """Generate an embedding vector using Bedrock Titan Embeddings."""
        try:
            response = self._bedrock.invoke_model(
                modelId=self._embedding_model,
                contentType="application/json",
                accept="application/json",
                body=json.dumps({
                    "inputText": text[:8192],
                    "dimensions": 1024,
                    "normalize": True,
                }),
            )
            response_body = json.loads(response["body"].read())
            return response_body.get("embedding", [])
        except ClientError as e:
            logger.warning("Embedding generation failed: %s", e)
            return []

    @staticmethod
    def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if len(vec_a) != len(vec_b) or not vec_a:
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
        magnitude_a = math.sqrt(sum(a * a for a in vec_a))
        magnitude_b = math.sqrt(sum(b * b for b in vec_b))

        if magnitude_a == 0.0 or magnitude_b == 0.0:
            return 0.0

        return dot_product / (magnitude_a * magnitude_b)
