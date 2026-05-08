"""
Atlassian Integration — Confluence read + Jira CRUD via MCP proxy.

Provides an MCP server interface for reading Confluence pages and
performing Jira issue CRUD operations. Authentication uses OAuth 2.0 (3LO)
with tokens stored in AWS Secrets Manager.

Gated by ENABLE_ATLASSIAN feature flag (default: false).

Activities: 5.03, 5.04
Ref: docs/integration/atlassian-setup.md
"""

from src.integrations.atlassian.atlassian_mcp_proxy import AtlassianMCPProxy
from src.integrations.atlassian.auth import AtlassianAuth

__all__ = ["AtlassianMCPProxy", "AtlassianAuth"]
