"""Repository structure scanning and file/module mapping."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ..types import RoleType


class RepoKnowledge:
    """Scans repo structure, builds file/module map, identifies key directories per role."""

    def __init__(self, project_dir: Optional[str] = None) -> None:
        self._project_dir = Path(project_dir or ".")
        self._scan_cache: Optional[Dict[str, Any]] = {}

    def scan(self, project_dir: Optional[str] = None) -> Dict[str, Any]:
        """Scan repo structure. Returns dict with structure, file counts, module map."""
        base = Path(project_dir or self._project_dir)
        result: Dict[str, Any] = {
            "files": [],
            "directories": [],
            "extensions": {},
            "frontend_files": [],
            "backend_files": [],
            "test_files": [],
            "doc_files": [],
            "config_files": [],
        }
        skip = {"node_modules", "__pycache__", ".venv", ".git", "dist", "build"}

        for p in base.rglob("*"):
            if p.is_dir():
                if not any(s in str(p) for s in skip):
                    result["directories"].append(str(p.relative_to(base)))
            else:
                rel = str(p.relative_to(base))
                result["files"].append(rel)
                ext = p.suffix or "none"
                result["extensions"][ext] = result["extensions"].get(ext, 0) + 1
                if self._is_frontend(p):
                    result["frontend_files"].append(rel)
                if self._is_backend(p):
                    result["backend_files"].append(rel)
                if self._is_test(p):
                    result["test_files"].append(rel)
                if self._is_doc(p):
                    result["doc_files"].append(rel)
                if self._is_config(p):
                    result["config_files"] = result.get("config_files", []) + [rel]

        self._scan_cache = result
        return result

    def _is_frontend(self, p: Path) -> bool:
        return (
            p.suffix in (".tsx", ".jsx", ".vue", ".svelte")
            or (p.suffix in (".ts", ".js") and "component" in p.name.lower())
            or "frontend" in str(p)
            or "src" in str(p) and p.suffix in (".tsx", ".jsx", ".ts", ".js")
        )

    def _is_backend(self, p: Path) -> bool:
        return (
            p.suffix == ".py"
            and "__pycache__" not in str(p)
            and ".venv" not in str(p)
        ) or "api" in p.name.lower()

    def _is_test(self, p: Path) -> bool:
        return (
            "test" in p.name.lower()
            or "tests" in str(p)
            or p.name.endswith("_test.py")
            or p.name.endswith(".test.ts")
            or p.name.endswith(".spec.ts")
        )

    def _is_doc(self, p: Path) -> bool:
        return p.suffix == ".md" or "docs" in str(p)

    def _is_config(self, p: Path) -> bool:
        return p.name in (
            "pyproject.toml", "package.json", "tsconfig.json",
            "chai.yaml", "Makefile", "Dockerfile",
        )

    def get_files_for_role(self, role: RoleType) -> List[str]:
        """Return file paths relevant to the given role."""
        if not self._scan_cache:
            self.scan()
        cache = self._scan_cache or {}
        if role == RoleType.FRONTEND:
            return cache.get("frontend_files", [])
        if role == RoleType.BACKEND:
            return cache.get("backend_files", [])
        if role == RoleType.QA:
            return cache.get("test_files", [])
        if role == RoleType.RESEARCHER:
            return cache.get("doc_files", [])
        if role == RoleType.DEPLOYMENT:
            return cache.get("config_files", [])
        if role == RoleType.LEAD:
            return cache.get("doc_files", []) + cache.get("config_files", [])
        return cache.get("files", [])[:100]

    def get_summary(self) -> str:
        """Return a human-readable summary of the repo structure."""
        if not self._scan_cache:
            self.scan()
        cache = self._scan_cache or {}
        lines = [
            f"Files: {len(cache.get('files', []))}",
            f"Frontend: {len(cache.get('frontend_files', []))}",
            f"Backend: {len(cache.get('backend_files', []))}",
            f"Tests: {len(cache.get('test_files', []))}",
            f"Docs: {len(cache.get('doc_files', []))}",
        ]
        exts = cache.get("extensions", {})
        if exts:
            lines.append("Extensions: " + ", ".join(f"{k}:{v}" for k, v in sorted(exts.items())[:10]))
        return "\n".join(lines)
