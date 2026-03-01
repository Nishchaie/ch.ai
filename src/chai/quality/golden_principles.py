"""Golden principle checker: mechanical enforcement of code standards."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class GoldenPrinciple:
    """A single golden principle rule."""

    id: str
    name: str
    description: str
    check_type: str  # regex, file_size, naming
    pattern: str
    remediation: str


@dataclass
class Violation:
    """A violation of a golden principle."""

    principle_id: str
    principle_name: str
    message: str
    line: Optional[int] = None
    remediation: str = ""


class GoldenPrincipleChecker:
    """Parses principles from docs/golden-principles/index.md and runs checks."""

    def __init__(self, base_dir: Optional[str] = None) -> None:
        self._base_dir = base_dir or str(Path.cwd())
        self._principles: List[GoldenPrinciple] = []

    @property
    def principles(self) -> List[GoldenPrinciple]:
        return self._principles

    def load_principles(self, base_dir: Optional[str] = None) -> List[GoldenPrinciple]:
        """Load principles from docs/golden-principles/index.md."""
        base = Path(base_dir or self._base_dir)
        index_path = base / "docs" / "golden-principles" / "index.md"
        self._principles = []
        if not index_path.exists():
            return self._principles

        content = index_path.read_text(encoding="utf-8")
        current: Optional[GoldenPrinciple] = None
        for line in content.splitlines():
            if line.startswith("## ") and not line.startswith("## Principle"):
                name = line[3:].strip()
                pid = re.sub(r"[^a-zA-Z0-9]+", "-", name.lower()).strip("-") or "unnamed"
                if current:
                    self._principles.append(current)
                current = GoldenPrinciple(
                    id=pid,
                    name=name,
                    description="",
                    check_type="regex",
                    pattern="",
                    remediation="",
                )
            elif current is not None:
                lower = line.strip().lower()
                if lower.startswith("check:"):
                    current.check_type = line.split(":", 1)[1].strip().lower()
                elif lower.startswith("pattern:"):
                    current.pattern = line.split(":", 1)[1].strip()
                elif lower.startswith("remediation:"):
                    current.remediation = line.split(":", 1)[1].strip()
                elif line.strip() and not lower.startswith("check:") and not current.description:
                    current.description = line.strip()
        if current:
            self._principles.append(current)
        return self._principles

    def check_file(self, path: str) -> List[Violation]:
        """Run principle checks against a single file. Returns list of violations."""
        violations: List[Violation] = []
        if not self._principles:
            self.load_principles()

        p = Path(path)
        if not p.exists():
            return violations
        try:
            content = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return violations

        lines = content.splitlines()
        for principle in self._principles:
            if principle.check_type == "file_size":
                try:
                    max_lines = int(principle.pattern or "500")
                    if len(lines) > max_lines:
                        violations.append(
                            Violation(
                                principle_id=principle.id,
                                principle_name=principle.name,
                                message=f"File has {len(lines)} lines (max {max_lines})",
                                remediation=principle.remediation,
                            )
                        )
                except ValueError:
                    pass
            elif principle.check_type == "regex" and principle.pattern:
                try:
                    regex = re.compile(principle.pattern)
                    for i, line in enumerate(lines, 1):
                        if regex.search(line):
                            violations.append(
                                Violation(
                                    principle_id=principle.id,
                                    principle_name=principle.name,
                                    message=f"Line matches pattern: {line[:80]}",
                                    line=i,
                                    remediation=principle.remediation,
                                )
                            )
                except re.error:
                    pass
            elif principle.check_type == "naming" and principle.pattern:
                # Check filename against pattern
                try:
                    regex = re.compile(principle.pattern)
                    if not regex.search(p.name):
                        violations.append(
                            Violation(
                                principle_id=principle.id,
                                principle_name=principle.name,
                                message=f"Filename '{p.name}' does not match pattern",
                                remediation=principle.remediation,
                            )
                        )
                except re.error:
                    pass

        return violations

    def check_all(self, paths: List[str]) -> List[Violation]:
        """Run checks against multiple paths. Returns all violations."""
        violations: List[Violation] = []
        for path in paths:
            violations.extend(self.check_file(path))
        return violations
