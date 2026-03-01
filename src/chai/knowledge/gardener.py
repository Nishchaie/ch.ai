"""Doc gardening: stale docs, broken cross-links, drift detection."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Set


class DocGardener:
    """Scans for stale docs, validates cross-links, identifies drift between docs and code."""

    def __init__(self, project_dir: Optional[str] = None) -> None:
        self._project_dir = Path(project_dir or ".")

    def scan(self, project_dir: Optional[str] = None) -> List[str]:
        """Scan for issues. Returns list of issue descriptions."""
        base = Path(project_dir or self._project_dir)
        issues: List[str] = []

        docs_dir = base / "docs"
        if not docs_dir.exists():
            return issues

        all_doc_paths: Set[Path] = set()
        for p in docs_dir.rglob("*.md"):
            all_doc_paths.add(p)

        for doc_path in all_doc_paths:
            try:
                content = doc_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                issues.append(f"Cannot read: {doc_path.relative_to(base)}")
                continue

            # Check markdown links [text](path)
            for match in re.finditer(r"\]\(([^\)]+)\)", content):
                link = match.group(1).split("#")[0].strip()
                if not link or link.startswith("http"):
                    continue
                target = (doc_path.parent / link).resolve()
                if not target.exists():
                    issues.append(f"Broken link in {doc_path.relative_to(base)}: {link}")

            # Check for references to files that may have been moved
            for match in re.finditer(r"`([a-zA-Z0-9_/\.\-]+\.(py|ts|tsx|js|jsx|md))`", content):
                ref = match.group(1)
                target = (base / ref).resolve()
                if not target.exists() and not ref.startswith("http"):
                    issues.append(f"Possibly stale reference in {doc_path.relative_to(base)}: {ref}")

        return issues

    def fix_issues(self, issues: List[str]) -> List[str]:
        """Produce fix descriptions for issues. Returns list of fix descriptions."""
        fixes: List[str] = []
        for issue in issues:
            if "Broken link" in issue:
                fixes.append(f"Update or remove broken link: {issue}")
            elif "stale reference" in issue:
                fixes.append(f"Update reference or remove: {issue}")
            elif "Cannot read" in issue:
                fixes.append(f"Fix file encoding or restore: {issue}")
            else:
                fixes.append(f"Review and fix: {issue}")
        return fixes
