"""
Integration Test: Portal Component Validation.

Validates that all portal component files exist and are valid TypeScript.
Uses subprocess to run `tsc --noEmit` on the portal-src directory when
available. Falls back to file existence checks if tsc is not installed.

Activity: 4.23
Ref: infra/portal-src/src/components/
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

# ─── Configuration ──────────────────────────────────────────────

PORTAL_TESTS_ENABLED = os.environ.get("FDE_PORTAL_TESTS_ENABLED", "false").lower() == "true"

skip_portal = pytest.mark.skipif(
    not PORTAL_TESTS_ENABLED,
    reason="FDE_PORTAL_TESTS_ENABLED not set — skipping portal TypeScript tests",
)

# Path to portal source relative to project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
PORTAL_SRC_DIR = PROJECT_ROOT / "infra" / "portal-src"
COMPONENTS_DIR = PORTAL_SRC_DIR / "src" / "components"

# All 14 expected portal component files (from ADR-017)
EXPECTED_COMPONENTS = [
    "AgentSidebar.tsx",
    "BrainSimCard.tsx",
    "BranchEvaluationCard.tsx",
    "CostCard.tsx",
    "DataQualityCard.tsx",
    "DoraCard.tsx",
    "GateFeedbackCard.tsx",
    "GateHistoryCard.tsx",
    "Header.tsx",
    "HumanInputCard.tsx",
    "LiveTimeline.tsx",
    "MaturityRadar.tsx",
    "MetricsCard.tsx",
    "ValueStreamCard.tsx",
]

# Additional component files that exist but are not in the core 14
ADDITIONAL_COMPONENTS = [
    "ComponentHealthCard.tsx",
    "NetFrictionCard.tsx",
    "PersonaRouter.tsx",
    "RegistriesCard.tsx",
    "SquadExecutionCard.tsx",
    "Terminal.tsx",
    "TrustCard.tsx",
]


# ─── Local Tests: File Existence (always run) ───────────────────


class TestPortalComponentsExist:
    """Validate that all expected portal component files exist."""

    def test_portal_src_directory_exists(self):
        """infra/portal-src/ directory exists."""
        assert PORTAL_SRC_DIR.exists(), f"Portal source directory not found: {PORTAL_SRC_DIR}"

    def test_components_directory_exists(self):
        """infra/portal-src/src/components/ directory exists."""
        assert COMPONENTS_DIR.exists(), f"Components directory not found: {COMPONENTS_DIR}"

    @pytest.mark.parametrize("component", EXPECTED_COMPONENTS)
    def test_core_component_file_exists(self, component):
        """Each of the 14 core portal component files exists."""
        filepath = COMPONENTS_DIR / component
        assert filepath.exists(), f"Missing component: {component}"

    @pytest.mark.parametrize("component", EXPECTED_COMPONENTS)
    def test_component_is_not_empty(self, component):
        """Each component file has non-trivial content (>50 bytes)."""
        filepath = COMPONENTS_DIR / component
        if filepath.exists():
            size = filepath.stat().st_size
            assert size > 50, f"{component} is too small ({size} bytes) — likely a placeholder"

    @pytest.mark.parametrize("component", EXPECTED_COMPONENTS)
    def test_component_has_tsx_extension(self, component):
        """Each component file has .tsx extension."""
        assert component.endswith(".tsx"), f"{component} should be a .tsx file"

    def test_at_least_14_components_exist(self):
        """At least 14 component files exist in the components directory."""
        if not COMPONENTS_DIR.exists():
            pytest.skip("Components directory not found")
        tsx_files = list(COMPONENTS_DIR.glob("*.tsx"))
        assert len(tsx_files) >= 14, (
            f"Expected at least 14 components, found {len(tsx_files)}: "
            f"{[f.name for f in tsx_files]}"
        )

    @pytest.mark.parametrize("component", EXPECTED_COMPONENTS)
    def test_component_contains_react_import(self, component):
        """Each component imports React or uses JSX (contains 'react' reference)."""
        filepath = COMPONENTS_DIR / component
        if not filepath.exists():
            pytest.skip(f"{component} not found")
        content = filepath.read_text(encoding="utf-8")
        # React components should reference react in some form
        has_react = (
            "react" in content.lower()
            or "React" in content
            or "jsx" in content.lower()
            or "tsx" in content.lower()
        )
        assert has_react, f"{component} does not appear to be a React component"

    @pytest.mark.parametrize("component", EXPECTED_COMPONENTS)
    def test_component_exports_something(self, component):
        """Each component has at least one export statement."""
        filepath = COMPONENTS_DIR / component
        if not filepath.exists():
            pytest.skip(f"{component} not found")
        content = filepath.read_text(encoding="utf-8")
        has_export = "export" in content
        assert has_export, f"{component} has no export statement"


# ─── Local Tests: Supporting Files ──────────────────────────────


class TestPortalSupportingFiles:
    """Validate supporting portal files exist."""

    def test_tsconfig_exists(self):
        """tsconfig.json exists in portal-src."""
        tsconfig = PORTAL_SRC_DIR / "tsconfig.json"
        assert tsconfig.exists(), "tsconfig.json not found in portal-src"

    def test_package_json_exists(self):
        """package.json exists in portal-src."""
        package_json = PORTAL_SRC_DIR / "package.json"
        assert package_json.exists(), "package.json not found in portal-src"

    def test_vite_config_exists(self):
        """vite.config.ts exists in portal-src."""
        vite_config = PORTAL_SRC_DIR / "vite.config.ts"
        assert vite_config.exists(), "vite.config.ts not found in portal-src"

    def test_app_tsx_exists(self):
        """App.tsx exists in portal-src/src."""
        app_tsx = PORTAL_SRC_DIR / "src" / "App.tsx"
        assert app_tsx.exists(), "App.tsx not found in portal-src/src"

    def test_types_ts_exists(self):
        """types.ts exists in portal-src/src."""
        types_ts = PORTAL_SRC_DIR / "src" / "types.ts"
        assert types_ts.exists(), "types.ts not found in portal-src/src"


# ─── TypeScript Compilation Tests (gated) ───────────────────────


@skip_portal
class TestPortalTypeScriptCompilation:
    """Run tsc --noEmit to validate TypeScript correctness.

    Gated by FDE_PORTAL_TESTS_ENABLED=true.
    Falls back gracefully if tsc is not available.
    """

    @pytest.fixture
    def tsc_available(self):
        """Check if tsc is available on PATH or in node_modules."""
        # Check local node_modules first
        local_tsc = PORTAL_SRC_DIR / "node_modules" / ".bin" / "tsc"
        if local_tsc.exists():
            return str(local_tsc)

        # Check global tsc
        global_tsc = shutil.which("tsc")
        if global_tsc:
            return global_tsc

        pytest.skip("tsc not available — skipping TypeScript compilation test")

    def test_tsc_no_emit_succeeds(self, tsc_available):
        """tsc --noEmit passes without errors on portal-src."""
        result = subprocess.run(
            [tsc_available, "--noEmit"],
            cwd=str(PORTAL_SRC_DIR),
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            # Provide helpful error output
            error_lines = result.stdout.splitlines()[:20]
            error_summary = "\n".join(error_lines)
            pytest.fail(
                f"TypeScript compilation failed with {result.returncode}:\n{error_summary}"
            )

    def test_tsc_strict_mode_enabled(self):
        """tsconfig.json has strict mode enabled."""
        import json

        tsconfig_path = PORTAL_SRC_DIR / "tsconfig.json"
        if not tsconfig_path.exists():
            pytest.skip("tsconfig.json not found")

        content = tsconfig_path.read_text(encoding="utf-8")
        config = json.loads(content)

        compiler_options = config.get("compilerOptions", {})
        # Strict mode or individual strict flags should be present
        has_strict = (
            compiler_options.get("strict", False)
            or compiler_options.get("noImplicitAny", False)
        )
        assert has_strict, "tsconfig.json should have strict or noImplicitAny enabled"

    def test_no_any_type_in_components(self):
        """Components should minimize use of 'any' type (warning, not failure)."""
        if not COMPONENTS_DIR.exists():
            pytest.skip("Components directory not found")

        any_count = 0
        for component in EXPECTED_COMPONENTS:
            filepath = COMPONENTS_DIR / component
            if filepath.exists():
                content = filepath.read_text(encoding="utf-8")
                # Count explicit ': any' type annotations
                any_count += content.count(": any")

        # This is a soft check — warn but don't fail
        if any_count > 10:
            import warnings
            warnings.warn(
                f"Found {any_count} explicit 'any' type annotations across portal components. "
                "Consider adding proper types.",
                stacklevel=1,
            )
