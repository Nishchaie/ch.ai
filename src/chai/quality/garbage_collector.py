"""Pattern drift, dead code, duplicated helpers detection."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import List, Optional, Tuple

from ..types import RoleType, TaskSpec


class GarbageCollector:
    """Finds pattern drift, dead code, duplicated helpers. Produces cleanup task list."""

    def __init__(self, project_dir: Optional[str] = None) -> None:
        self._project_dir = Path(project_dir or ".")

    def scan(self, project_dir: Optional[str] = None) -> List[str]:
        """Scan for cleanup items. Returns list of issue descriptions."""
        base = Path(project_dir or self._project_dir)
        items: List[str] = []

        # Duplicated helpers: find similar small functions by content hash
        py_files = list(base.rglob("*.py"))
        skip = {"node_modules", "__pycache__", ".venv", ".git"}
        py_files = [p for p in py_files if not any(s in str(p) for s in skip)]

        seen_hashes: dict[str, Tuple[Path, str]] = {}
        for p in py_files:
            try:
                content = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            # Normalize and hash ~20+ char function-like blocks
            for block in self._extract_blocks(content):
                if len(block) < 50:
                    continue
                h = hashlib.sha256(block.encode()).hexdigest()[:16]
                if h in seen_hashes:
                    other_path, _ = seen_hashes[h]
                    if other_path != p:
                        items.append(f"Potential duplicate: {p.relative_to(base)} resembles {other_path.relative_to(base)}")
                else:
                    seen_hashes[h] = (p, block)

        # Orphan files: files not imported (simplified heuristic)
        # Skip for now - would need full import graph

        return items

    def _extract_blocks(self, content: str) -> List[str]:
        """Extract function/block bodies for fingerprinting."""
        blocks: List[str] = []
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    try:
                        block = ast.get_source_segment(content, node) or ""
                        if block:
                            blocks.append(block)
                    except (TypeError, ValueError):
                        pass
        except SyntaxError:
            pass
        return blocks

    def generate_cleanup_tasks(self, items: List[str]) -> List[TaskSpec]:
        """Convert cleanup items to TaskSpec list."""
        tasks: List[TaskSpec] = []
        for i, item in enumerate(items):
            tasks.append(
                TaskSpec(
                    id=f"cleanup-{i + 1}",
                    title=f"Cleanup: {item[:60]}",
                    description=item,
                    role=RoleType.BACKEND,
                    dependencies=[],
                )
            )
        return tasks
