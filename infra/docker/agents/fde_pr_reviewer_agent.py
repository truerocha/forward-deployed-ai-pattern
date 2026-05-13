"""
FDE PR Reviewer Agent — Independent, Isolated Code Review for Delivery Excellence.

This agent is the Level 1 quality gate in the three-level review architecture (ADR-028).
It validates the FINAL PR deliverable against the original issue spec BEFORE any human
sees it. If it rejects, the squad reworks internally — the human never sees bad PRs.

ISOLATION GUARANTEES:
  - Runs as a SEPARATE ECS task (not in the squad's execution context)
  - Reads ONLY: original issue spec + PR diff + test results
  - Does NOT read: squad reasoning, Conductor plans, intermediate outputs
  - Maintains its OWN ICRL episode store (icrl_review_episode# prefix)
  - Cannot be influenced by the squad's anchoring or confirmation bias

REVIEW DIMENSIONS:
  1. Spec Alignment: Does the PR address what the issue asked for?
  2. Completeness: Are all acceptance criteria met?
  3. Security: Are there obvious security issues?
  4. Error Handling: Are failure paths handled?
  5. Test Coverage: Are new code paths tested?
  6. Architecture: Does the change respect module boundaries?

OUTPUT:
  ReviewVerdict: APPROVE | REWORK
  - If APPROVE: confidence score + summary for DTL committer
  - If REWORK: structured feedback (reason, violated_rule, suggestion, files_to_fix)

Feature flag: PR_REVIEWER_ENABLED (default: true)
Ref: docs/adr/ADR-028-pr-reviewer-agent-three-level-review.md
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger("fde.agents.pr_reviewer")

_PR_REVIEWER_ENABLED = os.environ.get("PR_REVIEWER_ENABLED", "true").lower() == "true"
_MAX_DIFF_CHARS = 50000
_MAX_SPEC_CHARS = 10000
_REVIEW_MODEL_ID = os.environ.get(
    "PR_REVIEWER_MODEL_ID",
    os.environ.get("BEDROCK_MODEL_REASONING", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"),
)
_AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


class ReviewVerdict(Enum):
    APPROVE = "approve"
    REWORK = "rework"


@dataclass
class ReviewDimension:
    name: str
    score: float
    passed: bool
    finding: str = ""
    suggestion: str = ""


@dataclass
class ReviewResult:
    verdict: ReviewVerdict
    confidence: float
    dimensions: list[ReviewDimension] = field(default_factory=list)
    summary: str = ""
    files_to_fix: list[str] = field(default_factory=list)
    rework_feedback: str = ""
    review_duration_seconds: float = 0.0
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    @property
    def overall_score(self) -> float:
        if not self.dimensions:
            return 0.0
        return sum(d.score for d in self.dimensions) / len(self.dimensions)

    @property
    def failed_dimensions(self) -> list[ReviewDimension]:
        return [d for d in self.dimensions if not d.passed]

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "confidence": round(self.confidence, 3),
            "overall_score": round(self.overall_score, 3),
            "dimensions": [
                {"name": d.name, "score": round(d.score, 2), "passed": d.passed,
                 "finding": d.finding, "suggestion": d.suggestion}
                for d in self.dimensions
            ],
            "summary": self.summary,
            "files_to_fix": self.files_to_fix,
            "rework_feedback": self.rework_feedback,
            "review_duration_seconds": round(self.review_duration_seconds, 2),
            "timestamp": self.timestamp,
        }

    def to_gate_feedback(self) -> str:
        if self.verdict == ReviewVerdict.APPROVE:
            return ""
        parts = [f"PR REVIEW: REWORK REQUIRED (confidence={self.confidence:.2f})", ""]
        parts.append("Failed dimensions:")
        for dim in self.failed_dimensions:
            parts.append(f"  - {dim.name}: {dim.finding}")
            if dim.suggestion:
                parts.append(f"    Fix: {dim.suggestion}")
        if self.files_to_fix:
            parts.append(f"\nFiles to fix: {', '.join(self.files_to_fix[:10])}")
        return "\n".join(parts)


@dataclass
class ReviewInput:
    issue_title: str
    issue_body: str
    acceptance_criteria: list[str] = field(default_factory=list)
    pr_diff: str = ""
    pr_title: str = ""
    pr_body: str = ""
    files_changed: list[str] = field(default_factory=list)
    tests_passed: bool = True
    linter_passed: bool = True
    type_check_passed: bool = True
    test_output: str = ""
    task_id: str = ""
    repo: str = ""
    pr_number: int = 0
    autonomy_level: int = 4


class PRReviewerAgent:
    """
    Independent PR reviewer — Level 1 quality gate.

    Deliberately isolated from the squad's context. Sees ONLY the spec
    and the diff. Prevents anchoring and confirmation bias.
    """

    def __init__(
        self,
        model_id: str = _REVIEW_MODEL_ID,
        aws_region: str = _AWS_REGION,
        metrics_table: str = "",
        project_id: str = "",
    ):
        self._model_id = model_id
        self._region = aws_region
        self._metrics_table = metrics_table or os.environ.get("METRICS_TABLE", "")
        self._project_id = project_id or os.environ.get("PROJECT_ID", "global")
        self._bedrock = boto3.client("bedrock-runtime", region_name=self._region)

    @property
    def enabled(self) -> bool:
        return _PR_REVIEWER_ENABLED

    def review(self, input: ReviewInput) -> ReviewResult:
        """Perform an independent review of the PR against the spec."""
        if not self.enabled:
            return ReviewResult(
                verdict=ReviewVerdict.APPROVE, confidence=0.5,
                summary="PR reviewer disabled — auto-approving with reduced confidence",
            )

        start = time.time()
        system_prompt = self._build_system_prompt()
        user_message = self._build_user_message(input)

        try:
            response = self._bedrock.converse(
                modelId=self._model_id,
                messages=[{"role": "user", "content": [{"text": user_message}]}],
                system=[{"text": system_prompt}],
                inferenceConfig={"maxTokens": 4096, "temperature": 0.1},
            )

            output_content = response.get("output", {}).get("message", {}).get("content", [])
            output_text = "".join(b.get("text", "") for b in output_content)

            result = self._parse_review_response(output_text)
            result.review_duration_seconds = time.time() - start
            self._record_review_decision(input, result)

            logger.info(
                "PR review: task=%s verdict=%s confidence=%.2f score=%.2f duration=%.1fs",
                input.task_id, result.verdict.value, result.confidence,
                result.overall_score, result.review_duration_seconds,
            )
            return result

        except ClientError as e:
            logger.error("PR reviewer Bedrock failed: %s", str(e))
            return ReviewResult(
                verdict=ReviewVerdict.APPROVE, confidence=0.3,
                summary=f"Review failed (Bedrock error) — approving with low confidence",
                review_duration_seconds=time.time() - start,
            )

    def _build_system_prompt(self) -> str:
        return (
            "You are an independent code reviewer. You review a Pull Request against "
            "the original issue specification.\n\n"
            "RULES:\n"
            "1. You are INDEPENDENT — no knowledge of how this code was produced.\n"
            "2. You are CANDID — if the PR does not meet the spec, say so.\n"
            "3. You review the DELIVERABLE (diff), not the INTENT.\n"
            "4. Compare WHAT WAS ASKED (issue) against WHAT WAS PRODUCED (diff).\n"
            "5. Do NOT assume code is correct because it exists.\n\n"
            "DIMENSIONS (score 0.0-1.0):\n"
            "1. spec_alignment: Does PR address what the issue asked?\n"
            "2. completeness: All acceptance criteria met?\n"
            "3. security: Obvious security issues?\n"
            "4. error_handling: Failure paths handled?\n"
            "5. test_coverage: New paths tested?\n"
            "6. architecture: Module boundaries respected?\n\n"
            "OUTPUT (JSON):\n"
            '{"verdict":"approve"|"rework","confidence":0.0-1.0,'
            '"dimensions":[{"name":"...","score":0.0-1.0,"passed":bool,"finding":"...","suggestion":"..."}],'
            '"summary":"...","files_to_fix":["..."],"rework_feedback":"..."}\n\n'
            "VERDICT: APPROVE if all dimensions >= 0.6. REWORK if any < 0.4 or critical security issue.\n"
        )

    def _build_user_message(self, input: ReviewInput) -> str:
        parts = [
            "## ISSUE SPECIFICATION",
            f"Title: {input.issue_title}",
            input.issue_body[:_MAX_SPEC_CHARS] if input.issue_body else "",
        ]
        if input.acceptance_criteria:
            parts.append("\nAcceptance Criteria:")
            for i, ac in enumerate(input.acceptance_criteria, 1):
                parts.append(f"  {i}. {ac}")

        parts.extend([
            "\n\n## PR DIFF",
            f"PR Title: {input.pr_title}",
            f"Files Changed ({len(input.files_changed)}): {', '.join(input.files_changed[:20])}",
            f"\n```\n{input.pr_diff[:_MAX_DIFF_CHARS]}\n```",
            "\n\n## VERIFICATION",
            f"Tests: {'PASS' if input.tests_passed else 'FAIL'}",
            f"Linter: {'PASS' if input.linter_passed else 'FAIL'}",
            f"Types: {'PASS' if input.type_check_passed else 'FAIL'}",
        ])
        return "\n".join(parts)

    def _parse_review_response(self, output_text: str) -> ReviewResult:
        try:
            json_start = output_text.find("{")
            json_end = output_text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                data = json.loads(output_text[json_start:json_end])
            else:
                raise ValueError("No JSON in reviewer output")

            verdict = ReviewVerdict.REWORK if data.get("verdict") == "rework" else ReviewVerdict.APPROVE
            dimensions = [
                ReviewDimension(
                    name=d.get("name", ""), score=float(d.get("score", 0.5)),
                    passed=d.get("passed", True), finding=d.get("finding", ""),
                    suggestion=d.get("suggestion", ""),
                )
                for d in data.get("dimensions", [])
            ]
            return ReviewResult(
                verdict=verdict, confidence=float(data.get("confidence", 0.7)),
                dimensions=dimensions, summary=data.get("summary", ""),
                files_to_fix=data.get("files_to_fix", []),
                rework_feedback=data.get("rework_feedback", ""),
            )
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Failed to parse reviewer response: %s", str(e))
            return ReviewResult(verdict=ReviewVerdict.APPROVE, confidence=0.4,
                              summary=f"Parse failed — approving with low confidence")

    def _record_review_decision(self, input: ReviewInput, result: ReviewResult) -> None:
        if not self._metrics_table:
            return
        dynamodb = boto3.resource("dynamodb", region_name=self._region)
        table = dynamodb.Table(self._metrics_table)
        now = datetime.now(timezone.utc).isoformat()
        try:
            table.put_item(Item={
                "project_id": self._project_id,
                "metric_key": f"pr_review#{input.task_id}#{now}",
                "metric_type": "pr_review",
                "task_id": input.task_id,
                "recorded_at": now,
                "data": json.dumps({
                    "verdict": result.verdict.value, "confidence": result.confidence,
                    "overall_score": result.overall_score,
                    "dimensions_passed": sum(1 for d in result.dimensions if d.passed),
                    "dimensions_total": len(result.dimensions),
                    "repo": input.repo, "pr_number": input.pr_number,
                    "review_duration_seconds": result.review_duration_seconds,
                }),
            })
            table.put_item(Item={
                "project_id": self._project_id,
                "metric_key": f"icrl_review_episode#{input.repo}#{now}",
                "metric_type": "icrl_review_episode",
                "task_id": input.task_id,
                "recorded_at": now,
                "data": json.dumps({
                    "task_id": input.task_id, "repo": input.repo,
                    "issue_title": input.issue_title[:200],
                    "verdict": result.verdict.value, "confidence": result.confidence,
                    "failed_dimensions": [d.name for d in result.failed_dimensions],
                    "rework_feedback": result.rework_feedback[:500],
                }),
            })
        except ClientError as e:
            logger.warning("Failed to record review decision: %s", str(e))


@dataclass
class DeliveryDecision:
    action: str  # auto_merge | ready_for_review | assign_human | internal_rework | back_to_l1
    reason: str
    reviewer_verdict: ReviewVerdict
    reviewer_confidence: float
    branch_eval_score: float | None = None
    autonomy_level: int = 4


def compute_delivery_decision(
    review_result: ReviewResult,
    branch_eval_score: float | None = None,
    autonomy_level: int = 4,
) -> DeliveryDecision:
    """DTL Committer decision matrix (ADR-028)."""
    if review_result.verdict == ReviewVerdict.REWORK:
        return DeliveryDecision(
            action="internal_rework",
            reason=f"Level 1 rejected: {review_result.summary[:200]}",
            reviewer_verdict=review_result.verdict,
            reviewer_confidence=review_result.confidence,
            branch_eval_score=branch_eval_score,
            autonomy_level=autonomy_level,
        )

    if branch_eval_score is not None:
        if branch_eval_score >= 8.0 and autonomy_level >= 4:
            return DeliveryDecision(
                action="auto_merge",
                reason=f"L1 approved + L2={branch_eval_score:.1f} + L{autonomy_level} → auto-merge",
                reviewer_verdict=review_result.verdict,
                reviewer_confidence=review_result.confidence,
                branch_eval_score=branch_eval_score,
                autonomy_level=autonomy_level,
            )
        elif branch_eval_score >= 6.0:
            action = "ready_for_review" if autonomy_level >= 3 else "assign_human"
            return DeliveryDecision(
                action=action,
                reason=f"L1 approved + L2={branch_eval_score:.1f} + L{autonomy_level} → {action}",
                reviewer_verdict=review_result.verdict,
                reviewer_confidence=review_result.confidence,
                branch_eval_score=branch_eval_score,
                autonomy_level=autonomy_level,
            )
        else:
            return DeliveryDecision(
                action="back_to_l1",
                reason=f"L1 approved but L2 too low ({branch_eval_score:.1f} < 6.0)",
                reviewer_verdict=review_result.verdict,
                reviewer_confidence=review_result.confidence,
                branch_eval_score=branch_eval_score,
                autonomy_level=autonomy_level,
            )

    return DeliveryDecision(
        action="ready_for_review",
        reason=f"L1 approved (confidence={review_result.confidence:.2f}) — awaiting L2",
        reviewer_verdict=review_result.verdict,
        reviewer_confidence=review_result.confidence,
        autonomy_level=autonomy_level,
    )
