"""Search tools for finding patterns in files."""

from __future__ import annotations

import glob as globlib
import os
import re
from typing import Optional

from .base import Tool, ToolParameter, ToolResult


class GrepTool(Tool):
    """Search for patterns in files."""

    name = "grep"
    description = "Search for a regex pattern in files. Returns matching lines with file paths and line numbers."
    parameters = [
        ToolParameter("pattern", "string", "Regular expression pattern to search for"),
        ToolParameter("path", "string", "File or directory to search (default: current directory)", optional=True),
        ToolParameter("file_pattern", "string", "Glob pattern for files to search (e.g., '*.py')", optional=True),
        ToolParameter("case_insensitive", "boolean", "Case-insensitive search (default: false)", optional=True),
        ToolParameter("max_results", "integer", "Maximum results to return (default: 50)", optional=True),
    ]
    reads_files = True
    writes_files = False

    SKIP_DIRS = {
        "node_modules", ".git", ".svn", ".hg", "__pycache__",
        ".pytest_cache", ".mypy_cache", "venv", ".venv", "env",
        "dist", "build", ".next", ".cache", "coverage",
        ".tox", ".eggs", "*.egg-info",
    }

    SKIP_EXTENSIONS = {
        ".pyc", ".pyo", ".so", ".o", ".a", ".lib", ".dll",
        ".exe", ".bin", ".obj", ".class", ".jar",
        ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx",
        ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
        ".mp3", ".mp4", ".avi", ".mov", ".mkv",
        ".lock", ".min.js", ".min.css",
    }

    def _should_skip(self, path: str) -> bool:
        parts = path.split(os.sep)
        for part in parts:
            if part in self.SKIP_DIRS:
                return True
        ext = os.path.splitext(path)[1].lower()
        if ext in self.SKIP_EXTENSIONS:
            return True
        return False

    def _get_files(self, path: str, file_pattern: Optional[str]) -> list:
        path = os.path.expanduser(path)
        if os.path.isfile(path):
            return [path]
        if not os.path.isdir(path):
            return []
        if file_pattern:
            pattern = os.path.join(path, "**", file_pattern)
        else:
            pattern = os.path.join(path, "**", "*")
        files = []
        for f in globlib.glob(pattern, recursive=True):
            if os.path.isfile(f) and not self._should_skip(f):
                files.append(f)
        return files

    def execute(
        self,
        pattern: str,
        path: str = ".",
        file_pattern: Optional[str] = None,
        case_insensitive: bool = False,
        max_results: int = 50,
        **kwargs: object,
    ) -> ToolResult:
        try:
            flags = re.IGNORECASE if case_insensitive else 0
            regex = re.compile(pattern, flags)
        except re.error as e:
            return ToolResult(success=False, output="", error=f"Invalid regex: {e}")

        try:
            files = self._get_files(path, file_pattern)
            if not files:
                return ToolResult(success=True, output="No files to search")

            hits = []
            files_searched = 0
            for filepath in files:
                if len(hits) >= max_results:
                    break
                try:
                    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                        for line_num, line in enumerate(f, 1):
                            if regex.search(line):
                                display_path = os.path.relpath(filepath, path) if path != "." else filepath
                                hits.append(f"{display_path}:{line_num}:{line.rstrip()}")
                                if len(hits) >= max_results:
                                    break
                    files_searched += 1
                except (IOError, OSError):
                    continue

            if not hits:
                return ToolResult(success=True, output=f"No matches found (searched {files_searched} files)")

            output = "\n".join(hits)
            if len(hits) >= max_results:
                output += f"\n\n(showing first {max_results} results)"

            return ToolResult(success=True, output=output)

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))
