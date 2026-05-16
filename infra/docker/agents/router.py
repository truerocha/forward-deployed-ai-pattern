"""
Agent Router — Maps incoming events to the correct agent and extracts the data contract.

The router examines the event source and detail to determine:
1. Which agent should handle this event
2. What prompt to construct from the event data
3. Whether the event should be processed at all
4. The data contract fields extracted from the platform-specific event

Routing rules:
- fde.github.webhook + issue.labeled → reconnaissance-agent
- fde.gitlab.webhook + issue.updated → reconnaissance-agent
- fde.asana.webhook + task.moved → reconnaissance-agent
- direct spec execution → engineering-agent
- completion events → reporting-agent

Data contract extraction:
  Every routing method now also extracts the canonical data contract fields
  (tech_stack, type, constraints, related_docs, target_environment, etc.)
  from the platform-specific event payload. This contract is passed to the
  Orchestrator, which feeds it to the Constraint Extractor and Agent Builder.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger("fde.router")


@dataclass
class RoutingDecision:
    """Result of routing an event to an agent."""

    agent_name: str
    prompt: str
    metadata: dict
    should_process: bool = True
    skip_reason: str = ""
    data_contract: dict = field(default_factory=dict)


class AgentRouter:
    """Routes events to the appropriate agent based on source and content."""

    def route_event(self, event: dict) -> RoutingDecision:
        """Route an EventBridge event to the correct agent.

        Args:
            event: EventBridge event with source, detail-type, and detail.

        Returns:
            RoutingDecision with agent name, constructed prompt, and data contract.
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
            data_contract={
                "source": "direct",
                "spec_path": spec_path,
                "type": "feature",
                "tech_stack": [],
                "constraints": "",
                "related_docs": [],
                "target_environment": [],
            },
        )

    # ─── GitHub ─────────────────────────────────────────────────

    def _route_github(self, detail: dict) -> RoutingDecision:
        """Route GitHub webhook events and extract the data contract."""
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

        # COE-011: When triggered via flat env vars (InputTransformer limitation),
        # the issue body is not available. Fetch it from GitHub API.
        if not issue.get("body") and issue.get("number"):
            issue = self._fetch_github_issue(detail, issue)

        # Ensure repo is available in issue dict for data contract extraction
        if "repository_url" not in issue:
            repo_full_name = detail.get("repository", {}).get("full_name", "")
            if repo_full_name:
                issue["repository_url"] = f"https://api.github.com/repos/{repo_full_name}"
                issue["repo"] = repo_full_name

        # Extract data contract from GitHub issue body
        contract = self._extract_github_contract(issue)

        spec_content = self._build_github_spec(issue)
        return RoutingDecision(
            agent_name="reconnaissance",
            prompt=(
                "A new task has arrived from GitHub. Perform Phase 1 "
                "Reconnaissance, then hand off to the engineering agent.\n\n"
                f"{spec_content}"
            ),
            metadata={
                "source": "github",
                "issue_number": issue.get("number"),
                "repo": (
                    issue.get("repository_url", "").split("/repos/")[-1]
                    if "repository_url" in issue else ""
                ),
            },
            data_contract=contract,
        )

    def _fetch_github_issue(self, detail: dict, issue: dict) -> dict:
        """Fetch the full issue from GitHub API when body is missing.

        COE-011: The flat env vars InputTransformer pattern cannot pass the
        issue body (too large/complex for ECS environment variables). Instead,
        we fetch it at runtime using the GitHub PAT from Secrets Manager.

        Args:
            detail: The event detail containing repository info.
            issue: The partial issue dict (has number, title, labels but no body).

        Returns:
            The enriched issue dict with body populated from GitHub API.
        """
        repo_full_name = detail.get("repository", {}).get("full_name", "")
        issue_number = issue.get("number")

        if not repo_full_name or not issue_number:
            logger.warning("Cannot fetch issue: missing repo (%s) or number (%s)", repo_full_name, issue_number)
            return issue

        try:
            # Fetch GitHub PAT from Secrets Manager (ADR-014: fetch-use-discard)
            secrets_id = os.environ.get("SECRETS_ID", f"fde-{os.environ.get('ENVIRONMENT', 'dev')}/alm-tokens")
            secrets_client = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1"))
            secret_value = secrets_client.get_secret_value(SecretId=secrets_id)
            tokens = json.loads(secret_value["SecretString"])
            github_pat = tokens.get("github_pat", "")

            if not github_pat:
                logger.warning("GitHub PAT not configured in Secrets Manager — cannot fetch issue body")
                return issue

            # Fetch issue from GitHub API
            import urllib.request
            url = f"https://api.github.com/repos/{repo_full_name}/issues/{issue_number}"
            req = urllib.request.Request(url, headers={
                "Authorization": f"Bearer {github_pat}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                github_issue = json.loads(resp.read().decode())

            logger.info("Fetched issue #%s from %s (body length: %d chars)",
                        issue_number, repo_full_name, len(github_issue.get("body", "") or ""))

            # Merge: keep labels from event (most current), take body from API
            enriched = {**issue}
            enriched["body"] = github_issue.get("body", "")
            if not enriched.get("labels"):
                enriched["labels"] = github_issue.get("labels", [])
            return enriched

        except ClientError as e:
            logger.error("Secrets Manager error fetching GitHub PAT: %s", e)
            return issue
        except Exception as e:
            logger.error("Failed to fetch issue #%s from GitHub: %s", issue_number, e)
            return issue

    def _extract_github_contract(self, issue: dict) -> dict:
        """Extract the canonical data contract from a GitHub issue.

        GitHub issue forms serialize form fields into the issue body as
        markdown sections. This parser extracts the structured fields.
        """
        body = issue.get("body", "") or ""
        labels = [l.get("name", "") for l in issue.get("labels", [])]

        # Extract repo from repository_url (set by _fetch_github_issue or event)
        repo = ""
        if "repository_url" in issue:
            repo = issue["repository_url"].split("/repos/")[-1]
        elif "repo" in issue:
            repo = issue["repo"]

        contract: dict = {
            "task_id": f"GH-{issue.get('number', 0)}",
            "title": issue.get("title", ""),
            "description": body,
            "source": "github",
            "repo": repo,
            "issue_number": issue.get("number", 0),
            "type": self._extract_section_value(body, "Task Type") or "feature",
            "priority": self._extract_section_value(body, "Priority") or "P2",
            "level": self._extract_section_value(body, "Engineering Level") or "L3",
            "acceptance_criteria": self._extract_checklist(body, "Acceptance Criteria"),
            "tech_stack": self._extract_checkboxes(body, "Tech Stack"),
            "target_environment": self._extract_checkboxes(body, "Target Environment"),
            "constraints": self._extract_section_text(body, "Constraints"),
            "related_docs": self._extract_section_lines(body, "Related Documents"),
            "depends_on": self._extract_section_value(body, "Dependencies") or "",
        }

        # Normalize priority: "P2 (medium)" → "P2"
        if contract["priority"]:
            contract["priority"] = contract["priority"].split(" ")[0]
        if contract["level"]:
            contract["level"] = contract["level"].split(" ")[0]

        return contract

    # ─── GitLab ─────────────────────────────────────────────────

    def _route_gitlab(self, detail: dict) -> RoutingDecision:
        """Route GitLab webhook events and extract the data contract."""
        attrs = detail.get("object_attributes", {})
        labels = [l.get("title", "") for l in detail.get("labels", [])]

        contract = self._extract_gitlab_contract(attrs, labels)

        spec_content = self._build_gitlab_spec(attrs, labels)
        return RoutingDecision(
            agent_name="reconnaissance",
            prompt=(
                "A new task has arrived from GitLab. Perform Phase 1 "
                "Reconnaissance, then hand off to the engineering agent.\n\n"
                f"{spec_content}"
            ),
            metadata={
                "source": "gitlab",
                "issue_iid": attrs.get("iid"),
                "project_id": detail.get("project", {}).get("id"),
            },
            data_contract=contract,
        )

    def _extract_gitlab_contract(self, attrs: dict, labels: list[str]) -> dict:
        """Extract the canonical data contract from GitLab scoped labels."""
        description = attrs.get("description", "") or ""

        # GitLab uses scoped labels: type::feature, priority::P2, level::L3, stack::Python
        def _scoped(prefix: str) -> str:
            for label in labels:
                if label.lower().startswith(f"{prefix}::"):
                    return label.split("::", 1)[1]
            return ""

        def _scoped_all(prefix: str) -> list[str]:
            return [
                label.split("::", 1)[1]
                for label in labels
                if label.lower().startswith(f"{prefix}::")
            ]

        return {
            "title": attrs.get("title", ""),
            "description": description,
            "source": "gitlab",
            "type": _scoped("type") or "feature",
            "priority": _scoped("priority") or "P2",
            "level": _scoped("level") or "L3",
            "acceptance_criteria": self._extract_checklist(description, "Acceptance Criteria"),
            "tech_stack": _scoped_all("stack"),
            "target_environment": _scoped_all("env"),
            "constraints": self._extract_section_text(description, "Constraints"),
            "related_docs": self._extract_section_lines(description, "Related Documents"),
            "depends_on": "",
        }

    # ─── Asana ──────────────────────────────────────────────────

    def _route_asana(self, detail: dict) -> RoutingDecision:
        """Route Asana webhook events and extract the data contract."""
        resource = detail.get("resource", {})

        contract = self._extract_asana_contract(resource)

        spec_content = self._build_asana_spec(resource)
        return RoutingDecision(
            agent_name="reconnaissance",
            prompt=(
                "A new task has arrived from Asana. Perform Phase 1 "
                "Reconnaissance, then hand off to the engineering agent.\n\n"
                f"{spec_content}"
            ),
            metadata={
                "source": "asana",
                "task_gid": resource.get("gid"),
            },
            data_contract=contract,
        )

    def _extract_asana_contract(self, resource: dict) -> dict:
        """Extract the canonical data contract from Asana custom fields."""
        notes = resource.get("notes", "") or ""
        custom_fields = {
            cf.get("name", "").lower(): cf.get("display_value", "") or cf.get("text_value", "")
            for cf in resource.get("custom_fields", [])
        }

        # Asana multi-select fields come as lists
        tech_stack_raw = custom_fields.get("tech stack", "")
        tech_stack = (
            [s.strip() for s in tech_stack_raw.split(",") if s.strip()]
            if isinstance(tech_stack_raw, str)
            else tech_stack_raw if isinstance(tech_stack_raw, list)
            else []
        )

        return {
            "title": resource.get("name", ""),
            "description": notes,
            "source": "asana",
            "type": custom_fields.get("type", "feature"),
            "priority": custom_fields.get("priority", "P2"),
            "level": custom_fields.get("engineering level", "L3"),
            "acceptance_criteria": self._extract_checklist(notes, "Acceptance Criteria"),
            "tech_stack": tech_stack,
            "target_environment": [],
            "constraints": self._extract_section_text(notes, "Constraints"),
            "related_docs": self._extract_section_lines(notes, "Related Documents"),
            "depends_on": "",
        }

    # ─── Direct Spec ────────────────────────────────────────────

    def _route_direct_spec(self, detail: dict) -> RoutingDecision:
        """Route direct spec execution."""
        spec_content = detail.get("spec_content", "")
        spec_path = detail.get("spec_path", "")

        # Direct specs can carry an explicit data contract
        contract = detail.get("data_contract", {})
        if not contract:
            contract = {
                "source": "direct",
                "type": "feature",
                "tech_stack": [],
                "constraints": "",
                "related_docs": [],
                "target_environment": [],
            }

        return RoutingDecision(
            agent_name="engineering",
            prompt=self._build_spec_prompt(spec_content),
            metadata={"spec_path": spec_path, "source": "direct"},
            data_contract=contract,
        )

    # ─── Spec Builders ──────────────────────────────────────────

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

    # ─── Body Parsing Helpers ───────────────────────────────────

    @staticmethod
    def _extract_section_value(body: str, section_name: str) -> str:
        """Extract a single value from a GitHub issue form section.

        GitHub issue forms render as:
          ### Section Name
          value
        """
        pattern = rf"###\s+{re.escape(section_name)}\s*\n+(.+?)(?:\n###|\n\n|\Z)"
        match = re.search(pattern, body, re.DOTALL)
        if match:
            return match.group(1).strip().split("\n")[0].strip()
        return ""

    @staticmethod
    def _extract_section_text(body: str, section_name: str) -> str:
        """Extract the full text block under a section header."""
        pattern = rf"###\s+{re.escape(section_name)}\s*\n+(.+?)(?=\n###|\Z)"
        match = re.search(pattern, body, re.DOTALL)
        if match:
            text = match.group(1).strip()
            if text.lower() in ("_no response_", "none", "n/a", ""):
                return ""
            return text
        return ""

    @staticmethod
    def _extract_section_lines(body: str, section_name: str) -> list[str]:
        """Extract non-empty lines from a section as a list."""
        pattern = rf"###\s+{re.escape(section_name)}\s*\n+(.+?)(?=\n###|\Z)"
        match = re.search(pattern, body, re.DOTALL)
        if match:
            lines = [
                line.strip().lstrip("- ").strip()
                for line in match.group(1).strip().split("\n")
                if line.strip() and line.strip().lower() not in ("_no response_", "none", "n/a")
            ]
            return lines
        return []

    @staticmethod
    def _extract_checklist(body: str, section_name: str) -> list[str]:
        """Extract checklist items (- [ ] item) from a section.

        Supports both ## and ### heading levels (GitHub issue templates use ##,
        factory-task YAML template uses ###).
        """
        pattern = rf"#{2,3}\s+{re.escape(section_name)}\s*\n+(.+?)(?=\n#{2,3}\s|\Z)"
        match = re.search(pattern, body, re.DOTALL)
        if match:
            items = re.findall(r"-\s*\[[ x]\]\s*(.+)", match.group(1))
            return [item.strip() for item in items if item.strip()]
        return []

    @staticmethod
    def _extract_checkboxes(body: str, section_name: str) -> list[str]:
        """Extract checked checkbox items (- [X] item) from a section.

        Supports both ## and ### heading levels.
        """
        pattern = rf"#{2,3}\s+{re.escape(section_name)}\s*\n+(.+?)(?=\n#{2,3}\s|\Z)"
        match = re.search(pattern, body, re.DOTALL)
        if match:
            items = re.findall(r"-\s*\[[xX]\]\s*(.+)", match.group(1))
            return [item.strip() for item in items if item.strip()]
        return []
