"""
Agent Registry — Stores agent definitions and creates Strands Agent instances.

Each agent has:
- name: unique identifier
- system_prompt: the FDE protocol instructions for this agent type
- tools: list of tool functions the agent can call
- model_id: Bedrock model to use (can vary per agent)

The registry is the source of truth for what agents exist and how they're configured.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from strands import Agent
from strands.models.bedrock import BedrockModel

logger = logging.getLogger("fde.registry")


@dataclass
class AgentDefinition:
    """Definition of an agent in the registry."""

    name: str
    system_prompt: str
    tools: list[Any] = field(default_factory=list)
    model_id: str = ""
    description: str = ""


class AgentRegistry:
    """Registry of all available FDE agents.

    Stores agent definitions and creates Strands Agent instances on demand.
    Agents are registered at startup and looked up by name when events arrive.
    """

    def __init__(self, default_model_id: str, aws_region: str):
        self._definitions: dict[str, AgentDefinition] = {}
        self._default_model_id = default_model_id
        self._aws_region = aws_region

    def register(self, definition: AgentDefinition) -> None:
        """Register an agent definition."""
        if definition.name in self._definitions:
            logger.warning("Overwriting agent definition: %s", definition.name)
        self._definitions[definition.name] = definition
        logger.info(
            "Registered agent: %s (%d tools, model: %s)",
            definition.name,
            len(definition.tools),
            definition.model_id or self._default_model_id,
        )

    def get_definition(self, name: str) -> AgentDefinition | None:
        """Get an agent definition by name."""
        return self._definitions.get(name)

    def list_agents(self) -> list[str]:
        """List all registered agent names."""
        return list(self._definitions.keys())

    def create_agent(self, name: str) -> Agent:
        """Create a Strands Agent instance from a registered definition.

        Raises:
            KeyError: If the agent name is not registered.
        """
        defn = self._definitions.get(name)
        if defn is None:
            raise KeyError(f"Agent not registered: {name}. Available: {self.list_agents()}")

        model_id = defn.model_id or self._default_model_id
        model = BedrockModel(model_id=model_id, region_name=self._aws_region)

        agent = Agent(
            model=model,
            system_prompt=defn.system_prompt,
            tools=defn.tools,
        )

        logger.info("Created agent instance: %s (model: %s)", name, model_id)
        return agent
