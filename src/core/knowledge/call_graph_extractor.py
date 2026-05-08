"""
Call Graph Extractor — AST-Based Code Structure Analysis (Activity 3.01).

Parses Python source files in an EFS workspace using the `ast` module to
extract function definitions, call relationships, and class hierarchies.
Produces a structured call graph per module and persists it to DynamoDB.

Output schema per module:
  {
    "module_path": "src/core/metrics/cost_tracker.py",
    "functions": ["record", "get_task_summary", ...],
    "classes": ["CostTracker", "TokenUsage", ...],
    "calls_to": ["boto3.resource", "logger.warning", ...],
    "called_by": [],  # populated by cross-module resolution
    "class_hierarchy": {"CostTracker": [], "TokenUsage": []},
    "imports": ["boto3", "json", "logging", ...]
  }

DynamoDB key schema:
  PK: project_id
  SK: "callgraph#{module_path}"

Ref: docs/design/fde-core-brain-development.md Section 3 (Knowledge Plane)
"""

from __future__ import annotations

import ast
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# File extensions to parse
_PYTHON_EXTENSIONS = {".py"}

# Maximum file size to parse (avoid OOM on generated files)
_MAX_FILE_SIZE_BYTES = 512_000  # 512 KB


@dataclass
class FunctionNode:
    """A function or method discovered in a module."""

    name: str
    qualified_name: str  # e.g., "ClassName.method_name"
    lineno: int
    calls: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    is_method: bool = False
    is_async: bool = False


@dataclass
class ClassNode:
    """A class discovered in a module."""

    name: str
    lineno: int
    bases: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)


@dataclass
class ModuleCallGraph:
    """Complete call graph for a single Python module."""

    module_path: str
    functions: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    calls_to: list[str] = field(default_factory=list)
    called_by: list[str] = field(default_factory=list)
    class_hierarchy: dict[str, list[str]] = field(default_factory=dict)
    imports: list[str] = field(default_factory=list)
    function_nodes: list[FunctionNode] = field(default_factory=list)
    class_nodes: list[ClassNode] = field(default_factory=list)
    extracted_at: str = ""
    line_count: int = 0

    def __post_init__(self) -> None:
        if not self.extracted_at:
            self.extracted_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "module_path": self.module_path,
            "functions": self.functions,
            "classes": self.classes,
            "calls_to": sorted(set(self.calls_to)),
            "called_by": self.called_by,
            "class_hierarchy": self.class_hierarchy,
            "imports": self.imports,
            "line_count": self.line_count,
            "extracted_at": self.extracted_at,
        }


class _CallVisitor(ast.NodeVisitor):
    """AST visitor that collects function calls within a scope."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        call_name = self._resolve_call_name(node.func)
        if call_name:
            self.calls.append(call_name)
        self.generic_visit(node)

    @staticmethod
    def _resolve_call_name(node: ast.expr) -> str:
        """Resolve a call target to a dotted name string."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parts: list[str] = [node.attr]
            current = node.value
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            return ".".join(reversed(parts))
        return ""


class CallGraphExtractor:
    """
    Extracts call graphs from Python source files in an EFS workspace.

    Usage:
        extractor = CallGraphExtractor(
            project_id="my-repo",
            workspace_path="/mnt/efs/workspaces/my-repo",
            knowledge_table="fde-knowledge-prod",
        )
        graphs = extractor.extract_all()
        extractor.persist_all(graphs)
    """

    def __init__(
        self,
        project_id: str,
        workspace_path: str,
        knowledge_table: str | None = None,
    ):
        self._project_id = project_id
        self._workspace_path = Path(workspace_path)
        self._knowledge_table = knowledge_table or os.environ.get(
            "KNOWLEDGE_TABLE", "fde-knowledge"
        )
        self._dynamodb = boto3.resource("dynamodb")

    def extract_all(self) -> list[ModuleCallGraph]:
        """
        Walk the workspace and extract call graphs for all Python files.

        Returns:
            List of ModuleCallGraph objects, one per parseable module.
        """
        graphs: list[ModuleCallGraph] = []
        start = time.time()

        for py_file in self._discover_python_files():
            graph = self.extract_module(py_file)
            if graph:
                graphs.append(graph)

        # Cross-reference: populate called_by from calls_to
        self._resolve_called_by(graphs)

        elapsed = time.time() - start
        logger.info(
            "Extracted call graphs: project=%s modules=%d elapsed=%.2fs",
            self._project_id,
            len(graphs),
            elapsed,
        )
        return graphs

    def extract_module(self, file_path: Path) -> ModuleCallGraph | None:
        """
        Extract the call graph for a single Python module.

        Args:
            file_path: Absolute path to the .py file.

        Returns:
            ModuleCallGraph or None if the file cannot be parsed.
        """
        try:
            stat = file_path.stat()
            if stat.st_size > _MAX_FILE_SIZE_BYTES:
                logger.debug("Skipping oversized file: %s", file_path)
                return None

            source = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(file_path))
        except (SyntaxError, UnicodeDecodeError, OSError) as e:
            logger.debug("Cannot parse %s: %s", file_path, e)
            return None

        relative_path = str(file_path.relative_to(self._workspace_path))
        graph = ModuleCallGraph(
            module_path=relative_path,
            line_count=len(source.splitlines()),
        )

        # Extract imports
        graph.imports = self._extract_imports(tree)

        # Extract classes and functions
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                class_node = self._extract_class(node, graph)
                graph.class_nodes.append(class_node)
                graph.classes.append(class_node.name)
                graph.class_hierarchy[class_node.name] = class_node.bases

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_node = self._extract_function(node, class_name=None)
                graph.function_nodes.append(func_node)
                graph.functions.append(func_node.name)
                graph.calls_to.extend(func_node.calls)

        return graph

    def persist_all(self, graphs: list[ModuleCallGraph]) -> int:
        """
        Persist all extracted call graphs to DynamoDB.

        Args:
            graphs: List of ModuleCallGraph objects to store.

        Returns:
            Number of successfully persisted items.
        """
        persisted = 0
        table = self._dynamodb.Table(self._knowledge_table)

        for graph in graphs:
            try:
                table.put_item(
                    Item={
                        "project_id": self._project_id,
                        "sk": f"callgraph#{graph.module_path}",
                        "data": json.dumps(graph.to_dict()),
                        "module_path": graph.module_path,
                        "extracted_at": graph.extracted_at,
                        "line_count": graph.line_count,
                        "function_count": len(graph.functions),
                        "class_count": len(graph.classes),
                    }
                )
                persisted += 1
            except ClientError as e:
                logger.warning(
                    "Failed to persist call graph for %s: %s",
                    graph.module_path,
                    e,
                )

        logger.info(
            "Persisted call graphs: project=%s persisted=%d/%d",
            self._project_id,
            persisted,
            len(graphs),
        )
        return persisted

    def get_module_graph(self, module_path: str) -> ModuleCallGraph | None:
        """
        Retrieve a previously stored call graph from DynamoDB.

        Args:
            module_path: Relative path of the module.

        Returns:
            ModuleCallGraph or None if not found.
        """
        table = self._dynamodb.Table(self._knowledge_table)
        try:
            response = table.get_item(
                Key={
                    "project_id": self._project_id,
                    "sk": f"callgraph#{module_path}",
                }
            )
            item = response.get("Item")
            if not item:
                return None

            data = json.loads(item["data"])
            return ModuleCallGraph(
                module_path=data["module_path"],
                functions=data.get("functions", []),
                classes=data.get("classes", []),
                calls_to=data.get("calls_to", []),
                called_by=data.get("called_by", []),
                class_hierarchy=data.get("class_hierarchy", {}),
                imports=data.get("imports", []),
                line_count=data.get("line_count", 0),
                extracted_at=data.get("extracted_at", ""),
            )
        except ClientError as e:
            logger.warning("Failed to retrieve call graph for %s: %s", module_path, e)
            return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _discover_python_files(self) -> list[Path]:
        """Find all Python files in the workspace, excluding hidden/venv dirs."""
        excluded_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox"}
        files: list[Path] = []

        for path in self._workspace_path.rglob("*"):
            if any(part in excluded_dirs for part in path.parts):
                continue
            if path.suffix in _PYTHON_EXTENSIONS and path.is_file():
                files.append(path)

        return sorted(files)

    def _extract_imports(self, tree: ast.Module) -> list[str]:
        """Extract top-level import names from an AST."""
        imports: list[str] = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imports.append(module)
        return sorted(set(imports))

    def _extract_class(self, node: ast.ClassDef, graph: ModuleCallGraph) -> ClassNode:
        """Extract class metadata including bases and methods."""
        bases: list[str] = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(ast.unparse(base))

        methods: list[str] = []
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(item.name)
                func_node = self._extract_function(item, class_name=node.name)
                graph.function_nodes.append(func_node)
                graph.calls_to.extend(func_node.calls)

        return ClassNode(
            name=node.name,
            lineno=node.lineno,
            bases=bases,
            methods=methods,
        )

    def _extract_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, class_name: str | None
    ) -> FunctionNode:
        """Extract function metadata and internal calls."""
        visitor = _CallVisitor()
        visitor.visit(node)

        decorators: list[str] = []
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name):
                decorators.append(dec.id)
            elif isinstance(dec, ast.Attribute):
                decorators.append(ast.unparse(dec))

        qualified_name = f"{class_name}.{node.name}" if class_name else node.name

        return FunctionNode(
            name=node.name,
            qualified_name=qualified_name,
            lineno=node.lineno,
            calls=visitor.calls,
            decorators=decorators,
            is_method=class_name is not None,
            is_async=isinstance(node, ast.AsyncFunctionDef),
        )

    def _resolve_called_by(self, graphs: list[ModuleCallGraph]) -> None:
        """
        Cross-reference graphs to populate called_by relationships.

        For each module, if its functions appear in another module's calls_to,
        record that reverse relationship.
        """
        # Build a lookup: function_name -> module_path
        function_to_module: dict[str, str] = {}
        for graph in graphs:
            for func in graph.functions:
                function_to_module[func] = graph.module_path

        # Populate called_by
        for graph in graphs:
            for call_target in graph.calls_to:
                target_module = function_to_module.get(call_target)
                if target_module and target_module != graph.module_path:
                    for target_graph in graphs:
                        if target_graph.module_path == target_module:
                            if graph.module_path not in target_graph.called_by:
                                target_graph.called_by.append(graph.module_path)
                            break
