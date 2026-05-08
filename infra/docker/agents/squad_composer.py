"""
Squad Composer — Dynamic agent squad composition based on task analysis.

The Squad Composer replaces the static 3-agent pipeline with a dynamic
DAG of specialized agents. It reads the task-intake-eval output (Squad
Manifest) and resolves which agents to invoke, in what order, and which
can run in parallel.

Design ref: ADR-019 (Agentic Squad Architecture)

Flow:
  1. task-intake-eval-agent analyzes the task and produces a Squad Manifest
  2. Squad Composer validates the manifest against the capability registry
  3. Orchestrator executes agents in the order specified by the manifest
  4. Parallel groups are executed concurrently (future: asyncio)

Feature flag: SQUAD_MODE=classic|dynamic (default: classic for backward compat)
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("fde.squad_composer")

# Feature flag — controls whether dynamic squad composition is active
SQUAD_MODE = os.environ.get("SQUAD_MODE", "classic")


# ─── Squad Manifest Schema ──────────────────────────────────────

@dataclass
class SquadManifest:
    """The output of task-intake-eval-agent — tells the orchestrator what to do.

    Attributes:
        task_id: The task being executed.
        complexity: low | medium | high (determines squad size).
        groups: Ordered dict of group_name → list of agent roles.
        parallel_groups: Groups that can execute concurrently.
        skip_groups: Groups to skip (e.g., security for docs-only tasks).
        rationale: Why this composition was chosen.
        waf_pillars: Which WAF pillars are relevant to this task.
    """

    task_id: str
    complexity: str = "medium"
    groups: dict[str, list[str]] = field(default_factory=dict)
    parallel_groups: list[str] = field(default_factory=list)
    skip_groups: list[str] = field(default_factory=list)
    rationale: str = ""
    waf_pillars: list[str] = field(default_factory=list)

    def get_execution_order(self) -> list[list[str]]:
        """Resolve the execution order as a list of stages.

        Each stage is a list of agent roles. Stages execute sequentially.
        Agents within a stage can execute in parallel.

        Returns:
            List of stages, where each stage is a list of agent role names.
        """
        stages: list[list[str]] = []
        for group_name, agents in self.groups.items():
            if group_name in self.skip_groups:
                continue
            if group_name in self.parallel_groups:
                stages.append(agents)
            else:
                for agent in agents:
                    stages.append([agent])
        return stages

    def get_all_agents(self) -> list[str]:
        """Get a flat list of all agents in execution order (no duplicates)."""
        seen = set()
        result = []
        for group_name, agents in self.groups.items():
            if group_name in self.skip_groups:
                continue
            for agent in agents:
                if agent not in seen:
                    seen.add(agent)
                    result.append(agent)
        return result

    def to_dict(self) -> dict:
        """Serialize to dict for logging/storage."""
        return {
            "task_id": self.task_id,
            "complexity": self.complexity,
            "groups": self.groups,
            "parallel_groups": self.parallel_groups,
            "skip_groups": self.skip_groups,
            "rationale": self.rationale,
            "waf_pillars": self.waf_pillars,
            "total_agents": len(self.get_all_agents()),
        }


# ─── Capability Registry ────────────────────────────────────────

AGENT_CAPABILITIES: dict[str, dict[str, Any]] = {
    # Quarteto (Control Plane) — Sonnet 4 for better instruction following
    "task-intake-eval-agent": {"layer": "quarteto", "tools": "RECON_TOOLS", "model": "standard", "description": "Analyzes task, determines complexity, composes squad"},
    "architect-standard-agent": {"layer": "quarteto", "tools": "RECON_TOOLS", "model": "reasoning", "description": "Validates architecture decisions and component boundaries"},
    "reviewer-security-agent": {"layer": "quarteto", "tools": "RECON_TOOLS", "model": "reasoning", "description": "Security review: threat model, OWASP, secrets"},
    "fde-code-reasoning": {"layer": "quarteto", "tools": "ENGINEERING_TOOLS", "model": "reasoning", "description": "Deep code reasoning for refactoring"},
    # WAF Pillar Agents — Standard (focused review, not implementation)
    "code-ops-agent": {"layer": "waf", "pillar": "operational_excellence", "tools": "RECON_TOOLS", "model": "standard", "description": "OPS: logging, monitoring, runbooks"},
    "code-sec-agent": {"layer": "waf", "pillar": "security", "tools": "RECON_TOOLS", "model": "reasoning", "description": "SEC: IAM, encryption, network isolation"},
    "code-rel-agent": {"layer": "waf", "pillar": "reliability", "tools": "RECON_TOOLS", "model": "standard", "description": "REL: error handling, retries, circuit breakers"},
    "code-perf-agent": {"layer": "waf", "pillar": "performance_efficiency", "tools": "RECON_TOOLS", "model": "standard", "description": "PERF: caching, pooling, async"},
    "code-cost-agent": {"layer": "waf", "pillar": "cost_optimization", "tools": "RECON_TOOLS", "model": "fast", "description": "COST: right-sizing, spot, reserved"},
    "code-sus-agent": {"layer": "waf", "pillar": "sustainability", "tools": "RECON_TOOLS", "model": "fast", "description": "SUS: efficient algorithms, minimal resources"},
    # SWE Agents (Execution) — Developer uses reasoning, readers use standard
    "swe-issue-code-reader-agent": {"layer": "swe", "tools": "RECON_TOOLS", "model": "standard", "description": "Reads issue, related code, and existing tests"},
    "swe-code-context-agent": {"layer": "swe", "tools": "RECON_TOOLS", "model": "standard", "description": "Maps codebase: dependencies, call graphs, modules"},
    "swe-developer-agent": {"layer": "swe", "tools": "ENGINEERING_TOOLS", "model": "reasoning", "description": "Writes new code: features, implementations"},
    "swe-architect-agent": {"layer": "swe", "tools": "RECON_TOOLS", "model": "reasoning", "description": "Designs component structure, interfaces, data models"},
    "swe-code-quality-agent": {"layer": "swe", "tools": "RECON_TOOLS", "model": "standard", "description": "Linting, coverage, code smells, DRY/SOLID"},
    "swe-adversarial-agent": {"layer": "swe", "tools": "RECON_TOOLS", "model": "reasoning", "description": "Challenges implementation: edge cases, failures"},
    "swe-redteam-agent": {"layer": "swe", "tools": "RECON_TOOLS", "model": "reasoning", "description": "Attacks implementation: injection, escalation, leaks"},
    # Delivery Agents — Standard (git ops, docs)
    "swe-tech-writer-agent": {"layer": "delivery", "tools": "ENGINEERING_TOOLS", "model": "standard", "description": "Updates repo docs: README, CHANGELOG, ADRs"},
    "swe-dtl-commiter-agent": {"layer": "delivery", "tools": "ENGINEERING_TOOLS", "model": "fast", "description": "Commits with FDE Squad Leader identity"},
    # Reporting — Fast (structured output, no reasoning needed)
    "reporting-agent": {"layer": "reporting", "tools": "REPORTING_TOOLS", "model": "fast", "description": "Writes completion report, updates ALM"},
}

# Model tier mapping — resolved at runtime from env vars
# Allows override via BEDROCK_MODEL_REASONING, BEDROCK_MODEL_STANDARD, BEDROCK_MODEL_FAST
MODEL_TIERS: dict[str, str] = {
    "reasoning": os.environ.get("BEDROCK_MODEL_REASONING", "us.anthropic.claude-sonnet-4-20250514-v1:0"),
    "standard": os.environ.get("BEDROCK_MODEL_STANDARD", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"),
    "fast": os.environ.get("BEDROCK_MODEL_FAST", "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
}


def get_model_for_agent(agent_role: str) -> str:
    """Resolve the Bedrock model ID for a given agent role.

    Model routing strategy:
    - reasoning: Claude Sonnet 4 — best instruction following, extended thinking with tools
      Used by: developer, architect, adversarial, redteam, security, code-reasoning
    - standard: Claude Sonnet 4.5 — best for coding and agents
      Used by: intake-eval, issue-reader, code-context, quality, ops, rel, perf, tech-writer
    - fast: Claude Haiku 4.5 — fastest, cheapest, sufficient for structured output
      Used by: dtl-commiter, reporting, cost, sustainability

    Returns:
        Bedrock model ID string.
    """
    capability = AGENT_CAPABILITIES.get(agent_role, {})
    tier = capability.get("model", "standard")
    model_id = MODEL_TIERS.get(tier, MODEL_TIERS["standard"])
    return model_id

_MAX_SQUAD_SIZE = 8


# ─── Composition Functions ──────────────────────────────────────

def compose_classic_pipeline(task_type: str, task_id: str) -> SquadManifest:
    """Compose the classic 3-agent pipeline (backward compatibility)."""
    if task_type == "bugfix":
        groups = {"implementation": ["swe-developer-agent"], "reporting": ["reporting-agent"]}
    elif task_type == "documentation":
        groups = {"reporting": ["reporting-agent"]}
    else:
        groups = {"intake": ["swe-issue-code-reader-agent"], "implementation": ["swe-developer-agent"], "reporting": ["reporting-agent"]}

    return SquadManifest(task_id=task_id, complexity="low", groups=groups, rationale="Classic pipeline (SQUAD_MODE=classic)")


def compose_from_manifest_json(manifest_json: str, task_id: str) -> SquadManifest:
    """Parse a Squad Manifest from the task-intake-eval-agent's JSON output."""
    try:
        data = json.loads(manifest_json)
    except json.JSONDecodeError as e:
        logger.warning("Invalid manifest JSON — falling back to classic: %s", e)
        return compose_classic_pipeline("feature", task_id)

    groups = data.get("squad", data.get("groups", {}))
    validated_groups: dict[str, list[str]] = {}

    for group_name, agents in groups.items():
        valid_agents = [a for a in agents if a in AGENT_CAPABILITIES]
        invalid = [a for a in agents if a not in AGENT_CAPABILITIES]
        if invalid:
            logger.warning("Unknown agents in manifest (skipped): %s", invalid)
        if valid_agents:
            validated_groups[group_name] = valid_agents

    all_agents = [a for agents in validated_groups.values() for a in agents]
    if len(all_agents) > _MAX_SQUAD_SIZE:
        logger.warning("Squad size %d exceeds max %d — trimming", len(all_agents), _MAX_SQUAD_SIZE)
        kept = set(all_agents[:_MAX_SQUAD_SIZE])
        validated_groups = {k: [a for a in v if a in kept] for k, v in validated_groups.items()}
        validated_groups = {k: v for k, v in validated_groups.items() if v}

    manifest = SquadManifest(
        task_id=task_id, complexity=data.get("complexity", "medium"),
        groups=validated_groups, parallel_groups=data.get("parallel_groups", []),
        skip_groups=data.get("skip_groups", []), rationale=data.get("rationale", ""),
        waf_pillars=data.get("waf_pillars", []),
    )
    logger.info("Squad composed: task=%s agents=%d groups=%d", task_id, len(manifest.get_all_agents()), len(manifest.groups))
    return manifest


def compose_default_squad(task_type: str, task_id: str, complexity: str = "medium") -> SquadManifest:
    """Compose a default squad when the intake agent doesn't produce a manifest."""
    if task_type == "bugfix":
        groups = {"intake": ["swe-issue-code-reader-agent"], "implementation": ["swe-developer-agent"], "quality": ["swe-code-quality-agent"], "delivery": ["swe-dtl-commiter-agent"], "reporting": ["reporting-agent"]}
        parallel, pillars = [], []
    elif task_type == "documentation":
        groups = {"intake": ["swe-issue-code-reader-agent"], "implementation": ["swe-tech-writer-agent"], "delivery": ["swe-dtl-commiter-agent"], "reporting": ["reporting-agent"]}
        parallel, pillars = [], []
    elif task_type == "refactoring":
        groups = {"intake": ["swe-issue-code-reader-agent", "swe-code-context-agent"], "architecture": ["fde-code-reasoning"], "implementation": ["swe-developer-agent"], "quality": ["swe-code-quality-agent", "swe-adversarial-agent"], "delivery": ["swe-dtl-commiter-agent"], "reporting": ["reporting-agent"]}
        parallel, pillars = ["quality"], []
    elif task_type == "infrastructure":
        groups = {"intake": ["swe-issue-code-reader-agent", "swe-code-context-agent"], "architecture": ["swe-architect-agent", "architect-standard-agent"], "implementation": ["swe-developer-agent"], "waf_review": ["code-ops-agent", "code-sec-agent", "code-cost-agent"], "quality": ["swe-code-quality-agent"], "delivery": ["swe-tech-writer-agent", "swe-dtl-commiter-agent"], "reporting": ["reporting-agent"]}
        parallel, pillars = ["waf_review"], ["operational_excellence", "security", "cost_optimization"]
    else:  # feature
        if complexity == "low":
            groups = {"intake": ["swe-issue-code-reader-agent"], "implementation": ["swe-developer-agent"], "quality": ["swe-code-quality-agent"], "delivery": ["swe-dtl-commiter-agent"], "reporting": ["reporting-agent"]}
            parallel, pillars = [], []
        elif complexity == "high":
            groups = {"intake": ["swe-issue-code-reader-agent", "swe-code-context-agent"], "architecture": ["swe-architect-agent", "architect-standard-agent"], "implementation": ["swe-developer-agent"], "waf_review": ["code-sec-agent", "code-rel-agent", "code-perf-agent"], "quality": ["swe-code-quality-agent", "swe-adversarial-agent"], "delivery": ["swe-tech-writer-agent", "swe-dtl-commiter-agent"], "reporting": ["reporting-agent"]}
            parallel, pillars = ["waf_review", "quality"], ["security", "reliability", "performance_efficiency"]
        else:  # medium
            groups = {"intake": ["swe-issue-code-reader-agent"], "implementation": ["swe-developer-agent"], "waf_review": ["code-sec-agent", "code-rel-agent"], "quality": ["swe-code-quality-agent"], "delivery": ["swe-dtl-commiter-agent"], "reporting": ["reporting-agent"]}
            parallel, pillars = ["waf_review"], ["security", "reliability"]

    return SquadManifest(task_id=task_id, complexity=complexity, groups=groups, parallel_groups=parallel, rationale=f"Default {task_type}/{complexity} squad", waf_pillars=pillars)


def should_use_dynamic_squad() -> bool:
    """Check if dynamic squad mode is enabled."""
    return SQUAD_MODE == "dynamic"
