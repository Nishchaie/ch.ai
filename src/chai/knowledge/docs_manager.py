"""Manages docs/ directory structure."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional


class DocsManager:
    """Manages docs/ directory: design docs, references, exec plans."""

    def __init__(self, project_dir: Optional[str] = None) -> None:
        self._project_dir = Path(project_dir or ".")

    def init_docs(self, project_dir: Optional[str] = None) -> str:
        """Create docs directory structure. Returns docs path."""
        base = Path(project_dir or self._project_dir)
        docs = base / "docs"
        (docs / "design-docs").mkdir(parents=True, exist_ok=True)
        (docs / "references").mkdir(parents=True, exist_ok=True)
        (docs / "exec-plans").mkdir(parents=True, exist_ok=True)
        (docs / "golden-principles").mkdir(parents=True, exist_ok=True)
        return str(docs)

    def create_design_doc(self, title: str, content: str, project_dir: Optional[str] = None) -> str:
        """Create a design doc. Returns path."""
        base = Path(project_dir or self._project_dir)
        design_dir = base / "docs" / "design-docs"
        design_dir.mkdir(parents=True, exist_ok=True)
        slug = title.lower().replace(" ", "-").replace("_", "-")
        slug = "".join(c for c in slug if c.isalnum() or c == "-")
        path = design_dir / f"{slug}.md"
        full_content = f"# {title}\n\n{datetime.utcnow().strftime('%Y-%m-%d')}\n\n{content}"
        path.write_text(full_content, encoding="utf-8")
        return str(path)

    def list_docs(self, project_dir: Optional[str] = None) -> List[str]:
        """List all docs (design-docs, references, exec-plans)."""
        base = Path(project_dir or self._project_dir)
        docs: List[str] = []
        for sub in ["design-docs", "references", "exec-plans", "golden-principles"]:
            subdir = base / "docs" / sub
            if subdir.exists():
                for p in subdir.glob("*.md"):
                    docs.append(str(p.relative_to(base)))
        return sorted(docs)
