"""
Contract test: EventBridge InputTransformer substitution safety.

This test simulates the EXACT behavior of EventBridge InputTransformer:
  1. Extract values from Detail JSON using input_paths (JSONPath → raw value)
  2. Substitute placeholders in input_template with extracted values
  3. Validate the resulting JSON is parseable

If this test fails, the sanitization in shared/eventbridge_sanitizer.py
has a gap that will cause silent target invocation failures in production.

Root cause reference: ADR-036
Pipeline edge: E3 (Lambda → EventBridge InputTransformer → ECS Target)
"""

import json
import re
import sys
import os

import pytest

# Add shared module to path for import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../infra/terraform/lambda"))

from shared.eventbridge_sanitizer import sanitize_dispatch_detail, clamp_depth


# ─── InputTransformer Simulation ─────────────────────────────────
# This replicates the exact behavior of EventBridge InputTransformer
# as defined in cognitive_router.tf

INPUT_PATHS = {
    "taskId": "$.detail.task_id",
    "targetMode": "$.detail.target_mode",
    "depth": "$.detail.depth",
    "repo": "$.detail.repo",
    "issueId": "$.detail.issue_id",
    "title": "$.detail.title",
    "priority": "$.detail.priority",
}

INPUT_TEMPLATE = """{
  "containerOverrides": [{
    "name": "strands-agent",
    "environment": [
      {"name": "TASK_ID", "value": "<taskId>"},
      {"name": "TARGET_MODE", "value": "<targetMode>"},
      {"name": "DEPTH", "value": "<depth>"},
      {"name": "EVENT_REPO", "value": "<repo>"},
      {"name": "EVENT_ISSUE_ID", "value": "<issueId>"},
      {"name": "EVENT_ISSUE_TITLE", "value": "<title>"},
      {"name": "EVENT_PRIORITY", "value": "<priority>"}
    ]
  }]
}"""


def simulate_input_transformer(detail: dict) -> str:
    """Simulate EventBridge InputTransformer behavior.

    EventBridge InputTransformer:
      1. Extracts values from the event Detail using JSONPath (input_paths)
      2. For string values: extracts the raw string (unquoted)
      3. For numeric values: extracts the number as string representation
      4. Substitutes <placeholder> in input_template with the extracted value
      5. The substitution is RAW TEXT — no escaping is applied

    If the resulting string is not valid JSON, the target invocation fails.
    """
    # Step 1: Extract values using input_paths
    extracted = {}
    for placeholder, jsonpath in INPUT_PATHS.items():
        # Parse simple JSONPath: $.detail.field_name
        field = jsonpath.split(".")[-1]
        value = detail.get(field, "")
        # EventBridge converts all extracted values to their string representation
        extracted[placeholder] = str(value) if value is not None else ""

    # Step 2: Substitute placeholders in template (raw text replacement)
    result = INPUT_TEMPLATE
    for placeholder, value in extracted.items():
        result = result.replace(f"<{placeholder}>", value)

    return result


# ─── Test Cases ──────────────────────────────────────────────────


class TestSanitizedDetailProducesValidJSON:
    """Verify that sanitize_dispatch_detail output always produces valid JSON
    when processed by the InputTransformer simulation."""

    def test_clean_title(self):
        """Baseline: clean title passes through unchanged."""
        detail = sanitize_dispatch_detail({
            "task_id": "TASK-abc123",
            "target_mode": "monolith",
            "depth": 0.7,
            "repo": "org/repo",
            "issue_id": "42",
            "title": "Add logging to error handlers",
            "priority": "P2",
            "signals": {"dependency_count": 2},
        })
        result = simulate_input_transformer(detail)
        parsed = json.loads(result)
        env_vars = {e["name"]: e["value"] for e in parsed["containerOverrides"][0]["environment"]}
        assert env_vars["TASK_ID"] == "TASK-abc123"
        assert env_vars["EVENT_ISSUE_TITLE"] == "Add logging to error handlers"

    def test_title_with_double_quotes(self):
        """Title containing double quotes — the primary failure case."""
        detail = sanitize_dispatch_detail({
            "task_id": "TASK-quotes",
            "target_mode": "distributed",
            "depth": 0.8,
            "repo": "org/repo",
            "issue_id": "99",
            "title": 'Fix the "broken" parser',
            "priority": "P1",
            "signals": {},
        })
        result = simulate_input_transformer(detail)
        parsed = json.loads(result)  # Must not raise
        env_vars = {e["name"]: e["value"] for e in parsed["containerOverrides"][0]["environment"]}
        # Double quotes replaced with single quotes
        assert '"' not in env_vars["EVENT_ISSUE_TITLE"]
        assert "broken" in env_vars["EVENT_ISSUE_TITLE"]

    def test_title_with_newlines(self):
        """Title containing newlines — breaks JSON string literals."""
        detail = sanitize_dispatch_detail({
            "task_id": "TASK-newline",
            "target_mode": "monolith",
            "depth": 0.3,
            "repo": "org/repo",
            "issue_id": "7",
            "title": "Line one\nLine two\rLine three",
            "priority": "P2",
            "signals": {},
        })
        result = simulate_input_transformer(detail)
        parsed = json.loads(result)  # Must not raise
        env_vars = {e["name"]: e["value"] for e in parsed["containerOverrides"][0]["environment"]}
        assert "\n" not in env_vars["EVENT_ISSUE_TITLE"]
        assert "\r" not in env_vars["EVENT_ISSUE_TITLE"]

    def test_title_with_backslashes(self):
        """Title containing backslashes — can create invalid escape sequences."""
        detail = sanitize_dispatch_detail({
            "task_id": "TASK-backslash",
            "target_mode": "monolith",
            "depth": 0.5,
            "repo": "org/repo",
            "issue_id": "12",
            "title": r"Fix path C:\Users\admin\file.txt",
            "priority": "P2",
            "signals": {},
        })
        result = simulate_input_transformer(detail)
        parsed = json.loads(result)  # Must not raise
        env_vars = {e["name"]: e["value"] for e in parsed["containerOverrides"][0]["environment"]}
        assert "\\" not in env_vars["EVENT_ISSUE_TITLE"]

    def test_title_with_control_characters(self):
        """Title with control characters (tabs, null bytes)."""
        detail = sanitize_dispatch_detail({
            "task_id": "TASK-ctrl",
            "target_mode": "monolith",
            "depth": 0.4,
            "repo": "org/repo",
            "issue_id": "3",
            "title": "Tab\there\x00null\x01ctrl",
            "priority": "P2",
            "signals": {},
        })
        result = simulate_input_transformer(detail)
        parsed = json.loads(result)  # Must not raise
        env_vars = {e["name"]: e["value"] for e in parsed["containerOverrides"][0]["environment"]}
        assert "\t" not in env_vars["EVENT_ISSUE_TITLE"]
        assert "\x00" not in env_vars["EVENT_ISSUE_TITLE"]

    def test_repo_with_special_characters(self):
        """Repo field with unusual characters."""
        detail = sanitize_dispatch_detail({
            "task_id": "TASK-repo",
            "target_mode": "monolith",
            "depth": 0.6,
            "repo": 'org/"special-repo"',
            "issue_id": "5",
            "title": "Normal title",
            "priority": "P2",
            "signals": {},
        })
        result = simulate_input_transformer(detail)
        parsed = json.loads(result)  # Must not raise

    def test_all_fields_adversarial(self):
        """All user-generated fields contain adversarial content simultaneously."""
        detail = sanitize_dispatch_detail({
            "task_id": "TASK-adversarial",
            "target_mode": "monolith",
            "depth": 0.9,
            "repo": 'org/"repo\nwith\tstuff"',
            "issue_id": 'issue"123',
            "title": '"Fix"\nthe\t\\broken\x00thing',
            "priority": 'P1"injected',
            "signals": {"key": "value"},
        })
        result = simulate_input_transformer(detail)
        parsed = json.loads(result)  # Must not raise — this is the critical assertion


class TestDepthClamping:
    """Verify depth is always safe for InputTransformer substitution."""

    def test_normal_depth(self):
        assert clamp_depth(0.7) == 0.7

    def test_depth_zero(self):
        assert clamp_depth(0.0) == 0.0

    def test_depth_one(self):
        assert clamp_depth(1.0) == 1.0

    def test_depth_exceeds_one(self):
        assert clamp_depth(1.5) == 1.0

    def test_depth_negative(self):
        assert clamp_depth(-0.3) == 0.0

    def test_depth_nan(self):
        import math
        assert clamp_depth(float("nan")) == 0.0

    def test_depth_infinity(self):
        assert clamp_depth(float("inf")) == 0.0

    def test_depth_negative_infinity(self):
        assert clamp_depth(float("-inf")) == 0.0

    def test_depth_none(self):
        assert clamp_depth(None) == 0.0

    def test_depth_string(self):
        assert clamp_depth("0.7") == 0.7

    def test_depth_invalid_string(self):
        assert clamp_depth("not_a_number") == 0.0

    def test_depth_floating_point_precision(self):
        """Floating point noise is rounded to 3 decimals."""
        result = clamp_depth(0.30000000000000004)
        assert result == 0.3

    def test_depth_in_transformer_output(self):
        """Depth value produces valid JSON in InputTransformer."""
        detail = sanitize_dispatch_detail({
            "task_id": "TASK-depth",
            "target_mode": "monolith",
            "depth": 0.7777777,
            "repo": "org/repo",
            "issue_id": "1",
            "title": "test",
            "priority": "P2",
            "signals": {},
        })
        result = simulate_input_transformer(detail)
        parsed = json.loads(result)
        env_vars = {e["name"]: e["value"] for e in parsed["containerOverrides"][0]["environment"]}
        assert env_vars["DEPTH"] == "0.778"


class TestSignalsPassthrough:
    """Verify signals field is passed through without modification."""

    def test_signals_dict_preserved(self):
        signals = {"dependency_count": 3, "cfr_history": 0.15, "metrics_available": True}
        detail = sanitize_dispatch_detail({
            "task_id": "TASK-signals",
            "target_mode": "monolith",
            "depth": 0.5,
            "repo": "org/repo",
            "issue_id": "1",
            "title": "test",
            "priority": "P2",
            "signals": signals,
        })
        assert detail["signals"] == signals

    def test_signals_not_in_transformer(self):
        """Signals field is NOT extracted by InputTransformer — it's ignored."""
        detail = sanitize_dispatch_detail({
            "task_id": "TASK-signals",
            "target_mode": "monolith",
            "depth": 0.5,
            "repo": "org/repo",
            "issue_id": "1",
            "title": "test",
            "priority": "P2",
            "signals": {"evil": 'value"with"quotes'},
        })
        # The signals field doesn't appear in input_paths, so it can't break anything
        result = simulate_input_transformer(detail)
        parsed = json.loads(result)  # Must not raise
