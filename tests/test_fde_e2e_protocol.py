#!/usr/bin/env python3
"""E2E simulation of the Forward Deployed AI Engineer (FDE) protocol.

This test validates that the FDE mechanism — steering, hooks, and gates —
forms a coherent quality lifecycle. It does NOT test LLM output quality;
it tests that the structural contracts are enforceable and that each gate
produces the expected artifact shape.

The simulation walks through a realistic task scenario:
  Task: "Fix the severity distribution — findings are all MEDIUM"

And validates that each protocol phase produces the required output.

Run: python3 -m pytest tests/test_fde_e2e_protocol.py -v
"""
import json
import os
import re

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = os.path.join(os.path.dirname(__file__), "..")
HOOKS_DIR = os.path.join(ROOT, ".kiro", "hooks")
STEERING_DIR = os.path.join(ROOT, ".kiro", "steering")
DESIGN_DOC = os.path.join(ROOT, "docs", "design", "forward-deployed-ai-engineers.md")


# ===========================================================================
# Fixture: load all FDE artifacts
# ===========================================================================
@pytest.fixture(scope="module")
def fde_hooks():
    """Load all FDE hook files as parsed JSON."""
    hooks = {}
    for fname in os.listdir(HOOKS_DIR):
        if fname.startswith("fde-") and fname.endswith(".kiro.hook"):
            path = os.path.join(HOOKS_DIR, fname)
            with open(path) as f:
                hooks[fname.replace(".kiro.hook", "")] = json.load(f)
    return hooks


@pytest.fixture(scope="module")
def fde_steering():
    """Load the FDE steering file content."""
    path = os.path.join(STEERING_DIR, "fde.md")
    with open(path) as f:
        return f.read()


@pytest.fixture(scope="module")
def design_doc():
    """Load the FDE design document."""
    with open(DESIGN_DOC) as f:
        return f.read()


# ===========================================================================
# 1. ARTIFACT EXISTENCE — All FDE artifacts exist
# ===========================================================================
class TestArtifactExistence:
    """Verify all FDE protocol artifacts are present."""

    def test_steering_exists(self):
        assert os.path.isfile(os.path.join(STEERING_DIR, "fde.md"))

    def test_dor_gate_exists(self):
        assert os.path.isfile(os.path.join(HOOKS_DIR, "fde-dor-gate.kiro.hook"))

    def test_adversarial_gate_exists(self):
        assert os.path.isfile(
            os.path.join(HOOKS_DIR, "fde-adversarial-gate.kiro.hook")
        )

    def test_dod_gate_exists(self):
        assert os.path.isfile(os.path.join(HOOKS_DIR, "fde-dod-gate.kiro.hook"))

    def test_pipeline_validation_exists(self):
        assert os.path.isfile(
            os.path.join(HOOKS_DIR, "fde-pipeline-validation.kiro.hook")
        )

    def test_design_doc_exists(self):
        assert os.path.isfile(DESIGN_DOC)


# ===========================================================================
# 2. HOOK SCHEMA — All hooks follow the required schema
# ===========================================================================
class TestHookSchema:
    """Verify all FDE hooks conform to the Kiro hook schema."""

    REQUIRED_KEYS = {"name", "version", "when", "then"}
    VALID_EVENT_TYPES = {
        "fileEdited",
        "fileCreated",
        "fileDeleted",
        "userTriggered",
        "promptSubmit",
        "agentStop",
        "preToolUse",
        "postToolUse",
        "preTaskExecution",
        "postTaskExecution",
    }

    def test_all_hooks_have_required_keys(self, fde_hooks):
        for name, hook in fde_hooks.items():
            for key in self.REQUIRED_KEYS:
                assert key in hook, f"Hook '{name}' missing required key '{key}'"

    def test_all_hooks_have_valid_event_type(self, fde_hooks):
        for name, hook in fde_hooks.items():
            event_type = hook["when"]["type"]
            assert event_type in self.VALID_EVENT_TYPES, (
                f"Hook '{name}' has invalid event type '{event_type}'"
            )

    def test_all_hooks_have_prompt_or_command(self, fde_hooks):
        for name, hook in fde_hooks.items():
            then = hook["then"]
            if then["type"] == "askAgent":
                assert "prompt" in then, (
                    f"Hook '{name}' is askAgent but missing 'prompt'"
                )
            elif then["type"] == "runCommand":
                assert "command" in then, (
                    f"Hook '{name}' is runCommand but missing 'command'"
                )


# ===========================================================================
# 3. QUALITY LIFECYCLE ORDER — Hooks fire in the correct sequence
# ===========================================================================
class TestQualityLifecycle:
    """Verify the 4 hooks form the correct quality lifecycle sequence."""

    EXPECTED_LIFECYCLE = [
        ("fde-dor-gate", "preTaskExecution"),
        ("fde-adversarial-gate", "preToolUse"),
        ("fde-dod-gate", "postTaskExecution"),
        ("fde-pipeline-validation", "postTaskExecution"),
    ]

    def test_lifecycle_sequence(self, fde_hooks):
        for hook_name, expected_event in self.EXPECTED_LIFECYCLE:
            assert hook_name in fde_hooks, f"Missing hook: {hook_name}"
            actual_event = fde_hooks[hook_name]["when"]["type"]
            assert actual_event == expected_event, (
                f"Hook '{hook_name}' should fire on '{expected_event}' "
                f"but fires on '{actual_event}'"
            )

    def test_adversarial_gate_scoped_to_write(self, fde_hooks):
        hook = fde_hooks["fde-adversarial-gate"]
        tool_types = hook["when"].get("toolTypes", [])
        assert "write" in tool_types, (
            "Adversarial gate must be scoped to 'write' tool type"
        )


# ===========================================================================
# 4. DoR GATE — Structured Intake Contract validation
# ===========================================================================
class TestDoRGate:
    """Verify the DoR gate enforces the Phase 2 Structured Intake Contract."""

    def test_dor_requires_context_section(self, fde_hooks):
        prompt = fde_hooks["fde-dor-gate"]["then"]["prompt"]
        assert "CONTEXT" in prompt
        assert "upstream" in prompt.lower()
        assert "downstream" in prompt.lower()
        assert "artifact type" in prompt.lower()

    def test_dor_requires_instruction_section(self, fde_hooks):
        prompt = fde_hooks["fde-dor-gate"]["then"]["prompt"]
        assert "INSTRUCTION" in prompt
        assert "acceptance criteria" in prompt.lower()

    def test_dor_requires_constraints_section(self, fde_hooks):
        prompt = fde_hooks["fde-dor-gate"]["then"]["prompt"]
        assert "CONSTRAINT" in prompt
        assert "out of scope" in prompt.lower()

    def test_dor_requires_quality_standards_check(self, fde_hooks):
        prompt = fde_hooks["fde-dor-gate"]["then"]["prompt"]
        assert "QUALITY STANDARDS" in prompt or "APPLICABLE STANDARDS" in prompt
        assert "régua" in prompt.lower() or "regua" in prompt.lower()


# ===========================================================================
# 5. ADVERSARIAL GATE — Phase 3.a challenges
# ===========================================================================
class TestAdversarialGate:
    """Verify the adversarial gate asks the required challenge questions."""

    REQUIRED_CHALLENGES = [
        "downstream",
        "parallel",
        "root cause",
        "knowledge validation",
        "architectural",
        "anticipatory",
    ]

    def test_all_challenges_present(self, fde_hooks):
        prompt = fde_hooks["fde-adversarial-gate"]["then"]["prompt"].lower()
        for challenge in self.REQUIRED_CHALLENGES:
            assert challenge in prompt, (
                f"Adversarial gate missing challenge: '{challenge}'"
            )

    def test_references_intake_contract(self, fde_hooks):
        prompt = fde_hooks["fde-adversarial-gate"]["then"]["prompt"].lower()
        assert "intake contract" in prompt or "context + instruction" in prompt, (
            "Adversarial gate must reference the Phase 2 intake contract"
        )

    def test_references_recipe_position(self, fde_hooks):
        prompt = fde_hooks["fde-adversarial-gate"]["then"]["prompt"].lower()
        assert "recipe" in prompt or "step" in prompt, (
            "Adversarial gate must reference recipe position awareness"
        )


# ===========================================================================
# 6. DoD GATE — Compliance matrix validation
# ===========================================================================
class TestDoDGate:
    """Verify the DoD gate produces a compliance matrix."""

    def test_dod_requires_compliance_matrix(self, fde_hooks):
        prompt = fde_hooks["fde-dod-gate"]["then"]["prompt"]
        assert "COMPLIANCE MATRIX" in prompt
        assert "Standard" in prompt
        assert "Met?" in prompt or "Evidence" in prompt

    def test_dod_requires_pass_partial_block(self, fde_hooks):
        prompt = fde_hooks["fde-dod-gate"]["then"]["prompt"]
        assert "PASS" in prompt
        assert "PARTIAL" in prompt
        assert "BLOCK" in prompt

    def test_dod_distinguishes_validation_verification(self, fde_hooks):
        prompt = fde_hooks["fde-dod-gate"]["then"]["prompt"].lower()
        assert "verification" in prompt
        assert "validation" in prompt


# ===========================================================================
# 7. PIPELINE VALIDATION — 5W2H and 5 Whys
# ===========================================================================
class TestPipelineValidation:
    """Verify the pipeline validation hook enforces 5W2H and 5 Whys."""

    W2H_DIMENSIONS = ["what", "where", "when", "who", "why", "how"]

    def test_5w2h_present(self, fde_hooks):
        prompt = fde_hooks["fde-pipeline-validation"]["then"]["prompt"].lower()
        for dim in self.W2H_DIMENSIONS:
            assert dim in prompt, f"Pipeline validation missing 5W2H dimension: {dim}"

    def test_5_whys_present(self, fde_hooks):
        prompt = fde_hooks["fde-pipeline-validation"]["then"]["prompt"].lower()
        assert "5 whys" in prompt or "whys" in prompt
        assert "root cause" in prompt
        assert "symptom" in prompt

    def test_completion_report_present(self, fde_hooks):
        prompt = fde_hooks["fde-pipeline-validation"]["then"]["prompt"].lower()
        assert "completion report" in prompt or "summarize" in prompt
        assert "delivered" in prompt
        assert "validated" in prompt
        assert "not validated" in prompt or "residual" in prompt


# ===========================================================================
# 8. STEERING — FDE identity and protocol rules
# ===========================================================================
class TestSteering:
    """Verify the FDE steering establishes identity and protocol rules."""

    def test_fde_identity(self, fde_steering):
        assert "Forward Deployed AI Engineer" in fde_steering

    def test_manual_inclusion(self, fde_steering):
        assert "inclusion: manual" in fde_steering

    def test_phase2_rule(self, fde_steering):
        assert "Structured Prompt Contract" in fde_steering
        assert "Context" in fde_steering
        assert "Instruction" in fde_steering
        assert "Constraints" in fde_steering

    def test_phase3_rule(self, fde_steering):
        assert "Recipe-Aware" in fde_steering or "recipe" in fde_steering.lower()
        assert "accumulated context" in fde_steering.lower()

    def test_regua_section(self, fde_steering):
        assert "Régua" in fde_steering or "régua" in fde_steering
        assert "Quality Reference Artifacts" in fde_steering

    def test_anti_patterns(self, fde_steering):
        assert "Symptom chasing" in fde_steering
        assert "Node-scoped verification" in fde_steering
        assert "Independent interaction" in fde_steering
        assert "Architecture-unaware patching" in fde_steering

    def test_hook_references(self, fde_steering):
        assert "fde-dor-gate" in fde_steering
        assert "fde-adversarial-gate" in fde_steering
        assert "fde-dod-gate" in fde_steering
        assert "fde-pipeline-validation" in fde_steering


# ===========================================================================
# 9. DESIGN DOC — Structural integrity
# ===========================================================================
class TestDesignDoc:
    """Verify the design doc has all required sections and no stale refs."""

    REQUIRED_SECTIONS = [
        "Purpose and Scope",
        "Research Foundations",
        "The Problem",
        "Four-Phase Autonomous Engineering Protocol",
        "Kiro Implementation",
        "Engineering Level Classification",
        "Applying This Pattern to Other Projects",
        "How to Use",
        "References",
    ]

    def test_all_sections_present(self, design_doc):
        for section in self.REQUIRED_SECTIONS:
            assert section in design_doc, f"Design doc missing section: '{section}'"

    def test_no_stale_forward_applied_ai_refs(self, design_doc):
        assert "Forward Applied AI" not in design_doc, (
            "Design doc still contains stale 'Forward Applied AI' references"
        )

    def test_no_stale_file_refs(self, design_doc):
        assert "applied-forward-AI-dev-wafr" not in design_doc, (
            "Design doc still references old filename"
        )

    def test_no_stale_hook_refs(self, design_doc):
        assert "forward-ai-adversarial-gate" not in design_doc
        assert "forward-ai-dor-gate" not in design_doc
        assert "forward-ai-dod-gate" not in design_doc
        assert "forward-ai-pipeline-validation" not in design_doc

    def test_fde_branding(self, design_doc):
        assert "Forward Deployed AI Engineer" in design_doc
        assert "FDE" in design_doc

    def test_four_research_papers(self, design_doc):
        assert "Esposito" in design_doc
        assert "Vandeputte" in design_doc
        assert "Shonan" in design_doc
        assert "DiCuffa" in design_doc

    def test_dor_dod_sections(self, design_doc):
        assert "Definition of Ready" in design_doc
        assert "Definition of Done" in design_doc
        assert "régua" in design_doc.lower() or "Régua" in design_doc

    def test_diagram_section(self, design_doc):
        assert "Architecture Diagram Generation" in design_doc

    def test_structured_intake(self, design_doc):
        assert "Structured Prompt Contract" in design_doc

    def test_recipe_aware(self, design_doc):
        assert "Recipe-Aware" in design_doc


# ===========================================================================
# 10. E2E SCENARIO — Simulate a full task lifecycle
# ===========================================================================
class TestE2EScenario:
    """Simulate a complete FDE task lifecycle for a realistic scenario.

    Scenario: "Fix the severity distribution — findings are all MEDIUM"

    This test validates that the protocol's structural contracts would
    produce the right sequence of gates and that each gate's prompt
    contains the questions relevant to this specific task type.
    """

    TASK = "Fix the severity distribution — findings are all MEDIUM"

    def test_phase1_steering_provides_pipeline_context(self, fde_steering):
        """Phase 1: Steering must provide a pipeline chain so the agent
        can locate where changes sit in the data flow."""
        assert "pipeline" in fde_steering.lower() or "module" in fde_steering.lower()
        assert "Edge" in fde_steering or "E1" in fde_steering or "Producer" in fde_steering

    def test_phase2_dor_would_reformulate_intake(self, fde_hooks):
        """Phase 2: DoR gate must ask the agent to reformulate the bare
        question into Context + Instruction + Constraints."""
        prompt = fde_hooks["fde-dor-gate"]["then"]["prompt"]
        # The gate must force reformulation, not accept the raw question
        assert "reformulate" in prompt.lower() or "Reformulate" in prompt
        assert "bare question" in prompt.lower() or "raw task" in prompt.lower()

    def test_phase3a_adversarial_catches_knowledge_artifact(self, fde_hooks):
        """Phase 3.a: For a severity fix, the adversarial gate must ask
        about knowledge validation (severity map is a knowledge artifact)."""
        prompt = fde_hooks["fde-adversarial-gate"]["then"]["prompt"].lower()
        assert "knowledge validation" in prompt
        assert "domain source of truth" in prompt or "semantically correct" in prompt

    def test_phase3a_adversarial_catches_architectural_escalation(self, fde_hooks):
        """Phase 3.a: Severity being flat might be an architecture problem
        (flat map vs risk engine). The gate must ask about escalation."""
        prompt = fde_hooks["fde-adversarial-gate"]["then"]["prompt"].lower()
        assert "architectural" in prompt
        assert "patching" in prompt or "wrong design" in prompt

    def test_phase3b_pipeline_validation_checks_downstream(self, fde_hooks):
        """Phase 3.b: Pipeline validation must check edges and contracts."""
        prompt = fde_hooks["fde-pipeline-validation"]["then"]["prompt"].lower()
        assert "edge" in prompt or "downstream" in prompt
        assert "contract" in prompt

    def test_phase4_dod_requires_compliance_evidence(self, fde_hooks):
        """Phase 4: DoD must require evidence that the fix conforms to
        quality standards, not just that tests pass."""
        prompt = fde_hooks["fde-dod-gate"]["then"]["prompt"].lower()
        assert "evidence" in prompt
        assert "compliance" in prompt or "standard" in prompt

    def test_full_lifecycle_no_gaps(self, fde_hooks):
        """The 4 hooks must cover all lifecycle moments with no gaps:
        preTask → preToolUse(write) → postTask(DoD) → postTask(pipeline)"""
        events = [h["when"]["type"] for h in fde_hooks.values()]
        assert "preTaskExecution" in events, "Missing preTask gate"
        assert "preToolUse" in events, "Missing preToolUse gate"
        assert events.count("postTaskExecution") >= 2, (
            "Need at least 2 postTask gates (DoD + pipeline)"
        )
