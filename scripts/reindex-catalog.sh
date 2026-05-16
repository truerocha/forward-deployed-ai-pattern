#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# reindex-catalog.sh — Align code-intelligence catalog to HEAD
#
# Usage:
#   ./scripts/reindex-catalog.sh              # Index current repo
#   ./scripts/reindex-catalog.sh /path/to/repo  # Index specific path
#
# What it does:
#   1. Validates environment (Python, tree-sitter available)
#   2. Extracts components (functions, classes, methods) via AST
#   3. Builds call graph (caller/callee relationships)
#   4. Writes SQLite catalog to catalogs/catalog.db
#   5. Reports stats (components indexed, edges found)
#
# When to run:
#   - After merging a feature branch with new modules
#   - When the code-intelligence MCP reports stale results
#   - Before a reconnaissance phase that needs fresh graph data
#   - After any structural refactoring (moved/renamed modules)
#
# Dependencies:
#   - Python 3.10+
#   - sqlite3 (stdlib)
#   - ast (stdlib) — no external deps required
#
# Ref: ADR-035 (Code Intelligence Auto-Activation)
# ─────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${1:-$(cd "$SCRIPT_DIR/.." && pwd)}"
CATALOG_DIR="${REPO_ROOT}/catalogs"
CATALOG_DB="${CATALOG_DIR}/catalog.db"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
HEAD_SHA=$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo "unknown")

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Code Intelligence Reindex                                   ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Repo:    $REPO_ROOT"
echo "║  HEAD:    $HEAD_SHA"
echo "║  Catalog: $CATALOG_DB"
echo "║  Time:    $TIMESTAMP"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ─── Pre-flight ──────────────────────────────────────────────────

if ! command -v python3 &>/dev/null; then
    echo "❌ python3 not found in PATH"
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "✓ Python $PYTHON_VERSION"

mkdir -p "$CATALOG_DIR"

# ─── Backup existing catalog ────────────────────────────────────

if [ -f "$CATALOG_DB" ]; then
    BACKUP="${CATALOG_DB}.bak"
    cp "$CATALOG_DB" "$BACKUP"
    echo "✓ Backed up existing catalog → catalog.db.bak"
fi

# ─── Run indexer ─────────────────────────────────────────────────

echo ""
echo "⏳ Indexing Python modules..."
echo ""

python3 - "$REPO_ROOT" "$CATALOG_DB" "$HEAD_SHA" "$TIMESTAMP" << 'INDEXER_SCRIPT'
"""
Lightweight AST-based code intelligence indexer.

Extracts:
  - Components: functions, classes, methods with signatures
  - Call graph: function → function relationships
  - Module membership: which file owns which component
  - Docstrings: first line for quick reference

Uses only stdlib (ast, sqlite3, os, sys) — zero external deps.
"""

import ast
import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = sys.argv[1]
CATALOG_DB = sys.argv[2]
HEAD_SHA = sys.argv[3]
TIMESTAMP = sys.argv[4]

# File patterns to index
INCLUDE_DIRS = ["src", "infra/docker/agents", "infra/terraform/lambda"]
EXCLUDE_PATTERNS = [
    "__pycache__", ".git", "node_modules", ".venv", "venv",
    "dist", "build", ".pytest_cache", ".mypy_cache",
]


def should_index(path: str) -> bool:
    """Check if a file should be indexed."""
    rel = os.path.relpath(path, REPO_ROOT)
    if any(exc in rel for exc in EXCLUDE_PATTERNS):
        return False
    if not any(rel.startswith(d) for d in INCLUDE_DIRS):
        return False
    return rel.endswith(".py")


def extract_components(filepath: str) -> list:
    """Extract functions, classes, and methods from a Python file."""
    components = []
    rel_path = os.path.relpath(filepath, REPO_ROOT)

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            source = f.read()
        tree = ast.parse(source, filename=filepath)
    except (SyntaxError, UnicodeDecodeError):
        return []

    module_name = rel_path.replace("/", ".").replace(".py", "")

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            parent_class = _find_parent_class(tree, node)
            kind = "method" if parent_class else "function"
            full_name = f"{parent_class}.{node.name}" if parent_class else node.name

            components.append({
                "name": node.name,
                "full_name": full_name,
                "kind": kind,
                "module": module_name,
                "file": rel_path,
                "line": node.lineno,
                "docstring": ast.get_docstring(node) or "",
                "args": _format_args(node.args),
                "parent_class": parent_class or "",
            })

        elif isinstance(node, ast.ClassDef):
            components.append({
                "name": node.name,
                "full_name": node.name,
                "kind": "class",
                "module": module_name,
                "file": rel_path,
                "line": node.lineno,
                "docstring": ast.get_docstring(node) or "",
                "args": "",
                "parent_class": "",
            })

    return components


def extract_calls(filepath: str) -> list:
    """Extract function call relationships from a Python file."""
    calls = []
    rel_path = os.path.relpath(filepath, REPO_ROOT)

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            source = f.read()
        tree = ast.parse(source, filename=filepath)
    except (SyntaxError, UnicodeDecodeError):
        return []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            caller = node.name
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    callee = _resolve_call_name(child)
                    if callee and callee != caller:
                        calls.append({
                            "caller": caller,
                            "callee": callee,
                            "file": rel_path,
                            "line": child.lineno,
                        })

    return calls


def _find_parent_class(tree, target_node):
    """Find the parent class of a method node."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if item is target_node:
                    return node.name
    return ""


def _format_args(args):
    """Format function arguments as a string."""
    parts = []
    for arg in args.args:
        if arg.arg != "self" and arg.arg != "cls":
            parts.append(arg.arg)
    return ", ".join(parts[:5])


def _resolve_call_name(call_node):
    """Resolve the name of a function call."""
    func = call_node.func
    if isinstance(func, ast.Name):
        return func.id
    elif isinstance(func, ast.Attribute):
        return func.attr
    return ""


def create_database(db_path: str):
    """Create the SQLite catalog schema."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("DROP TABLE IF EXISTS components")
    c.execute("DROP TABLE IF EXISTS calls")
    c.execute("DROP TABLE IF EXISTS metadata")

    c.execute("""
        CREATE TABLE components (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            full_name TEXT NOT NULL,
            kind TEXT NOT NULL,
            module TEXT NOT NULL,
            file TEXT NOT NULL,
            line INTEGER,
            docstring TEXT,
            args TEXT,
            parent_class TEXT
        )
    """)

    c.execute("""
        CREATE TABLE calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            caller TEXT NOT NULL,
            callee TEXT NOT NULL,
            file TEXT NOT NULL,
            line INTEGER
        )
    """)

    c.execute("""
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    c.execute("CREATE INDEX idx_components_name ON components(name)")
    c.execute("CREATE INDEX idx_components_module ON components(module)")
    c.execute("CREATE INDEX idx_components_kind ON components(kind)")
    c.execute("CREATE INDEX idx_calls_caller ON calls(caller)")
    c.execute("CREATE INDEX idx_calls_callee ON calls(callee)")

    conn.commit()
    return conn


def main():
    py_files = []
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_PATTERNS]
        for f in files:
            filepath = os.path.join(root, f)
            if should_index(filepath):
                py_files.append(filepath)

    print(f"  Found {len(py_files)} Python files to index")

    conn = create_database(CATALOG_DB)
    cursor = conn.cursor()

    total_components = 0
    total_calls = 0

    for filepath in py_files:
        components = extract_components(filepath)
        for comp in components:
            cursor.execute(
                "INSERT INTO components (name, full_name, kind, module, file, line, docstring, args, parent_class) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (comp["name"], comp["full_name"], comp["kind"], comp["module"],
                 comp["file"], comp["line"], comp["docstring"][:200], comp["args"], comp["parent_class"]),
            )
            total_components += 1

        calls = extract_calls(filepath)
        for call in calls:
            cursor.execute(
                "INSERT INTO calls (caller, callee, file, line) VALUES (?, ?, ?, ?)",
                (call["caller"], call["callee"], call["file"], call["line"]),
            )
            total_calls += 1

    cursor.execute("INSERT INTO metadata (key, value) VALUES (?, ?)", ("head_sha", HEAD_SHA))
    cursor.execute("INSERT INTO metadata (key, value) VALUES (?, ?)", ("indexed_at", TIMESTAMP))
    cursor.execute("INSERT INTO metadata (key, value) VALUES (?, ?)", ("total_components", str(total_components)))
    cursor.execute("INSERT INTO metadata (key, value) VALUES (?, ?)", ("total_calls", str(total_calls)))
    cursor.execute("INSERT INTO metadata (key, value) VALUES (?, ?)", ("total_files", str(len(py_files))))

    conn.commit()
    conn.close()

    print(f"  Components: {total_components}")
    print(f"  Call edges: {total_calls}")
    print(f"  Files:      {len(py_files)}")
    print(f"  Catalog:    {CATALOG_DB}")


main()
INDEXER_SCRIPT

# ─── Verify ─────────────────────────────────────────────────────

echo ""
if [ -f "$CATALOG_DB" ]; then
    SIZE=$(du -h "$CATALOG_DB" | cut -f1)
    COMPONENTS=$(sqlite3 "$CATALOG_DB" "SELECT value FROM metadata WHERE key='total_components'" 2>/dev/null || echo "?")
    CALLS=$(sqlite3 "$CATALOG_DB" "SELECT value FROM metadata WHERE key='total_calls'" 2>/dev/null || echo "?")
    FILES=$(sqlite3 "$CATALOG_DB" "SELECT value FROM metadata WHERE key='total_files'" 2>/dev/null || echo "?")

    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  ✅ Reindex Complete                                         ║"
    echo "╠══════════════════════════════════════════════════════════════╣"
    echo "║  HEAD:       $HEAD_SHA"
    echo "║  Components: $COMPONENTS"
    echo "║  Call edges:  $CALLS"
    echo "║  Files:      $FILES"
    echo "║  Size:       $SIZE"
    echo "║  Path:       $CATALOG_DB"
    echo "╚══════════════════════════════════════════════════════════════╝"
else
    echo "❌ Catalog generation failed — check Python output above"
    exit 1
fi
