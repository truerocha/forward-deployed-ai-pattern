"""
Atlassian OAuth 2.0 (3LO) Token Management.

Manages OAuth 2.0 tokens for Atlassian API access. Tokens are stored in
AWS Secrets Manager and proactively refreshed before expiry to avoid
interruptions during agent execution.

Activity: 5.04
Ref: docs/integration/atlassian-setup.md

Token lifecycle:
  1. Initial token obtained via OAuth 2.0 authorization code flow (manual setup)
  2. Access token + refresh token stored in Secrets Manager
  3. AtlassianAuth.get_token() retrieves current access token
  4. AtlassianAuth.is_token_valid() checks if token is still valid
  5. AtlassianAuth.refresh_token() proactively refreshes before expiry

Proactive refresh strategy:
  - Tokens are refreshed when less than 5 minutes remain before expiry
  - This avoids mid-request token expiration during long agent operations
  - If refresh fails, the error is logged and the current token is returned
    (it may still be valid for a few more minutes)

Usage:
    auth = AtlassianAuth(secret_name="fde/atlassian/oauth-token")
    token = auth.get_token()

    if not auth.is_token_valid():
        token = auth.refresh_token()
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger("fde.integrations.atlassian.auth")

_AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Atlassian OAuth 2.0 endpoints
_ATLASSIAN_TOKEN_URL = "https://auth.atlassian.com/oauth/token"

# Refresh buffer: refresh token when less than this many seconds remain
_REFRESH_BUFFER_SECONDS = 300  # 5 minutes


@dataclass
class AtlassianAuth:
    """OAuth 2.0 (3LO) token management for Atlassian APIs.

    Retrieves and manages OAuth tokens stored in AWS Secrets Manager.
    Supports proactive refresh to avoid token expiration during operations.

    Attributes:
        secret_name: AWS Secrets Manager secret name containing token data.
    """

    secret_name: str = "fde/atlassian/oauth-token"
    _secrets_client: Any = field(default=None, init=False, repr=False)
    _cached_token_data: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _token_fetched_at: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        self._secrets_client = boto3.client("secretsmanager", region_name=_AWS_REGION)

    def get_token(self) -> str:
        """Retrieve the current access token from Secrets Manager.

        If the token is close to expiry, proactively refreshes it.

        Returns:
            Valid OAuth 2.0 access token string.

        Raises:
            ClientError: If Secrets Manager access fails.
            ValueError: If secret does not contain expected token fields.
        """
        token_data = self._get_token_data()
        access_token = token_data.get("access_token", "")

        if not access_token:
            raise ValueError(
                f"Secret '{self.secret_name}' does not contain 'access_token' field. "
                "Ensure the OAuth flow has been completed and token stored correctly."
            )

        # Proactive refresh if close to expiry
        if not self.is_token_valid():
            logger.info("Token close to expiry — proactively refreshing")
            try:
                access_token = self.refresh_token()
            except Exception as e:
                logger.warning(
                    "Proactive token refresh failed: %s. Using existing token.", e
                )

        return access_token

    def refresh_token(self) -> str:
        """Refresh the OAuth 2.0 access token using the refresh token.

        Calls Atlassian's token endpoint with the refresh_token grant,
        then stores the new token pair in Secrets Manager.

        Returns:
            New access token string.

        Raises:
            ValueError: If refresh token is not available.
            urllib.error.HTTPError: If token refresh request fails.
        """
        token_data = self._get_token_data()
        refresh_token = token_data.get("refresh_token", "")

        if not refresh_token:
            raise ValueError(
                f"Secret '{self.secret_name}' does not contain 'refresh_token'. "
                "Re-run the OAuth authorization flow to obtain a new refresh token."
            )

        client_id = token_data.get("client_id", "")
        client_secret = token_data.get("client_secret", "")

        if not client_id or not client_secret:
            raise ValueError(
                f"Secret '{self.secret_name}' missing 'client_id' or 'client_secret'. "
                "These are required for token refresh."
            )

        # Request new token from Atlassian
        new_token_data = self._request_token_refresh(
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
        )

        # Update stored secret with new tokens
        updated_secret = {
            **token_data,
            "access_token": new_token_data["access_token"],
            "refresh_token": new_token_data.get("refresh_token", refresh_token),
            "expires_in": new_token_data.get("expires_in", 3600),
            "refreshed_at": int(time.time()),
        }

        self._store_token_data(updated_secret)
        self._cached_token_data = updated_secret
        self._token_fetched_at = time.time()

        logger.info("Atlassian OAuth token refreshed successfully")
        return new_token_data["access_token"]

    def is_token_valid(self) -> bool:
        """Check if the current access token is still valid (not expired or close to expiry).

        Returns:
            True if token has more than REFRESH_BUFFER_SECONDS remaining.
            False if token is expired or close to expiry.
        """
        token_data = self._get_token_data()

        expires_in = token_data.get("expires_in", 3600)
        refreshed_at = token_data.get("refreshed_at", 0)

        if refreshed_at == 0:
            # No refresh timestamp — assume token might be stale
            # Use fetch time as approximation
            if self._token_fetched_at == 0:
                return False
            elapsed = time.time() - self._token_fetched_at
        else:
            elapsed = time.time() - refreshed_at

        remaining = expires_in - elapsed

        if remaining <= _REFRESH_BUFFER_SECONDS:
            logger.debug(
                "Token has %.0f seconds remaining (buffer: %d) — needs refresh",
                remaining, _REFRESH_BUFFER_SECONDS,
            )
            return False

        return True

    def _get_token_data(self) -> dict[str, Any]:
        """Retrieve token data from Secrets Manager (with caching).

        Caches the token data for the lifetime of this instance to avoid
        repeated Secrets Manager calls within a single operation.
        """
        if self._cached_token_data:
            return self._cached_token_data

        try:
            response = self._secrets_client.get_secret_value(SecretId=self.secret_name)
            secret_string = response.get("SecretString", "{}")
            self._cached_token_data = json.loads(secret_string)
            self._token_fetched_at = time.time()
            return self._cached_token_data
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "ResourceNotFoundException":
                raise ValueError(
                    f"Secret '{self.secret_name}' not found in Secrets Manager. "
                    "Complete the OAuth setup flow first. "
                    "See docs/integration/atlassian-setup.md"
                ) from e
            raise

    def _store_token_data(self, token_data: dict[str, Any]) -> None:
        """Store updated token data back to Secrets Manager."""
        try:
            self._secrets_client.put_secret_value(
                SecretId=self.secret_name,
                SecretString=json.dumps(token_data),
            )
        except ClientError as e:
            logger.error("Failed to store refreshed token in Secrets Manager: %s", e)
            raise

    def _request_token_refresh(
        self,
        refresh_token: str,
        client_id: str,
        client_secret: str,
    ) -> dict[str, Any]:
        """Make the OAuth 2.0 token refresh request to Atlassian.

        Args:
            refresh_token: Current refresh token.
            client_id: OAuth app client ID.
            client_secret: OAuth app client secret.

        Returns:
            Parsed JSON response with new access_token and optionally new refresh_token.

        Raises:
            urllib.error.HTTPError: If the refresh request fails.
        """
        data = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        }).encode("utf-8")

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }

        req = urllib.request.Request(
            _ATLASSIAN_TOKEN_URL,
            data=data,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                response_body = response.read().decode("utf-8")
                return json.loads(response_body)
        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8")
            except Exception:
                pass
            logger.error(
                "Atlassian token refresh failed (%d): %s", e.code, error_body
            )
            raise
