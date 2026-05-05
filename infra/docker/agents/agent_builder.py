"""
Agent Builder — Just-in-time agent provisioning driven by the data contract.

The Agent Builder reads tech_stack, type, and extracted constraints from the
data contract to provision a specialized agent. It queries the Prompt Registry
for context-aware prompts and configures the agent's tool set accordingly.

Flow (triggered by Orchestrator after Constraint Extraction passes DoR):
  1. Receive the data contract + extracted constraints
  2. Resolve the prompt: query Prompt Registry by tech_stack context tags
  3. If no specialized prompt exists, fall back to the role's base prompt
  4. Inject extracted constraints as a structured block into the prompt
  5. Select the tool set based on type (bugfix skips recon tools, infra adds IaC tools)
  6. Build an AgentDefinition and register it as a transient agent
  7. Return the agent name for the Orchestrator to execute

Rule of Three:
  Create a specialized agent only when a task requires a unique set of tools
  or a fundamentally different system prompt. Otherwise, use the base agents
  (reconnaissance, engineering, reporting) with context-injected prompts.

No fake code — every function is callable with real Prompt Registry data.
"""

import logging
from dataclasses import asdict

from . import prompt_registry
from .constraint_extractor import Constraint, ExtractionResult
from .prompts import RECONNAISSANCE_PROMPT, ENGINEERING_PROMPT, REPORTING_PROMPT
from .registry import AgentRegistry, AgentDefinition
from .tools import (
    RECON_TOOLS,
    ENGINEERING_TOOLS,
    REPORTING_TOOLS,
    read_spec,
    write_artifact,
    run_shell_command,
    update_github_issue,
    update_gitlab_issue,
    update_asana_task,
)

logger = logging.getLogger("fde.agent_builder")


# ─── Prompt Resolution ──────────────────────────────────────────

# Maps task type → base prompt to use as fallback
_BASE_PROMPTS: dict[str, str] = {
    "feature": ENGINEERING_PROMPT,
    "bugfix": ENGINEERING_PROMPT,
    "infrastructure": ENGINEERING_PROMPT,
    "documentation": REPORTING_PROMPT,
}

# Maps task type → which FDE phase to start from
_TYPE_PHASE_MAP: dict[str, str] = {
    "feature": "reconnaissance",       # Full pipeline: Phase 1 → 2 → 3 → 4
    "bugfix": "engineering",            # Skip recon, go straight to diagnostic
    "infrastructure": "reconnaissance", # Full pipeline with IaC tools
    "documentation": "reporting",       # Skip engineering, go to reporting
}

# Maps task type → tool set override
_TYPE_TOOL_MAP: dict[str, list] = {
    "feature": ENGINEERING_TOOLS,
    "bugfix": ENGINEERING_TOOLS,
    "infrastructure": ENGINEERING_TOOLS,
    "documentation": REPORTING_TOOLS,
}


def resolve_prompt(
    agent_role: str,
    tech_stack: list[str],
    task_type: str,
    constraints: list[Constraint] | None = None,
) -> tuple[str, int, str]:
    """Resolve the best prompt for this agent from the Prompt Registry.

    Strategy:
    1. Query the Prompt Registry with prompt_name="{role}-agent" and
       context_tags derived from tech_stack (e.g., ["python", "fastapi"]).
    2. If a context-matched prompt exists, use it (specialized).
    3. If not, fall back to the base prompt from prompts.py.
    4. Inject extracted constraints as a structured block into the prompt.

    Args:
        agent_role: The agent role name (e.g., "engineering", "reconnaissance").
        tech_stack: The tech_stack array from the data contract.
        task_type: The task type (feature, bugfix, infrastructure, documentation).
        constraints: Optional list of extracted Constraint objects.

    Returns:
        Tuple of (prompt_content, prompt_version, prompt_hash).
        Version 0 and empty hash mean the base prompt was used (no Registry hit).
    """
    prompt_name = f"{agent_role}-agent"
    context_tags = [s.lower().replace(" ", "-") for s in tech_stack]

    # Try Prompt Registry first
    registry_prompt = None
    try:
        registry_prompt = prompt_registry.get_prompt_by_context(prompt_name, context_tags)
    except Exception as e:
        logger.warning("Prompt Registry unavailable, using base prompt: %s", e)

    if registry_prompt and registry_prompt.get("integrity_valid", False):
        base_content = registry_prompt["content"]
        version = registry_prompt["version"]
        prompt_hash = registry_prompt.get("sha256_hash", "")
        logger.info(
            "Resolved prompt from Registry: %s v%d (tags: %s)",
            prompt_name, version, context_tags,
        )
    else:
        base_content = _BASE_PROMPTS.get(task_type, ENGINEERING_PROMPT)
        version = 0
        prompt_hash = ""
        logger.info(
            "Using base prompt for role=%s type=%s (no Registry match for tags: %s)",
            agent_role, task_type, context_tags,
        )

    # Inject constraints block if present
    if constraints:
        constraints_block = _build_constraints_block(constraints)
        base_content = base_content + "\n\n" + constraints_block

    # Inject tech_stack context
    stack_block = _build_tech_stack_block(tech_stack)
    base_content = base_content + "\n\n" + stack_block

    return base_content, version, prompt_hash


def _build_constraints_block(constraints: list[Constraint]) -> str:
    """Build a structured constraints block to inject into the agent prompt."""
    lines = ["## Extracted Constraints (from DoR Gate)", ""]
    lines.append("The following constraints were extracted from the task's related documents")
    lines.append("and constraints field. You MUST respect these during execution.")
    lines.append("")

    for c in constraints:
        ambiguous_tag = " ⚠️ AMBIGUOUS" if c.is_ambiguous else ""
        lines.append(
            f"- **{c.id}** [{c.category}] {c.subject} {c.operator} `{c.value}`"
            f"  (source: \"{c.source_text}\"){ambiguous_tag}"
        )

    lines.append("")
    lines.append("If any constraint conflicts with the task description, flag it in your")
    lines.append("completion report and do NOT proceed with the conflicting change.")
    return "\n".join(lines)


def _build_tech_stack_block(tech_stack: list[str]) -> str:
    """Build a tech stack context block to inject into the agent prompt."""
    if not tech_stack:
        return ""
    return (
        "## Tech Stack Context\n\n"
        f"This task targets: {', '.join(tech_stack)}.\n"
        "Use idiomatic patterns for this stack. Follow the stack's standard "
        "project layout, testing conventions, and dependency management."
    )


# ─── Tool Set Selection ─────────────────────────────────────────

def select_tools(task_type: str, tech_stack: list[str]) -> list:
    """Select the tool set for the agent based on task type and tech stack.

    The Rule of Three: only add specialized tools when the task genuinely
    needs them. Most tasks use the standard ENGINEERING_TOOLS set.

    Args:
        task_type: The task type from the data contract.
        tech_stack: The tech_stack array from the data contract.

    Returns:
        List of tool functions for the agent.
    """
    base_tools = list(_TYPE_TOOL_MAP.get(task_type, ENGINEERING_TOOLS))

    # Infrastructure tasks always get read_spec if not already present
    if task_type == "infrastructure" and read_spec not in base_tools:
        base_tools.insert(0, read_spec)

    return base_tools


# ─── Agent Builder ──────────────────────────────────────────────

class AgentBuilder:
    """Provisions specialized agents just-in-time from the data contract.

    The builder is called by the Orchestrator after the Constraint Extractor
    has run and the DoR Gate has passed. It produces an AgentDefinition that
    the Registry can instantiate.
    """

    def __init__(self, registry: AgentRegistry):
        self._registry = registry

    def build_agent(
        self,
        task_contract: dict,
        extraction_result: ExtractionResult | None = None,
    ) -> str:
        """Build and register a specialized agent for this task.

        Args:
            task_contract: The full data contract dict.
            extraction_result: Optional result from the Constraint Extractor.

        Returns:
            The agent name (registered in the Registry, ready to create_agent).
        """
        task_type = task_contract.get("type", "feature")
        tech_stack = task_contract.get("tech_stack", []) or []
        task_id = task_contract.get("task_id", "unknown")
        source = task_contract.get("source", "direct")

        # Determine which phase/role to start from
        start_role = _TYPE_PHASE_MAP.get(task_type, "reconnaissance")

        # Resolve the prompt (Registry lookup + constraint injection)
        constraints = extraction_result.constraints if extraction_result else []
        prompt_content, prompt_version, prompt_hash = resolve_prompt(
            agent_role=start_role,
            tech_stack=tech_stack,
            task_type=task_type,
            constraints=constraints,
        )

        # Select tools
        tools = select_tools(task_type, tech_stack)

        # Build a transient agent name scoped to this task
        agent_name = f"{start_role}-{task_id}"

        # Register the specialized agent definition
        definition = AgentDefinition(
            name=agent_name,
            system_prompt=prompt_content,
            tools=tools,
            description=(
                f"Specialized {start_role} agent for {task_type} task {task_id} "
                f"(stack: {', '.join(tech_stack)}, source: {source})"
            ),
        )
        self._registry.register(definition)

        logger.info(
            "Built agent: %s (role=%s, type=%s, stack=%s, prompt_v=%d, "
            "constraints=%d, tools=%d)",
            agent_name, start_role, task_type, tech_stack,
            prompt_version, len(constraints), len(tools),
        )

        return agent_name

    def build_pipeline_agents(
        self,
        task_contract: dict,
        extraction_result: ExtractionResult | None = None,
    ) -> list[str]:
        """Build all agents needed for the full FDE pipeline.

        For a feature task, this builds: reconnaissance → engineering → reporting.
        For a bugfix, this builds: engineering → reporting (skips recon).
        For documentation, this builds: reporting only.

        Args:
            task_contract: The full data contract dict.
            extraction_result: Optional result from the Constraint Extractor.

        Returns:
            Ordered list of agent names for the pipeline.
        """
        task_type = task_contract.get("type", "feature")
        task_id = task_contract.get("task_id", "unknown")
        tech_stack = task_contract.get("tech_stack", []) or []
        constraints = extraction_result.constraints if extraction_result else []

        # Determine the pipeline phases based on task type
        if task_type == "bugfix":
            roles = ["engineering", "reporting"]
        elif task_type == "documentation":
            roles = ["reporting"]
        else:
            roles = ["reconnaissance", "engineering", "reporting"]

        agent_names: list[str] = []
        for role in roles:
            prompt_content, prompt_version, prompt_hash = resolve_prompt(
                agent_role=role,
                tech_stack=tech_stack,
                task_type=task_type,
                constraints=constraints,
            )

            # Role-specific tool selection
            if role == "reconnaissance":
                tools = list(RECON_TOOLS)
            elif role == "reporting":
                tools = list(REPORTING_TOOLS)
            else:
                tools = select_tools(task_type, tech_stack)

            agent_name = f"{role}-{task_id}"
            definition = AgentDefinition(
                name=agent_name,
                system_prompt=prompt_content,
                tools=tools,
                description=f"Pipeline {role} agent for task {task_id}",
            )
            self._registry.register(definition)
            agent_names.append(agent_name)

        logger.info(
            "Built pipeline for task %s (type=%s): %s",
            task_id, task_type, " → ".join(agent_names),
        )

        return agent_names
