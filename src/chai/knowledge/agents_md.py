"""AGENTS.md generation and maintenance as table of contents."""

from __future__ import annotations

from pathlib import Path
from typing import Optional


MAX_LINES = 100


class AgentsMdManager:
    """Generates and maintains AGENTS.md as a table of contents with pointers to docs/."""

    def __init__(self, project_dir: Optional[str] = None) -> None:
        self._project_dir = Path(project_dir or ".")

    def generate(self, project_dir: Optional[str] = None) -> str:
        """Generate AGENTS.md content. Keeps under ~100 lines with pointers to docs/."""
        base = Path(project_dir or self._project_dir)
        lines: list[str] = [
            "# ch.ai Agent Guide",
            "",
            "> This file is a map, not an encyclopedia. It points you to where to look.",
            "",
            "## Project Overview",
            "",
            "See [ARCHITECTURE.md](ARCHITECTURE.md) for the full system design.",
            "",
            "## Directory Map",
            "",
        ]

        if (base / "src").exists():
            lines.append("- `src/` -- Application source")
        if (base / "frontend").exists():
            lines.append("- `frontend/` -- Frontend application")
        if (base / "tests").exists():
            lines.append("- `tests/` -- Test suite")
        if (base / "docs").exists():
            lines.append("- `docs/` -- Design docs, references, exec plans")
        lines.append("")
        lines.append("## Key Concepts")
        lines.append("")
        lines.append("- **Harness**: Runtime that boots teams and manages agent lifecycles")
        lines.append("- **Team**: Group of role-specialized agents")
        lines.append("- **TaskGraph**: DAG of tasks with dependencies")
        lines.append("- **ValidationGate**: Self-testing between execution and review")
        lines.append("")
        lines.append("## Documentation")
        lines.append("")

        docs = base / "docs"
        if docs.exists():
            for sub in ["design-docs", "exec-plans", "golden-principles", "references"]:
                subdir = docs / sub
                if subdir.exists():
                    lines.append(f"- `docs/{sub}/` -- {sub.replace('-', ' ').title()}")
            lines.append("")

        lines.append("## Conventions")
        lines.append("")
        lines.append("- Python: type hints, dataclasses, Pydantic models")
        lines.append("- Tests mirror source under `tests/`")
        lines.append("")

        content = "\n".join(lines)
        if len(lines) > MAX_LINES:
            content = "\n".join(lines[:MAX_LINES]) + "\n\n... (truncated)\n"
        return content

    def update(self, project_dir: Optional[str] = None) -> str:
        """Update AGENTS.md on disk. Returns path."""
        base = Path(project_dir or self._project_dir)
        content = self.generate(str(base))
        path = base / "AGENTS.md"
        path.write_text(content, encoding="utf-8")
        return str(path)

    def is_stale(self, project_dir: Optional[str] = None) -> bool:
        """Check if AGENTS.md is missing or significantly different from generated."""
        base = Path(project_dir or self._project_dir)
        path = base / "AGENTS.md"
        if not path.exists():
            return True
        current = path.read_text(encoding="utf-8")
        generated = self.generate(str(base))
        return current.strip() != generated.strip()
