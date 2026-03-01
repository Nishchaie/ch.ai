"""Code review helper tool - formats code for agent review."""

from __future__ import annotations

import os
from typing import Optional

from .base import Tool, ToolParameter, ToolResult


class CodeReviewTool(Tool):
    """Helper tool that formats code or diffs for agent review. Returns structured output."""

    name = "review"
    description = (
        "Format a file or diff for code review. Returns structured output with "
        "file path, line numbers, and content. Use for preparing code for agent review."
    )
    parameters = [
        ToolParameter("path", "string", "Path to the file to review", optional=True),
        ToolParameter("diff", "string", "Diff content to review (if no path)", optional=True),
    ]
    reads_files = True
    writes_files = False

    def execute(
        self,
        path: Optional[str] = None,
        diff: Optional[str] = None,
        **kwargs: object,
    ) -> ToolResult:
        if path:
            return self._review_file(path)
        elif diff:
            return self._review_diff(diff)
        return ToolResult(
            success=False,
            output="",
            error="Provide either path (to review a file) or diff (to review diff content)",
        )

    def _review_file(self, path: str) -> ToolResult:
        try:
            path = os.path.expanduser(path)
            if not os.path.exists(path):
                return ToolResult(success=False, output="", error=f"File not found: {path}")
            if os.path.isdir(path):
                return ToolResult(success=False, output="", error=f"Path is a directory: {path}")

            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            output_parts = [
                f"=== Code Review: {path} ===",
                f"Lines: {len(lines)}",
                "",
                "--- Content ---",
            ]
            for i, line in enumerate(lines, 1):
                output_parts.append(f"{i:4}| {line.rstrip()}")

            output_parts.extend([
                "",
                "--- Review Checklist ---",
                "- [ ] Correctness and logic",
                "- [ ] Error handling",
                "- [ ] Security considerations",
                "- [ ] Performance",
                "- [ ] Style and consistency",
                "- [ ] Documentation",
            ])

            return ToolResult(success=True, output="\n".join(output_parts))

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    def _review_diff(self, diff: str) -> ToolResult:
        lines = diff.strip().split("\n")
        output_parts = [
            "=== Diff Review ===",
            f"Lines: {len(lines)}",
            "",
            "--- Diff Content ---",
            diff.strip(),
            "",
            "--- Review Checklist ---",
            "- [ ] Changes are minimal and focused",
            "- [ ] No unintended side effects",
            "- [ ] Tests cover the change",
            "- [ ] Documentation updated if needed",
        ]
        return ToolResult(success=True, output="\n".join(output_parts))
