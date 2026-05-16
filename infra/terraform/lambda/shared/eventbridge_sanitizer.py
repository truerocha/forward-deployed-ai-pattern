"""
Shared EventBridge sanitization utilities for all producer Lambdas.

Problem:
  EventBridge InputTransformer performs raw text substitution of placeholders
  inside the input_template JSON. If extracted values contain characters that
  are invalid in JSON string context (double quotes, newlines, backslashes),
  the resulting JSON is malformed and the target invocation fails SILENTLY.

  This module provides sanitization that ensures all string values are safe
  for InputTransformer substitution, and depth values are clamped/validated.

Usage:
  from shared.eventbridge_sanitizer import sanitize_dispatch_detail

  detail = sanitize_dispatch_detail({
      "task_id": task["task_id"],
      "target_mode": target_mode,
      "depth": depth_result["depth"],
      "repo": task.get("repo", ""),
      "issue_id": task.get("issue_id", ""),
      "title": task.get("title", ""),
      "priority": task.get("priority", "P2"),
      "signals": depth_result["signals"],
  })

Well-Architected alignment:
  REL 4: Design interactions to prevent failures — sanitize at producer boundary
  OPS 8: Understand operational health — log when sanitization alters values
  SEC 8: Protect data in transit — no injection via crafted issue titles
"""

import logging
import math
import re

logger = logging.getLogger(__name__)

# Characters that break EventBridge InputTransformer JSON substitution.
# InputTransformer does: replace("<placeholder>", extracted_value) inside "quoted" context.
# If extracted_value contains these, the resulting JSON is invalid.
_UNSAFE_CHARS_PATTERN = re.compile(r'["\\\n\r\t\x00-\x1f]')

# Fields that come from user-generated content (GitHub issues, etc.)
# and MUST be sanitized before EventBridge emission.
_USER_GENERATED_FIELDS = frozenset({"title", "repo", "issue_id", "priority", "redispatch_source"})

# Fields that are system-generated (UUIDs, enums) and safe by construction.
_SYSTEM_FIELDS = frozenset({"task_id", "target_mode"})


def sanitize_string_for_input_transformer(value: str, field_name: str = "") -> str:
    """Sanitize a string value for safe EventBridge InputTransformer substitution.

    Replaces characters that would break JSON when substituted into
    an input_template placeholder like: {"name": "X", "value": "<field>"}

    Returns the sanitized string. Logs a WARNING if the value was altered,
    including the field name for observability.
    """
    if not isinstance(value, str):
        return str(value)

    if not value:
        return value

    sanitized = _UNSAFE_CHARS_PATTERN.sub(_replacement_char, value)

    if sanitized != value:
        logger.warning(
            "EventBridge sanitization altered value: field=%s original_len=%d sanitized_len=%d "
            "chars_replaced=%d sample_original=%.50s",
            field_name,
            len(value),
            len(sanitized),
            sum(1 for a, b in zip(value, sanitized) if a != b),
            repr(value[:50]),
        )

    return sanitized


def _replacement_char(match: re.Match) -> str:
    """Replace unsafe characters with safe equivalents."""
    char = match.group(0)
    if char == '"':
        return "'"  # Double quote → single quote (preserves readability)
    elif char == '\\':
        return '/'  # Backslash → forward slash (common in paths)
    elif char in ('\n', '\r'):
        return ' '  # Newlines → space
    elif char == '\t':
        return ' '  # Tab → space
    else:
        return ''   # Control characters → removed


def clamp_depth(depth) -> float:
    """Clamp and validate depth value for EventBridge emission.

    Ensures:
      - Value is a valid float (not NaN, not Infinity)
      - Value is in range [0.0, 1.0]
      - Precision is limited to 3 decimal places (avoids floating point noise)

    Returns 0.0 for invalid inputs (graceful degradation).
    """
    try:
        depth_float = float(depth)
    except (TypeError, ValueError):
        logger.warning("Invalid depth value (not numeric), defaulting to 0.0: %s", repr(depth))
        return 0.0

    if math.isnan(depth_float) or math.isinf(depth_float):
        logger.warning("Invalid depth value (NaN/Inf), defaulting to 0.0: %s", repr(depth))
        return 0.0

    clamped = round(max(0.0, min(1.0, depth_float)), 3)

    if clamped != round(depth_float, 3):
        logger.warning(
            "Depth clamped from %.6f to %.3f (out of [0.0, 1.0] range)",
            depth_float, clamped,
        )

    return clamped


def sanitize_dispatch_detail(detail: dict) -> dict:
    """Sanitize an entire dispatch event detail dict for EventBridge emission.

    Applies:
      1. String sanitization to all user-generated fields
      2. Depth clamping and validation
      3. Passes through system fields and non-string fields unchanged

    The 'signals' field (nested dict) is passed through unchanged — it is NOT
    extracted by the InputTransformer (not in input_paths) and therefore cannot
    break the JSON substitution. It exists in the Detail for observability only.

    Returns a new dict (does not mutate the input).
    """
    sanitized = {}

    for key, value in detail.items():
        if key == "depth":
            sanitized[key] = clamp_depth(value)
        elif key in _USER_GENERATED_FIELDS and isinstance(value, str):
            sanitized[key] = sanitize_string_for_input_transformer(value, field_name=key)
        elif key in _SYSTEM_FIELDS:
            # System fields are safe by construction (UUIDs, enum values)
            sanitized[key] = value
        else:
            # Pass through: signals (dict), retry_count (int), etc.
            sanitized[key] = value

    return sanitized
