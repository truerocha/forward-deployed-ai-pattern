# Atlassian Integration Setup Guide

> Activity 5.06 — OAuth app registration, Secrets Manager configuration, and feature flag activation for Confluence + Jira integration.

---

## Overview

The Atlassian integration provides:
- **Confluence read**: Fetch page content for context enrichment during agent execution
- **Jira CRUD**: Create issues, update status, and track work items programmatically

Authentication uses **OAuth 2.0 (3-legged OAuth / 3LO)** with tokens stored in AWS Secrets Manager. The integration is gated by the `ENABLE_ATLASSIAN` feature flag.

---

## Prerequisites

- Atlassian Cloud instance (e.g., `your-domain.atlassian.net`)
- Admin access to create OAuth apps in Atlassian Developer Console
- AWS account with Secrets Manager access
- Factory ECS task role with Secrets Manager read/write permissions

---

## Step 1: Register OAuth App in Atlassian

### 1.1 Create the App

1. Go to [Atlassian Developer Console](https://developer.atlassian.com/console/myapps/)
2. Click **Create** → **OAuth 2.0 integration**
3. Name: `FDE Code Factory` (or your preferred name)
4. Accept the terms

### 1.2 Configure Permissions

Under **Permissions**, add:

| Product | Scope | Purpose |
|---------|-------|---------|
| Confluence | `read:confluence-content.all` | Read page content |
| Confluence | `read:confluence-space.summary` | List spaces |
| Jira | `read:jira-work` | Read issues |
| Jira | `write:jira-work` | Create/update issues |
| Jira | `read:jira-user` | Resolve user references |

### 1.3 Configure Authorization

Under **Authorization**:
- **Authorization type**: OAuth 2.0 (3LO)
- **Callback URL**: `https://your-factory-domain.com/oauth/callback` (or `http://localhost:3000/callback` for local testing)

### 1.4 Note Credentials

From the **Settings** page, note:
- **Client ID**: `your-client-id`
- **Client Secret**: `your-client-secret`

---

## Step 2: Obtain Initial Tokens

### 2.1 Authorization URL

Direct a browser to:

```
https://auth.atlassian.com/authorize?
  audience=api.atlassian.com&
  client_id={CLIENT_ID}&
  scope=read:confluence-content.all read:confluence-space.summary read:jira-work write:jira-work read:jira-user offline_access&
  redirect_uri={CALLBACK_URL}&
  state={RANDOM_STATE}&
  response_type=code&
  prompt=consent
```

**Important**: Include `offline_access` scope to receive a refresh token.

### 2.2 Exchange Code for Tokens

After authorization, exchange the code:

```bash
curl -X POST https://auth.atlassian.com/oauth/token \
  -H "Content-Type: application/json" \
  -d '{
    "grant_type": "authorization_code",
    "client_id": "YOUR_CLIENT_ID",
    "client_secret": "YOUR_CLIENT_SECRET",
    "code": "AUTHORIZATION_CODE",
    "redirect_uri": "YOUR_CALLBACK_URL"
  }'
```

Response:
```json
{
  "access_token": "eyJ...",
  "refresh_token": "abc...",
  "expires_in": 3600,
  "token_type": "Bearer",
  "scope": "read:confluence-content.all ..."
}
```

---

## Step 3: Store Tokens in Secrets Manager

### 3.1 Create the Secret

```bash
aws secretsmanager create-secret \
  --name "fde/atlassian/oauth-token" \
  --description "Atlassian OAuth 2.0 tokens for FDE Code Factory" \
  --secret-string '{
    "access_token": "eyJ...",
    "refresh_token": "abc...",
    "client_id": "YOUR_CLIENT_ID",
    "client_secret": "YOUR_CLIENT_SECRET",
    "expires_in": 3600,
    "refreshed_at": 0,
    "base_url": "https://your-domain.atlassian.net"
  }'
```

### 3.2 Secret Schema

| Field | Type | Description |
|-------|------|-------------|
| `access_token` | string | Current OAuth access token |
| `refresh_token` | string | Long-lived refresh token |
| `client_id` | string | OAuth app client ID |
| `client_secret` | string | OAuth app client secret |
| `expires_in` | int | Token lifetime in seconds (typically 3600) |
| `refreshed_at` | int | Unix timestamp of last refresh (0 = never) |
| `base_url` | string | Atlassian instance URL |

### 3.3 IAM Policy for ECS Task Role

Add to the ECS task role:

```json
{
  "Effect": "Allow",
  "Action": [
    "secretsmanager:GetSecretValue",
    "secretsmanager:PutSecretValue"
  ],
  "Resource": "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:fde/atlassian/oauth-token-*"
}
```

---

## Step 4: Enable the Feature Flag

### 4.1 Terraform (Persistent)

In your ECS task definition:

```hcl
{ name = "ENABLE_ATLASSIAN", value = "true" }
```

### 4.2 Runtime Override (Testing)

```bash
aws ecs run-task --overrides '{
  "containerOverrides": [{
    "name": "orchestrator",
    "environment": [{"name": "ENABLE_ATLASSIAN", "value": "true"}]
  }]
}'
```

### 4.3 Per-Project Override

Store in DynamoDB metrics table:
```
PK: {project_id}, SK: "config#feature_flags"
{ "ENABLE_ATLASSIAN": "true" }
```

---

## Step 5: Verify Integration

### 5.1 Test Confluence Read

```python
from src.integrations.atlassian import AtlassianMCPProxy

proxy = AtlassianMCPProxy.from_secrets_manager(
    base_url="https://your-domain.atlassian.net",
)

page = proxy.read_confluence_page("12345678")
print(f"Title: {page['title']}")
print(f"Content length: {len(page['content'])} chars")
```

### 5.2 Test Jira Create

```python
result = proxy.create_jira_issue(
    project="PROJ",
    summary="Test issue from FDE factory",
    description="This is a test issue created by the integration verification.",
)
print(f"Created: {result['issue_key']}")
```

### 5.3 Test Jira Status Update

```python
result = proxy.update_jira_status("PROJ-42", "In Progress")
print(f"Transitioned to: {result['new_status']}")
```

---

## Token Refresh Behavior

The `AtlassianAuth` module handles token refresh automatically:

1. **Proactive refresh**: When `get_token()` is called and the token has less than 5 minutes remaining, it refreshes automatically
2. **Transparent to callers**: The proxy checks token validity before each API call
3. **Failure resilience**: If refresh fails, the existing token is used (may still be valid)
4. **Secrets Manager update**: New tokens are written back to Secrets Manager after refresh

### Refresh Timeline

```
Token issued ──────────────────────────────── Token expires
|                                    |←5min→|
|         Token valid                | Refresh zone |
|         (no action)                | (auto-refresh)|
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `AtlassianDisabledError` | Feature flag off | Set `ENABLE_ATLASSIAN=true` |
| `ResourceNotFoundException` | Secret not created | Run Step 3 to create secret |
| `ValueError: missing access_token` | OAuth flow incomplete | Complete Step 2 |
| `HTTPError 401` | Token expired, refresh failed | Re-run OAuth flow (Step 2) |
| `HTTPError 403` | Insufficient scopes | Update app permissions (Step 1.2) |
| `Connection error` | Wrong base_url | Verify Atlassian instance URL |
| `No transition available` | Invalid Jira workflow state | Check issue's current status and available transitions |

---

## Security Considerations

- **Secrets Manager**: Tokens are never stored in code, environment variables, or config files
- **Least privilege**: OAuth scopes are limited to required operations only
- **Token rotation**: Refresh tokens are rotated on each refresh (Atlassian's default behavior)
- **Audit trail**: All Secrets Manager access is logged in CloudTrail
- **Network**: All API calls use HTTPS with TLS 1.2+
- **Feature flag**: Integration is disabled by default — explicit opt-in required
