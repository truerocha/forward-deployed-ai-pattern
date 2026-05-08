"""
Atlassian MCP Proxy — MCP server wrapping Atlassian REST API.

Provides Confluence read and Jira CRUD operations as MCP tool methods
that agents can invoke during execution. Authentication is handled by
the companion auth module using OAuth 2.0 (3LO) tokens from Secrets Manager.

Activity: 5.03
Ref: docs/integration/atlassian-setup.md

Feature flag: ENABLE_ATLASSIAN (default: false)

Methods:
  - read_confluence_page(page_id) → page content as markdown
  - create_jira_issue(project, summary, description) → issue key
  - update_jira_status(issue_key, status) → updated issue

Usage:
    proxy = AtlassianMCPProxy(
        base_url="https://your-domain.atlassian.net",
        auth_token="<from Secrets Manager>",
    )
    content = proxy.read_confluence_page("12345678")
    issue_key = proxy.create_jira_issue("PROJ", "Fix bug", "Description here")
    proxy.update_jira_status("PROJ-42", "In Progress")
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import boto3
import urllib.request
import urllib.error
import urllib.parse

from src.integrations.atlassian.auth import AtlassianAuth

logger = logging.getLogger("fde.integrations.atlassian")

# Feature flag
ENABLE_ATLASSIAN = os.environ.get("ENABLE_ATLASSIAN", "false").lower() == "true"

_AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


class AtlassianDisabledError(Exception):
    """Raised when Atlassian integration is called but feature flag is disabled."""

    def __init__(self):
        super().__init__(
            "Atlassian integration is disabled. Set ENABLE_ATLASSIAN=true to enable. "
            "See docs/integration/atlassian-setup.md for setup instructions."
        )


class AtlassianAPIError(Exception):
    """Raised when an Atlassian REST API call fails."""

    def __init__(self, status_code: int, message: str, endpoint: str):
        self.status_code = status_code
        self.endpoint = endpoint
        super().__init__(
            f"Atlassian API error ({status_code}) at {endpoint}: {message}"
        )


@dataclass
class AtlassianMCPProxy:
    """MCP server wrapping Atlassian REST API (Confluence read + Jira CRUD).

    This proxy exposes Atlassian operations as tool methods that agents
    can invoke. It handles authentication, request formatting, and error
    mapping to provide a clean interface for the factory.

    Attributes:
        base_url: Atlassian instance base URL (e.g., https://your-domain.atlassian.net).
        auth_token: OAuth 2.0 bearer token (retrieved from Secrets Manager).
    """

    base_url: str
    auth_token: str
    _auth: AtlassianAuth | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not ENABLE_ATLASSIAN:
            logger.warning("Atlassian MCP proxy instantiated but feature flag is disabled")
        # Normalize base URL
        self.base_url = self.base_url.rstrip("/")

    @classmethod
    def from_secrets_manager(
        cls,
        base_url: str,
        secret_name: str = "fde/atlassian/oauth-token",
    ) -> AtlassianMCPProxy:
        """Create proxy with auth token retrieved from AWS Secrets Manager.

        Args:
            base_url: Atlassian instance base URL.
            secret_name: Secrets Manager secret name containing the OAuth token.

        Returns:
            Configured AtlassianMCPProxy instance.
        """
        auth = AtlassianAuth(secret_name=secret_name)
        token = auth.get_token()

        proxy = cls(base_url=base_url, auth_token=token)
        proxy._auth = auth
        return proxy

    def _ensure_enabled(self) -> None:
        """Check feature flag before any operation."""
        if not ENABLE_ATLASSIAN:
            raise AtlassianDisabledError()

    def _ensure_valid_token(self) -> None:
        """Refresh token if auth manager is available and token is expiring."""
        if self._auth is not None and not self._auth.is_token_valid():
            self.auth_token = self._auth.refresh_token()

    def _make_request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated request to the Atlassian REST API.

        Args:
            method: HTTP method (GET, POST, PUT).
            path: API path (appended to base_url).
            body: Optional JSON body for POST/PUT requests.

        Returns:
            Parsed JSON response.

        Raises:
            AtlassianAPIError: If the API returns a non-2xx status.
        """
        self._ensure_valid_token()

        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.auth_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")

        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                response_body = response.read().decode("utf-8")
                if response_body:
                    return json.loads(response_body)
                return {}
        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8")
            except Exception:
                pass
            raise AtlassianAPIError(
                status_code=e.code,
                message=error_body or str(e.reason),
                endpoint=path,
            )
        except urllib.error.URLError as e:
            raise AtlassianAPIError(
                status_code=0,
                message=f"Connection error: {e.reason}",
                endpoint=path,
            )

    # ─── Confluence Methods ─────────────────────────────────────

    def read_confluence_page(self, page_id: str) -> dict[str, Any]:
        """Read a Confluence page by ID.

        Args:
            page_id: Confluence page ID (numeric string).

        Returns:
            Dict with keys: page_id, title, content (body in storage format),
            space_key, version, last_modified.

        Raises:
            AtlassianDisabledError: If feature flag is disabled.
            AtlassianAPIError: If API call fails.
        """
        self._ensure_enabled()

        path = f"/wiki/api/v2/pages/{page_id}?body-format=storage"
        response = self._make_request("GET", path)

        # Extract relevant fields
        body_content = ""
        if "body" in response:
            body_content = response["body"].get("storage", {}).get("value", "")

        return {
            "page_id": page_id,
            "title": response.get("title", ""),
            "content": body_content,
            "space_id": response.get("spaceId", ""),
            "version": response.get("version", {}).get("number", 0),
            "last_modified": response.get("version", {}).get("createdAt", ""),
            "status": response.get("status", ""),
        }

    # ─── Jira Methods ───────────────────────────────────────────

    def create_jira_issue(
        self,
        project: str,
        summary: str,
        description: str,
        issue_type: str = "Task",
        priority: str = "Medium",
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a Jira issue.

        Args:
            project: Jira project key (e.g., "PROJ").
            summary: Issue summary/title.
            description: Issue description (plain text or ADF).
            issue_type: Issue type name (default: "Task").
            priority: Priority name (default: "Medium").
            labels: Optional list of labels.

        Returns:
            Dict with keys: issue_key, issue_id, self_url.

        Raises:
            AtlassianDisabledError: If feature flag is disabled.
            AtlassianAPIError: If API call fails.
        """
        self._ensure_enabled()

        # Build Atlassian Document Format (ADF) for description
        adf_description = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": description}
                    ],
                }
            ],
        }

        body = {
            "fields": {
                "project": {"key": project},
                "summary": summary,
                "description": adf_description,
                "issuetype": {"name": issue_type},
                "priority": {"name": priority},
            }
        }

        if labels:
            body["fields"]["labels"] = labels

        path = "/rest/api/3/issue"
        response = self._make_request("POST", path, body=body)

        return {
            "issue_key": response.get("key", ""),
            "issue_id": response.get("id", ""),
            "self_url": response.get("self", ""),
        }

    def update_jira_status(
        self,
        issue_key: str,
        status: str,
    ) -> dict[str, Any]:
        """Update a Jira issue's status via transition.

        Args:
            issue_key: Jira issue key (e.g., "PROJ-42").
            status: Target status name (e.g., "In Progress", "Done").

        Returns:
            Dict with keys: issue_key, new_status, transition_id.

        Raises:
            AtlassianDisabledError: If feature flag is disabled.
            AtlassianAPIError: If API call fails or transition not found.
        """
        self._ensure_enabled()

        # First, get available transitions for the issue
        transitions_path = f"/rest/api/3/issue/{issue_key}/transitions"
        transitions_response = self._make_request("GET", transitions_path)

        # Find the transition matching the target status
        target_transition = None
        for transition in transitions_response.get("transitions", []):
            if transition.get("to", {}).get("name", "").lower() == status.lower():
                target_transition = transition
                break
            # Also match on transition name itself
            if transition.get("name", "").lower() == status.lower():
                target_transition = transition
                break

        if target_transition is None:
            available = [
                t.get("to", {}).get("name", t.get("name", ""))
                for t in transitions_response.get("transitions", [])
            ]
            raise AtlassianAPIError(
                status_code=400,
                message=(
                    f"No transition to status '{status}' available for {issue_key}. "
                    f"Available transitions: {available}"
                ),
                endpoint=transitions_path,
            )

        # Execute the transition
        transition_body = {
            "transition": {"id": target_transition["id"]}
        }
        self._make_request("POST", transitions_path, body=transition_body)

        logger.info("Transitioned %s to '%s'", issue_key, status)

        return {
            "issue_key": issue_key,
            "new_status": target_transition.get("to", {}).get("name", status),
            "transition_id": target_transition["id"],
        }

    # ─── MCP Tool Registration ──────────────────────────────────

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return MCP tool definitions for agent registration.

        These definitions follow the MCP tool schema and can be registered
        with the agent's tool registry.
        """
        return [
            {
                "name": "read_confluence_page",
                "description": "Read a Confluence page by ID. Returns title and content.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "page_id": {
                            "type": "string",
                            "description": "Confluence page ID (numeric)",
                        }
                    },
                    "required": ["page_id"],
                },
            },
            {
                "name": "create_jira_issue",
                "description": "Create a new Jira issue in a project.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Jira project key (e.g., PROJ)",
                        },
                        "summary": {
                            "type": "string",
                            "description": "Issue summary/title",
                        },
                        "description": {
                            "type": "string",
                            "description": "Issue description",
                        },
                    },
                    "required": ["project", "summary", "description"],
                },
            },
            {
                "name": "update_jira_status",
                "description": "Update a Jira issue's workflow status.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "issue_key": {
                            "type": "string",
                            "description": "Jira issue key (e.g., PROJ-42)",
                        },
                        "status": {
                            "type": "string",
                            "description": "Target status name (e.g., In Progress, Done)",
                        },
                    },
                    "required": ["issue_key", "status"],
                },
            },
        ]
