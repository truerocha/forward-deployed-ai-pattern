"""
Knowledge Annotation — Module Governance Mapping (Activity 3.05).

Manages knowledge annotations that link each module to its governing
knowledge artifacts. Used by the task-intake-eval-agent to determine
which knowledge context applies to each agent's work.

Each annotation records:
  - module_path: The source module being annotated
  - governing_artifacts: List of knowledge artifacts that govern this module
    (e.g., ADRs, design docs, WAF pillars, compliance rules)
  - domain_source_of_truth: The authoritative reference for this module's domain
  - last_validated: When the annotation was last confirmed accurate
  - confidence: How confident we are in the annotation (0.0 - 1.0)

DynamoDB key schema:
  PK: project_id
  SK: "annotation#{module_path}"

Ref: docs/design/fde-core-brain-development.md Section 3 (Knowledge Plane)
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


@dataclass
class KnowledgeAnnotation:
    """
    A knowledge annotation linking a module to its governing artifacts.

    Attributes:
        module_path: Relative path to the annotated module.
        governing_artifacts: List of artifact identifiers that govern this module.
            Examples: "ADR-009", "WAF/security/encryption-at-rest",
                      "docs/design/fde-core-brain-development.md"
        domain_source_of_truth: The authoritative reference document or system
            for this module's domain logic.
        last_validated: ISO timestamp of when this annotation was last confirmed.
        confidence: Confidence score (0.0 - 1.0) in the annotation's accuracy.
            1.0 = manually verified, 0.5 = auto-generated, < 0.3 = needs review.
        tags: Optional categorization tags (e.g., "security", "data-plane").
        created_by: Who/what created this annotation (agent name or "manual").
        notes: Free-form notes about the annotation.
    """

    module_path: str
    governing_artifacts: list[str] = field(default_factory=list)
    domain_source_of_truth: str = ""
    last_validated: str = ""
    confidence: float = 0.5
    tags: list[str] = field(default_factory=list)
    created_by: str = ""
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
        if not self.last_validated:
            self.last_validated = now

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "module_path": self.module_path,
            "governing_artifacts": self.governing_artifacts,
            "domain_source_of_truth": self.domain_source_of_truth,
            "last_validated": self.last_validated,
            "confidence": self.confidence,
            "tags": self.tags,
            "created_by": self.created_by,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KnowledgeAnnotation:
        """Deserialize from a dictionary."""
        return cls(
            module_path=data.get("module_path", ""),
            governing_artifacts=data.get("governing_artifacts", []),
            domain_source_of_truth=data.get("domain_source_of_truth", ""),
            last_validated=data.get("last_validated", ""),
            confidence=float(data.get("confidence", 0.5)),
            tags=data.get("tags", []),
            created_by=data.get("created_by", ""),
            notes=data.get("notes", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


class KnowledgeAnnotationStore:
    """
    CRUD operations for knowledge annotations in DynamoDB.

    Used by the task-intake-eval-agent to determine which knowledge
    context applies to each agent's work on a given module.

    Usage:
        store = KnowledgeAnnotationStore(project_id="my-repo")

        # Create an annotation
        annotation = KnowledgeAnnotation(
            module_path="src/core/metrics/cost_tracker.py",
            governing_artifacts=["ADR-009", "WAF/cost-optimization/budget-controls"],
            domain_source_of_truth="docs/design/fde-core-brain-development.md",
            confidence=0.85,
            created_by="repo-onboarding-agent",
        )
        store.create(annotation)

        # Read it back
        ann = store.get("src/core/metrics/cost_tracker.py")

        # Update confidence after manual review
        store.update("src/core/metrics/cost_tracker.py", confidence=1.0)

        # List all annotations
        all_annotations = store.list_all()

        # Delete
        store.delete("src/core/metrics/cost_tracker.py")
    """

    def __init__(
        self,
        project_id: str,
        knowledge_table: str | None = None,
    ):
        self._project_id = project_id
        self._knowledge_table = knowledge_table or os.environ.get(
            "KNOWLEDGE_TABLE", "fde-knowledge"
        )
        self._dynamodb = boto3.resource("dynamodb")

    def create(self, annotation: KnowledgeAnnotation) -> bool:
        """
        Create a new knowledge annotation.

        Args:
            annotation: The KnowledgeAnnotation to store.

        Returns:
            True if creation succeeded, False otherwise.
        """
        table = self._dynamodb.Table(self._knowledge_table)
        try:
            table.put_item(
                Item={
                    "project_id": self._project_id,
                    "sk": f"annotation#{annotation.module_path}",
                    "module_path": annotation.module_path,
                    "data": json.dumps(annotation.to_dict()),
                    "confidence": str(annotation.confidence),
                    "last_validated": annotation.last_validated,
                    "created_at": annotation.created_at,
                    "updated_at": annotation.updated_at,
                    "created_by": annotation.created_by,
                },
                ConditionExpression="attribute_not_exists(sk)",
            )
            logger.info(
                "Created annotation: project=%s module=%s",
                self._project_id,
                annotation.module_path,
            )
            return True
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "ConditionalCheckFailedException":
                logger.warning(
                    "Annotation already exists for %s, use update() instead",
                    annotation.module_path,
                )
            else:
                logger.warning(
                    "Failed to create annotation for %s: %s",
                    annotation.module_path,
                    e,
                )
            return False

    def get(self, module_path: str) -> KnowledgeAnnotation | None:
        """
        Retrieve a knowledge annotation by module path.

        Args:
            module_path: Relative path of the annotated module.

        Returns:
            KnowledgeAnnotation or None if not found.
        """
        table = self._dynamodb.Table(self._knowledge_table)
        try:
            response = table.get_item(
                Key={
                    "project_id": self._project_id,
                    "sk": f"annotation#{module_path}",
                }
            )
            item = response.get("Item")
            if not item:
                return None

            data = json.loads(item.get("data", "{}"))
            return KnowledgeAnnotation.from_dict(data)
        except ClientError as e:
            logger.warning("Failed to get annotation for %s: %s", module_path, e)
            return None

    def update(self, module_path: str, **kwargs: Any) -> bool:
        """
        Update fields of an existing annotation.

        Supported kwargs: governing_artifacts, domain_source_of_truth,
        last_validated, confidence, tags, notes.

        Args:
            module_path: The module whose annotation to update.
            **kwargs: Fields to update.

        Returns:
            True if update succeeded, False otherwise.
        """
        existing = self.get(module_path)
        if not existing:
            logger.warning("Cannot update non-existent annotation: %s", module_path)
            return False

        # Apply updates
        if "governing_artifacts" in kwargs:
            existing.governing_artifacts = kwargs["governing_artifacts"]
        if "domain_source_of_truth" in kwargs:
            existing.domain_source_of_truth = kwargs["domain_source_of_truth"]
        if "last_validated" in kwargs:
            existing.last_validated = kwargs["last_validated"]
        if "confidence" in kwargs:
            existing.confidence = float(kwargs["confidence"])
        if "tags" in kwargs:
            existing.tags = kwargs["tags"]
        if "notes" in kwargs:
            existing.notes = kwargs["notes"]

        existing.updated_at = datetime.now(timezone.utc).isoformat()

        # Persist
        table = self._dynamodb.Table(self._knowledge_table)
        try:
            table.put_item(
                Item={
                    "project_id": self._project_id,
                    "sk": f"annotation#{module_path}",
                    "module_path": module_path,
                    "data": json.dumps(existing.to_dict()),
                    "confidence": str(existing.confidence),
                    "last_validated": existing.last_validated,
                    "created_at": existing.created_at,
                    "updated_at": existing.updated_at,
                    "created_by": existing.created_by,
                }
            )
            logger.info(
                "Updated annotation: project=%s module=%s",
                self._project_id,
                module_path,
            )
            return True
        except ClientError as e:
            logger.warning("Failed to update annotation for %s: %s", module_path, e)
            return False

    def delete(self, module_path: str) -> bool:
        """
        Delete a knowledge annotation.

        Args:
            module_path: The module whose annotation to delete.

        Returns:
            True if deletion succeeded, False otherwise.
        """
        table = self._dynamodb.Table(self._knowledge_table)
        try:
            table.delete_item(
                Key={
                    "project_id": self._project_id,
                    "sk": f"annotation#{module_path}",
                }
            )
            logger.info(
                "Deleted annotation: project=%s module=%s",
                self._project_id,
                module_path,
            )
            return True
        except ClientError as e:
            logger.warning("Failed to delete annotation for %s: %s", module_path, e)
            return False

    def list_all(self) -> list[KnowledgeAnnotation]:
        """
        List all annotations for this project.

        Returns:
            List of KnowledgeAnnotation objects.
        """
        table = self._dynamodb.Table(self._knowledge_table)
        annotations: list[KnowledgeAnnotation] = []

        try:
            response = table.query(
                KeyConditionExpression=(
                    boto3.dynamodb.conditions.Key("project_id").eq(self._project_id)
                    & boto3.dynamodb.conditions.Key("sk").begins_with("annotation#")
                )
            )

            for item in response.get("Items", []):
                data = json.loads(item.get("data", "{}"))
                if data:
                    annotations.append(KnowledgeAnnotation.from_dict(data))

            while "LastEvaluatedKey" in response:
                response = table.query(
                    KeyConditionExpression=(
                        boto3.dynamodb.conditions.Key("project_id").eq(self._project_id)
                        & boto3.dynamodb.conditions.Key("sk").begins_with("annotation#")
                    ),
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                for item in response.get("Items", []):
                    data = json.loads(item.get("data", "{}"))
                    if data:
                        annotations.append(KnowledgeAnnotation.from_dict(data))

        except ClientError as e:
            logger.warning("Failed to list annotations: %s", e)

        return annotations

    def list_by_artifact(self, artifact_id: str) -> list[KnowledgeAnnotation]:
        """
        Find all modules governed by a specific artifact.

        Args:
            artifact_id: The artifact identifier (e.g., "ADR-009").

        Returns:
            List of annotations that reference this artifact.
        """
        all_annotations = self.list_all()
        return [
            ann
            for ann in all_annotations
            if artifact_id in ann.governing_artifacts
        ]

    def list_by_tag(self, tag: str) -> list[KnowledgeAnnotation]:
        """
        Find all annotations with a specific tag.

        Args:
            tag: The tag to filter by.

        Returns:
            List of annotations with this tag.
        """
        all_annotations = self.list_all()
        return [ann for ann in all_annotations if tag in ann.tags]

    def list_stale(self, max_age_days: int = 90) -> list[KnowledgeAnnotation]:
        """
        Find annotations that haven't been validated recently.

        Args:
            max_age_days: Maximum days since last validation before
                         considering stale.

        Returns:
            List of stale annotations.
        """
        all_annotations = self.list_all()
        now = datetime.now(timezone.utc)
        stale: list[KnowledgeAnnotation] = []

        for ann in all_annotations:
            try:
                validated = datetime.fromisoformat(ann.last_validated)
                age_days = (now - validated).days
                if age_days > max_age_days:
                    stale.append(ann)
            except (ValueError, TypeError):
                # If we can't parse the date, consider it stale
                stale.append(ann)

        return stale

    def list_low_confidence(self, threshold: float = 0.5) -> list[KnowledgeAnnotation]:
        """
        Find annotations with confidence below a threshold.

        Args:
            threshold: Minimum acceptable confidence score.

        Returns:
            List of low-confidence annotations needing review.
        """
        all_annotations = self.list_all()
        return [ann for ann in all_annotations if ann.confidence < threshold]
