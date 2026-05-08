"""
Integrations Package — External system connectors for the Autonomous Code Factory.

This package contains adapters and proxies for integrating with external
systems such as AI-DLC, Atlassian (Jira/Confluence), and future connectors.

All integrations are gated by feature flags (default: disabled) and follow
the principle of safe-by-default, opt-in-to-power.

Subpackages:
  - aidlc: AI-DLC SharedState artifact import adapter
  - atlassian: Confluence read + Jira CRUD via MCP proxy
"""
