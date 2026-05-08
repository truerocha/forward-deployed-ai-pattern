"""
AI-DLC Integration — SharedState artifact import adapter.

Reads AI-DLC artifacts from S3 and converts them to factory spec format.
Gated by ENABLE_AIDLC_ADAPTER feature flag (default: false).

Activity: 5.01
Ref: docs/integration/aidlc-handoff.md
"""

from src.integrations.aidlc.aidlc_adapter import AIDLCAdapter, AIDLCSchemaError

__all__ = ["AIDLCAdapter", "AIDLCSchemaError"]
