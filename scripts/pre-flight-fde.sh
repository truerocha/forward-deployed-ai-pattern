#!/usr/bin/env bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════════
# Forward Deployed Engineer — Pre-Flight Validation
# ═══════════════════════════════════════════════════════════════════
#
# Purpose: Validates the Staff Engineer's machine has all required
#          tools, runtimes, and credentials. Collects configuration
#          interactively and writes a manifest for downstream scripts.
#
# Usage:   bash scripts/pre-flight-fde.sh
# Output:  ~/.kiro/fde-manifest.json (consumed by validate-deploy-fde.sh)
#
# Flow:    pre-flight-fde.sh → validate-deploy-fde.sh → code-factory-setup.sh
# ═══════════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0
AWS_PROFILE_ARG=""

log_ok()   { echo -e "  ${GREEN}✓${NC} $1"; ((PASS++)); }
log_fail() { echo -e "  ${RED}✗${NC} $1"; ((FAIL++)); }
log_warn() { echo -e "  ${YELLOW}⚠${NC} $1"; ((WARN++)); }
log_head() { echo -e "\n${CYAN}── $1 ──${NC}"; }
log_info() { echo -e "  ${BOLD}ℹ${NC} $1"; }
log_fix()  { echo -e "  ${BOLD}  → Fix:${NC} $1"; }

# Helper: run aws CLI with optional --profile
aws_cmd() {
    if [ -n "$AWS_PROFILE_ARG" ]; then
        aws --profile "$AWS_PROFILE_ARG" "$@"
    else
        aws "$@"
    fi
}

# Manifest accumulator
declare -A MANIFEST
MANIFEST[timestamp]=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
MANIFEST[os]=$(uname -s)
MANIFEST[arch]=$(uname -m)

# ─── SECTION 1: Core Tools ──────────────────────────────────────
check_core_tools() {
    log_head "Section 1: Core Tools"

    # Git
    if command -v git &>/dev/null; then
        GIT_VER=$(git --version | awk '{print $3}')
        log_ok "git $GIT_VER"
        MANIFEST[git]="$GIT_VER"
    else
        log_fail "git not found — install: brew install git"
        MANIFEST[git]="missing"
    fi

    # Node.js (for GitHub/GitLab MCP servers)
    if command -v node &>/dev/null; then
        NODE_VER=$(node --version)
        log_ok "node $NODE_VER"
        MANIFEST[node]="$NODE_VER"
    else
        log_fail "node not found — install: brew install node"
        MANIFEST[node]="missing"
    fi

    # npx (for MCP servers)
    if command -v npx &>/dev/null; then
        log_ok "npx available"
        MANIFEST[npx]="true"
    else
        log_fail "npx not found — comes with Node.js"
        MANIFEST[npx]="false"
    fi

    # Python 3 (for scripts, linting, tests)
    if command -v python3 &>/dev/null; then
        PY_VER=$(python3 --version | awk '{print $2}')
        log_ok "python3 $PY_VER"
        MANIFEST[python3]="$PY_VER"
    else
        log_warn "python3 not found — needed for lint and test scripts"
        MANIFEST[python3]="missing"
    fi

    # uv/uvx (for Asana MCP server)
    if command -v uvx &>/dev/null; then
        log_ok "uvx available (needed for Asana MCP)"
        MANIFEST[uvx]="true"
    else
        log_warn "uvx not found — needed for Asana MCP. Install: https://docs.astral.sh/uv/getting-started/installation/"
        MANIFEST[uvx]="false"
    fi

    # Docker (for ship-readiness)
    if command -v docker &>/dev/null; then
        DOCKER_VER=$(docker --version 2>/dev/null | awk '{print $3}' | tr -d ',')
        if docker info &>/dev/null 2>&1; then
            log_ok "docker $DOCKER_VER (daemon running)"
            MANIFEST[docker]="$DOCKER_VER"
        else
            log_warn "docker $DOCKER_VER (daemon NOT running — start Docker Desktop)"
            MANIFEST[docker]="$DOCKER_VER-stopped"
        fi
    else
        log_warn "docker not found — needed for ship-readiness. Install: https://docker.com"
        MANIFEST[docker]="missing"
    fi

    # curl (for API validation)
    if command -v curl &>/dev/null; then
        log_ok "curl available"
        MANIFEST[curl]="true"
    else
        log_fail "curl not found — required for API validation"
        MANIFEST[curl]="false"
    fi

    # AWS CLI
    if command -v aws &>/dev/null; then
        AWS_VER=$(aws --version 2>&1 | awk '{print $1}' | cut -d/ -f2)
        log_ok "aws-cli $AWS_VER"
        MANIFEST[aws_cli]="$AWS_VER"
    else
        log_warn "aws-cli not found — needed for cloud deployment. Install: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
        MANIFEST[aws_cli]="missing"
    fi

    # Terraform
    if command -v terraform &>/dev/null; then
        TF_VER=$(terraform version -json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('terraform_version','unknown'))" 2>/dev/null || terraform version | head -1 | awk '{print $2}')
        log_ok "terraform $TF_VER"
        MANIFEST[terraform]="$TF_VER"
    else
        log_warn "terraform not found — needed for AWS IaC. Install: https://developer.hashicorp.com/terraform/install"
        MANIFEST[terraform]="missing"
    fi
}

# ─── SECTION 2: Credentials ─────────────────────────────────────
check_credentials() {
    log_head "Section 2: Credentials & Tokens"

    MANIFEST[github_configured]="false"
    MANIFEST[asana_configured]="false"
    MANIFEST[gitlab_configured]="false"

    # GitHub
    if [ -n "${GITHUB_TOKEN:-}" ]; then
        # Mask token for display
        MASKED="${GITHUB_TOKEN:0:4}...${GITHUB_TOKEN: -4}"
        log_ok "GITHUB_TOKEN is set ($MASKED)"
        MANIFEST[github_configured]="true"
    else
        log_fail "GITHUB_TOKEN not set"
        log_info "Create at: GitHub → Settings → Developer Settings → Personal Access Tokens"
        log_info "Required scopes: repo, project"
        log_info "Add to shell: export GITHUB_TOKEN=\"ghp_...\""
    fi

    # Asana
    if [ -n "${ASANA_ACCESS_TOKEN:-}" ]; then
        MASKED="${ASANA_ACCESS_TOKEN:0:4}...${ASANA_ACCESS_TOKEN: -4}"
        log_ok "ASANA_ACCESS_TOKEN is set ($MASKED)"
        MANIFEST[asana_configured]="true"
    else
        log_warn "ASANA_ACCESS_TOKEN not set (optional — skip if not using Asana)"
        log_info "Create at: Asana → My Settings → Apps → Personal Access Tokens"
    fi

    # GitLab
    if [ -n "${GITLAB_TOKEN:-}" ]; then
        MASKED="${GITLAB_TOKEN:0:4}...${GITLAB_TOKEN: -4}"
        log_ok "GITLAB_TOKEN is set ($MASKED)"
        MANIFEST[gitlab_configured]="true"
        if [ -n "${GITLAB_URL:-}" ]; then
            log_ok "GITLAB_URL: ${GITLAB_URL}"
            MANIFEST[gitlab_url]="${GITLAB_URL}"
        else
            log_info "GITLAB_URL not set — will default to https://gitlab.com"
            MANIFEST[gitlab_url]="https://gitlab.com"
        fi
    else
        log_warn "GITLAB_TOKEN not set (optional — skip if not using GitLab)"
        log_info "Create at: GitLab → Preferences → Access Tokens (scope: api)"
    fi

    # AWS
    MANIFEST[aws_configured]="false"
    MANIFEST[aws_profile]=""
    if command -v aws &>/dev/null; then
        # Ask for AWS profile (SSO, named profiles, or default)
        echo ""
        log_info "AWS authentication — supports SSO, named profiles, or env vars"
        read -rp "    AWS profile name (leave blank for default/env vars): " AWS_PROF
        AWS_PROF="${AWS_PROF:-}"
        if [ -n "$AWS_PROF" ]; then
            AWS_PROFILE_ARG="$AWS_PROF"
            MANIFEST[aws_profile]="$AWS_PROF"
            log_info "Using AWS profile: $AWS_PROF"
            log_info "If SSO session expired, run: aws sso login --profile $AWS_PROF"
        fi

        AWS_IDENTITY=$(aws_cmd sts get-caller-identity 2>/dev/null || echo "")
        if [ -n "$AWS_IDENTITY" ]; then
            AWS_ACCOUNT=$(echo "$AWS_IDENTITY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('Account','unknown'))" 2>/dev/null || echo "unknown")
            AWS_ARN=$(echo "$AWS_IDENTITY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('Arn','unknown'))" 2>/dev/null || echo "unknown")
            log_ok "AWS authenticated: account $AWS_ACCOUNT"
            log_info "Identity: $AWS_ARN"
            MANIFEST[aws_configured]="true"
            MANIFEST[aws_account]="$AWS_ACCOUNT"
            MANIFEST[aws_region]="${AWS_DEFAULT_REGION:-${AWS_REGION:-us-east-1}}"

            # Validate specific IAM permissions
            if [ -f "$SCRIPT_DIR/scripts/validate-aws-iam.py" ]; then
                log_info "Running IAM permission validation..."
                if python3 "$SCRIPT_DIR/scripts/validate-aws-iam.py" --region "${AWS_DEFAULT_REGION:-${AWS_REGION:-us-east-1}}" 2>/dev/null; then
                    log_ok "AWS IAM permissions validated"
                    MANIFEST[aws_iam_valid]="true"
                else
                    log_warn "Some AWS IAM permissions missing — cloud deployment may fail"
                    log_fix "Attach required policies to your IAM role. See: docs/flows/12-staff-engineer-onboarding.md"
                    MANIFEST[aws_iam_valid]="false"
                fi
            fi
        else
            log_warn "AWS credentials not valid or session expired"
            if [ -n "$AWS_PROF" ]; then
                log_fix "Run: aws sso login --profile $AWS_PROF"
            else
                log_fix "Run: aws configure (or aws sso login --profile <name>)"
                log_fix "Or set: export AWS_ACCESS_KEY_ID=... && export AWS_SECRET_ACCESS_KEY=..."
            fi
        fi
    else
        log_warn "AWS CLI not installed — cloud deployment unavailable"
        log_fix "Install: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
    fi
}

# ─── SECTION 3: Kiro Environment ────────────────────────────────
check_kiro() {
    log_head "Section 3: Kiro Environment"

    # Check for global Kiro directory
    if [ -d ~/.kiro ]; then
        log_ok "~/.kiro directory exists"
        MANIFEST[kiro_global]="true"
    else
        log_warn "~/.kiro not found — will be created by code-factory-setup.sh"
        MANIFEST[kiro_global]="false"
    fi

    # Check for global steerings
    if [ -d ~/.kiro/steering ] && [ "$(ls ~/.kiro/steering/*.md 2>/dev/null | wc -l | tr -d ' ')" -gt 0 ]; then
        STEERING_COUNT=$(ls ~/.kiro/steering/*.md 2>/dev/null | wc -l | tr -d ' ')
        log_ok "Global steerings: $STEERING_COUNT files"
        MANIFEST[kiro_steerings]="$STEERING_COUNT"
    else
        log_warn "No global steerings found — will be installed by code-factory-setup.sh"
        MANIFEST[kiro_steerings]="0"
    fi

    # Check for global MCP config
    if [ -f ~/.kiro/settings/mcp.json ]; then
        log_ok "Global MCP config exists"
        MANIFEST[kiro_mcp]="true"
    else
        log_warn "No global MCP config — will be created by code-factory-setup.sh"
        MANIFEST[kiro_mcp]="false"
    fi

    # Check for factory state
    if [ -f ~/.kiro/factory-state.md ]; then
        log_ok "Factory state file exists"
        MANIFEST[factory_state]="true"
    else
        log_info "No factory state file — will be created by code-factory-setup.sh"
        MANIFEST[factory_state]="false"
    fi

    # Check for factory template repo
    if [ -d "$SCRIPT_DIR/.kiro/hooks" ]; then
        HOOK_COUNT=$(ls "$SCRIPT_DIR"/.kiro/hooks/*.kiro.hook 2>/dev/null | wc -l | tr -d ' ')
        log_ok "Factory template found at $SCRIPT_DIR ($HOOK_COUNT hooks)"
        MANIFEST[template_path]="$SCRIPT_DIR"
        MANIFEST[template_hooks]="$HOOK_COUNT"
    else
        log_fail "Factory template not found — run this script from the factory-template repo"
        MANIFEST[template_path]="missing"
    fi
}

# ─── SECTION 4: Interactive Configuration ───────────────────────
collect_config() {
    log_head "Section 4: Factory Configuration"
    echo ""

    # How many projects?
    read -rp "  How many projects will you manage? [1-10, default: 1]: " PROJECT_COUNT
    PROJECT_COUNT="${PROJECT_COUNT:-1}"
    MANIFEST[project_count]="$PROJECT_COUNT"
    log_ok "Projects: $PROJECT_COUNT"

    # Collect project details
    PROJECTS_JSON="["
    for i in $(seq 1 "$PROJECT_COUNT"); do
        echo ""
        echo -e "  ${BOLD}Project $i:${NC}"

        read -rp "    Name (e.g., payment-service): " PROJ_NAME
        PROJ_NAME="${PROJ_NAME:-project-$i}"

        read -rp "    Type [experiment/greenfield/brownfield, default: brownfield]: " PROJ_TYPE
        PROJ_TYPE="${PROJ_TYPE:-brownfield}"

        if [ "$PROJ_TYPE" = "experiment" ]; then
            PROJ_REPO=""
            PROJ_PATH="${PROJ_PATH:-$HOME/projects/$PROJ_NAME}"
            read -rp "    Local path [default: ~/projects/$PROJ_NAME]: " PROJ_PATH
            PROJ_PATH="${PROJ_PATH:-$HOME/projects/$PROJ_NAME}"
            PROJ_ALM="none"
            log_info "Experiment mode: local git only, no remote repo, no ALM"
        else
            read -rp "    Repo URL (leave blank to create new): " PROJ_REPO
            PROJ_REPO="${PROJ_REPO:-}"

            read -rp "    Local path [default: ~/projects/$PROJ_NAME]: " PROJ_PATH
            PROJ_PATH="${PROJ_PATH:-$HOME/projects/$PROJ_NAME}"

            read -rp "    ALM platform [github/asana/gitlab, default: github]: " PROJ_ALM
            PROJ_ALM="${PROJ_ALM:-github}"
        fi

        read -rp "    Existing Kiro workspace path (leave blank if none): " PROJ_KIRO_WS
        PROJ_KIRO_WS="${PROJ_KIRO_WS:-}"

        read -rp "    Engineering level [L2/L3/L4, default: L3]: " PROJ_LEVEL
        PROJ_LEVEL="${PROJ_LEVEL:-L3}"

        if [ "$i" -gt 1 ]; then
            PROJECTS_JSON+=","
        fi
        PROJECTS_JSON+="{\"name\":\"$PROJ_NAME\",\"type\":\"$PROJ_TYPE\",\"repo\":\"$PROJ_REPO\",\"path\":\"$PROJ_PATH\",\"alm\":\"$PROJ_ALM\",\"level\":\"$PROJ_LEVEL\",\"kiro_workspace\":\"$PROJ_KIRO_WS\"}"

        log_ok "Project $i: $PROJ_NAME ($PROJ_TYPE, $PROJ_ALM, $PROJ_LEVEL)"
    done
    PROJECTS_JSON+="]"
    MANIFEST[projects]="$PROJECTS_JSON"

    # Cloud deployment config
    echo ""
    echo -e "  ${BOLD}Cloud Deployment (AWS):${NC}"
    read -rp "    Deploy to AWS? [yes/no, default: no]: " DEPLOY_AWS
    DEPLOY_AWS="${DEPLOY_AWS:-no}"
    MANIFEST[deploy_aws]="$DEPLOY_AWS"

    if [ "$DEPLOY_AWS" = "yes" ]; then
        read -rp "    AWS region [default: us-east-1]: " AWS_DEPLOY_REGION
        AWS_DEPLOY_REGION="${AWS_DEPLOY_REGION:-us-east-1}"
        MANIFEST[aws_deploy_region]="$AWS_DEPLOY_REGION"

        read -rp "    Environment [dev/staging/prod, default: dev]: " AWS_ENV
        AWS_ENV="${AWS_ENV:-dev}"
        MANIFEST[aws_environment]="$AWS_ENV"

        read -rp "    Bedrock model [default: anthropic.claude-sonnet-4-20250514-v1:0]: " BEDROCK_MODEL
        BEDROCK_MODEL="${BEDROCK_MODEL:-anthropic.claude-sonnet-4-20250514-v1:0}"
        MANIFEST[bedrock_model]="$BEDROCK_MODEL"

        read -rp "    Enable AgentCore Runtime? [yes/no, default: no]: " ENABLE_AC
        ENABLE_AC="${ENABLE_AC:-no}"
        MANIFEST[enable_agentcore]="$ENABLE_AC"

        read -rp "    Enable ECS always-on service? [yes/no, default: no]: " ENABLE_ECS
        ENABLE_ECS="${ENABLE_ECS:-no}"
        MANIFEST[enable_ecs_service]="$ENABLE_ECS"

        log_ok "Cloud: AWS $AWS_DEPLOY_REGION ($AWS_ENV), Bedrock: $BEDROCK_MODEL"

        read -rp "    AWS profile for Terraform [default: same as above]: " TF_PROFILE
        TF_PROFILE="${TF_PROFILE:-$AWS_PROFILE_ARG}"
        MANIFEST[aws_tf_profile]="$TF_PROFILE"
        if [ -n "$TF_PROFILE" ]; then
            log_ok "Terraform will use AWS profile: $TF_PROFILE"
        fi
    else
        MANIFEST[aws_deploy_region]=""
        MANIFEST[aws_environment]=""
        MANIFEST[bedrock_model]=""
        MANIFEST[enable_agentcore]="no"
        MANIFEST[enable_ecs_service]="no"
        log_ok "Cloud: local-only mode (no AWS deployment)"
    fi
}

# ─── SECTION 5: Write Manifest ──────────────────────────────────
write_manifest() {
    log_head "Writing Manifest"

    mkdir -p ~/.kiro

    # Build JSON manifest
    cat > ~/.kiro/fde-manifest.json << MANIFEST_EOF
{
  "version": "2.0.0",
  "timestamp": "${MANIFEST[timestamp]}",
  "system": {
    "os": "${MANIFEST[os]}",
    "arch": "${MANIFEST[arch]}"
  },
  "tools": {
    "git": "${MANIFEST[git]:-missing}",
    "node": "${MANIFEST[node]:-missing}",
    "npx": ${MANIFEST[npx]:-false},
    "python3": "${MANIFEST[python3]:-missing}",
    "uvx": ${MANIFEST[uvx]:-false},
    "docker": "${MANIFEST[docker]:-missing}",
    "curl": ${MANIFEST[curl]:-false},
    "aws_cli": "${MANIFEST[aws_cli]:-missing}",
    "terraform": "${MANIFEST[terraform]:-missing}"
  },
  "credentials": {
    "github": ${MANIFEST[github_configured]:-false},
    "asana": ${MANIFEST[asana_configured]:-false},
    "gitlab": ${MANIFEST[gitlab_configured]:-false},
    "gitlab_url": "${MANIFEST[gitlab_url]:-https://gitlab.com}",
    "aws": ${MANIFEST[aws_configured]:-false},
    "aws_account": "${MANIFEST[aws_account]:-}",
    "aws_region": "${MANIFEST[aws_region]:-us-east-1}",
    "aws_profile": "${MANIFEST[aws_profile]:-}"
  },
  "kiro": {
    "global_dir": ${MANIFEST[kiro_global]:-false},
    "steerings": ${MANIFEST[kiro_steerings]:-0},
    "mcp_config": ${MANIFEST[kiro_mcp]:-false},
    "factory_state": ${MANIFEST[factory_state]:-false},
    "template_path": "${MANIFEST[template_path]:-missing}",
    "template_hooks": ${MANIFEST[template_hooks]:-0}
  },
  "cloud": {
    "deploy_aws": "${MANIFEST[deploy_aws]:-no}",
    "aws_region": "${MANIFEST[aws_deploy_region]:-}",
    "aws_tf_profile": "${MANIFEST[aws_tf_profile]:-}",
    "environment": "${MANIFEST[aws_environment]:-}",
    "bedrock_model": "${MANIFEST[bedrock_model]:-}",
    "enable_agentcore": "${MANIFEST[enable_agentcore]:-no}",
    "enable_ecs_service": "${MANIFEST[enable_ecs_service]:-no}"
  },
  "factory": {
    "project_count": ${MANIFEST[project_count]:-1},
    "projects": ${MANIFEST[projects]:-[]}
  }
}
MANIFEST_EOF

    log_ok "Manifest written to ~/.kiro/fde-manifest.json"
}

# ─── SUMMARY ────────────────────────────────────────────────────
print_summary() {
    echo ""
    echo "═══════════════════════════════════════════════════════════"
    echo " Pre-Flight Report"
    echo "═══════════════════════════════════════════════════════════"
    echo -e " ${GREEN}Passed${NC}: $PASS"
    echo -e " ${RED}Issues${NC}: $FAIL"
    echo -e " ${YELLOW}Warnings${NC}: $WARN"
    echo ""

    if [ "$FAIL" -gt 0 ]; then
        echo -e " ${YELLOW}ATTENTION:${NC} $FAIL items need your attention before proceeding."
        echo ""
        echo " The manifest was still written — you can fix issues and re-run,"
        echo " or proceed if the missing items are not needed for your setup."
        echo ""
        echo " To re-run after fixing:"
        echo "   bash scripts/pre-flight-fde.sh"
        echo ""
        echo " To proceed anyway (issues will surface in validate-deploy):"
        echo "   bash scripts/validate-deploy-fde.sh"
        echo ""
    elif [ "$WARN" -gt 0 ]; then
        echo -e " ${GREEN}READY:${NC} $WARN optional items flagged. You can proceed."
        echo ""
        echo " Next step:"
        echo "   bash scripts/validate-deploy-fde.sh"
        echo ""
    else
        echo -e " ${GREEN}ALL CLEAR:${NC} Environment is fully ready."
        echo ""
        echo " Next step:"
        echo "   bash scripts/validate-deploy-fde.sh"
        echo ""
    fi
}

# ─── MAIN ───────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo " Forward Deployed Engineer — Pre-Flight Validation"
echo " Date: $(date '+%Y-%m-%d %H:%M:%S')"
echo " System: $(uname -s) $(uname -m)"
echo "═══════════════════════════════════════════════════════════"

check_core_tools
check_credentials
check_kiro
collect_config
write_manifest
print_summary
