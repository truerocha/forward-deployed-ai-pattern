#!/usr/bin/env bash
# ─── Reindex Knowledge Graph ────────────────────────────────────────────────
# Regenerates the code-intelligence catalog (call graph + semantic index)
# after source changes. Run after any session that modifies production code.
#
# Usage:
#   ./scripts/reindex-knowledge-graph.sh [repo-path]
#
# Default: indexes the current repository root.
# Output: catalogs/catalog.db (SQLite)
#
# The indexer uses the onboarding pipeline's local mode (trigger_handler)
# which scans the workspace without cloning.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

REPO_ROOT="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
CATALOG_PATH="${REPO_ROOT}/catalogs/catalog.db"
BACKUP_PATH="${CATALOG_PATH}.bak"

echo "╭─────────────────────────────────────────────╮"
echo "│  Knowledge Graph Reindexer                  │"
echo "╰─────────────────────────────────────────────╯"
echo ""
echo "  Repo:    ${REPO_ROOT}"
echo "  Output:  ${CATALOG_PATH}"
echo ""

# Backup existing catalog
if [ -f "${CATALOG_PATH}" ]; then
    cp "${CATALOG_PATH}" "${BACKUP_PATH}"
    echo "  ✓ Backed up existing catalog → catalog.db.bak"
fi

# Run the indexer via Docker (same image used in production)
echo "  ⏳ Indexing via Docker (onboarding pipeline local mode)..."

# Use the strands-agent image which has all dependencies
docker run --rm \
    -v "${REPO_ROOT}:/workspace:ro" \
    -v "${REPO_ROOT}/catalogs:/output" \
    -w /workspace \
    -e ONBOARDING_MODE=local \
    -e CATALOG_OUTPUT=/output/catalog.db \
    --entrypoint python3 \
    785640717688.dkr.ecr.us-east-1.amazonaws.com/fde-dev-strands-agent:latest \
    -c "
import sys, os
sys.path.insert(0, '/app')
os.chdir('/workspace')

try:
    from agents.onboarding.trigger_handler import build_local_context
    from agents.onboarding.pipeline import run_scan_only

    ctx = build_local_context()
    result = run_scan_only(ctx, output_path='/output/catalog.db')
    print(f'  ✓ Indexed: {result.get(\"files\", 0)} files, {result.get(\"symbols\", 0)} symbols')
except ImportError as e:
    # Fallback: use the code_intelligence_mcp indexer directly
    print(f'  ⚠ Onboarding pipeline not available: {e}')
    print('  → Attempting direct tree-sitter scan...')
    try:
        from agents.code_intelligence_mcp import _build_catalog_from_workspace
        _build_catalog_from_workspace('/workspace', '/output/catalog.db')
        print('  ✓ Indexed via code_intelligence_mcp')
    except Exception as e2:
        print(f'  ✗ Indexing failed: {e2}')
        sys.exit(1)
except Exception as e:
    print(f'  ✗ Indexing failed: {e}')
    sys.exit(1)
" 2>&1 | grep -v "^WARNING:"

if [ -f "${CATALOG_PATH}" ]; then
    SIZE=$(du -h "${CATALOG_PATH}" | cut -f1)
    echo ""
    echo "  ✅ Knowledge graph reindexed successfully"
    echo "     Catalog: ${CATALOG_PATH} (${SIZE})"
    echo "     Staleness: cleared (HEAD is now indexed)"
else
    echo ""
    echo "  ⚠ Catalog file not found after indexing."
    echo "     Check Docker output above for errors."
    exit 1
fi
echo ""
