"""Context management: selects relevant files/docs per role."""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Dict, List, Optional

from ..types import TaskSpec
from .role import RoleDefinition


class ContextManager:
    """Selects relevant project files per role using glob patterns."""

    def __init__(self, project_dir: str) -> None:
        self._project_dir = Path(project_dir)
        self._all_files: Optional[List[str]] = None

    def get_context_for_role(
        self,
        role: RoleDefinition,
        task: Optional[TaskSpec] = None,
    ) -> str:
        """Scan project using role's context_filters, return summary of relevant file paths."""
        files = self._get_all_files()
        matched: List[str] = []
        for rel_path in files:
            for pattern in role.context_filters:
                if fnmatch.fnmatch(rel_path, pattern):
                    matched.append(rel_path)
                    break
                # **/foo patterns should also match foo at the project root
                if pattern.startswith("**/") and fnmatch.fnmatch(rel_path, pattern[3:]):
                    matched.append(rel_path)
                    break
        matched.sort()

        if not matched:
            return "No relevant files found for this role."
        return "Relevant files:\n" + "\n".join(matched[:50])

    def _get_all_files(self) -> List[str]:
        """Collect all project files, caching result."""
        if self._all_files is not None:
            return self._all_files
        result: List[str] = []
        if not self._project_dir.exists():
            self._all_files = result
            return result
        skip = {"node_modules", "__pycache__", ".git", "venv", ".venv", ".nox"}
        try:
            for p in self._project_dir.rglob("*"):
                if p.is_file() and p.name != ".DS_Store":
                    parts = p.relative_to(self._project_dir).parts
                    if any(s in parts for s in skip):
                        continue
                    result.append(str(p.relative_to(self._project_dir)))
        except PermissionError:
            pass
        self._all_files = result
        return result

    def scan_project(self) -> Dict[str, List[str]]:
        """Map directory categories to file lists."""
        files = self._get_all_files()
        result: Dict[str, List[str]] = {}
        for f in files:
            parts = Path(f).parts
            if len(parts) > 1:
                category = parts[0] + "/"
            else:
                category = "root"
            result.setdefault(category, []).append(f)
        return result
