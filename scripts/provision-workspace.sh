#!/usr/bin/env bash
set -euo pipefail

# Forward Deployed Engineer — Workspace Provisioning Script
# Usage:
#   bash scripts/provision-workspace.sh --global    # One-time global setup
#   bash scripts/provision-workspace.sh --project   # Onboard current directory as factory workspace

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_ok()   { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_err()  { echo -e "${RED}✗${NC} $1"; }

# ─── GLOBAL SETUP ───────────────────────────────────────────────
setup_global() {
    echo ""
    echo "═══════════════════════════════════════════════════════════"
    echo " Forward Deployed Engineer — Global Factory Setup"
    echo "═══════════════════════════════════════════════════════════"
    echo ""

    # 1. Global steerings
    mkdir -p ~/.kiro/steering
    if [ -f "$SCRIPT_DIR/docs/global-steerings/agentic-tdd-mandate.md" ]; then
        cp "$SCRIPT_DIR/docs/global-steerings/agentic-tdd-mandate.md" ~/.kiro/steering/
        log_ok "Global steering: agentic-tdd-mandate.md"
    else
        log_err "Template not found: docs/global-steerings/agentic-tdd-mandate.md"
    fi

    if [ -f "$SCRIPT_DIR/docs/global-steerings/adversarial-protocol.md" ]; then
        cp "$SCRIPT_DIR/docs/global-steerings/adversarial-protocol.md" ~/.kiro/steering/
        log_ok "Global steering: adversarial-protocol.md"
    else
        log_err "Template not found: docs/global-steerings/adversarial-protocol.md"
    fi

    # 2. Global MCP config (only if not exists — don't overwrite user's config)
    mkdir -p ~/.kiro/settings
    if [ ! -f ~/.kiro/settings/mcp.json ]; then
        cp "$SCRIPT_DIR/.kiro/settings/mcp.json" ~/.kiro/settings/mcp.json
        log_ok "Global MCP config: ~/.kiro/settings/mcp.json (template — edit with your tokens)"
    else
        log_warn "Global MCP config already exists — skipping (won't overwrite)"
    fi

    # 3. Global notes
    mkdir -p ~/.kiro/notes/shared
    log_ok "Global notes directory: ~/.kiro/notes/shared/"

    # 4. Factory state
    if [ ! -f ~/.kiro/factory-state.md ]; then
        cat > ~/.kiro/factory-state.md << 'STATE'
# Factory State — Updated by Staff Engineer

| Project | Status | Spec | Progress | Blockers |
|---------|--------|------|----------|----------|
| (none)  | —      | —    | —        | —        |

## Pending Human Actions
(none)
STATE
        log_ok "Factory state: ~/.kiro/factory-state.md"
    else
        log_warn "Factory state already exists — skipping"
    fi

    echo ""
    echo "─── Verification ───"

    # Check environment variables
    if [ -n "${GITHUB_TOKEN:-}" ]; then
        log_ok "GITHUB_TOKEN is set"
    else
        log_warn "GITHUB_TOKEN not set — MCP GitHub won't work. Add to ~/.zshrc: export GITHUB_TOKEN=\"ghp_...\""
    fi

    if [ -n "${GITLAB_TOKEN:-}" ]; then
        log_ok "GITLAB_TOKEN is set"
    else
        log_warn "GITLAB_TOKEN not set — MCP GitLab won't work (optional)"
    fi

    if [ -n "${ASANA_ACCESS_TOKEN:-}" ]; then
        log_ok "ASANA_ACCESS_TOKEN is set"
    else
        log_warn "ASANA_ACCESS_TOKEN not set — MCP Asana won't work (optional)"
    fi

    echo ""
    log_ok "Global setup complete. Run with --project in each project directory to onboard."
    echo ""
}

# ─── PROJECT SETUP ──────────────────────────────────────────────
setup_project() {
    echo ""
    echo "═══════════════════════════════════════════════════════════"
    echo " Forward Deployed Engineer — Project Onboarding"
    echo " Directory: $(pwd)"
    echo "═══════════════════════════════════════════════════════════"
    echo ""

    # Check we're in a git repo
    if [ ! -d .git ]; then
        log_err "Not a git repository. Run this from the root of your project."
        exit 1
    fi

    # 1. Create directory structure
    mkdir -p .kiro/{steering,hooks,specs/holdout,notes/project,notes/archive,meta,settings}
    log_ok "Directory structure created"

    # 2. Copy hooks
    if [ -d "$SCRIPT_DIR/.kiro/hooks" ]; then
        cp "$SCRIPT_DIR"/.kiro/hooks/*.kiro.hook .kiro/hooks/ 2>/dev/null || true
        HOOK_COUNT=$(ls .kiro/hooks/*.kiro.hook 2>/dev/null | wc -l | tr -d ' ')
        log_ok "Hooks copied: $HOOK_COUNT files"
    else
        log_err "Template hooks not found at $SCRIPT_DIR/.kiro/hooks/"
    fi

    # 3. Copy steerings
    if [ -d "$SCRIPT_DIR/.kiro/steering" ]; then
        cp "$SCRIPT_DIR"/.kiro/steering/*.md .kiro/steering/ 2>/dev/null || true
        log_ok "Steerings copied"
    else
        log_err "Template steerings not found"
    fi

    # 3.5. Copy task templates
    if [ -d "$SCRIPT_DIR/docs/templates" ]; then
        mkdir -p docs/templates
        cp "$SCRIPT_DIR"/docs/templates/task-template-*.md docs/templates/ 2>/dev/null || true
        cp "$SCRIPT_DIR"/docs/templates/canonical-task-schema.yaml docs/templates/ 2>/dev/null || true
        log_ok "Task templates copied to docs/templates/"
    fi

    # 4. Copy templates
    for tmpl in specs/WORKING_MEMORY.md notes/README.md meta/feedback.md meta/refinement-log.md; do
        if [ -f "$SCRIPT_DIR/.kiro/$tmpl" ]; then
            cp "$SCRIPT_DIR/.kiro/$tmpl" ".kiro/$tmpl"
            log_ok "Template: .kiro/$tmpl"
        fi
    done

    # 5. Add to .gitignore
    GITIGNORE_ENTRIES=(
        ".kiro/notes/"
        ".kiro/meta/feedback.md"
        ".kiro/settings/mcp.json"
        ".kiro/specs/WORKING_MEMORY.md"
        ".kiro/specs/holdout/"
    )

    touch .gitignore
    for entry in "${GITIGNORE_ENTRIES[@]}"; do
        if ! grep -qF "$entry" .gitignore 2>/dev/null; then
            echo "$entry" >> .gitignore
            log_ok "Added to .gitignore: $entry"
        fi
    done

    echo ""
    echo "─── Next Steps ───"
    echo ""
    log_warn "REQUIRED: Customize .kiro/steering/fde.md for THIS project:"
    echo "    - Replace pipeline chain with your data flow"
    echo "    - Replace module boundaries with your edges"
    echo "    - Replace régua with your quality standards"
    echo "    - Replace test commands with your test infrastructure"
    echo ""
    log_warn "REQUIRED: Enable hooks for your engineering level:"
    echo "    L2: adversarial-gate, test-immutability, circuit-breaker"
    echo "    L3: All L2 + dor-gate, dod-gate, pipeline-validation, enterprise-*"
    echo "    L4: All L3 + alternative-exploration"
    echo "    Edit each .kiro.hook file: change \"enabled\": false → true"
    echo ""
    log_warn "OPTIONAL: Configure ALM platforms for board-to-factory automation:"
    echo "    1. Set environment variables (GITHUB_TOKEN, ASANA_ACCESS_TOKEN, GITLAB_TOKEN)"
    echo "    2. Run: bash scripts/validate-alm-api.sh --all"
    echo "    3. Enable MCP servers in .kiro/settings/mcp.json (set disabled: false)"
    echo "    4. Enable fde-work-intake hook for board scanning"
    echo "    5. Use task templates from docs/templates/ when creating board items"
    echo ""
    log_ok "Project onboarded. Open in Kiro IDE and type #fde to verify."
    echo ""
}

# ─── MAIN ───────────────────────────────────────────────────────
case "${1:-}" in
    --global)
        setup_global
        ;;
    --project)
        setup_project
        ;;
    *)
        echo "Usage:"
        echo "  bash scripts/provision-workspace.sh --global    # One-time global setup"
        echo "  bash scripts/provision-workspace.sh --project   # Onboard current project"
        exit 1
        ;;
esac
