"""Agent-friendly lint rules with remediation instructions."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set


@dataclass
class LintIssue:
    """A single lint issue."""

    path: str
    line: int
    column: int
    code: str
    message: str
    remediation: str


class AgentLinter:
    """Custom lint rules with agent-friendly error messages."""

    MAX_FILE_LINES = 500
    MAX_FILE_LINES_WARNING = 400

    def __init__(self) -> None:
        pass

    def lint_file(self, path: str) -> List[LintIssue]:
        """Lint a single file. Returns list of issues."""
        issues: List[LintIssue] = []
        p = Path(path)
        if not p.exists():
            return issues

        try:
            content = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return issues

        lines = content.splitlines()

        # File too large
        if len(lines) > self.MAX_FILE_LINES:
            issues.append(
                LintIssue(
                    path=path,
                    line=0,
                    column=0,
                    code="FILE_TOO_LARGE",
                    message=f"File has {len(lines)} lines (max {self.MAX_FILE_LINES}). Consider splitting.",
                    remediation="Split into smaller modules. Extract cohesive logic into separate files.",
                )
            )
        elif len(lines) > self.MAX_FILE_LINES_WARNING:
            issues.append(
                LintIssue(
                    path=path,
                    line=0,
                    column=0,
                    code="FILE_LARGE",
                    message=f"File has {len(lines)} lines. Consider splitting before reaching {self.MAX_FILE_LINES}.",
                    remediation="Consider extracting submodules or helpers.",
                )
            )

        if p.suffix == ".py":
            issues.extend(self._lint_python(path, content))

        return issues

    def _lint_python(self, path: str, content: str) -> List[LintIssue]:
        issues: List[LintIssue] = []
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return issues

        # Check for missing docstrings on public functions/classes
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name.startswith("_"):
                    continue
                docstring = ast.get_docstring(node)
                if not docstring:
                    issues.append(
                        LintIssue(
                            path=path,
                            line=node.lineno,
                            column=node.col_offset,
                            code="MISSING_DOCSTRING",
                            message=f"Public {('function' if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else 'class')} '{node.name}' has no docstring",
                            remediation="Add a docstring describing purpose, args, and return value.",
                        )
                    )

        # Unused imports (simplified: detect 'import x' when x not in identifiers)
        try:
            tree = ast.parse(content)
            used_names: Set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    used_names.add(node.id)
                elif isinstance(node, ast.Attribute):
                    used_names.add(node.attr)
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        name = alias.asname or alias.name
                        if "." in name:
                            name = name.split(".")[0]
                        if name not in used_names and not name.startswith("_"):
                            # Conservative: only flag if clearly unused (name never appears)
                            if name not in content.replace(f"import {name}", "").replace(f"from ", ""):
                                pass  # Skip to avoid false positives
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        name = alias.asname or alias.name
                        if name != "*" and name not in used_names:
                            pass  # Could flag but high false positive
        except (SyntaxError, Exception):
            pass

        return issues

    def lint_project(self, project_dir: str) -> List[LintIssue]:
        """Lint all relevant files in project. Returns all issues."""
        base = Path(project_dir)
        issues: List[LintIssue] = []
        for ext in ("*.py", "*.ts", "*.tsx", "*.js", "*.jsx"):
            for p in base.rglob(ext):
                if "node_modules" in str(p) or "__pycache__" in str(p) or ".venv" in str(p):
                    continue
                issues.extend(self.lint_file(str(p)))
        return issues
