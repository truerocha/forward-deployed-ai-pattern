"""
ICRL Episode Store — In-Context Reinforcement Learning Memory.

Stores structured episodes from human PR review feedback for injection
into agent context at rework time. Implements the ICRL principle:
the model adapts to repository-specific patterns through trial-and-error
entirely within the prompt window — no retraining required.

Episode structure:
  (task_context, agent_action, human_reward, correction)

Where:
  - task_context: what the task asked for (spec summary)
  - agent_action: what the agent produced (diff summary, approach taken)
  - human_reward: rejection classification + reviewer comment
  - correction: extracted actionable feedback (what was wrong, what to do)

Storage:
  DynamoDB SK pattern: icrl_episode#{repo}#{date}#{review_id}

Retrieval strategies:
  - Relevance-filtered: same repo + file-path overlap + recency
  - Pattern digest: after 10+ episodes, consolidate into common patterns
  - TTL: 30 days (stale episodes auto-expire)

Research grounding:
  - ICRL (arXiv:2602.17084): Dynamic strategy updates from success/failure history
  - RepoSearch-R1 (arXiv:2505.16339): Repository-level reasoning with MCTS
  - Self-Improving Agent (arXiv:2504.15228): Autonomous self-editing from feedback

Ref: docs/adr/ADR-027-review-feedback-loop.md (V2: ICRL Enhancement)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger("fde.memory.icrl_episodes")

# Configuration
_MAX_EPISODES_IN_CONTEXT = 5
_PATTERN_DIGEST_THRESHOLD = 10
_EPISODE_TTL_DAYS = 30
_MAX_EPISODE_CONTENT_CHARS = 500


@dataclass
class ICRLEpisode:
    """A single ICRL episode from a human review feedback event.

    Represents one cycle of: agent tried -> human evaluated -> feedback given.
    These episodes are injected into the agent's context at rework time
    to enable in-context learning without retraining.
    """

    episode_id: str
    repo: str
    task_id: str
    timestamp: str

    # What the task asked for
    task_context: str

    # What the agent produced
    agent_action: str
    files_changed: list[str] = field(default_factory=list)

    # Human evaluation
    reward: str  # "rejected" | "partial_fix" | "approved"
    reviewer: str = ""
    review_body: str = ""

    # Extracted correction (actionable feedback)
    correction: str = ""

    # Metadata for relevance filtering
    pr_number: int = 0
    classification: str = ""
    rework_attempt: int = 0

    def to_context_block(self) -> str:
        """Format episode for injection into agent context window."""
        files_str = ", ".join(self.files_changed[:5])
        if len(self.files_changed) > 5:
            files_str += f" (+{len(self.files_changed) - 5} more)"

        return (
            f"--- Episode (repo={self.repo}, {self.timestamp[:10]}) ---\n"
            f"Task: {self.task_context[:200]}\n"
            f"Approach: {self.agent_action[:200]}\n"
            f"Files: {files_str}\n"
            f"Result: {self.reward.upper()}\n"
            f"Feedback: {self.correction[:300]}\n"
            f"---"
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize for DynamoDB storage."""
        return {
            "episode_id": self.episode_id,
            "repo": self.repo,
            "task_id": self.task_id,
            "timestamp": self.timestamp,
            "task_context": self.task_context,
            "agent_action": self.agent_action,
            "files_changed": self.files_changed,
            "reward": self.reward,
            "reviewer": self.reviewer,
            "review_body": self.review_body[:_MAX_EPISODE_CONTENT_CHARS],
            "correction": self.correction,
            "pr_number": self.pr_number,
            "classification": self.classification,
            "rework_attempt": self.rework_attempt,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ICRLEpisode:
        """Deserialize from DynamoDB record."""
        return cls(
            episode_id=data.get("episode_id", ""),
            repo=data.get("repo", ""),
            task_id=data.get("task_id", ""),
            timestamp=data.get("timestamp", ""),
            task_context=data.get("task_context", ""),
            agent_action=data.get("agent_action", ""),
            files_changed=data.get("files_changed", []),
            reward=data.get("reward", ""),
            reviewer=data.get("reviewer", ""),
            review_body=data.get("review_body", ""),
            correction=data.get("correction", ""),
            pr_number=data.get("pr_number", 0),
            classification=data.get("classification", ""),
            rework_attempt=data.get("rework_attempt", 0),
        )


@dataclass
class PatternDigest:
    """Consolidated pattern from multiple episodes.

    After 10+ episodes accumulate for a repo, individual episodes are
    consolidated into a pattern digest that captures common rejection
    reasons without consuming excessive context tokens.
    """

    repo: str
    total_episodes: int
    common_rejection_reasons: list[str]
    common_files_rejected: list[str]
    common_reviewer_preferences: list[str]
    success_patterns: list[str]
    generated_at: str = ""

    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.now(timezone.utc).isoformat()

    def to_context_block(self) -> str:
        """Format digest for injection into agent context."""
        rejections = "\n".join(f"  - {r}" for r in self.common_rejection_reasons[:5])
        files = ", ".join(self.common_files_rejected[:5])
        successes = "\n".join(f"  - {s}" for s in self.success_patterns[:3])

        return (
            f"=== Pattern Digest (repo={self.repo}, {self.total_episodes} episodes) ===\n"
            f"Common rejection reasons:\n{rejections}\n"
            f"Frequently rejected files: {files}\n"
            f"What works (approved patterns):\n{successes}\n"
            f"==="
        )


class ICRLEpisodeStore:
    """
    Stores and retrieves ICRL episodes for in-context learning.

    The store manages the lifecycle of episodes:
      1. Record: Store new episodes from review feedback events
      2. Retrieve: Get relevant episodes for a rework task (filtered by repo + files)
      3. Digest: Consolidate old episodes into pattern digests
      4. Expire: Remove episodes older than TTL

    Usage:
        store = ICRLEpisodeStore(project_id="my-repo")
        store.record_episode(episode)
        context = store.get_context_for_rework(
            repo="owner/repo",
            files_to_fix=["src/auth.py", "src/models.py"],
        )
    """

    def __init__(
        self,
        project_id: str = "",
        metrics_table: str | None = None,
    ):
        self._project_id = project_id or os.environ.get("PROJECT_ID", "global")
        self._metrics_table = metrics_table or os.environ.get("METRICS_TABLE", "")
        self._dynamodb = boto3.resource("dynamodb")

    def record_episode(self, episode: ICRLEpisode) -> None:
        """Store a new ICRL episode from a review feedback event."""
        if not self._metrics_table:
            return

        table = self._dynamodb.Table(self._metrics_table)
        now = datetime.now(timezone.utc).isoformat()

        try:
            table.put_item(
                Item={
                    "project_id": self._project_id,
                    "metric_key": f"icrl_episode#{episode.repo}#{now}#{episode.episode_id}",
                    "metric_type": "icrl_episode",
                    "task_id": episode.task_id,
                    "recorded_at": now,
                    "ttl": int(
                        (datetime.now(timezone.utc) + timedelta(days=_EPISODE_TTL_DAYS)).timestamp()
                    ),
                    "data": json.dumps(episode.to_dict()),
                }
            )
            logger.info(
                "ICRL episode recorded: repo=%s task=%s reward=%s",
                episode.repo, episode.task_id, episode.reward,
            )
        except ClientError as e:
            logger.warning("Failed to record ICRL episode: %s", str(e))

    def get_context_for_rework(
        self,
        repo: str,
        files_to_fix: list[str] | None = None,
        max_episodes: int = _MAX_EPISODES_IN_CONTEXT,
    ) -> str:
        """Retrieve relevant ICRL context for a rework task.

        Returns a formatted string ready to inject into the agent's prompt.
        If 10+ episodes exist, returns a pattern digest instead.
        """
        episodes = self._query_episodes(repo)

        if not episodes:
            return ""

        # If enough episodes exist, generate a pattern digest
        if len(episodes) >= _PATTERN_DIGEST_THRESHOLD:
            digest = self._generate_pattern_digest(repo, episodes)
            recent = self._rank_by_relevance(episodes, files_to_fix)[:2]
            parts = [digest.to_context_block()]
            parts.extend(ep.to_context_block() for ep in recent)
            return "\n\n".join(parts)

        # Otherwise, return individual episodes ranked by relevance
        ranked = self._rank_by_relevance(episodes, files_to_fix)[:max_episodes]
        if not ranked:
            return ""

        header = (
            f"[ICRL LEARNING CONTEXT — {len(ranked)} episodes from {repo}]\n"
            f"Learn from these past review outcomes. Do NOT repeat rejected approaches.\n"
        )
        episode_blocks = [ep.to_context_block() for ep in ranked]
        return header + "\n\n".join(episode_blocks)

    def get_episode_count(self, repo: str) -> int:
        """Get the number of stored episodes for a repo."""
        episodes = self._query_episodes(repo)
        return len(episodes)

    def _query_episodes(self, repo: str) -> list[ICRLEpisode]:
        """Query all episodes for a repo within TTL window."""
        if not self._metrics_table:
            return []

        table = self._dynamodb.Table(self._metrics_table)
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=_EPISODE_TTL_DAYS)
        ).isoformat()
        prefix = f"icrl_episode#{repo}#"

        try:
            response = table.query(
                KeyConditionExpression=(
                    "project_id = :pid AND begins_with(metric_key, :prefix)"
                ),
                FilterExpression="recorded_at >= :cutoff",
                ExpressionAttributeValues={
                    ":pid": self._project_id,
                    ":prefix": prefix,
                    ":cutoff": cutoff,
                },
                ScanIndexForward=False,
                Limit=50,
            )

            episodes = []
            for item in response.get("Items", []):
                data = json.loads(item.get("data", "{}"))
                episodes.append(ICRLEpisode.from_dict(data))
            return episodes

        except ClientError as e:
            logger.warning("Failed to query ICRL episodes: %s", str(e))
            return []

    def _rank_by_relevance(
        self,
        episodes: list[ICRLEpisode],
        files_to_fix: list[str] | None,
    ) -> list[ICRLEpisode]:
        """Rank episodes by relevance to the current rework task."""
        if not files_to_fix:
            return episodes

        fix_set = set(files_to_fix)

        def score(ep: ICRLEpisode) -> float:
            s = 0.0
            overlap = len(set(ep.files_changed) & fix_set)
            s += overlap * 2.0
            try:
                ep_time = datetime.fromisoformat(ep.timestamp)
                age_days = (datetime.now(timezone.utc) - ep_time).days
                if age_days <= 7:
                    s += 1.0
            except (ValueError, TypeError):
                pass
            if ep.reward in ("rejected", "full_rework"):
                s += 1.0
            return s

        return sorted(episodes, key=score, reverse=True)

    def _generate_pattern_digest(
        self, repo: str, episodes: list[ICRLEpisode]
    ) -> PatternDigest:
        """Generate a consolidated pattern digest from multiple episodes."""
        rejection_reasons: dict[str, int] = {}
        rejected_files: dict[str, int] = {}
        success_patterns: list[str] = []

        for ep in episodes:
            if ep.reward in ("rejected", "full_rework"):
                correction = ep.correction.lower()
                for keyword in [
                    "error handling", "security", "type safety", "tests",
                    "documentation", "performance", "architecture", "naming",
                    "edge cases", "validation", "logging", "imports",
                ]:
                    if keyword in correction:
                        rejection_reasons[keyword] = rejection_reasons.get(keyword, 0) + 1
                for f in ep.files_changed:
                    rejected_files[f] = rejected_files.get(f, 0) + 1
            elif ep.reward == "approved":
                if ep.agent_action:
                    success_patterns.append(ep.agent_action[:100])

        top_reasons = sorted(rejection_reasons.items(), key=lambda x: x[1], reverse=True)
        top_files = sorted(rejected_files.items(), key=lambda x: x[1], reverse=True)

        return PatternDigest(
            repo=repo,
            total_episodes=len(episodes),
            common_rejection_reasons=[r[0] for r in top_reasons[:5]],
            common_files_rejected=[f[0] for f in top_files[:5]],
            common_reviewer_preferences=[],
            success_patterns=success_patterns[:3],
        )


def create_episode_from_review_feedback(
    review_event: dict[str, Any],
    task_context: str = "",
    agent_action: str = "",
) -> ICRLEpisode:
    """Factory function to create an ICRL episode from a review feedback event."""
    classification = review_event.get("classification", "")
    reward_map = {
        "full_rework": "rejected",
        "partial_fix": "partial_fix",
        "approval": "approved",
        "informational": "approved",
    }

    return ICRLEpisode(
        episode_id=review_event.get("review_id", ""),
        repo=review_event.get("repo", ""),
        task_id=review_event.get("task_id", ""),
        timestamp=datetime.now(timezone.utc).isoformat(),
        task_context=task_context or review_event.get("task_id", ""),
        agent_action=agent_action,
        files_changed=review_event.get("files_commented", []),
        reward=reward_map.get(classification, "rejected"),
        reviewer=review_event.get("reviewer", ""),
        review_body=review_event.get("review_body", ""),
        correction=review_event.get("review_body", "")[:_MAX_EPISODE_CONTENT_CHARS],
        pr_number=review_event.get("pr_number", 0),
        classification=classification,
        rework_attempt=review_event.get("rework_attempt", 0),
    )
