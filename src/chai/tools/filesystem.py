"""File system tools for reading, writing, and editing files."""

from __future__ import annotations

import glob as globlib
import os
import re
from typing import Optional

from .base import Tool, ToolParameter, ToolResult

_LINE_PREFIX_PATTERNS = (
    re.compile(r"^\s*\d+\|\s"),
    re.compile(r"^L\d+:\s?"),
)


def _strip_line_prefixes(text: str) -> str:
    lines = text.splitlines(keepends=True)
    normalized = []
    for line in lines:
        updated = line
        for pattern in _LINE_PREFIX_PATTERNS:
            updated = pattern.sub("", updated, count=1)
        normalized.append(updated)
    return "".join(normalized)


def _normalize_whitespace(text: str) -> str:
    lines = text.splitlines(keepends=True)
    normalized = []
    for line in lines:
        line_ending = "\n" if line.endswith("\n") else ""
        content = line[:-1] if line_ending else line
        if content.strip() == "":
            normalized.append(line_ending)
        else:
            normalized.append(content.rstrip() + line_ending)
    return "".join(normalized)


class ReadTool(Tool):
    """Read file contents with line numbers."""

    name = "read"
    description = "Read file contents with line numbers. Use for viewing source code or text files."
    parameters = [
        ToolParameter("path", "string", "Path to the file to read"),
        ToolParameter("offset", "integer", "Starting line number (0-indexed)", optional=True),
        ToolParameter("limit", "integer", "Maximum number of lines to read", optional=True),
    ]
    reads_files = True
    writes_files = False

    def execute(
        self,
        path: str,
        offset: int = 0,
        limit: Optional[int] = None,
        **kwargs: object,
    ) -> ToolResult:
        try:
            path = os.path.expanduser(path)

            if not os.path.exists(path):
                return ToolResult(success=False, output="", error=f"File not found: {path}")

            if os.path.isdir(path):
                return ToolResult(success=False, output="", error=f"Path is a directory: {path}")

            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            total_lines = len(lines)
            if limit is None:
                limit = total_lines

            selected = lines[offset : offset + limit]

            output_lines = []
            for idx, line in enumerate(selected):
                line_num = offset + idx + 1
                output_lines.append(f"{line_num:4}| {line.rstrip()}")

            output = "\n".join(output_lines)
            if offset + limit < total_lines:
                output += f"\n... {total_lines - (offset + limit)} more lines"

            return ToolResult(success=True, output=output)

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class ReadRawTool(Tool):
    """Read raw file contents without line numbers."""

    name = "read_raw"
    description = (
        "Read raw file contents without line numbers. "
        "Use for exact text matching before edit operations."
    )
    parameters = [
        ToolParameter("path", "string", "Path to the file to read"),
        ToolParameter("offset", "integer", "Starting line number (0-indexed)", optional=True),
        ToolParameter("limit", "integer", "Maximum number of lines to read", optional=True),
    ]
    reads_files = True
    writes_files = False

    def execute(
        self,
        path: str,
        offset: int = 0,
        limit: Optional[int] = None,
        **kwargs: object,
    ) -> ToolResult:
        try:
            path = os.path.expanduser(path)

            if not os.path.exists(path):
                return ToolResult(success=False, output="", error=f"File not found: {path}")

            if os.path.isdir(path):
                return ToolResult(success=False, output="", error=f"Path is a directory: {path}")

            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            total_lines = len(lines)
            if limit is None:
                limit = total_lines
            selected = lines[offset : offset + limit]
            output = "".join(selected)
            return ToolResult(success=True, output=output)

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class WriteTool(Tool):
    """Write content to a file."""

    name = "write"
    description = "Write content to a file. Creates the file if it doesn't exist, overwrites if it does."
    parameters = [
        ToolParameter("path", "string", "Path to the file to write"),
        ToolParameter("content", "string", "Content to write to the file"),
    ]
    reads_files = False
    writes_files = True

    def execute(self, path: str, content: str, **kwargs: object) -> ToolResult:
        try:
            path = os.path.expanduser(path)
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)

            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

            lines = content.count("\n") + 1
            return ToolResult(success=True, output=f"Wrote {lines} lines to {path}")

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class EditTool(Tool):
    """Edit a file by replacing text."""

    name = "edit"
    description = "Replace text in a file. The old_string must be unique unless replace_all is true."
    parameters = [
        ToolParameter("path", "string", "Path to the file to edit"),
        ToolParameter("old_string", "string", "Text to find and replace"),
        ToolParameter("new_string", "string", "Text to replace with"),
        ToolParameter("replace_all", "boolean", "Replace all occurrences (default: false)", optional=True),
    ]
    reads_files = True
    writes_files = True

    def execute(
        self,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
        **kwargs: object,
    ) -> ToolResult:
        try:
            path = os.path.expanduser(path)

            if not os.path.exists(path):
                return ToolResult(success=False, output="", error=f"File not found: {path}")

            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            normalized_old = old_string
            normalization = "exact"
            if old_string not in content:
                candidates = [
                    ("line_prefix", _strip_line_prefixes(old_string)),
                    ("whitespace", _normalize_whitespace(old_string)),
                    ("line_prefix_whitespace", _normalize_whitespace(_strip_line_prefixes(old_string))),
                ]
                matched = False
                for label, candidate in candidates:
                    if candidate != old_string and candidate in content:
                        normalized_old = candidate
                        normalization = label
                        matched = True
                        break
                if not matched:
                    old_preview = old_string[:200] + "..." if len(old_string) > 200 else old_string
                    file_preview = content[:500] + "..." if len(content) > 500 else content
                    hint = ""
                    if any(pattern.search(old_string) for pattern in _LINE_PREFIX_PATTERNS):
                        hint += (
                            "\n\nNOTE: It looks like your old_string includes line numbers. "
                            "Use read_raw or remove the line prefixes."
                        )
                    if _normalize_whitespace(old_string) != old_string:
                        hint += (
                            "\n\nNOTE: Your old_string includes trailing whitespace on blank lines. "
                            "Use read_raw to capture exact whitespace."
                        )
                    return ToolResult(
                        success=False,
                        output="",
                        error=(
                            "EDIT FAILED: The text you're trying to replace does not exist in the file.\n\n"
                            f"YOU SEARCHED FOR:\n'''\n{old_preview}\n'''\n\n"
                            f"BUT THE FILE CONTAINS:\n'''\n{file_preview}\n'''\n\n"
                            "IMPORTANT: You must use the EXACT text from the file. "
                            "Read the file again and copy the exact text you want to replace."
                            f"{hint}"
                        ),
                    )

            count = content.count(normalized_old)
            if not replace_all and count > 1:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"old_string appears {count} times. Use replace_all=true or make old_string unique.",
                )

            if replace_all:
                new_content = content.replace(normalized_old, new_string)
                replaced = count
            else:
                new_content = content.replace(normalized_old, new_string, 1)
                replaced = 1

            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)

            return ToolResult(success=True, output=f"Replaced {replaced} occurrence(s) in {path}")

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class GlobTool(Tool):
    """Find files matching a glob pattern."""

    name = "glob"
    description = "Find files matching a glob pattern. Returns files sorted by modification time (newest first)."
    parameters = [
        ToolParameter("pattern", "string", "Glob pattern (e.g., '**/*.py', '*.txt')"),
        ToolParameter("path", "string", "Base directory to search in (default: current directory)", optional=True),
    ]
    reads_files = True
    writes_files = False

    def execute(
        self,
        pattern: str,
        path: str = ".",
        **kwargs: object,
    ) -> ToolResult:
        try:
            path = os.path.expanduser(path)

            if not os.path.isdir(path):
                return ToolResult(success=False, output="", error=f"Directory not found: {path}")

            full_pattern = os.path.join(path, pattern)
            files = globlib.glob(full_pattern, recursive=True)

            files = sorted(
                files,
                key=lambda f: os.path.getmtime(f) if os.path.isfile(f) else 0,
                reverse=True,
            )
            files = [os.path.relpath(f, path) if path != "." else f for f in files]

            if not files:
                return ToolResult(success=True, output="No files found")

            output = "\n".join(files[:100])
            if len(files) > 100:
                output += f"\n... and {len(files) - 100} more files"

            return ToolResult(success=True, output=output)

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class ListDirTool(Tool):
    """List directory contents."""

    name = "list_dir"
    description = "List files and directories in a path. Shows file types and basic info."
    parameters = [
        ToolParameter("path", "string", "Directory path to list (default: current directory)", optional=True),
        ToolParameter("show_hidden", "boolean", "Show hidden files (default: false)", optional=True),
    ]
    reads_files = True
    writes_files = False

    def execute(
        self,
        path: str = ".",
        show_hidden: bool = False,
        **kwargs: object,
    ) -> ToolResult:
        try:
            path = os.path.expanduser(path)

            if not os.path.exists(path):
                return ToolResult(success=False, output="", error=f"Path not found: {path}")

            if not os.path.isdir(path):
                return ToolResult(success=False, output="", error=f"Not a directory: {path}")

            entries = []
            for name in sorted(os.listdir(path)):
                if not show_hidden and name.startswith("."):
                    continue
                full_path = os.path.join(path, name)
                if os.path.isdir(full_path):
                    entries.append(f"  {name}/")
                else:
                    size = os.path.getsize(full_path)
                    if size < 1024:
                        size_str = f"{size}B"
                    elif size < 1024 * 1024:
                        size_str = f"{size // 1024}K"
                    else:
                        size_str = f"{size // (1024 * 1024)}M"
                    entries.append(f"  {name} ({size_str})")

            if not entries:
                return ToolResult(success=True, output="(empty directory)")

            header = f"{path}:\n"
            return ToolResult(success=True, output=header + "\n".join(entries))

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))
