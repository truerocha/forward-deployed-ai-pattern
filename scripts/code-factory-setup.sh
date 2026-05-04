#!/usr/bin/env bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════════
# Forward Deployed Engineer — Code Factory Setup
# ═══════════════════════════════════════════════════════════════════
#
# Purpose: Deploys the configured Code Factory environment:
#          1. Installs global Kiro infrastructure (steerings, MCP, notes)
#          2. For each project in the manifest:
#             - Greenfield: creates repo via MCP, initializes structure
#             - Brownfield: clones repo, reads conventions before setup
#          3. Provisions each workspace with hooks, steerings, specs
#          4. Enables hooks based on engineering level
#          5. Writes factory state dashboard
#
# Prereq:  Run validate-deploy-fde.sh first (all checks must pass)
# Usage:   bash scripts/code-factory-setup.sh
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

log_ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
log_warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }
log_err()  { echo -e "  ${RED}✗${NC} $1"; }
log_head() { echo -e "\n${CYAN}══ $1 ══${NC}"; }
log_sub()  { echo -e "\n${CYAN}── $1 ──${NC}"; }
log_fix()  { echo -e "  ${BOLD}  → Fix:${NC} $1"; }

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

# Helper: get terraform env vars for AWS profile
get_tf_env() {
    local TF_PROFILE
    TF_PROFILE=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('cloud',{}).get('aws_tf_profile',''))" 2>/dev/null || echo "")
    if [ -n "$TF_PROFILE" ]; then
        echo "AWS_PROFILE=$TF_PROFILE"
    fi
}

# ─── LOAD MANIFEST ──────────────────────────────────────────────
MANIFEST_PATH="$HOME/.kiro/fde-manifest.json"
if [ ! -f "$MANIFEST_PATH" ]; then
    echo -e "${RED}ERROR:${NC} Manifest not found. Run the full pipeline:"
    echo "  1. bash scripts/pre-flight-fde.sh"
    echo "  2. bash scripts/validate-deploy-fde.sh"
    echo "  3. bash scripts/code-factory-setup.sh"
    exit 1
fi

MANIFEST_JSON=$(cat "$MANIFEST_PATH")
PROJECT_COUNT=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['factory']['project_count'])")
TEMPLATE_PATH=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['kiro']['template_path'])")

echo ""
echo "═══════════════════════════════════════════════════════════"
echo " Forward Deployed Engineer — Code Factory Setup"
echo " Date: $(date '+%Y-%m-%d %H:%M:%S')"
echo " Projects: $PROJECT_COUNT"
echo "═══════════════════════════════════════════════════════════"

# ─── STEP 1: Global Infrastructure ──────────────────────────────
setup_global() {
    log_head "Step 1: Global Infrastructure"

    bash "$TEMPLATE_PATH/scripts/provision-workspace.sh" --global

    log_ok "Global infrastructure deployed"
}

# ─── STEP 2: Project Setup ──────────────────────────────────────
setup_project() {
    local INDEX=$1
    local PROJ_NAME PROJ_TYPE PROJ_REPO PROJ_PATH PROJ_ALM PROJ_LEVEL

    PROJ_NAME=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['factory']['projects'][$INDEX]['name'])")
    PROJ_TYPE=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['factory']['projects'][$INDEX]['type'])")
    PROJ_REPO=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['factory']['projects'][$INDEX]['repo'])")
    PROJ_PATH=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['factory']['projects'][$INDEX]['path'])")
    PROJ_ALM=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['factory']['projects'][$INDEX]['alm'])")
    PROJ_LEVEL=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['factory']['projects'][$INDEX]['level'])")

    log_head "Step 2.$((INDEX + 1)): Project — $PROJ_NAME"
    echo -e "  Type: $PROJ_TYPE | ALM: $PROJ_ALM | Level: $PROJ_LEVEL"
    echo -e "  Path: $PROJ_PATH"

    # ── 2a: Get the code ────────────────────────────────────────
    log_sub "2a: Repository Setup ($PROJ_TYPE)"

    if [ "$PROJ_TYPE" = "experiment" ]; then
        setup_experiment "$PROJ_NAME" "$PROJ_PATH"
    elif [ "$PROJ_TYPE" = "greenfield" ]; then
        setup_greenfield "$PROJ_NAME" "$PROJ_REPO" "$PROJ_PATH" "$PROJ_ALM"
    else
        setup_brownfield "$PROJ_NAME" "$PROJ_REPO" "$PROJ_PATH"
    fi

    # ── 2b: Provision workspace ─────────────────────────────────
    log_sub "2b: Workspace Provisioning"

    mkdir -p "$PROJ_PATH/.kiro"/{steering,hooks,specs/holdout,notes/project,notes/archive,meta,settings}
    log_ok "Directory structure created"

    cp "$TEMPLATE_PATH"/.kiro/hooks/*.kiro.hook "$PROJ_PATH/.kiro/hooks/" 2>/dev/null || true
    HOOK_COUNT=$(ls "$PROJ_PATH"/.kiro/hooks/*.kiro.hook 2>/dev/null | wc -l | tr -d ' ')
    log_ok "Hooks copied: $HOOK_COUNT"

    cp "$TEMPLATE_PATH"/.kiro/steering/*.md "$PROJ_PATH/.kiro/steering/" 2>/dev/null || true
    log_ok "Steerings copied"

    mkdir -p "$PROJ_PATH/docs/templates"
    cp "$TEMPLATE_PATH"/docs/templates/task-template-*.md "$PROJ_PATH/docs/templates/" 2>/dev/null || true
    cp "$TEMPLATE_PATH"/docs/templates/canonical-task-schema.yaml "$PROJ_PATH/docs/templates/" 2>/dev/null || true
    log_ok "Task templates copied"

    for tmpl in specs/WORKING_MEMORY.md notes/README.md meta/feedback.md meta/refinement-log.md; do
        if [ -f "$TEMPLATE_PATH/.kiro/$tmpl" ]; then
            cp "$TEMPLATE_PATH/.kiro/$tmpl" "$PROJ_PATH/.kiro/$tmpl"
        fi
    done
    log_ok "Templates copied"

    cp "$TEMPLATE_PATH/.kiro/settings/mcp.json" "$PROJ_PATH/.kiro/settings/mcp.json"
    configure_mcp "$PROJ_PATH/.kiro/settings/mcp.json" "$PROJ_ALM"
    log_ok "MCP config deployed (primary: $PROJ_ALM)"

    # ── 2c: Enable hooks by level ──────────────────────────────
    log_sub "2c: Hook Activation (Level $PROJ_LEVEL)"
    enable_hooks_for_level "$PROJ_PATH" "$PROJ_LEVEL"

    # ── 2d: Brownfield convention scan ──────────────────────────
    if [ "$PROJ_TYPE" = "brownfield" ]; then
        log_sub "2d: Brownfield Convention Scan"
        scan_conventions "$PROJ_PATH" "$PROJ_NAME"
    fi

    # ── 2e: .gitignore ──────────────────────────────────────────
    log_sub "2e: Git Configuration"
    GITIGNORE_ENTRIES=(
        ".kiro/notes/"
        ".kiro/meta/feedback.md"
        ".kiro/settings/mcp.json"
        ".kiro/specs/WORKING_MEMORY.md"
        ".kiro/specs/holdout/"
    )

    touch "$PROJ_PATH/.gitignore"
    for entry in "${GITIGNORE_ENTRIES[@]}"; do
        if ! grep -qF "$entry" "$PROJ_PATH/.gitignore" 2>/dev/null; then
            echo "$entry" >> "$PROJ_PATH/.gitignore"
        fi
    done
    log_ok ".gitignore updated"

    log_ok "Project $PROJ_NAME fully provisioned"
}

# ─── EXPERIMENT: Local-only project ──────────────────────────────
setup_experiment() {
    local NAME=$1 PATH_=$2

    mkdir -p "$PATH_"

    if [ ! -d "$PATH_/.git" ]; then
        git -C "$PATH_" init
    fi
    log_ok "Experiment repo initialized (local git only, no remote)"

    if [ ! -f "$PATH_/requirements.md" ]; then
        cat > "$PATH_/requirements.md" << 'REQ'
# Experiment Requirements

> This is an experiment / POC project. Local-only, no remote repo.
> The FDE agent will read this file to understand what to build.

## Goal
<!-- What are you experimenting with? -->

## Technical Stack
<!-- Language, framework, tools -->

## Success Criteria
<!-- How do you know the experiment worked? -->
REQ
        log_ok "Created requirements.md (experiment template)"
    fi
}

# ─── GREENFIELD: Create new repo ────────────────────────────────
setup_greenfield() {
    local NAME=$1 REPO=$2 PATH_=$3 ALM=$4

    mkdir -p "$PATH_"

    if [ -n "$REPO" ]; then
        if [ ! -d "$PATH_/.git" ]; then
            git clone "$REPO" "$PATH_" 2>/dev/null || {
                git -C "$PATH_" init
                git -C "$PATH_" remote add origin "$REPO" 2>/dev/null || true
                log_warn "Repo appears empty — initialized locally"
            }
        fi
        log_ok "Greenfield repo cloned: $REPO"
    else
        if [ ! -d "$PATH_/.git" ]; then
            git -C "$PATH_" init
        fi
        log_ok "Greenfield repo initialized locally"
        log_warn "No remote repo — agent will need requirements.md to create one"
    fi

    if [ ! -f "$PATH_/requirements.md" ]; then
        cat > "$PATH_/requirements.md" << 'REQ'
# Project Requirements

> This is a greenfield project. The FDE agent will read this file
> to understand what needs to be built.
>
> Replace this content with your project requirements.

## Overview
<!-- What is this project? What problem does it solve? -->

## Technical Stack
<!-- Language, framework, database, infrastructure -->

## Key Features
<!-- List the features to build, in priority order -->

## Constraints
<!-- Non-functional requirements, compliance, performance targets -->
REQ
        log_ok "Created requirements.md template (edit before starting agent)"
    fi
}

# ─── BROWNFIELD: Clone existing repo ────────────────────────────
setup_brownfield() {
    local NAME=$1 REPO=$2 PATH_=$3

    if [ -d "$PATH_/.git" ]; then
        log_ok "Brownfield repo already exists at $PATH_"
        git -C "$PATH_" pull --ff-only 2>/dev/null || log_warn "Could not pull latest (check branch state)"
    elif [ -n "$REPO" ]; then
        git clone "$REPO" "$PATH_"
        log_ok "Brownfield repo cloned: $REPO"
    else
        log_err "Brownfield project requires a repo URL or existing local path"
        return 1
    fi
}

# ─── BROWNFIELD: Scan conventions ────────────────────────────────
scan_conventions() {
    local PATH_=$1 NAME=$2
    local CONVENTIONS_FILE="$PATH_/.kiro/notes/project/conventions-$NAME.md"

    {
        echo "# Conventions Scan — $NAME"
        echo ""
        echo "> Auto-generated by code-factory-setup.sh"
        echo "> Date: $(date '+%Y-%m-%d %H:%M:%S')"
        echo "> Status: UNVERIFIED — Agent must read these before any task"
        echo ""

        echo "## Languages Detected"
        echo ""
        for ext in py js ts jsx tsx java go rs rb php cs; do
            COUNT=$(find "$PATH_" -name "*.${ext}" -not -path "*/node_modules/*" -not -path "*/.git/*" -not -path "*/venv/*" 2>/dev/null | wc -l | tr -d ' ')
            if [ "$COUNT" -gt 0 ]; then
                echo "- .$ext: $COUNT files"
            fi
        done
        echo ""

        echo "## Package Managers / Build Tools"
        echo ""
        for f in package.json pom.xml build.gradle Cargo.toml go.mod Gemfile requirements.txt pyproject.toml Makefile CMakeLists.txt; do
            if [ -f "$PATH_/$f" ]; then
                echo "- $f"
            fi
        done
        echo ""

        echo "## Test Infrastructure"
        echo ""
        if [ -f "$PATH_/package.json" ]; then
            TEST_CMD=$(python3 -c "import json; d=json.load(open('$PATH_/package.json')); print(d.get('scripts',{}).get('test','(none)'))" 2>/dev/null || echo "(none)")
            echo "- npm test: $TEST_CMD"
        fi
        if [ -f "$PATH_/pyproject.toml" ] || [ -f "$PATH_/setup.cfg" ]; then
            echo "- Python project (pytest likely)"
        fi
        for f in jest.config.js jest.config.ts vitest.config.ts .mocharc.yml pytest.ini conftest.py; do
            if [ -f "$PATH_/$f" ]; then
                echo "- Test config: $f"
            fi
        done
        echo ""

        echo "## Linters / Formatters"
        echo ""
        for f in .eslintrc.js .eslintrc.json eslint.config.js .prettierrc .prettierrc.json ruff.toml .flake8 .rubocop.yml .golangci.yml; do
            if [ -f "$PATH_/$f" ]; then
                echo "- $f"
            fi
        done
        echo ""

        echo "## CI/CD"
        echo ""
        if [ -d "$PATH_/.github/workflows" ]; then
            echo "- GitHub Actions"
            for wf in "$PATH_"/.github/workflows/*.yml "$PATH_"/.github/workflows/*.yaml; do
                if [ -f "$wf" ]; then
                    echo "  - $(basename "$wf")"
                fi
            done
        fi
        if [ -f "$PATH_/.gitlab-ci.yml" ]; then
            echo "- GitLab CI"
        fi
        if [ -f "$PATH_/Jenkinsfile" ]; then
            echo "- Jenkins"
        fi
        echo ""

        echo "## Containerization"
        echo ""
        if [ -f "$PATH_/Dockerfile" ]; then
            echo "- Dockerfile present"
        fi
        if [ -f "$PATH_/docker-compose.yml" ] || [ -f "$PATH_/docker-compose.yaml" ]; then
            echo "- Docker Compose present"
        fi
        echo ""

        echo "---"
        echo ""
        echo "## Agent Instructions"
        echo ""
        echo "Before starting any task on this brownfield project:"
        echo "1. Read this conventions file"
        echo "2. Match existing code patterns (indentation, naming, imports)"
        echo "3. Use the project's existing test framework and commands"
        echo "4. Follow the project's existing linter configuration"
        echo "5. Do NOT introduce new libraries or frameworks without human approval"

    } > "$CONVENTIONS_FILE"

    log_ok "Conventions scan written to .kiro/notes/project/conventions-$NAME.md"
    log_warn "Agent MUST read conventions before any brownfield task"
}

# ─── CONFIGURE MCP ──────────────────────────────────────────────
configure_mcp() {
    local MCP_FILE=$1 ALM=$2

    python3 << PYEOF
import json

with open("$MCP_FILE") as f:
    config = json.load(f)

for server_name, server_config in config["mcpServers"].items():
    if server_name == "$ALM":
        server_config["disabled"] = False
    if server_name == "github":
        server_config["disabled"] = False

with open("$MCP_FILE", "w") as f:
    json.dump(config, f, indent=2)
    f.write("\n")
PYEOF
}

# ─── ENABLE HOOKS BY LEVEL ──────────────────────────────────────
enable_hooks_for_level() {
    local PATH_=$1 LEVEL=$2

    L2_HOOKS=(
        "fde-adversarial-gate"
        "fde-test-immutability"
        "fde-circuit-breaker"
    )

    L3_HOOKS=(
        "fde-dor-gate"
        "fde-dod-gate"
        "fde-pipeline-validation"
        "fde-enterprise-backlog"
        "fde-enterprise-docs"
        "fde-enterprise-release"
        "fde-ship-readiness"
        "fde-notes-consolidate"
        "fde-prompt-refinement"
        "fde-work-intake"
    )

    L4_HOOKS=(
        "fde-alternative-exploration"
    )

    ENABLE_LIST=()
    ENABLE_LIST+=("${L2_HOOKS[@]}")

    if [ "$LEVEL" = "L3" ] || [ "$LEVEL" = "L4" ]; then
        ENABLE_LIST+=("${L3_HOOKS[@]}")
    fi

    if [ "$LEVEL" = "L4" ]; then
        ENABLE_LIST+=("${L4_HOOKS[@]}")
    fi

    ENABLED_COUNT=0
    for hook_name in "${ENABLE_LIST[@]}"; do
        HOOK_FILE="$PATH_/.kiro/hooks/${hook_name}.kiro.hook"
        if [ -f "$HOOK_FILE" ]; then
            python3 << PYEOF
import json
with open("$HOOK_FILE") as f:
    hook = json.load(f)
hook["enabled"] = True
with open("$HOOK_FILE", "w") as f:
    json.dump(hook, f, indent=2)
    f.write("\n")
PYEOF
            ((ENABLED_COUNT++))
        fi
    done

    log_ok "Enabled $ENABLED_COUNT hooks for level $LEVEL"
    echo -e "    L2 (core):       ${L2_HOOKS[*]}"
    if [ "$LEVEL" = "L3" ] || [ "$LEVEL" = "L4" ]; then
        echo -e "    L3 (enterprise): ${L3_HOOKS[*]}"
    fi
    if [ "$LEVEL" = "L4" ]; then
        echo -e "    L4 (autonomous): ${L4_HOOKS[*]}"
    fi
}

# ─── STEP 3: AWS Cloud Deployment ────────────────────────────────
deploy_cloud() {
    DEPLOY_AWS=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('cloud',{}).get('deploy_aws','no'))" 2>/dev/null || echo "no")

    if [ "$DEPLOY_AWS" != "yes" ]; then
        log_head "Step 3: Cloud Deployment (Skipped — local-only mode)"
        return
    fi

    log_head "Step 3: AWS Cloud Deployment"

    AWS_REGION=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['cloud']['aws_region'])")
    AWS_ENV=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['cloud']['environment'])")
    BEDROCK_MODEL=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['cloud']['bedrock_model'])")
    ENABLE_AC=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['cloud']['enable_agentcore'])")
    ENABLE_ECS=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['cloud']['enable_ecs_service'])")

    echo -e "  Region: $AWS_REGION | Env: $AWS_ENV | Model: $BEDROCK_MODEL"

    log_sub "3a: Terraform Configuration"

    TFVARS_FILE="$TEMPLATE_PATH/infra/terraform/factory.tfvars"
    cat > "$TFVARS_FILE" << TFVARS
aws_region          = "$AWS_REGION"
environment         = "$AWS_ENV"
bedrock_model_id    = "$BEDROCK_MODEL"
enable_agentcore    = $([ "$ENABLE_AC" = "yes" ] && echo "true" || echo "false")
enable_ecs_service  = $([ "$ENABLE_ECS" = "yes" ] && echo "true" || echo "false")
agent_cpu           = "1024"
agent_memory        = "2048"
agent_desired_count = 1
vpc_cidr            = "10.0.0.0/16"
TFVARS

    log_ok "Generated factory.tfvars"

    log_sub "3b: Terraform Init & Plan"

    TF_DIR="$TEMPLATE_PATH/infra/terraform"
    TF_ENV=$(get_tf_env)

    echo -e "  ${YELLOW}⚠${NC} About to provision AWS resources. Review the plan below."
    if [ -n "$TF_ENV" ]; then
        echo -e "  Using AWS profile for Terraform: $(echo "$TF_ENV" | cut -d= -f2)"
    fi
    echo ""

    env $TF_ENV terraform -chdir="$TF_DIR" init -input=false 2>&1 | tail -5
    log_ok "Terraform initialized"

    env $TF_ENV terraform -chdir="$TF_DIR" plan -var-file="factory.tfvars" -out=tfplan 2>&1 | tail -20

    echo ""
    read -rp "  Apply this plan? [yes/no]: " APPLY_CONFIRM
    if [ "$APPLY_CONFIRM" != "yes" ]; then
        log_warn "Terraform apply skipped — run manually:"
        echo "    cd $TF_DIR && terraform apply tfplan"
        return
    fi

    log_sub "3c: Terraform Apply"

    env $TF_ENV terraform -chdir="$TF_DIR" apply tfplan
    log_ok "AWS infrastructure deployed"

    log_sub "3d: Docker Build & ECR Push"

    ECR_URL=$(env $TF_ENV terraform -chdir="$TF_DIR" output -raw ecr_repository_url 2>/dev/null || echo "")
    if [ -n "$ECR_URL" ]; then
        aws_cmd ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_URL"
        log_ok "ECR login successful"

        docker build -t fde-strands-agent:latest -f "$TEMPLATE_PATH/infra/docker/Dockerfile.strands-agent" "$TEMPLATE_PATH"
        log_ok "Docker image built"

        docker tag fde-strands-agent:latest "$ECR_URL:latest"
        docker push "$ECR_URL:latest"
        log_ok "Image pushed to ECR: $ECR_URL:latest"
    else
        log_warn "Could not get ECR URL from Terraform output — push manually"
    fi

    log_sub "3e: Secrets Manager"

    SECRETS_ARN=$(env $TF_ENV terraform -chdir="$TF_DIR" output -raw secrets_arn 2>/dev/null || echo "")
    if [ -n "$SECRETS_ARN" ]; then
        SECRETS_JSON=$(python3 -c "
import json, os
secrets = {}
if os.environ.get('GITHUB_TOKEN'): secrets['GITHUB_TOKEN'] = os.environ['GITHUB_TOKEN']
if os.environ.get('ASANA_ACCESS_TOKEN'): secrets['ASANA_ACCESS_TOKEN'] = os.environ['ASANA_ACCESS_TOKEN']
if os.environ.get('GITLAB_TOKEN'): secrets['GITLAB_TOKEN'] = os.environ['GITLAB_TOKEN']
print(json.dumps(secrets))
")

        aws_cmd secretsmanager put-secret-value \
            --secret-id "$SECRETS_ARN" \
            --secret-string "$SECRETS_JSON" \
            --region "$AWS_REGION" 2>/dev/null
        log_ok "ALM tokens stored in Secrets Manager"
    else
        log_warn "Could not get Secrets ARN — store tokens manually"
    fi

    log_ok "AWS cloud deployment complete"
}

# ─── STEP 4: Factory State Dashboard ────────────────────────────
write_factory_state() {
    log_head "Step 4: Factory State Dashboard"

    STATE_FILE="$HOME/.kiro/factory-state.md"

    {
        echo "# Factory State — Updated by code-factory-setup.sh"
        echo ""
        echo "> Generated: $(date '+%Y-%m-%d %H:%M:%S')"
        echo "> Projects: $PROJECT_COUNT"
        echo ""
        echo "| # | Project | Type | ALM | Level | Path | Status |"
        echo "|---|---------|------|-----|-------|------|--------|"

        for i in $(seq 0 $((PROJECT_COUNT - 1))); do
            NAME=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['factory']['projects'][$i]['name'])")
            TYPE=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['factory']['projects'][$i]['type'])")
            ALM=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['factory']['projects'][$i]['alm'])")
            LEVEL=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['factory']['projects'][$i]['level'])")
            PROJ_PATH=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['factory']['projects'][$i]['path'])")
            echo "| $((i + 1)) | $NAME | $TYPE | $ALM | $LEVEL | $PROJ_PATH | Ready |"
        done

        echo ""
        echo "## Pending Human Actions"
        echo ""

        for i in $(seq 0 $((PROJECT_COUNT - 1))); do
            NAME=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['factory']['projects'][$i]['name'])")
            TYPE=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['factory']['projects'][$i]['type'])")

            echo "### $NAME"
            if [ "$TYPE" = "greenfield" ]; then
                echo "- [ ] Edit requirements.md with project requirements"
                echo "- [ ] Agent reads requirements.md to create/update repo"
            else
                echo "- [ ] Review .kiro/notes/project/conventions-$NAME.md"
            fi
            echo "- [ ] Customize .kiro/steering/fde.md for this project"
            echo "- [ ] Write first spec in .kiro/specs/"
            echo "- [ ] Create board items using task templates from docs/templates/"
            echo ""
        done

        echo "## Daily Rhythm"
        echo ""
        echo "1. Move items to 'In Progress' on your board"
        echo "2. Trigger \`fde-work-intake\` hook in Kiro"
        echo "3. Agent scans boards, creates specs, starts pipeline"
        echo "4. Review completion reports and MRs"
        echo "5. Approve and merge"

    } > "$STATE_FILE"

    log_ok "Factory state written to $STATE_FILE"
}

# ─── SUMMARY ────────────────────────────────────────────────────
print_summary() {
    echo ""
    echo "═══════════════════════════════════════════════════════════"
    echo " Code Factory Setup Complete"
    echo "═══════════════════════════════════════════════════════════"
    echo ""
    echo " Projects deployed: $PROJECT_COUNT"
    echo " Factory state: ~/.kiro/factory-state.md"
    echo " Deploy report: ~/.kiro/fde-deploy-report.md"
    echo ""
    echo -e " ${BOLD}Next steps for each project:${NC}"
    echo ""

    for i in $(seq 0 $((PROJECT_COUNT - 1))); do
        NAME=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['factory']['projects'][$i]['name'])")
        TYPE=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['factory']['projects'][$i]['type'])")
        PROJ_PATH=$(echo "$MANIFEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['factory']['projects'][$i]['path'])")

        echo -e "  ${CYAN}$NAME${NC} ($TYPE):"
        if [ "$TYPE" = "greenfield" ]; then
            echo "    1. Edit $PROJ_PATH/requirements.md"
            echo "    2. Open in Kiro: #fde Read requirements.md and create the repo"
        else
            echo "    1. Review $PROJ_PATH/.kiro/notes/project/conventions-$NAME.md"
            echo "    2. Customize $PROJ_PATH/.kiro/steering/fde.md"
        fi
        echo "    3. Write first spec in $PROJ_PATH/.kiro/specs/"
        echo "    4. In Kiro: #fde Execute the spec"
        echo ""
    done

    echo -e " ${GREEN}The factory is ready. Write specs. Ship code.${NC}"
    echo ""
}

# ─── MAIN ───────────────────────────────────────────────────────

setup_global

for i in $(seq 0 $((PROJECT_COUNT - 1))); do
    setup_project "$i"
done

deploy_cloud

write_factory_state

print_summary
