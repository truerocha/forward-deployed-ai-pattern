"""
Agent Router — Maps incoming events to the correct agent.

The router examines the event source and detail to determine:
1. Which agent should handle this event
2. What prompt to construct from the event data
3. Whether the event should be processed at all

Routing rules:
- fde.github.webhook + issue.labeled → reconnaissance-agent
- fde.gitlab.webhook + issue.updated → reconnaissance-agent
- fde.asana.webhook + task.moved → reconnaissance-agent
- direct spec execution → engineering-agent
- completion events → reporting-agent
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger("fde.router")


@dataclass
class RoutingDecision:
    """Result of routing an event to an agent."""

    agent_name: str
    prompt: str
    metadata: dict
    should_process: bool = True
    skip_reason: str = ""


class AgentRouter:
    """Routes events to the appropriate agent based on source and content."""

    def route_event(self, event: dict) -> RoutingDecision:
        """Route an EventBridge event to the correct agent.

        Args:
            event: EventBridge event with source, detail-type, and detail.

        Returns:
            RoutingDecision with agent name and constructed prompt.
        """
        source = event.get("source", "")
        detail_type = event.get("detail-type", "")
        detail = event.get("detail", {})

        logger.info("Routing event: source=%s, type=%s", source, detail_type)

        if source == "fde.github.webhook":
            return self._route_github(detail)
        elif source == "fde.gitlab.webhook":
            return self._route_gitlab(detail)
        elif source == "fde.asana.webhook":
            return self._route_asana(detail)
        elif source == "fde.direct":
            return self._route_direct_spec(detail)
        else:
            return RoutingDecision(
                agent_name="",
                prompt="",
                metadata={},
                should_process=False,
                skip_reason=f"Unknown event source: {source}",
            )

    def route_spec(self, spec_content: str, spec_path: str) -> RoutingDecision:
        """Route a direct spec execution to the engineering agent.

        Args:
            spec_content: The spec markdown content.
            spec_path: Path to the spec file.

        Returns:
            RoutingDecision targeting the engineering agent.
        """
        return RoutingDecision(
            agent_name="engineering",
            prompt=self._build_spec_prompt(spec_content),
            metadata={"spec_path": spec_path, "source": "direct"},
        )

    def _route_github(self, detail: dict) -> RoutingDecision:
        """Route GitHub webhook events."""
        action = detail.get("action", "")
        issue = detail.get("issue", {})
        labels = [l.get("name", "") for l in issue.get("labels", [])]

        if "factory-ready" not in labels:
            return RoutingDecision(
                agent_name="",
                prompt="",
                metadata={},
                should_process=False,
                skip_reason="Issue not labeled 'factory-ready'",
            )

        spec_content = self._build_github_spec(issue)
        return RoutingDecision(
            agent_name="reconnaissance",
            prompt=f"A new task has arrived from GitHub. Perform Phase 1 Reconnaissance, then hand off to the engineering agent.\n\n{spec_content}",
            metadata={
                "source": "github",
                "issue_number": issue.get("number"),
                "repo": issue.get("repository_url", "").split("/repos/")[-1] if "repository_url" in issue else "",
            },
        )

    def _route_gitlab(self, detail: dict) -> RoutingDecision:
        """Route GitLab webhook events."""
        attrs = detail.get("object_attributes", {})
        labels = [l.get("title", "") for l in detail.get("labels", [])]

        spec_content = self._build_gitlab_spec(attrs, labels)
        return RoutingDecision(
            agent_name="reconnaissance",
            prompt=f"A new task has arrived from GitLab. Perform Phase 1 Reconnaissance, then hand off to the engineering agent.\n\n{spec_content}",
            metadata={
                "source": "gitlab",
                "issue_iid": attrs.get("iid"),
                "project_id": detail.get("project", {}).get("id"),
            },
        )

    def _route_asana(self, detail: dict) -> RoutingDecision:
        """Route Asana webhook events."""
        resource = detail.get("resource", {})

        spec_content = self._build_asana_spec(resource)
        return RoutingDecision(
            agent_name="reconnaissance",
            prompt=f"A new task has arrived from Asana. Perform Phase 1 Reconnaissance, then hand off to the engineering agent.\n\n{spec_content}",
            metadata={
                "source": "asana",
                "task_gid": resource.get("gid"),
            },
        )

    def _route_direct_spec(self, detail: dict) -> RoutingDecision:
        """Route direct spec execution."""
        spec_content = detail.get("spec_content", "")
        spec_path = detail.get("spec_path", "")

        return RoutingDecision(
            agent_name="engineering",
            prompt=self._build_spec_prompt(spec_content),
            metadata={"spec_path": spec_path, "source": "direct"},
        )

    def _build_github_spec(self, issue: dict) -> str:
        return (
            f"---\nstatus: ready\nissue: \"GH-{issue.get('number', '')}\"\n"
            f"source: github\n---\n# {issue.get('title', 'Untitled')}\n\n"
            f"{issue.get('body', '')}"
        )

    def _build_gitlab_spec(self, attrs: dict, labels: list) -> str:
        return (
            f"---\nstatus: ready\nissue: \"GL-{attrs.get('iid', '')}\"\n"
            f"source: gitlab\nlabels: {labels}\n---\n"
            f"# {attrs.get('title', 'Untitled')}\n\n{attrs.get('description', '')}"
        )

    def _build_asana_spec(self, resource: dict) -> str:
        return (
            f"---\nstatus: ready\nissue: \"ASANA-{resource.get('gid', '')}\"\n"
            f"source: asana\n---\n# {resource.get('name', 'Untitled')}\n\n"
            f"{resource.get('notes', '')}"
        )

    def _build_spec_prompt(self, spec_content: str) -> str:
        return (
            "Execute the FDE 4-phase protocol on this task specification:\n\n"
            f"---\n{spec_content}\n---\n\n"
            "Follow all 4 phases. Write a completion report via write_artifact when done. "
            "Update the ALM platform referenced in the spec frontmatter."
        )
