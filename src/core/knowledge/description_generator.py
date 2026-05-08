"""
Description Generator — Business-Level Module Summarization (Activity 3.02).

Takes call graph output and source code snippets, then uses the Bedrock
Converse API (fast tier) to generate business-level descriptions for each
module. Descriptions explain *what* a module does in domain terms, not
implementation details.

Example output:
  {
    "src/core/metrics/cost_tracker.py":
      "Tracks per-agent and per-task token costs for Bedrock invocations,
       enforces budget thresholds, and emits CloudWatch alarms when tasks
       exceed cost limits."
  }

DynamoDB key schema:
  PK: project_id
  SK: "description#{module_path}"

Ref: docs/design/fde-core-brain-development.md Section 3 (Knowledge Plane)
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

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Bedrock model for fast-tier summarization
_DEFAULT_MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"

# Maximum source snippet length sent to the model (characters)
_MAX_SNIPPET_CHARS = 4000

# System prompt for description generation
_SYSTEM_PROMPT = (
    "You are a senior software architect. Given a Python module's call graph "
    "and source code snippet, write a concise 1-2 sentence business-level "
    "description of what this module does. Focus on the domain purpose, not "
    "implementation details. Do not mention specific variable names or line "
    "numbers. Write in present tense."
)


@dataclass
class ModuleDescription:
    """A business-level description for a single module."""

    module_path: str
    description: str
    generated_at: str = ""
    model_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0

    def __post_init__(self) -> None:
        if not self.generated_at:
            self.generated_at = datetime.now(timezone.utc).isoformat()


@dataclass
class DescriptionBatch:
    """Results from a batch description generation run."""

    project_id: str
    descriptions: dict[str, str] = field(default_factory=dict)
    total_modules: int = 0
    successful: int = 0
    failed: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    elapsed_seconds: float = 0.0


class DescriptionGenerator:
    """
    Generates business-level descriptions for Python modules using Bedrock.

    Usage:
        generator = DescriptionGenerator(
            project_id="my-repo",
            workspace_path="/mnt/efs/workspaces/my-repo",
            knowledge_table="fde-knowledge-prod",
        )
        # With call graph data (from CallGraphExtractor output):
        batch = generator.generate_descriptions(call_graphs)
        generator.persist_descriptions(batch)
    """

    def __init__(
        self,
        project_id: str,
        workspace_path: str,
        knowledge_table: str | None = None,
        model_id: str | None = None,
    ):
        self._project_id = project_id
        self._workspace_path = Path(workspace_path)
        self._knowledge_table = knowledge_table or os.environ.get(
            "KNOWLEDGE_TABLE", "fde-knowledge"
        )
        self._model_id = model_id or os.environ.get(
            "DESCRIPTION_MODEL_ID", _DEFAULT_MODEL_ID
        )
        self._dynamodb = boto3.resource("dynamodb")
        self._bedrock = boto3.client("bedrock-runtime")

    def generate_descriptions(
        self, call_graphs: list[dict[str, Any]]
    ) -> DescriptionBatch:
        """
        Generate descriptions for all modules in the call graph set.

        Args:
            call_graphs: List of call graph dicts (from CallGraphExtractor.to_dict()).
                         Each must have at minimum: module_path, functions, classes,
                         calls_to, imports.

        Returns:
            DescriptionBatch with all generated descriptions.
        """
        batch = DescriptionBatch(
            project_id=self._project_id,
            total_modules=len(call_graphs),
        )
        start = time.time()

        for graph_data in call_graphs:
            module_path = graph_data.get("module_path", "")
            if not module_path:
                batch.failed += 1
                continue

            description = self._generate_single(graph_data)
            if description:
                batch.descriptions[module_path] = description.description
                batch.successful += 1
                batch.total_input_tokens += description.input_tokens
                batch.total_output_tokens += description.output_tokens
            else:
                batch.failed += 1

        batch.elapsed_seconds = round(time.time() - start, 2)
        logger.info(
            "Generated descriptions: project=%s success=%d/%d elapsed=%.2fs",
            self._project_id,
            batch.successful,
            batch.total_modules,
            batch.elapsed_seconds,
        )
        return batch

    def generate_single_description(
        self, module_path: str, call_graph: dict[str, Any]
    ) -> ModuleDescription | None:
        """
        Generate a description for a single module.

        Args:
            module_path: Relative path to the module.
            call_graph: Call graph dict for this module.

        Returns:
            ModuleDescription or None on failure.
        """
        call_graph["module_path"] = module_path
        return self._generate_single(call_graph)

    def persist_descriptions(self, batch: DescriptionBatch) -> int:
        """
        Persist all generated descriptions to DynamoDB.

        Args:
            batch: DescriptionBatch from generate_descriptions().

        Returns:
            Number of successfully persisted items.
        """
        persisted = 0
        table = self._dynamodb.Table(self._knowledge_table)

        for module_path, description in batch.descriptions.items():
            try:
                table.put_item(
                    Item={
                        "project_id": self._project_id,
                        "sk": f"description#{module_path}",
                        "module_path": module_path,
                        "description": description,
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "model_id": self._model_id,
                    }
                )
                persisted += 1
            except ClientError as e:
                logger.warning(
                    "Failed to persist description for %s: %s", module_path, e
                )

        logger.info(
            "Persisted descriptions: project=%s persisted=%d/%d",
            self._project_id,
            persisted,
            len(batch.descriptions),
        )
        return persisted

    def get_description(self, module_path: str) -> str | None:
        """
        Retrieve a stored description from DynamoDB.

        Args:
            module_path: Relative path of the module.

        Returns:
            Description string or None if not found.
        """
        table = self._dynamodb.Table(self._knowledge_table)
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
            logger.warning(
                "Failed to retrieve description for %s: %s", module_path, e
            )
            return None

    def get_all_descriptions(self) -> dict[str, str]:
        """
        Retrieve all stored descriptions for this project.

        Returns:
            Dict mapping module_path to description string.
        """
        table = self._dynamodb.Table(self._knowledge_table)
        descriptions: dict[str, str] = {}

        try:
            response = table.query(
                KeyConditionExpression=(
                    boto3.dynamodb.conditions.Key("project_id").eq(self._project_id)
                    & boto3.dynamodb.conditions.Key("sk").begins_with("description#")
                )
            )
            for item in response.get("Items", []):
                module_path = item.get("module_path", "")
                description = item.get("description", "")
                if module_path and description:
                    descriptions[module_path] = description

            # Handle pagination
            while "LastEvaluatedKey" in response:
                response = table.query(
                    KeyConditionExpression=(
                        boto3.dynamodb.conditions.Key("project_id").eq(self._project_id)
                        & boto3.dynamodb.conditions.Key("sk").begins_with("description#")
                    ),
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                for item in response.get("Items", []):
                    module_path = item.get("module_path", "")
                    description = item.get("description", "")
                    if module_path and description:
                        descriptions[module_path] = description

        except ClientError as e:
            logger.warning("Failed to query descriptions: %s", e)

        return descriptions

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _generate_single(self, graph_data: dict[str, Any]) -> ModuleDescription | None:
        """Generate a description for one module via Bedrock Converse."""
        module_path = graph_data["module_path"]

        # Build the user prompt with call graph context and source snippet
        user_content = self._build_prompt(graph_data)

        try:
            response = self._bedrock.converse(
                modelId=self._model_id,
                system=[{"text": _SYSTEM_PROMPT}],
                messages=[
                    {
                        "role": "user",
                        "content": [{"text": user_content}],
                    }
                ],
                inferenceConfig={
                    "maxTokens": 200,
                    "temperature": 0.2,
                },
            )

            # Extract the generated text
            output_message = response.get("output", {}).get("message", {})
            content_blocks = output_message.get("content", [])
            description_text = ""
            for block in content_blocks:
                if "text" in block:
                    description_text += block["text"]

            # Extract token usage
            usage = response.get("usage", {})
            input_tokens = usage.get("inputTokens", 0)
            output_tokens = usage.get("outputTokens", 0)

            if not description_text.strip():
                logger.warning("Empty description returned for %s", module_path)
                return None

            return ModuleDescription(
                module_path=module_path,
                description=description_text.strip(),
                model_id=self._model_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

        except ClientError as e:
            logger.warning(
                "Bedrock call failed for %s: %s", module_path, e
            )
            return None

    def _build_prompt(self, graph_data: dict[str, Any]) -> str:
        """Build the user prompt combining call graph and source snippet."""
        module_path = graph_data["module_path"]
        functions = graph_data.get("functions", [])
        classes = graph_data.get("classes", [])
        calls_to = graph_data.get("calls_to", [])
        imports = graph_data.get("imports", [])

        # Try to read source snippet
        source_snippet = self._read_source_snippet(module_path)

        prompt_parts = [
            f"Module: {module_path}",
            f"Classes: {', '.join(classes) if classes else 'None'}",
            f"Functions: {', '.join(functions[:20]) if functions else 'None'}",
            f"External calls: {', '.join(calls_to[:15]) if calls_to else 'None'}",
            f"Imports: {', '.join(imports[:15]) if imports else 'None'}",
        ]

        if source_snippet:
            prompt_parts.append(f"\nSource code (first {_MAX_SNIPPET_CHARS} chars):")
            prompt_parts.append(source_snippet)

        prompt_parts.append(
            "\nWrite a concise 1-2 sentence business-level description of this module."
        )

        return "\n".join(prompt_parts)

    def _read_source_snippet(self, module_path: str) -> str:
        """Read the first N characters of a module's source code."""
        full_path = self._workspace_path / module_path
        try:
            if not full_path.exists():
                return ""
            text = full_path.read_text(encoding="utf-8", errors="replace")
            return text[:_MAX_SNIPPET_CHARS]
        except OSError:
            return ""
