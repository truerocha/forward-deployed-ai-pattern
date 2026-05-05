# Authentication Setup Guide

> Time: 5 minutes per platform
> Prerequisite: accounts on the platforms you want to connect
> Validation: `bash scripts/validate-alm-api.sh --all`

This guide walks you through creating Personal Access Tokens (PATs) for each ALM platform the Code Factory supports. You need at least one platform configured. The factory works with any combination.

---

## GitHub

### What you need
- A GitHub account with access to the repositories you want the factory to manage
- The `repo` scope (for issues, PRs, and code access)
- The `project` scope (for GitHub Projects v2 board reads — optional)

### Steps

1. Open **github.com → Settings → Developer settings → Personal access tokens → Tokens (classic)**
   - Direct link: https://github.com/settings/tokens
2. Click **Generate new token (classic)**
3. Set a descriptive name: `fde-code-factory`
4. Set expiration: 90 days (or "No expiration" for development)
5. Select scopes:
   - ✅ `repo` (Full control of private repositories)
   - ✅ `project` (Full control of projects) — optional, needed for board column reads
6. Click **Generate token**
7. Copy the token (starts with `ghp_`)

### Configure

```bash
export GITHUB_TOKEN="ghp_your_token_here"
```

Add to `~/.zshrc` or `~/.bashrc` for persistence.

### Validate

```bash
bash scripts/validate-alm-api.sh --github
```

Expected output:
```
✓ GITHUB_TOKEN is set
✓ Authenticated as: your-username
✓ Token scopes: repo,project
✓ Has 'repo' scope (issues, PRs, projects)
✓ Has 'project' scope (GitHub Projects v2)
✓ Rate limit: 4998 / 5000 remaining
```

---

## GitLab

### What you need
- A GitLab account (gitlab.com or self-hosted instance)
- The `api` scope (full API access for issues, MRs, boards, and labels)

### Steps

1. Open **GitLab → User Settings → Access Tokens**
   - gitlab.com: https://gitlab.com/-/user_settings/personal_access_tokens
   - Self-hosted: `https://your-instance.com/-/user_settings/personal_access_tokens`
2. Set a descriptive name: `fde-code-factory`
3. Set expiration date (recommended: 90 days)
4. Select scopes:
   - ✅ `api` (Grants complete read/write access to the API)
5. Click **Create personal access token**
6. Copy the token (starts with `glpat-`)

### Configure

```bash
export GITLAB_TOKEN="glpat-your_token_here"
export GITLAB_URL="https://gitlab.com"          # or your self-hosted URL
export GITLAB_PROJECT_ID="12345"                 # numeric project ID for board access
```

To find your project ID: open the project page → the ID is displayed below the project name, or in **Settings → General**.

### Validate

```bash
bash scripts/validate-alm-api.sh --gitlab
```

Expected output:
```
✓ GITLAB_TOKEN is set
✓ GitLab API URL: https://gitlab.com
✓ Authenticated as: your-username
✓ GitLab version: 17.x.x
✓ Token scopes: api (expires: 2026-08-04)
✓ Has 'api' scope (full API access for issues, MRs, boards)
✓ Token valid until 2026-08-04
✓ Board access verified for project 12345
```

---

## Asana

### What you need
- An Asana account with access to the workspace and projects you want the factory to manage
- A Personal Access Token (full access — Asana does not support granular scopes for PATs)

### Steps

1. Open **Asana → My Settings → Apps → Developer Apps**
   - Direct link: https://app.asana.com/0/my-apps
2. Click **Create new token** (under Personal Access Tokens)
3. Set a descriptive name: `fde-code-factory`
4. Click **Create token**
5. Copy the token (starts with `1/`)

### Configure

```bash
export ASANA_ACCESS_TOKEN="1/your_token_here"
```

### Validate

```bash
bash scripts/validate-alm-api.sh --asana
```

Expected output:
```
✓ ASANA_ACCESS_TOKEN is set
✓ Authenticated as: Your Name
✓ Accessible workspaces: 2
✓ uvx available (needed for Asana MCP server)
```

### Asana permissions note

Asana PATs inherit the permissions of the user who created them. The token can access any workspace and project the user belongs to. There are no granular scopes to configure — if the user can see a task, the token can read and update it.

---

## Progressive Configuration

The factory works with any combination of platforms. You do not need all three configured:

| Configuration | What works |
|---------------|-----------|
| GitHub only | Tasks from GitHub Issues, PRs opened on GitHub |
| GitHub + GitLab | Tasks from both, PRs/MRs on the respective platform |
| GitHub + Asana | Tasks from both, PRs on GitHub, status sync to Asana |
| All three | Full multi-platform support |

Platforms without tokens are skipped with a warning (not an error). The `mcp.json` configuration marks unconfigured platforms as `"disabled": true`.

---

## Cloud Deployment (Secrets Manager)

When deploying to AWS (ECS Fargate), tokens are stored in Secrets Manager instead of environment variables:

```bash
aws secretsmanager create-secret \
  --name "fde-dev/alm-tokens" \
  --secret-string '{
    "GITHUB_TOKEN": "ghp_...",
    "ASANA_ACCESS_TOKEN": "1/...",
    "GITLAB_TOKEN": "glpat-..."
  }'
```

The ECS task definition reads these secrets at container start. You do not need to set environment variables on the host when running in cloud mode.

---

## Token Rotation

| Platform | Rotation cadence | How to rotate |
|----------|-----------------|---------------|
| GitHub | Every 90 days (or on scope change) | Generate new token, update env var, run validation |
| GitLab | Before expiration date | Generate new token, update env var, run validation |
| Asana | No expiration (rotate on team changes) | Revoke old token in Asana settings, create new one |

After rotation, validate with:

```bash
bash scripts/validate-alm-api.sh --all
```

---

## Troubleshooting

| Symptom | Cause | Resolution |
|---------|-------|-----------|
| `401 Unauthorized` | Token expired or revoked | Generate a new token following the steps above |
| `403 Forbidden` | Token lacks required scope | Regenerate with correct scopes (`repo` for GitHub, `api` for GitLab) |
| `404 Not Found` on board access | Wrong project ID or no board configured | Verify `GITLAB_PROJECT_ID` matches the numeric ID in project settings |
| `Rate limit exceeded` | Too many API calls | Wait for reset (GitHub: 5000/hour, GitLab: 2000/min, Asana: 1500/min) |
| `Could not read token scopes` | Using fine-grained token (GitHub) or deploy token (GitLab) | Use classic PAT for full scope visibility |

---

## Related

- Validation script: `scripts/validate-alm-api.sh`
- MCP configuration: `.kiro/settings/mcp.json`
- Enterprise steering: `.kiro/steering/fde-enterprise.md`
- Cloud secrets: `infra/terraform/main.tf` (Secrets Manager resource)
