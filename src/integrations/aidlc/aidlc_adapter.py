"""
AI-DLC Adapter — Reads SharedState artifacts from S3 and converts to factory spec format.

The AI-DLC (AI Development Lifecycle) system produces SharedState artifacts
that describe tasks, acceptance criteria, and context. This adapter reads
those artifacts from a known S3 prefix and converts them into the factory's
internal spec format for ingestion by the orchestrator.

Activity: 5.01
Ref: docs/integration/aidlc-handoff.md

Feature flag: ENABLE_AIDLC_ADAPTER (default: false)

S3 prefix convention:
    s3://{bucket}/{prefix}/{project_id}/shared-state/
    └── task-{uuid}.json          — individual task artifacts
    └── manifest.json             — optional manifest listing all tasks

Schema versions supported:
    - v1.0: Original AI-DLC SharedState format
    - v1.1: Extended with acceptance_criteria array

Usage:
    adapter = AIDLCAdapter(
        project_id="PROJ-123",
        s3_bucket="aidlc-artifacts-prod",
        s3_prefix="shared-state",
    )
    specs = adapter.fetch_and_convert()
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger("fde.integrations.aidlc")

# Feature flag
ENABLE_AIDLC_ADAPTER = os.environ.get("ENABLE_AIDLC_ADAPTER", "false").lower() == "true"

# Supported schema versions
_SUPPORTED_SCHEMA_VERSIONS = {"1.0", "1.1"}

_AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


class AIDLCSchemaError(Exception):
    """Raised when an AI-DLC artifact has an unsupported or invalid schema version."""

    def __init__(self, version: str, supported: set[str] | None = None):
        self.version = version
        self.supported = supported or _SUPPORTED_SCHEMA_VERSIONS
        super().__init__(
            f"Unsupported AI-DLC schema version '{version}'. "
            f"Supported versions: {sorted(self.supported)}. "
            f"Please update the AI-DLC adapter or downgrade the artifact schema."
        )


class AIDLCAdapterDisabledError(Exception):
    """Raised when the adapter is called but the feature flag is disabled."""

    def __init__(self):
        super().__init__(
            "AI-DLC adapter is disabled. Set ENABLE_AIDLC_ADAPTER=true to enable. "
            "See docs/integration/aidlc-handoff.md for setup instructions."
        )


@dataclass
class FactorySpec:
    """Factory-internal spec format produced by the adapter.

    This is the normalized representation that the orchestrator consumes,
    regardless of the source system (AI-DLC, Jira, manual, etc.).
    """

    task_id: str
    user_value: str
    acceptance_criteria: list[str]
    context: dict[str, Any]
    source: str = "aidlc"
    source_version: str = ""
    raw_artifact: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for orchestrator consumption."""
        return {
            "task_id": self.task_id,
            "user_value": self.user_value,
            "acceptance_criteria": self.acceptance_criteria,
            "context": self.context,
            "source": self.source,
            "source_version": self.source_version,
        }


@dataclass
class AIDLCAdapter:
    """Reads AI-DLC SharedState artifacts from S3 and converts to factory specs.

    Attributes:
        project_id: Factory project identifier.
        s3_bucket: S3 bucket containing AI-DLC artifacts.
        s3_prefix: S3 key prefix for the project's shared-state directory.
    """

    project_id: str
    s3_bucket: str
    s3_prefix: str
    _s3_client: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not ENABLE_AIDLC_ADAPTER:
            logger.warning("AI-DLC adapter instantiated but feature flag is disabled")
        self._s3_client = boto3.client("s3", region_name=_AWS_REGION)

    def fetch_and_convert(self) -> list[FactorySpec]:
        """Fetch all AI-DLC artifacts from S3 and convert to factory specs.

        Returns:
            List of FactorySpec objects ready for orchestrator ingestion.

        Raises:
            AIDLCAdapterDisabledError: If ENABLE_AIDLC_ADAPTER is false.
            AIDLCSchemaError: If any artifact has an unsupported schema version.
        """
        if not ENABLE_AIDLC_ADAPTER:
            raise AIDLCAdapterDisabledError()

        artifacts = self._list_artifacts()
        specs = []

        for artifact_key in artifacts:
            raw = self._read_artifact(artifact_key)
            if raw is not None:
                spec = self._convert_artifact(raw, artifact_key)
                specs.append(spec)

        logger.info(
            "AI-DLC adapter converted %d artifacts for project %s",
            len(specs), self.project_id,
        )
        return specs

    def fetch_single(self, task_artifact_key: str) -> FactorySpec:
        """Fetch and convert a single AI-DLC artifact by S3 key.

        Args:
            task_artifact_key: Full S3 key to the task artifact JSON.

        Returns:
            FactorySpec for the single artifact.

        Raises:
            AIDLCAdapterDisabledError: If feature flag is disabled.
            AIDLCSchemaError: If artifact has unsupported schema version.
            FileNotFoundError: If artifact does not exist in S3.
        """
        if not ENABLE_AIDLC_ADAPTER:
            raise AIDLCAdapterDisabledError()

        raw = self._read_artifact(task_artifact_key)
        if raw is None:
            raise FileNotFoundError(
                f"AI-DLC artifact not found: s3://{self.s3_bucket}/{task_artifact_key}"
            )
        return self._convert_artifact(raw, task_artifact_key)

    def validate_schema(self, artifact: dict[str, Any]) -> bool:
        """Validate that an artifact's schema version is supported.

        Args:
            artifact: Parsed JSON artifact from AI-DLC.

        Returns:
            True if schema version is supported.

        Raises:
            AIDLCSchemaError: If schema version is unknown or unsupported.
        """
        version = artifact.get("schema_version", artifact.get("version", ""))
        if not version:
            raise AIDLCSchemaError(
                version="<missing>",
                supported=_SUPPORTED_SCHEMA_VERSIONS,
            )

        if version not in _SUPPORTED_SCHEMA_VERSIONS:
            raise AIDLCSchemaError(
                version=version,
                supported=_SUPPORTED_SCHEMA_VERSIONS,
            )

        return True

    def _list_artifacts(self) -> list[str]:
        """List all task artifact keys under the project's S3 prefix."""
        prefix = f"{self.s3_prefix}/{self.project_id}/shared-state/"
        artifact_keys = []

        try:
            paginator = self._s3_client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.s3_bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    # Only include task JSON files, skip manifest
                    if key.endswith(".json") and "task-" in key.split("/")[-1]:
                        artifact_keys.append(key)
        except ClientError as e:
            logger.error(
                "Failed to list AI-DLC artifacts at s3://%s/%s: %s",
                self.s3_bucket, prefix, e,
            )

        logger.debug("Found %d AI-DLC artifacts for project %s", len(artifact_keys), self.project_id)
        return artifact_keys

    def _read_artifact(self, key: str) -> dict[str, Any] | None:
        """Read and parse a single artifact from S3.

        Returns None if the object cannot be read or parsed.
        """
        try:
            response = self._s3_client.get_object(Bucket=self.s3_bucket, Key=key)
            body = response["Body"].read().decode("utf-8")
            return json.loads(body)
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "NoSuchKey":
                logger.warning("AI-DLC artifact not found: s3://%s/%s", self.s3_bucket, key)
            else:
                logger.error("Failed to read AI-DLC artifact s3://%s/%s: %s", self.s3_bucket, key, e)
            return None
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error("Failed to parse AI-DLC artifact s3://%s/%s: %s", self.s3_bucket, key, e)
            return None

    def _convert_artifact(self, artifact: dict[str, Any], source_key: str) -> FactorySpec:
        """Convert a raw AI-DLC artifact to FactorySpec format.

        Args:
            artifact: Parsed JSON artifact.
            source_key: S3 key for logging/tracing.

        Returns:
            FactorySpec instance.

        Raises:
            AIDLCSchemaError: If schema version is unsupported.
        """
        # Validate schema version
        self.validate_schema(artifact)

        version = artifact.get("schema_version", artifact.get("version", "1.0"))

        # Extract fields based on schema version
        if version == "1.0":
            return self._convert_v1_0(artifact, source_key)
        elif version == "1.1":
            return self._convert_v1_1(artifact, source_key)
        else:
            # Should not reach here due to validate_schema, but defensive
            raise AIDLCSchemaError(version=version)

    def _convert_v1_0(self, artifact: dict[str, Any], source_key: str) -> FactorySpec:
        """Convert v1.0 schema artifact."""
        shared_state = artifact.get("shared_state", artifact)

        task_id = (
            shared_state.get("task_id")
            or shared_state.get("id")
            or f"aidlc-{self.project_id}-unknown"
        )

        user_value = (
            shared_state.get("user_value")
            or shared_state.get("description", "")
            or shared_state.get("objective", "")
        )

        # v1.0 has acceptance_criteria as a single string or missing
        ac_raw = shared_state.get("acceptance_criteria", "")
        if isinstance(ac_raw, str):
            acceptance_criteria = [ac_raw] if ac_raw else []
        elif isinstance(ac_raw, list):
            acceptance_criteria = ac_raw
        else:
            acceptance_criteria = []

        context = {
            "source_key": source_key,
            "project_id": self.project_id,
            "dependencies": shared_state.get("dependencies", []),
            "priority": shared_state.get("priority", "medium"),
            "tags": shared_state.get("tags", []),
        }

        return FactorySpec(
            task_id=task_id,
            user_value=user_value,
            acceptance_criteria=acceptance_criteria,
            context=context,
            source="aidlc",
            source_version=str(artifact.get("schema_version", "1.0")),
            raw_artifact=artifact,
        )

    def _convert_v1_1(self, artifact: dict[str, Any], source_key: str) -> FactorySpec:
        """Convert v1.1 schema artifact (extended with structured AC)."""
        shared_state = artifact.get("shared_state", artifact)

        task_id = (
            shared_state.get("task_id")
            or shared_state.get("id")
            or f"aidlc-{self.project_id}-unknown"
        )

        user_value = (
            shared_state.get("user_value")
            or shared_state.get("user_story", "")
            or shared_state.get("description", "")
        )

        # v1.1 has acceptance_criteria as a structured array
        ac_raw = shared_state.get("acceptance_criteria", [])
        if isinstance(ac_raw, list):
            # Each item may be a string or a dict with "description" key
            acceptance_criteria = []
            for item in ac_raw:
                if isinstance(item, str):
                    acceptance_criteria.append(item)
                elif isinstance(item, dict):
                    acceptance_criteria.append(
                        item.get("description", item.get("text", str(item)))
                    )
                else:
                    acceptance_criteria.append(str(item))
        elif isinstance(ac_raw, str):
            acceptance_criteria = [ac_raw] if ac_raw else []
        else:
            acceptance_criteria = []

        context = {
            "source_key": source_key,
            "project_id": self.project_id,
            "dependencies": shared_state.get("dependencies", []),
            "priority": shared_state.get("priority", "medium"),
            "tags": shared_state.get("tags", []),
            "technical_context": shared_state.get("technical_context", {}),
            "constraints": shared_state.get("constraints", []),
        }

        return FactorySpec(
            task_id=task_id,
            user_value=user_value,
            acceptance_criteria=acceptance_criteria,
            context=context,
            source="aidlc",
            source_version=str(artifact.get("schema_version", "1.1")),
            raw_artifact=artifact,
        )
