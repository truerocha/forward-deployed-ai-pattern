#!/usr/bin/env python3
"""
validate_fde_profile.py — Validates fde-profile.json schema and consistency.

Usage:
    python3 scripts/validate_fde_profile.py [path/to/fde-profile.json]

Exit codes:
    0 — Valid profile
    1 — Validation errors found
    2 — File not found (acceptable — means "use defaults")
"""

import json
import sys
from pathlib import Path
from typing import Any

# ─── Profile Preset Definitions ──────────────────────────────────────────────

PRESETS: dict[str, dict[str, Any]] = {
    "minimal": {
        "gates": {
            "dor": True,
            "adversarial": False,
            "dod": True,
            "pipeline-validation": False,
            "branch-evaluation": False,
            "icrl-feedback": False,
        },
        "extensions": {
            "multi-platform-export": False,
            "brown-field-elevation": False,
            "ddd-design-phase": False,
        },
    },
    "standard": {
        "gates": {
            "dor": True,
            "adversarial": True,
            "dod": True,
            "pipeline-validation": True,
            "branch-evaluation": False,
            "icrl-feedback": True,
        },
        "extensions": {
            "multi-platform-export": False,
            "brown-field-elevation": False,
            "ddd-design-phase": False,
        },
    },
    "strict": {
        "gates": {
            "dor": True,
            "adversarial": True,
            "dod": True,
            "pipeline-validation": True,
            "branch-evaluation": True,
            "icrl-feedback": True,
        },
        "extensions": {
            "multi-platform-export": True,
            "brown-field-elevation": True,
            "ddd-design-phase": True,
        },
    },
}

VALID_GATE_KEYS = {"dor", "adversarial", "dod", "pipeline-validation", "branch-evaluation", "icrl-feedback"}
VALID_EXTENSION_KEYS = {"multi-platform-export", "brown-field-elevation", "ddd-design-phase"}
VALID_PROFILES = {"minimal", "standard", "strict", "custom"}


def validate_profile(profile_path: Path) -> list[str]:
    """Validate fde-profile.json and return list of errors (empty = valid)."""
    errors: list[str] = []

    if not profile_path.exists():
        return []  # Missing file is valid — means "use all defaults"

    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [f"Invalid JSON: {e}"]

    # Required fields
    if "version" not in data:
        errors.append("Missing required field: 'version'")
    elif data["version"] != "1.0":
        errors.append(f"Unsupported version: {data['version']} (expected '1.0')")

    if "profile" not in data:
        errors.append("Missing required field: 'profile'")
    elif data["profile"] not in VALID_PROFILES:
        errors.append(f"Invalid profile: '{data['profile']}' (valid: {sorted(VALID_PROFILES)})")

    # Gates validation
    gates = data.get("gates", {})
    if not isinstance(gates, dict):
        errors.append("'gates' must be an object")
    else:
        for key in gates:
            if key not in VALID_GATE_KEYS:
                errors.append(f"Unknown gate: '{key}' (valid: {sorted(VALID_GATE_KEYS)})")
            elif not isinstance(gates[key], bool):
                errors.append(f"Gate '{key}' must be boolean, got {type(gates[key]).__name__}")

    # Extensions validation
    extensions = data.get("extensions", {})
    if not isinstance(extensions, dict):
        errors.append("'extensions' must be an object")
    else:
        for key in extensions:
            if key not in VALID_EXTENSION_KEYS:
                errors.append(f"Unknown extension: '{key}' (valid: {sorted(VALID_EXTENSION_KEYS)})")
            elif not isinstance(extensions[key], bool):
                errors.append(f"Extension '{key}' must be boolean, got {type(extensions[key]).__name__}")

    # Conductor validation
    conductor = data.get("conductor", {})
    if not isinstance(conductor, dict):
        errors.append("'conductor' must be an object")
    else:
        threshold = conductor.get("auto-design-threshold")
        if threshold is not None:
            if not isinstance(threshold, (int, float)):
                errors.append("'conductor.auto-design-threshold' must be a number")
            elif not (0.0 <= threshold <= 1.0):
                errors.append(f"'conductor.auto-design-threshold' must be 0.0-1.0, got {threshold}")

    # Preset consistency check
    profile_name = data.get("profile")
    if profile_name and profile_name != "custom" and profile_name in PRESETS:
        preset = PRESETS[profile_name]
        for section in ("gates", "extensions"):
            expected = preset.get(section, {})
            actual = data.get(section, {})
            for key, expected_value in expected.items():
                actual_value = actual.get(key, expected_value)  # default = expected
                if actual_value != expected_value:
                    errors.append(
                        f"Profile '{profile_name}' requires {section}.{key}={expected_value}, "
                        f"but got {actual_value}. Use profile='custom' for non-standard configs."
                    )

    # Dependency checks
    if extensions.get("ddd-design-phase") and not extensions.get("brown-field-elevation"):
        # This is a warning, not an error — DDD can work without elevation for green-field
        pass  # Intentionally not an error

    return errors


def main() -> int:
    """CLI entry point."""
    profile_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("fde-profile.json")

    if not profile_path.exists():
        print(f"ℹ️  {profile_path} not found — FDE will use full enforcement (all gates ON)")
        return 2

    errors = validate_profile(profile_path)

    if errors:
        print(f"❌ {profile_path} has {len(errors)} validation error(s):")
        for err in errors:
            print(f"   • {err}")
        return 1

    # Success — show summary
    data = json.loads(profile_path.read_text(encoding="utf-8"))
    active_gates = [k for k, v in data.get("gates", {}).items() if v]
    active_extensions = [k for k, v in data.get("extensions", {}).items() if v]

    print(f"✅ {profile_path} is valid")
    print(f"   Profile: {data.get('profile')}")
    print(f"   Active gates: {', '.join(active_gates) or 'none'}")
    print(f"   Active extensions: {', '.join(active_extensions) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
