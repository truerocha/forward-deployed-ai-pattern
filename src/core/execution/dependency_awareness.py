"""
Dependency Awareness — Aggregates multiple sources to determine what a task needs.

This module answers: "What tools, packages, and binaries does this task require?"
by consulting three sources of truth:

  1. data_contract.tech_stack — from the issue template (e.g., ["Python", "Terraform"])
  2. Repo manifests — requirements.txt, package.json, Cargo.toml, pom.xml, etc.
  3. Parsed execution steps — binaries/scripts referenced in commands (ERP tasks only)

The output is a ProvisioningPlan that the DependencyResolver can execute.

Design decisions:
  - Language/framework agnostic: supports Python, Node, Go, Rust, Java, Terraform, etc.
  - Non-blocking: if a source is unavailable, skip it (best-effort aggregation)
  - Deterministic: no LLM calls — operates on file presence and pattern matching
  - Follows KG cascade pattern: aggregate what you can, degrade gracefully

Ref: ADR-038 Wave 4 (Dependency Provisioning Phase)
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Data Contracts
# ═══════════════════════════════════════════════════════════════════

@dataclass
class InstallAction:
    """A single dependency installation action."""

    name: str                    # e.g., "pytest", "terraform", "node_modules"
    strategy: str                # "pip_user" | "binary_download" | "npm_local" | "cargo_install" | "skip"
    command: str                 # e.g., "pip install --user pytest"
    source: str                  # "tech_stack" | "repo_manifest" | "step_commands"
    category: str                # "python" | "node" | "binary" | "rust" | "java" | "go"
    priority: int = 1            # 1=critical, 2=recommended, 3=optional
    timeout_seconds: int = 60    # Max time for this install action


@dataclass
class ProvisioningPlan:
    """What needs to be installed before agent execution."""

    tech_stack: list[str] = field(default_factory=list)
    actions: list[InstallAction] = field(default_factory=list)
    repo_manifests_found: list[str] = field(default_factory=list)
    sources_consulted: list[str] = field(default_factory=list)
    total_budget_seconds: int = 120  # Max total provisioning time

    def has_actions(self) -> bool:
        return bool(self.actions)

    def summary(self) -> str:
        if not self.actions:
            return "No provisioning needed"
        categories = {}
        for a in self.actions:
            categories.setdefault(a.category, []).append(a.name)
        parts = [f"{cat}: {', '.join(names)}" for cat, names in categories.items()]
        return f"{len(self.actions)} actions ({'; '.join(parts)})"


# ═══════════════════════════════════════════════════════════════════
# Tech Stack → Provisioning Mapping (Knowledge Artifact)
# ═══════════════════════════════════════════════════════════════════

# This mapping defines what each tech_stack tag implies for tooling.
# It is a knowledge artifact — domain validation, not syntax correctness.
# Extend this as new stacks are onboarded to the factory.

TECH_STACK_PROVISIONS: dict[str, list[InstallAction]] = {
    "Python": [
        InstallAction(
            name="pytest", strategy="pip_user",
            command="pip install --user pytest pytest-cov",
            source="tech_stack", category="python", priority=1, timeout_seconds=30,
        ),
        InstallAction(
            name="ruff", strategy="pip_user",
            command="pip install --user ruff",
            source="tech_stack", category="python", priority=2, timeout_seconds=20,
        ),
        InstallAction(
            name="pip-tools", strategy="pip_user",
            command="pip install --user pip-tools",
            source="tech_stack", category="python", priority=2, timeout_seconds=20,
        ),
    ],
    "FastAPI": [
        InstallAction(
            name="httpx", strategy="pip_user",
            command="pip install --user httpx",
            source="tech_stack", category="python", priority=2, timeout_seconds=20,
        ),
    ],
    "Terraform": [
        InstallAction(
            name="terraform", strategy="binary_download",
            command="curl -fsSL https://releases.hashicorp.com/terraform/1.8.5/terraform_1.8.5_linux_amd64.zip -o /tmp/tf.zip && unzip -o /tmp/tf.zip -d $HOME/.local/bin/ && rm /tmp/tf.zip",
            source="tech_stack", category="binary", priority=1, timeout_seconds=60,
        ),
    ],
    "Node": [
        # Node is already in the Dockerfile (setup_20.x) — verify only
        InstallAction(
            name="npm-check", strategy="skip",
            command="node --version",
            source="tech_stack", category="node", priority=3, timeout_seconds=5,
        ),
    ],
    "TypeScript": [
        InstallAction(
            name="typescript", strategy="npm_local",
            command="npm install --prefix $HOME/.local typescript ts-node",
            source="tech_stack", category="node", priority=2, timeout_seconds=30,
        ),
    ],
    "Go": [
        InstallAction(
            name="go", strategy="binary_download",
            command="curl -fsSL https://go.dev/dl/go1.22.4.linux-amd64.tar.gz | tar -C $HOME/.local -xzf -",
            source="tech_stack", category="binary", priority=1, timeout_seconds=60,
        ),
    ],
    "Rust": [
        InstallAction(
            name="cargo", strategy="binary_download",
            command="curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path --default-toolchain stable --profile minimal",
            source="tech_stack", category="binary", priority=1, timeout_seconds=90,
        ),
    ],
    "Java": [
        # Java/Quarkus/Maven — JDK too large for runtime install.
        # Mark as skip — should be in Dockerfile variant.
        InstallAction(
            name="java", strategy="skip",
            command="java -version",
            source="tech_stack", category="binary", priority=1, timeout_seconds=5,
        ),
    ],
    "Quarkus": [
        InstallAction(
            name="quarkus-cli", strategy="skip",
            command="quarkus --version",
            source="tech_stack", category="binary", priority=1, timeout_seconds=5,
        ),
    ],
    "AWS": [
        InstallAction(
            name="aws-cli-check", strategy="skip",
            command="aws --version",
            source="tech_stack", category="binary", priority=3, timeout_seconds=5,
        ),
    ],
}

# Manifest file detection patterns
MANIFEST_PATTERNS: dict[str, dict] = {
    "requirements.txt": {
        "category": "python",
        "strategy": "pip_user",
        "command_template": "pip install --user -r {path}",
        "priority": 1,
        "timeout_seconds": 60,
    },
    "requirements-dev.txt": {
        "category": "python",
        "strategy": "pip_user",
        "command_template": "pip install --user -r {path}",
        "priority": 2,
        "timeout_seconds": 60,
    },
    "pyproject.toml": {
        "category": "python",
        "strategy": "pip_user",
        "command_template": "pip install --user -e {dir}",
        "priority": 2,
        "timeout_seconds": 90,
    },
    "package.json": {
        "category": "node",
        "strategy": "npm_local",
        "command_template": "cd {dir} && npm install",
        "priority": 1,
        "timeout_seconds": 90,
    },
    "Cargo.toml": {
        "category": "rust",
        "strategy": "skip",
        "command_template": "",
        "priority": 3,
        "timeout_seconds": 0,
    },
    "go.mod": {
        "category": "go",
        "strategy": "skip",
        "command_template": "",
        "priority": 3,
        "timeout_seconds": 0,
    },
    "pom.xml": {
        "category": "java",
        "strategy": "skip",
        "command_template": "",
        "priority": 3,
        "timeout_seconds": 0,
    },
    "Makefile": {
        "category": "build",
        "strategy": "skip",
        "command_template": "",
        "priority": 3,
        "timeout_seconds": 0,
    },
}


# ═══════════════════════════════════════════════════════════════════
# Core Logic
# ═══════════════════════════════════════════════════════════════════

def build_provisioning_plan(
    tech_stack: list[str],
    workspace_dir: str,
    execution_commands: Optional[list[str]] = None,
) -> ProvisioningPlan:
    """Build a provisioning plan by aggregating all awareness sources.

    Args:
        tech_stack: From data_contract.tech_stack (e.g., ["Python", "Terraform"]).
        workspace_dir: Path to the cloned repo (for manifest detection).
        execution_commands: Optional list of commands from ERP steps (for binary detection).

    Returns:
        ProvisioningPlan with all required install actions.
    """
    plan = ProvisioningPlan(tech_stack=tech_stack)
    seen_names: set[str] = set()

    # ── Source 1: tech_stack mapping ─────────────────────────────────
    plan.sources_consulted.append("tech_stack")
    for stack_tag in tech_stack:
        # Normalize: "python" → "Python", "terraform" → "Terraform"
        normalized = stack_tag.strip().capitalize()
        actions = TECH_STACK_PROVISIONS.get(normalized, [])
        for action in actions:
            if action.name not in seen_names and action.strategy != "skip":
                plan.actions.append(action)
                seen_names.add(action.name)

    # ── Source 2: Repo manifests ─────────────────────────────────────
    if workspace_dir and os.path.isdir(workspace_dir):
        plan.sources_consulted.append("repo_manifest")
        for manifest_name, config in MANIFEST_PATTERNS.items():
            manifest_path = os.path.join(workspace_dir, manifest_name)
            if os.path.isfile(manifest_path):
                plan.repo_manifests_found.append(manifest_name)

                if config["strategy"] == "skip":
                    continue

                # Build the install command from template
                command = config["command_template"].format(
                    path=manifest_path,
                    dir=workspace_dir,
                )
                action_name = f"manifest:{manifest_name}"
                if action_name not in seen_names:
                    plan.actions.append(InstallAction(
                        name=action_name,
                        strategy=config["strategy"],
                        command=command,
                        source="repo_manifest",
                        category=config["category"],
                        priority=config["priority"],
                        timeout_seconds=config["timeout_seconds"],
                    ))
                    seen_names.add(action_name)

    # ── Source 3: Execution step commands (ERP tasks only) ───────────
    if execution_commands:
        plan.sources_consulted.append("step_commands")
        _extract_binary_needs(execution_commands, plan, seen_names)

    # Sort by priority (critical first)
    plan.actions.sort(key=lambda a: a.priority)

    # Compute total budget (capped at 180s)
    plan.total_budget_seconds = min(
        sum(a.timeout_seconds for a in plan.actions),
        180,
    )

    logger.info(
        "Provisioning plan built: %d actions, sources=%s, manifests=%s, budget=%ds",
        len(plan.actions),
        plan.sources_consulted,
        plan.repo_manifests_found,
        plan.total_budget_seconds,
    )

    return plan


def _extract_binary_needs(
    commands: list[str],
    plan: ProvisioningPlan,
    seen_names: set[str],
) -> None:
    """Extract binary requirements from execution step commands.

    Detects patterns like:
      - "terraform plan" → needs terraform
      - "pytest tests/" → needs pytest
      - "pip-compile requirements.in" → needs pip-tools
      - "cargo build" → needs cargo
      - "go build ./..." → needs go
      - "mvn package" → needs maven
      - "quarkus build" → needs quarkus
    """
    binary_mapping = {
        "terraform": ("terraform", "binary_download", "binary"),
        "pytest": ("pytest", "pip_user", "python"),
        "pip-compile": ("pip-tools", "pip_user", "python"),
        "ruff": ("ruff", "pip_user", "python"),
        "black": ("black", "pip_user", "python"),
        "mypy": ("mypy", "pip_user", "python"),
        "cargo": ("cargo", "binary_download", "rust"),
        "rustc": ("cargo", "binary_download", "rust"),
        "go": ("go", "binary_download", "go"),
        "mvn": ("maven", "skip", "java"),
        "gradle": ("gradle", "skip", "java"),
        "quarkus": ("quarkus-cli", "skip", "java"),
        "npm": ("npm", "skip", "node"),
        "npx": ("npx", "skip", "node"),
        "yarn": ("yarn", "skip", "node"),
    }

    for cmd in commands:
        for binary, (name, strategy, category) in binary_mapping.items():
            if re.search(rf"\b{re.escape(binary)}\b", cmd):
                if name not in seen_names and strategy != "skip":
                    full_action = _find_action_by_name(name)
                    if full_action:
                        action = InstallAction(
                            name=full_action.name,
                            strategy=full_action.strategy,
                            command=full_action.command,
                            source="step_commands",
                            category=full_action.category,
                            priority=1,
                            timeout_seconds=full_action.timeout_seconds,
                        )
                        plan.actions.append(action)
                    else:
                        if strategy == "pip_user":
                            plan.actions.append(InstallAction(
                                name=name,
                                strategy="pip_user",
                                command=f"pip install --user {name}",
                                source="step_commands",
                                category=category,
                                priority=1,
                                timeout_seconds=30,
                            ))
                    seen_names.add(name)


def _find_action_by_name(name: str) -> Optional[InstallAction]:
    """Find a pre-defined InstallAction by name across all tech stacks."""
    for actions in TECH_STACK_PROVISIONS.values():
        for action in actions:
            if action.name == name:
                return action
    return None
