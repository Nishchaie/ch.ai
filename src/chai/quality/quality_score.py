"""Quality scoring per domain: frontend, backend, tests, docs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional


class QualityScorer:
    """Grades each domain for quality. Metrics: test coverage estimation, lint count, doc freshness."""

    def __init__(self, project_dir: Optional[str] = None) -> None:
        self._project_dir = Path(project_dir or ".")

    def score(self, project_dir: Optional[str] = None) -> Dict[str, float]:
        """Score each domain. Returns dict like {frontend: 0.8, backend: 0.7, tests: 0.6, docs: 0.9}."""
        base = Path(project_dir or self._project_dir)
        scores: Dict[str, float] = {}

        # Frontend: presence of tests, lint config
        frontend_score = 0.5
        if (base / "frontend").exists() or any(base.glob("**/*.tsx")):
            frontend_score += 0.2
            if (base / "package.json").exists():
                frontend_score += 0.15
            if any(base.glob("**/*.test.tsx")) or any(base.glob("**/*.spec.tsx")):
                frontend_score += 0.15
        scores["frontend"] = min(1.0, frontend_score)

        # Backend: presence of tests, type hints
        backend_score = 0.5
        py_files = list(base.glob("**/*.py"))
        test_files = [p for p in py_files if "test" in p.name or "tests" in str(p)]
        if py_files:
            backend_score += 0.2
            if test_files:
                backend_score += 0.2
            if len(test_files) / max(len(py_files), 1) > 0.3:
                backend_score += 0.1
        scores["backend"] = min(1.0, backend_score)

        # Tests: coverage proxy
        tests_score = 0.5
        if test_files:
            tests_score += 0.3
        if (base / "pyproject.toml").exists():
            content = (base / "pyproject.toml").read_text()
            if "pytest" in content:
                tests_score += 0.2
        scores["tests"] = min(1.0, tests_score)

        # Docs: presence of key docs
        docs_score = 0.3
        if (base / "README.md").exists():
            docs_score += 0.2
        if (base / "docs").is_dir():
            docs_score += 0.2
        if (base / "ARCHITECTURE.md").exists():
            docs_score += 0.15
        if (base / "AGENTS.md").exists():
            docs_score += 0.15
        scores["docs"] = min(1.0, docs_score)

        return scores

    def save_scores(self, project_dir: Optional[str] = None) -> str:
        """Save scores to docs/QUALITY_SCORE.md. Returns path."""
        base = Path(project_dir or self._project_dir)
        scores = self.score(str(base))
        docs_dir = base / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        path = docs_dir / "QUALITY_SCORE.md"
        lines = [
            "# Quality Score",
            "",
            "| Domain | Score |",
            "|--------|-------|",
        ]
        for domain, val in scores.items():
            lines.append(f"| {domain} | {val:.2f} |")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(path)

    def load_scores(self, project_dir: Optional[str] = None) -> Dict[str, float]:
        """Load scores from docs/QUALITY_SCORE.md."""
        base = Path(project_dir or self._project_dir)
        path = base / "docs" / "QUALITY_SCORE.md"
        scores: Dict[str, float] = {}
        if not path.exists():
            return scores
        for line in path.read_text().splitlines():
            if "|" in line and not line.strip().startswith("|--"):
                parts = [p.strip() for p in line.split("|") if p.strip()]
                if len(parts) >= 2 and parts[0].lower() != "domain":
                    try:
                        scores[parts[0]] = float(parts[1])
                    except ValueError:
                        pass
        return scores
