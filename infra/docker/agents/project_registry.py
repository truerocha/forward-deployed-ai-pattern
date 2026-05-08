"""
Project Registry — Maps repositories to factory configuration.

When the factory manages multiple projects in parallel, each repo needs
its own configuration: default branch, tech stack, steering context,
concurrency limits, and priority rules.

The registry is loaded from environment (FACTORY_PROJECTS JSON) or
falls back to sensible defaults derived from the data contract.

Design ref: ADR-005 (Multi-Workspace Factory Topology)
"""

import json
import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger("fde.project_registry")


@dataclass
class ProjectConfig:
    """Configuration for a single project managed by the factory."""

    repo_full_name: str
    display_name: str = ""
    default_branch: str = "main"
    tech_stack: list[str] = field(default_factory=list)
    max_concurrent_tasks: int = 2
    priority_boost: int = 0  # Reserved: future scheduling algorithm (lower = higher priority)
    steering_context: str = ""  # Additional steering injected into agent prompts
    labels: dict[str, str] = field(default_factory=dict)  # Metadata labels

    def __post_init__(self):
        if not self.display_name:
            self.display_name = self.repo_full_name.split("/")[-1]


class ProjectRegistry:
    """Registry of projects managed by the factory.

    Provides:
    - Project lookup by repo name
    - Default configuration for unknown repos (auto-register with allowlist check)
    - Concurrency limits per project
    - Tech stack defaults for the Agent Builder

    Security: Auto-registration is gated by FACTORY_ALLOW_AUTO_REGISTER env var.
    When disabled, only pre-configured repos can use factory capacity.
    """

    def __init__(self):
        self._projects: dict[str, ProjectConfig] = {}
        self._allow_auto_register = os.environ.get(
            "FACTORY_ALLOW_AUTO_REGISTER", "true"
        ).lower() in ("true", "1", "yes")
        self._allowed_orgs: set[str] = set()
        self._load_from_env()

    def _load_from_env(self) -> None:
        """Load project configurations from FACTORY_PROJECTS env var.

        Format: JSON array of project config objects.
        Example:
        [
            {
                "repo_full_name": "truerocha/cognitive-wafr",
                "display_name": "Cognitive WAFR",
                "default_branch": "main",
                "tech_stack": ["python", "aws"],
                "max_concurrent_tasks": 3
            }
        ]

        Also loads FACTORY_ALLOWED_ORGS (comma-separated) to restrict
        auto-registration to specific GitHub/GitLab organizations.
        """
        # Load allowed orgs for auto-registration gating
        allowed_orgs_str = os.environ.get("FACTORY_ALLOWED_ORGS", "")
        if allowed_orgs_str:
            self._allowed_orgs = {org.strip() for org in allowed_orgs_str.split(",") if org.strip()}
            logger.info("Auto-registration restricted to orgs: %s", self._allowed_orgs)

        projects_json = os.environ.get("FACTORY_PROJECTS", "")
        if not projects_json:
            logger.info("No FACTORY_PROJECTS env var — using auto-registration mode")
            return

        try:
            projects = json.loads(projects_json)
            for p in projects:
                config = ProjectConfig(**p)
                self._projects[config.repo_full_name] = config
                logger.info("Registered project: %s (%s)",
                            config.repo_full_name, config.display_name)
        except (json.JSONDecodeError, TypeError) as e:
            logger.error("Failed to parse FACTORY_PROJECTS: %s", e)

    def get_project(self, repo_full_name: str) -> ProjectConfig:
        """Get project configuration by repo name.

        If the repo is not registered:
        - If auto-registration is enabled AND the org is allowed: auto-register with defaults
        - Otherwise: return a restricted config (max_concurrent_tasks=0 blocks execution)

        Args:
            repo_full_name: Full repo name (e.g., 'truerocha/cognitive-wafr').

        Returns:
            ProjectConfig for the repo.
        """
        if repo_full_name in self._projects:
            return self._projects[repo_full_name]

        # Check if auto-registration is allowed for this repo
        org = repo_full_name.split("/")[0] if "/" in repo_full_name else ""

        if not self._allow_auto_register:
            logger.warning(
                "Rejected unknown repo: %s (auto-registration disabled)", repo_full_name
            )
            # Return a config that will be blocked by concurrency guard (max=1 but not registered)
            return ProjectConfig(repo_full_name=repo_full_name, max_concurrent_tasks=1)

        if self._allowed_orgs and org not in self._allowed_orgs:
            logger.warning(
                "Rejected unknown repo: %s (org '%s' not in allowed list: %s)",
                repo_full_name, org, self._allowed_orgs,
            )
            return ProjectConfig(repo_full_name=repo_full_name, max_concurrent_tasks=1)

        # Auto-register with defaults
        config = ProjectConfig(repo_full_name=repo_full_name)
        self._projects[repo_full_name] = config
        logger.info("Auto-registered project: %s (defaults, org=%s)", repo_full_name, org)
        return config

    def list_projects(self) -> list[ProjectConfig]:
        """List all registered projects."""
        return list(self._projects.values())

    def get_max_concurrent(self, repo_full_name: str) -> int:
        """Get the max concurrent tasks allowed for a project."""
        return self.get_project(repo_full_name).max_concurrent_tasks

    def get_default_branch(self, repo_full_name: str) -> str:
        """Get the default branch for a project."""
        return self.get_project(repo_full_name).default_branch

    def get_tech_stack(self, repo_full_name: str) -> list[str]:
        """Get the default tech stack for a project."""
        return self.get_project(repo_full_name).tech_stack

    def to_dict(self) -> list[dict]:
        """Serialize registry for API responses."""
        return [
            {
                "repo": p.repo_full_name,
                "display_name": p.display_name,
                "default_branch": p.default_branch,
                "tech_stack": p.tech_stack,
                "max_concurrent_tasks": p.max_concurrent_tasks,
                "labels": p.labels,
            }
            for p in self._projects.values()
        ]


# Module-level singleton (loaded once per container lifecycle)
_registry: ProjectRegistry | None = None


def get_registry() -> ProjectRegistry:
    """Get the singleton project registry instance."""
    global _registry
    if _registry is None:
        _registry = ProjectRegistry()
    return _registry
