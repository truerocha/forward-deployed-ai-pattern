#!/usr/bin/env bash
set -euo pipefail

# Forward Deployed Engineer — ALM API Validation Script
# Validates connectivity to GitHub Projects, Asana, and GitLab Ultimate
# Usage: bash scripts/validate-alm-api.sh [--github] [--asana] [--gitlab] [--all]

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PASS=0
FAIL=0
SKIP=0

log_ok()   { echo -e "  ${GREEN}✓${NC} $1"; ((PASS++)); }
log_fail() { echo -e "  ${RED}✗${NC} $1"; ((FAIL++)); }
log_skip() { echo -e "  ${YELLOW}⊘${NC} $1"; ((SKIP++)); }
log_head() { echo -e "\n${CYAN}── $1 ──${NC}"; }

# ─── GITHUB PROJECTS ───────────────────────────────────────────
validate_github() {
    log_head "GitHub Projects"

    # 1. Token exists
    if [ -z "${GITHUB_TOKEN:-}" ]; then
        log_fail "GITHUB_TOKEN not set"
        log_skip "Skipping GitHub API checks (no token)"
        return
    fi
    log_ok "GITHUB_TOKEN is set"

    # 2. Token is valid (check authenticated user)
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer $GITHUB_TOKEN" \
        -H "Accept: application/vnd.github+json" \
        https://api.github.com/user 2>/dev/null || echo "000")

    if [ "$HTTP_CODE" = "200" ]; then
        GH_USER=$(curl -s \
            -H "Authorization: Bearer $GITHUB_TOKEN" \
            -H "Accept: application/vnd.github+json" \
            https://api.github.com/user | python3 -c "import sys,json; print(json.load(sys.stdin).get('login','unknown'))" 2>/dev/null || echo "unknown")
        log_ok "Authenticated as: $GH_USER"
    else
        log_fail "GitHub API returned HTTP $HTTP_CODE (expected 200)"
        return
    fi

    # 3. Check required scopes
    SCOPES=$(curl -s -I \
        -H "Authorization: Bearer $GITHUB_TOKEN" \
        -H "Accept: application/vnd.github+json" \
        https://api.github.com/user 2>/dev/null | grep -i "x-oauth-scopes:" | cut -d: -f2- | tr -d ' ' || echo "")

    if [ -n "$SCOPES" ]; then
        log_ok "Token scopes: $SCOPES"
        if echo "$SCOPES" | grep -q "repo"; then
            log_ok "Has 'repo' scope (issues, PRs, projects)"
        else
            log_fail "Missing 'repo' scope — needed for issues and PRs"
        fi
        if echo "$SCOPES" | grep -q "project"; then
            log_ok "Has 'project' scope (GitHub Projects v2)"
        else
            log_skip "No 'project' scope — GitHub Projects v2 board reads may fail"
        fi
    else
        log_skip "Could not read token scopes (fine-grained token or SSO)"
    fi

    # 4. Check MCP server availability
    if command -v npx &>/dev/null; then
        log_ok "npx available (needed for GitHub MCP server)"
    else
        log_fail "npx not found — install Node.js to use GitHub MCP"
    fi

    # 5. Check rate limit
    RATE_JSON=$(curl -s \
        -H "Authorization: Bearer $GITHUB_TOKEN" \
        -H "Accept: application/vnd.github+json" \
        https://api.github.com/rate_limit 2>/dev/null || echo "{}")

    REMAINING=$(echo "$RATE_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('rate',{}).get('remaining','?'))" 2>/dev/null || echo "?")
    LIMIT=$(echo "$RATE_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('rate',{}).get('limit','?'))" 2>/dev/null || echo "?")
    log_ok "Rate limit: $REMAINING / $LIMIT remaining"
}

# ─── ASANA ──────────────────────────────────────────────────────
validate_asana() {
    log_head "Asana"

    # 1. Token exists
    if [ -z "${ASANA_ACCESS_TOKEN:-}" ]; then
        log_fail "ASANA_ACCESS_TOKEN not set"
        log_skip "Skipping Asana API checks (no token)"
        return
    fi
    log_ok "ASANA_ACCESS_TOKEN is set"

    # 2. Token is valid
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer $ASANA_ACCESS_TOKEN" \
        https://app.asana.com/api/1.0/users/me 2>/dev/null || echo "000")

    if [ "$HTTP_CODE" = "200" ]; then
        ASANA_USER=$(curl -s \
            -H "Authorization: Bearer $ASANA_ACCESS_TOKEN" \
            https://app.asana.com/api/1.0/users/me | python3 -c "import sys,json; print(json.load(sys.stdin).get('data',{}).get('name','unknown'))" 2>/dev/null || echo "unknown")
        log_ok "Authenticated as: $ASANA_USER"
    elif [ "$HTTP_CODE" = "401" ]; then
        log_fail "Asana API returned 401 — token is invalid or expired"
        return
    else
        log_fail "Asana API returned HTTP $HTTP_CODE (expected 200)"
        return
    fi

    # 3. List workspaces
    WS_COUNT=$(curl -s \
        -H "Authorization: Bearer $ASANA_ACCESS_TOKEN" \
        https://app.asana.com/api/1.0/workspaces | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('data',[])))" 2>/dev/null || echo "0")
    log_ok "Accessible workspaces: $WS_COUNT"

    # 4. Check MCP server availability
    if command -v uvx &>/dev/null; then
        log_ok "uvx available (needed for Asana MCP server)"
    else
        log_fail "uvx not found — install uv (https://docs.astral.sh/uv/getting-started/installation/)"
    fi
}

# ─── GITLAB ULTIMATE ────────────────────────────────────────────
validate_gitlab() {
    log_head "GitLab Ultimate"

    # 1. Token exists
    if [ -z "${GITLAB_TOKEN:-}" ]; then
        log_fail "GITLAB_TOKEN not set"
        log_skip "Skipping GitLab API checks (no token)"
        return
    fi
    log_ok "GITLAB_TOKEN is set"

    # 2. Determine API URL
    GITLAB_API="${GITLAB_URL:-https://gitlab.com}"
    log_ok "GitLab API URL: $GITLAB_API"

    # 3. Token is valid
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
        "$GITLAB_API/api/v4/user" 2>/dev/null || echo "000")

    if [ "$HTTP_CODE" = "200" ]; then
        GL_USER=$(curl -s \
            -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
            "$GITLAB_API/api/v4/user" | python3 -c "import sys,json; print(json.load(sys.stdin).get('username','unknown'))" 2>/dev/null || echo "unknown")
        log_ok "Authenticated as: $GL_USER"
    elif [ "$HTTP_CODE" = "401" ]; then
        log_fail "GitLab API returned 401 — token is invalid or expired"
        return
    else
        log_fail "GitLab API returned HTTP $HTTP_CODE (expected 200)"
        return
    fi

    # 4. Check version
    LICENSE_INFO=$(curl -s \
        -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
        "$GITLAB_API/api/v4/version" 2>/dev/null || echo "{}")

    GL_VERSION=$(echo "$LICENSE_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin).get('version','unknown'))" 2>/dev/null || echo "unknown")
    log_ok "GitLab version: $GL_VERSION"

    # 4. Check token scopes (PAT self-introspection)
    SCOPE_JSON=$(curl -s \
        -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
        "$GITLAB_API/api/v4/personal_access_tokens/self" 2>/dev/null || echo "{}")

    GL_SCOPES=$(echo "$SCOPE_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(','.join(d.get('scopes',[])))" 2>/dev/null || echo "")
    GL_EXPIRES=$(echo "$SCOPE_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('expires_at','never'))" 2>/dev/null || echo "unknown")

    if [ -n "$GL_SCOPES" ]; then
        log_ok "Token scopes: $GL_SCOPES (expires: $GL_EXPIRES)"
        if echo "$GL_SCOPES" | grep -q "api"; then
            log_ok "Has 'api' scope (full API access for issues, MRs, boards)"
        else
            log_fail "Missing 'api' scope — needed for issue and MR operations"
        fi
    else
        log_skip "Could not read token scopes (token type may not support self-introspection)"
    fi

    # 5. Check if token is expired
    if [ "$GL_EXPIRES" != "never" ] && [ "$GL_EXPIRES" != "null" ] && [ "$GL_EXPIRES" != "unknown" ]; then
        TODAY=$(date '+%Y-%m-%d')
        if [[ "$GL_EXPIRES" < "$TODAY" ]]; then
            log_fail "Token expired on $GL_EXPIRES — generate a new one"
        else
            log_ok "Token valid until $GL_EXPIRES"
        fi
    fi

    # 6. Check board access (requires project)
    if [ -n "${GITLAB_PROJECT_ID:-}" ]; then
        BOARD_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
            -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
            "$GITLAB_API/api/v4/projects/$GITLAB_PROJECT_ID/boards" 2>/dev/null || echo "000")
        if [ "$BOARD_CODE" = "200" ]; then
            log_ok "Board access verified for project $GITLAB_PROJECT_ID"
        else
            log_fail "Cannot access boards for project $GITLAB_PROJECT_ID (HTTP $BOARD_CODE)"
        fi
    else
        log_skip "GITLAB_PROJECT_ID not set — cannot verify board access"
    fi

    # 7. Check MCP server availability
    if command -v npx &>/dev/null; then
        log_ok "npx available (needed for GitLab MCP server)"
    else
        log_fail "npx not found — install Node.js to use GitLab MCP"
    fi
}

# ─── SUMMARY ────────────────────────────────────────────────────
print_summary() {
    echo ""
    echo "═══════════════════════════════════════════════════════════"
    echo " ALM API Validation Summary"
    echo "═══════════════════════════════════════════════════════════"
    echo -e " ${GREEN}Passed${NC}: $PASS"
    echo -e " ${RED}Failed${NC}: $FAIL"
    echo -e " ${YELLOW}Skipped${NC}: $SKIP"
    echo ""

    if [ "$FAIL" -gt 0 ]; then
        echo -e " ${RED}Action required:${NC} Fix failed checks before enabling enterprise hooks."
        echo ""
        echo " Environment variables to set (add to ~/.zshrc or ~/.bashrc):"
        echo "   export GITHUB_TOKEN=\"ghp_...\"          # GitHub PAT with repo + project scopes"
        echo "   export ASANA_ACCESS_TOKEN=\"1/...\"       # Asana Personal Access Token"
        echo "   export GITLAB_TOKEN=\"glpat-...\"         # GitLab PAT with api scope"
        echo "   export GITLAB_URL=\"https://gitlab.com\"  # GitLab instance URL (default: gitlab.com)"
        echo "   export GITLAB_PROJECT_ID=\"12345\"        # GitLab project ID for board access"
        echo ""
        exit 1
    else
        echo -e " ${GREEN}All configured platforms are accessible.${NC}"
        echo ""
    fi
}

# ─── MAIN ───────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo " Forward Deployed Engineer — ALM API Validation"
echo " Date: $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════════════════════════"

case "${1:-}" in
    --github)
        validate_github
        ;;
    --asana)
        validate_asana
        ;;
    --gitlab)
        validate_gitlab
        ;;
    --all|"")
        validate_github
        validate_asana
        validate_gitlab
        ;;
    *)
        echo "Usage: bash scripts/validate-alm-api.sh [--github] [--asana] [--gitlab] [--all]"
        exit 1
        ;;
esac

print_summary
