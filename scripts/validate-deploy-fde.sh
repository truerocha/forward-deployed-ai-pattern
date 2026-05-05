#!/usr/bin/env bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════════
# Forward Deployed Engineer — Deployment Validation
# ═══════════════════════════════════════════════════════════════════
#
# Purpose: Validates all resources needed to deploy the Code Factory:
#          - Control Plane: Kiro steerings, hooks, specs structure
#          - Data Plane: ALM platforms (GitHub/Asana/GitLab) API access
#          - FDE Plane: MCP servers, factory template, global laws
#
# Prereq:  Run pre-flight-fde.sh first (generates ~/.kiro/fde-manifest.json)
# Usage:   bash scripts/validate-deploy-fde.sh
# Output:  ~/.kiro/fde-deploy-report.md (human-readable validation report)
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
REPORT_LINES=()

log_ok()   { echo -e "  ${GREEN}✓${NC} $1"; ((PASS++)); REPORT_LINES+=("✓ $1"); }
log_fail() { echo -e "  ${RED}✗${NC} $1"; ((FAIL++)); REPORT_LINES+=("✗ $1"); }
log_warn() { echo -e "  ${YELLOW}⚠${NC} $1"; ((WARN++)); REPORT_LINES+=("⚠ $1"); }
log_head() { echo -e "\n${CYAN}── $1 ──${NC}"; REPORT_LINES+=("" "## $1"); }
log_fix()  { echo -e "  ${BOLD}  → Fix:${NC} $1"; REPORT_LINES+=("  → Fix: $1"); }

# Helper: run aws CLI with optional --profile from manifest
aws_cmd() {
    local PROFILE
    PROFILE=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('credentials',{}).get('aws_profile',''))" 2>/dev/null || echo "")
    if [ -n "$PROFILE" ]; then
        aws --profile "$PROFILE" "$@"
    else
        aws "$@"
    fi
}

# ─── LOAD MANIFEST ──────────────────────────────────────────────
load_manifest() {
    MANIFEST_PATH="$HOME/.kiro/fde-manifest.json"
    if [ ! -f "$MANIFEST_PATH" ]; then
        echo -e "${RED}ERROR:${NC} Manifest not found at $MANIFEST_PATH"
        echo "Run pre-flight-fde.sh first:"
        echo "  bash scripts/pre-flight-fde.sh"
        exit 1
    fi

    MANIFEST_JSON=$(cat "$MANIFEST_PATH")
    log_ok "Manifest loaded from $MANIFEST_PATH"

    PROJECT_COUNT=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['factory']['project_count'])" 2>/dev/null || echo "0")
    TEMPLATE_PATH=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['kiro']['template_path'])" 2>/dev/null || echo "missing")
    GH_CONFIGURED=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['credentials']['github'])" 2>/dev/null || echo "False")
    AS_CONFIGURED=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['credentials']['asana'])" 2>/dev/null || echo "False")
    GL_CONFIGURED=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['credentials']['gitlab'])" 2>/dev/null || echo "False")
}

# ─── CONTROL PLANE: Kiro + Hooks + Steerings ────────────────────
validate_control_plane() {
    log_head "Control Plane (Kiro Infrastructure)"

    if [ "$TEMPLATE_PATH" != "missing" ] && [ -d "$TEMPLATE_PATH/.kiro" ]; then
        log_ok "Factory template: $TEMPLATE_PATH"

        REQUIRED_HOOKS=(
            "fde-adversarial-gate"
            "fde-circuit-breaker"
            "fde-dor-gate"
            "fde-dod-gate"
            "fde-test-immutability"
            "fde-pipeline-validation"
            "fde-enterprise-backlog"
            "fde-enterprise-release"
            "fde-work-intake"
        )

        HOOKS_FOUND=0
        HOOKS_MISSING=0
        for hook in "${REQUIRED_HOOKS[@]}"; do
            if [ -f "$TEMPLATE_PATH/.kiro/hooks/${hook}.kiro.hook" ]; then
                ((HOOKS_FOUND++))
            else
                log_fail "Missing hook: ${hook}.kiro.hook"
                ((HOOKS_MISSING++))
            fi
        done

        if [ "$HOOKS_MISSING" -eq 0 ]; then
            log_ok "All $HOOKS_FOUND required hooks present"
        fi

        if [ -f "$TEMPLATE_PATH/.kiro/steering/fde.md" ]; then
            log_ok "FDE steering template present"
        else
            log_fail "Missing: .kiro/steering/fde.md"
        fi

        if [ -f "$TEMPLATE_PATH/.kiro/steering/fde-enterprise.md" ]; then
            log_ok "Enterprise steering template present"
        else
            log_warn "Missing: .kiro/steering/fde-enterprise.md (optional)"
        fi

        if [ -f "$TEMPLATE_PATH/docs/global-steerings/agentic-tdd-mandate.md" ]; then
            log_ok "Global steering: agentic-tdd-mandate.md"
        else
            log_fail "Missing global steering: agentic-tdd-mandate.md"
        fi

        if [ -f "$TEMPLATE_PATH/docs/global-steerings/adversarial-protocol.md" ]; then
            log_ok "Global steering: adversarial-protocol.md"
        else
            log_fail "Missing global steering: adversarial-protocol.md"
        fi
    else
        log_fail "Factory template not found or incomplete"
    fi

    if [ -f "$TEMPLATE_PATH/docs/templates/canonical-task-schema.yaml" ]; then
        log_ok "Canonical task schema present"
    else
        log_warn "Missing: docs/templates/canonical-task-schema.yaml"
    fi

    for platform in github asana gitlab; do
        if [ -f "$TEMPLATE_PATH/docs/templates/task-template-${platform}.md" ]; then
            log_ok "Task template: ${platform}"
        else
            log_warn "Missing task template: ${platform}"
        fi
    done

    for script in provision-workspace.sh validate-alm-api.sh pre-flight-fde.sh; do
        if [ -f "$TEMPLATE_PATH/scripts/$script" ]; then
            log_ok "Script: $script"
        else
            log_fail "Missing script: $script"
        fi
    done
}

# ─── DATA PLANE: ALM Platforms ──────────────────────────────────
validate_data_plane() {
    log_head "Data Plane (ALM Platforms)"

    NEEDS_GITHUB=false
    NEEDS_ASANA=false
    NEEDS_GITLAB=false

    for i in $(seq 0 $((PROJECT_COUNT - 1))); do
        ALM=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['factory']['projects'][$i]['alm'])" 2>/dev/null || echo "github")
        case "$ALM" in
            github) NEEDS_GITHUB=true ;;
            asana)  NEEDS_ASANA=true ;;
            gitlab) NEEDS_GITLAB=true ;;
        esac
    done

    # GitHub
    if [ "$NEEDS_GITHUB" = true ]; then
        if [ "$GH_CONFIGURED" = "True" ]; then
            HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
                -H "Authorization: Bearer $GITHUB_TOKEN" \
                -H "Accept: application/vnd.github+json" \
                https://api.github.com/user 2>/dev/null || echo "000")

            if [ "$HTTP_CODE" = "200" ]; then
                GH_USER=$(curl -s \
                    -H "Authorization: Bearer $GITHUB_TOKEN" \
                    -H "Accept: application/vnd.github+json" \
                    https://api.github.com/user | python3 -c "import sys,json; print(json.load(sys.stdin).get('login','unknown'))" 2>/dev/null || echo "unknown")
                log_ok "GitHub API: authenticated as $GH_USER"

                for i in $(seq 0 $((PROJECT_COUNT - 1))); do
                    ALM=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['factory']['projects'][$i]['alm'])" 2>/dev/null || echo "")
                    REPO=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['factory']['projects'][$i]['repo'])" 2>/dev/null || echo "")
                    PROJ_NAME=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['factory']['projects'][$i]['name'])" 2>/dev/null || echo "")
                    PROJ_TYPE=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['factory']['projects'][$i]['type'])" 2>/dev/null || echo "")

                    if [ "$ALM" = "github" ] && [ -n "$REPO" ]; then
                        REPO_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
                            -H "Authorization: Bearer $GITHUB_TOKEN" \
                            -H "Accept: application/vnd.github+json" \
                            "https://api.github.com/repos/$REPO" 2>/dev/null || echo "000")
                        if [ "$REPO_CODE" = "200" ]; then
                            log_ok "GitHub repo accessible: $REPO ($PROJ_NAME)"
                        else
                            log_fail "GitHub repo not accessible: $REPO (HTTP $REPO_CODE)"
                        fi
                    elif [ "$ALM" = "github" ] && [ -z "$REPO" ] && [ "$PROJ_TYPE" = "greenfield" ]; then
                        log_ok "GitHub: $PROJ_NAME is greenfield — repo will be created"
                    fi
                done
            else
                log_fail "GitHub API returned HTTP $HTTP_CODE"
            fi
        else
            log_fail "GitHub token not configured but projects require it"
        fi
    else
        log_warn "No projects use GitHub — skipping"
    fi

    # Asana
    if [ "$NEEDS_ASANA" = true ]; then
        if [ "$AS_CONFIGURED" = "True" ]; then
            HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
                -H "Authorization: Bearer $ASANA_ACCESS_TOKEN" \
                https://app.asana.com/api/1.0/users/me 2>/dev/null || echo "000")
            if [ "$HTTP_CODE" = "200" ]; then
                ASANA_USER=$(curl -s \
                    -H "Authorization: Bearer $ASANA_ACCESS_TOKEN" \
                    https://app.asana.com/api/1.0/users/me | python3 -c "import sys,json; print(json.load(sys.stdin).get('data',{}).get('name','unknown'))" 2>/dev/null || echo "unknown")
                log_ok "Asana API: authenticated as $ASANA_USER"
            else
                log_fail "Asana API returned HTTP $HTTP_CODE"
            fi
        else
            log_fail "Asana token not configured but projects require it"
        fi
    else
        log_warn "No projects use Asana — skipping"
    fi

    # GitLab
    if [ "$NEEDS_GITLAB" = true ]; then
        if [ "$GL_CONFIGURED" = "True" ]; then
            GITLAB_API="${GITLAB_URL:-https://gitlab.com}"
            HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
                -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
                "$GITLAB_API/api/v4/user" 2>/dev/null || echo "000")
            if [ "$HTTP_CODE" = "200" ]; then
                GL_USER=$(curl -s \
                    -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
                    "$GITLAB_API/api/v4/user" | python3 -c "import sys,json; print(json.load(sys.stdin).get('username','unknown'))" 2>/dev/null || echo "unknown")
                log_ok "GitLab API: authenticated as $GL_USER"
            else
                log_fail "GitLab API returned HTTP $HTTP_CODE"
            fi
        else
            log_fail "GitLab token not configured but projects require it"
        fi
    else
        log_warn "No projects use GitLab — skipping"
    fi
}

# ─── FDE PLANE: MCP + Agent Readiness ───────────────────────────
validate_fde_plane() {
    log_head "FDE Plane (Agent Infrastructure)"

    if [ -f "$TEMPLATE_PATH/.kiro/settings/mcp.json" ]; then
        log_ok "MCP config template present"

        if python3 -c "import json; json.load(open('$TEMPLATE_PATH/.kiro/settings/mcp.json'))" 2>/dev/null; then
            log_ok "MCP config is valid JSON"
        else
            log_fail "MCP config is invalid JSON"
        fi

        for server in github asana gitlab; do
            if python3 -c "import json; d=json.load(open('$TEMPLATE_PATH/.kiro/settings/mcp.json')); assert '$server' in d['mcpServers']" 2>/dev/null; then
                log_ok "MCP server configured: $server"
            else
                log_warn "MCP server not configured: $server"
            fi
        done
    else
        log_fail "MCP config template not found"
    fi

    HOOK_VALID=0
    HOOK_INVALID=0
    for hook_file in "$TEMPLATE_PATH"/.kiro/hooks/*.kiro.hook; do
        if [ -f "$hook_file" ]; then
            if python3 -c "import json; json.load(open('$hook_file'))" 2>/dev/null; then
                ((HOOK_VALID++))
            else
                HOOK_NAME=$(basename "$hook_file")
                log_fail "Invalid JSON: $HOOK_NAME"
                ((HOOK_INVALID++))
            fi
        fi
    done

    if [ "$HOOK_INVALID" -eq 0 ]; then
        log_ok "All $HOOK_VALID hook files are valid JSON"
    fi

    for i in $(seq 0 $((PROJECT_COUNT - 1))); do
        PROJ_PATH=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['factory']['projects'][$i]['path'])" 2>/dev/null || echo "")
        PROJ_NAME=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['factory']['projects'][$i]['name'])" 2>/dev/null || echo "")
        PARENT_DIR=$(dirname "$PROJ_PATH")

        if [ -d "$PROJ_PATH" ]; then
            log_ok "Project path exists: $PROJ_PATH ($PROJ_NAME)"
        elif [ -d "$PARENT_DIR" ] && [ -w "$PARENT_DIR" ]; then
            log_ok "Parent directory writable: $PARENT_DIR ($PROJ_NAME — will be created)"
        else
            log_fail "Cannot create project at $PROJ_PATH — parent not writable"
        fi
    done
}

# ─── CLOUD PLANE: AWS Resources ──────────────────────────────────
validate_cloud_plane() {
    DEPLOY_AWS=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('cloud',{}).get('deploy_aws','no'))" 2>/dev/null || echo "no")

    if [ "$DEPLOY_AWS" != "yes" ]; then
        log_head "Cloud Plane (AWS — Skipped)"
        log_warn "Cloud deployment not requested — local-only mode"
        return
    fi

    log_head "Cloud Plane (AWS Infrastructure)"

    AWS_REGION=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['cloud']['aws_region'])" 2>/dev/null || echo "us-east-1")
    AWS_ENV=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['cloud']['environment'])" 2>/dev/null || echo "dev")
    BEDROCK_MODEL=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['cloud']['bedrock_model'])" 2>/dev/null || echo "")

    # 1. AWS CLI + credentials
    if command -v aws &>/dev/null; then
        log_ok "AWS CLI available"
        AWS_IDENTITY=$(aws_cmd sts get-caller-identity --region "$AWS_REGION" 2>/dev/null || echo "")
        if [ -n "$AWS_IDENTITY" ]; then
            AWS_ACCOUNT=$(echo "$AWS_IDENTITY" | python3 -c "import sys,json; print(json.load(sys.stdin)['Account'])" 2>/dev/null || echo "unknown")
            log_ok "AWS authenticated: account $AWS_ACCOUNT, region $AWS_REGION"
        else
            log_fail "AWS credentials invalid or expired"
            AWS_PROFILE=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('credentials',{}).get('aws_profile',''))" 2>/dev/null || echo "")
            if [ -n "$AWS_PROFILE" ]; then
                log_fix "Run: aws sso login --profile $AWS_PROFILE"
            else
                log_fix "Run: aws configure (or aws sso login --profile <name>)"
            fi
            return
        fi
    else
        log_fail "AWS CLI not installed"
        return
    fi

    # 2. Terraform
    if command -v terraform &>/dev/null; then
        log_ok "Terraform available"
        if [ -f "$TEMPLATE_PATH/infra/terraform/main.tf" ]; then
            log_ok "Terraform IaC found at infra/terraform/"
        else
            log_fail "Terraform IaC not found at infra/terraform/main.tf"
        fi
    else
        log_fail "Terraform not installed — needed for AWS deployment"
    fi

    # 3. Docker (for building Strands agent image)
    if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
        log_ok "Docker available and running (needed for ECR push)"
    else
        log_fail "Docker not running — needed to build and push Strands agent image"
    fi

    # 4. Bedrock model access
    if [ -n "$BEDROCK_MODEL" ]; then
        BEDROCK_CHECK=$(aws_cmd bedrock list-foundation-models --region "$AWS_REGION" \
            --query "modelSummaries[?modelId=='$BEDROCK_MODEL'].modelId" \
            --output text 2>/dev/null || echo "")
        if [ -n "$BEDROCK_CHECK" ]; then
            log_ok "Bedrock model available: $BEDROCK_MODEL"
        else
            log_warn "Bedrock model $BEDROCK_MODEL not found — may need model access request"
            log_fix "Request access at: AWS Console → Bedrock → Model access"
        fi
    fi

    # 5. ECR access
    ECR_CHECK=$(aws_cmd ecr describe-repositories --region "$AWS_REGION" \
        --query "repositories[?contains(repositoryName,'fde-')].repositoryName" \
        --output text 2>/dev/null || echo "")
    if [ -n "$ECR_CHECK" ]; then
        log_ok "Existing ECR repos found: $ECR_CHECK"
    else
        log_ok "No existing FDE ECR repos — Terraform will create them"
    fi

    # 6. ECS cluster check
    ECS_CHECK=$(aws_cmd ecs list-clusters --region "$AWS_REGION" \
        --query "clusterArns[?contains(@,'fde-')]" \
        --output text 2>/dev/null || echo "")
    if [ -n "$ECS_CHECK" ]; then
        log_ok "Existing ECS cluster found"
    else
        log_ok "No existing FDE ECS cluster — Terraform will create it"
    fi
}

# ─── WRITE REPORT ───────────────────────────────────────────────
write_report() {
    REPORT_PATH="$HOME/.kiro/fde-deploy-report.md"

    {
        echo "# FDE Deployment Validation Report"
        echo ""
        echo "> Generated: $(date '+%Y-%m-%d %H:%M:%S')"
        echo "> Passed: $PASS | Failed: $FAIL | Warnings: $WARN"
        echo ""
        for line in "${REPORT_LINES[@]}"; do
            echo "$line"
        done
        echo ""
        echo "---"
        echo ""
        if [ "$FAIL" -eq 0 ]; then
            echo "## Next Step"
            echo ""
            echo "\`\`\`bash"
            echo "bash scripts/code-factory-setup.sh"
            echo "\`\`\`"
        else
            echo "## Action Required"
            echo ""
            echo "Fix $FAIL failed checks, then re-run:"
            echo ""
            echo "\`\`\`bash"
            echo "bash scripts/validate-deploy-fde.sh"
            echo "\`\`\`"
        fi
    } > "$REPORT_PATH"

    log_ok "Report written to $REPORT_PATH"
}

# ─── SUMMARY ────────────────────────────────────────────────────
print_summary() {
    echo ""
    echo "═══════════════════════════════════════════════════════════"
    echo " Deployment Validation Summary"
    echo "═══════════════════════════════════════════════════════════"
    echo -e " ${GREEN}Passed${NC}: $PASS"
    echo -e " ${RED}Failed${NC}: $FAIL"
    echo -e " ${YELLOW}Warnings${NC}: $WARN"
    echo ""

    if [ "$FAIL" -gt 0 ]; then
        echo -e " ${YELLOW}ATTENTION:${NC} $FAIL items need fixing."
        echo ""
        echo " Report: ~/.kiro/fde-deploy-report.md"
        echo ""
        echo " Fix the issues above, then re-run:"
        echo "   bash scripts/validate-deploy-fde.sh"
        echo ""
        echo " Or proceed to setup (issues will be skipped gracefully):"
        echo "   bash scripts/code-factory-setup.sh"
        echo ""
    else
        echo -e " ${GREEN}READY TO DEPLOY.${NC}"
        echo ""
        echo " Next step:"
        echo "   bash scripts/code-factory-setup.sh"
        echo ""
    fi
}

# ─── MAIN ───────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo " Forward Deployed Engineer — Deployment Validation"
echo " Date: $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════════════════════════"

load_manifest
validate_control_plane
validate_data_plane
validate_fde_plane
validate_cloud_plane
write_report
print_summary
