#!/usr/bin/env python3
"""
Migrate Memory — One-Time Migration Script (Activity 3.12).

Converts existing cross_session_notes/ markdown files to the new
unified memory format in DynamoDB.

Operations:
  1. Reads markdown files from cross_session_notes/ directory
  2. Parses each note into: type (decision/outcome/learning), content, timestamp
  3. Writes to DynamoDB memory table using MemoryManager.store()
  4. Idempotent: skips already-migrated items (checks by content hash)
  5. Archives original files to S3 (preserves, does not delete)

Usage:
    python3 scripts/migrate_memory.py --project-id my-repo --notes-dir ./cross_session_notes

Options:
    --project-id    Project identifier for DynamoDB partition key
    --notes-dir     Path to cross_session_notes directory (default: ./cross_session_notes)
    --memory-table  DynamoDB table name (default: fde-dev-memory from env)
    --archive-bucket S3 bucket for archiving originals (default: from ARTIFACTS_BUCKET env)
    --dry-run       Parse and report without writing to DynamoDB

Ref: docs/design/fde-core-brain-development.md Section 3 (Wave 3)
     docs/adr/ADR-007-cross-session-learning-notes.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.memory.memory_manager import MemoryManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Patterns for detecting memory type from note content
_TYPE_PATTERNS: dict[str, list[str]] = {
    "decision": [
        r"(?i)\bdecision\b",
        r"(?i)\bdecided\b",
        r"(?i)\bchose\b",
        r"(?i)\bselected\b",
        r"(?i)\bADR\b",
        r"(?i)\barchitecture\b",
    ],
    "outcome": [
        r"(?i)\bresult\b",
        r"(?i)\boutcome\b",
        r"(?i)\bcompleted\b",
        r"(?i)\bsuccess\b",
        r"(?i)\bfailed\b",
        r"(?i)\bdeployed\b",
    ],
    "error_pattern": [
        r"(?i)\berror\b",
        r"(?i)\bbug\b",
        r"(?i)\bfix\b",
        r"(?i)\bworkaround\b",
        r"(?i)\bregression\b",
    ],
    "learning": [
        r"(?i)\blearned\b",
        r"(?i)\blesson\b",
        r"(?i)\binsight\b",
        r"(?i)\bnote\b",
        r"(?i)\btip\b",
        r"(?i)\bpattern\b",
    ],
}

# Timestamp patterns found in markdown notes
_TIMESTAMP_PATTERNS = [
    r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})",  # ISO format
    r"(\d{4}-\d{2}-\d{2})",  # Date only
    r"(?:Date|Created|Updated):\s*(\d{4}-\d{2}-\d{2})",  # Labeled date
]


@dataclass
class ParsedNote:
    """A parsed cross-session note ready for migration."""

    file_path: str
    memory_type: str
    content: str
    content_hash: str
    timestamp: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for reporting."""
        return {
            "file_path": self.file_path,
            "memory_type": self.memory_type,
            "content_preview": self.content[:100],
            "content_hash": self.content_hash,
            "timestamp": self.timestamp,
        }


@dataclass
class MigrationSummary:
    """Summary of migration results."""

    files_found: int = 0
    notes_parsed: int = 0
    notes_migrated: int = 0
    notes_skipped: int = 0
    notes_failed: int = 0
    files_archived: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for reporting."""
        return {
            "files_found": self.files_found,
            "notes_parsed": self.notes_parsed,
            "notes_migrated": self.notes_migrated,
            "notes_skipped": self.notes_skipped,
            "notes_failed": self.notes_failed,
            "files_archived": self.files_archived,
            "errors": self.errors[:20],
        }


def parse_note_file(file_path: Path) -> list[ParsedNote]:
    """
    Parse a markdown note file into one or more ParsedNote objects.

    Handles both single-note files and files with multiple sections
    separated by markdown headers.

    Args:
        file_path: Path to the markdown file.

    Returns:
        List of ParsedNote objects extracted from the file.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("Failed to read %s: %s", file_path, e)
        return []

    if not content.strip():
        return []

    # Split by top-level headers if multiple sections exist
    sections = re.split(r"^#{1,2}\s+", content, flags=re.MULTILINE)
    sections = [s.strip() for s in sections if s.strip()]

    if not sections:
        sections = [content.strip()]

    notes: list[ParsedNote] = []
    for section in sections:
        memory_type = _detect_memory_type(section)
        timestamp = _extract_timestamp(section, file_path)
        content_hash = hashlib.sha256(section.encode()).hexdigest()[:16]

        note = ParsedNote(
            file_path=str(file_path),
            memory_type=memory_type,
            content=section,
            content_hash=content_hash,
            timestamp=timestamp,
            metadata={
                "source": "cross_session_notes",
                "original_file": file_path.name,
                "migrated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        notes.append(note)

    return notes


def _detect_memory_type(content: str) -> str:
    """Detect memory type from content using pattern matching."""
    scores: dict[str, int] = {mtype: 0 for mtype in _TYPE_PATTERNS}

    for mtype, patterns in _TYPE_PATTERNS.items():
        for pattern in patterns:
            matches = re.findall(pattern, content)
            scores[mtype] += len(matches)

    # Return the type with highest score, default to "learning"
    best_type = max(scores, key=lambda k: scores[k])
    if scores[best_type] == 0:
        return "learning"
    return best_type


def _extract_timestamp(content: str, file_path: Path) -> str:
    """Extract timestamp from content or fall back to file modification time."""
    for pattern in _TIMESTAMP_PATTERNS:
        match = re.search(pattern, content)
        if match:
            ts = match.group(1)
            if "T" not in ts:
                ts += "T00:00:00"
            return ts + "+00:00"

    # Fall back to file modification time
    try:
        mtime = file_path.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    except OSError:
        return datetime.now(timezone.utc).isoformat()


def archive_to_s3(
    file_path: Path,
    project_id: str,
    bucket: str,
) -> bool:
    """
    Archive original note file to S3.

    Args:
        file_path: Path to the file to archive.
        project_id: Project identifier for S3 key prefix.
        bucket: S3 bucket name.

    Returns:
        True if archive succeeded, False otherwise.
    """
    if not bucket:
        logger.debug("No archive bucket configured, skipping archive")
        return False

    s3 = boto3.client("s3")
    key = f"archives/{project_id}/cross_session_notes/{file_path.name}"

    try:
        content = file_path.read_text(encoding="utf-8")
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType="text/markdown",
            Metadata={
                "project_id": project_id,
                "original_path": str(file_path),
                "archived_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        logger.info("Archived to S3: s3://%s/%s", bucket, key)
        return True
    except ClientError as e:
        logger.warning("Failed to archive %s to S3: %s", file_path.name, e)
        return False


def run_migration(
    project_id: str,
    notes_dir: Path,
    memory_table: str,
    archive_bucket: str,
    dry_run: bool = False,
) -> MigrationSummary:
    """
    Execute the full migration from cross_session_notes to DynamoDB memory.

    Args:
        project_id: Project identifier.
        notes_dir: Path to the cross_session_notes directory.
        memory_table: DynamoDB table name for memory storage.
        archive_bucket: S3 bucket for archiving originals.
        dry_run: If True, parse and report without writing.

    Returns:
        MigrationSummary with results.
    """
    summary = MigrationSummary()

    if not notes_dir.exists():
        logger.warning("Notes directory does not exist: %s", notes_dir)
        summary.errors.append(f"Directory not found: {notes_dir}")
        return summary

    # Find all markdown files
    md_files = sorted(notes_dir.glob("*.md"))
    summary.files_found = len(md_files)

    if not md_files:
        logger.info("No markdown files found in %s", notes_dir)
        return summary

    logger.info("Found %d markdown files in %s", len(md_files), notes_dir)

    # Initialize memory manager
    memory_manager = MemoryManager(
        project_id=project_id,
        memory_table=memory_table,
    )

    # Parse all notes
    all_notes: list[ParsedNote] = []
    for md_file in md_files:
        parsed = parse_note_file(md_file)
        all_notes.extend(parsed)

    summary.notes_parsed = len(all_notes)
    logger.info("Parsed %d notes from %d files", len(all_notes), len(md_files))

    if dry_run:
        logger.info("DRY RUN — would migrate %d notes", len(all_notes))
        for note in all_notes:
            logger.info(
                "  [%s] %s: %s...",
                note.memory_type, note.file_path, note.content[:60],
            )
        return summary

    # Migrate each note (idempotent: skip if hash exists)
    for note in all_notes:
        try:
            # Check idempotency by content hash
            if memory_manager.exists_by_hash(note.content_hash):
                summary.notes_skipped += 1
                logger.debug(
                    "Skipping already-migrated note: hash=%s", note.content_hash
                )
                continue

            # Store in DynamoDB
            memory_manager.store(
                memory_type=note.memory_type,
                content=note.content,
                metadata=note.metadata,
            )
            summary.notes_migrated += 1

        except Exception as e:
            summary.notes_failed += 1
            summary.errors.append(f"Failed to migrate {note.file_path}: {e}")
            logger.warning("Failed to migrate note from %s: %s", note.file_path, e)

    # Archive original files to S3 (preserve, don't delete)
    if archive_bucket:
        archived_files: set[str] = set()
        for note in all_notes:
            if note.file_path not in archived_files:
                if archive_to_s3(Path(note.file_path), project_id, archive_bucket):
                    summary.files_archived += 1
                archived_files.add(note.file_path)

    logger.info(
        "Migration complete: parsed=%d migrated=%d skipped=%d failed=%d archived=%d",
        summary.notes_parsed,
        summary.notes_migrated,
        summary.notes_skipped,
        summary.notes_failed,
        summary.files_archived,
    )
    return summary


def main() -> None:
    """CLI entry point for the migration script."""
    parser = argparse.ArgumentParser(
        description="Migrate cross_session_notes to DynamoDB memory format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python3 scripts/migrate_memory.py --project-id my-repo
    python3 scripts/migrate_memory.py --project-id my-repo --notes-dir ./cross_session_notes --dry-run
    python3 scripts/migrate_memory.py --project-id my-repo --memory-table fde-dev-memory
        """,
    )
    parser.add_argument(
        "--project-id",
        required=True,
        help="Project identifier (used as DynamoDB partition key)",
    )
    parser.add_argument(
        "--notes-dir",
        default="./cross_session_notes",
        help="Path to cross_session_notes directory (default: ./cross_session_notes)",
    )
    parser.add_argument(
        "--memory-table",
        default=os.environ.get("MEMORY_TABLE", "fde-dev-memory"),
        help="DynamoDB memory table name (default: fde-dev-memory)",
    )
    parser.add_argument(
        "--archive-bucket",
        default=os.environ.get("ARTIFACTS_BUCKET", ""),
        help="S3 bucket for archiving original files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report without writing to DynamoDB",
    )

    args = parser.parse_args()

    notes_path = Path(args.notes_dir)
    logger.info(
        "Starting migration: project=%s notes_dir=%s table=%s dry_run=%s",
        args.project_id, notes_path, args.memory_table, args.dry_run,
    )

    summary = run_migration(
        project_id=args.project_id,
        notes_dir=notes_path,
        memory_table=args.memory_table,
        archive_bucket=args.archive_bucket,
        dry_run=args.dry_run,
    )

    # Print summary
    print("\n" + "=" * 60)
    print("MIGRATION SUMMARY")
    print("=" * 60)
    print(json.dumps(summary.to_dict(), indent=2))
    print("=" * 60)

    if summary.errors:
        print(f"\n⚠️  {len(summary.errors)} error(s) occurred during migration.")
        sys.exit(1)
    else:
        print("\n✅ Migration completed successfully.")
        sys.exit(0)


if __name__ == "__main__":
    main()
