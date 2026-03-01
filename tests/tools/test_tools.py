"""Tests for tools and tool registry."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from chai.tools import (
    get_default_tools,
    ReadTool,
    ReadRawTool,
    WriteTool,
    EditTool,
    GlobTool,
    ListDirTool,
    GrepTool,
    ShellTool,
    ToolRegistry,
)
from chai.types import RoleType


class TestFilesystemTools:
    def test_read_tool(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3\n")
        t = ReadTool()
        r = t.execute(path=str(f))
        assert r.success
        assert "line1" in r.output
        assert "1   |" in r.output or "1|" in r.output

    def test_read_tool_offset_limit(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("a\nb\nc\nd\ne\n")
        t = ReadTool()
        r = t.execute(path=str(f), offset=1, limit=2)
        assert r.success
        assert "b" in r.output
        assert "c" in r.output
        assert "a" not in r.output and "d" not in r.output

    def test_read_tool_file_not_found(self) -> None:
        t = ReadTool()
        r = t.execute(path="/nonexistent/path/file.txt")
        assert not r.success
        assert "not found" in (r.error or "").lower()

    def test_read_raw_tool(self, tmp_path: Path) -> None:
        f = tmp_path / "raw.txt"
        content = "exact content\nno line numbers"
        f.write_text(content)
        t = ReadRawTool()
        r = t.execute(path=str(f))
        assert r.success
        assert r.output == content

    def test_write_tool(self, tmp_path: Path) -> None:
        f = tmp_path / "out.txt"
        t = WriteTool()
        r = t.execute(path=str(f), content="hello world")
        assert r.success
        assert f.read_text() == "hello world"

    def test_write_tool_creates_dirs(self, tmp_path: Path) -> None:
        f = tmp_path / "a" / "b" / "file.txt"
        t = WriteTool()
        r = t.execute(path=str(f), content="nested")
        assert r.success
        assert f.read_text() == "nested"

    def test_edit_tool(self, tmp_path: Path) -> None:
        f = tmp_path / "edit.txt"
        f.write_text("before\nmiddle\nafter\n")
        t = EditTool()
        r = t.execute(path=str(f), old_string="middle", new_string="replaced")
        assert r.success
        assert f.read_text() == "before\nreplaced\nafter\n"

    def test_edit_tool_replace_all(self, tmp_path: Path) -> None:
        f = tmp_path / "edit.txt"
        f.write_text("x\nx\nx\n")
        t = EditTool()
        r = t.execute(path=str(f), old_string="x", new_string="y", replace_all=True)
        assert r.success
        assert f.read_text() == "y\ny\ny\n"

    def test_glob_tool(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("")
        (tmp_path / "b.py").write_text("")
        (tmp_path / "c.txt").write_text("")
        t = GlobTool()
        r = t.execute(pattern="*.py", path=str(tmp_path))
        assert r.success
        assert "a.py" in r.output
        assert "b.py" in r.output
        assert "c.txt" not in r.output

    def test_list_dir_tool(self, tmp_path: Path) -> None:
        (tmp_path / "file1.txt").write_text("x")
        (tmp_path / "subdir").mkdir()
        t = ListDirTool()
        r = t.execute(path=str(tmp_path))
        assert r.success
        assert "file1.txt" in r.output
        assert "subdir" in r.output


class TestGrepTool:
    def test_grep_finds_pattern(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("def foo():\n    bar = 1\n")
        t = GrepTool()
        r = t.execute(pattern=r"def \w+", path=str(tmp_path))
        assert r.success
        assert "foo" in r.output

    def test_grep_file_pattern(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("import os")
        (tmp_path / "b.txt").write_text("import os")
        t = GrepTool()
        r = t.execute(pattern="import", path=str(tmp_path), file_pattern="*.py")
        assert r.success
        assert "a.py" in r.output
        assert "b.txt" not in r.output

    def test_grep_invalid_regex(self) -> None:
        t = GrepTool()
        r = t.execute(pattern="[invalid", path=".")
        assert not r.success
        assert "regex" in (r.error or "").lower()


class TestShellTool:
    def test_shell_simple_command(self) -> None:
        t = ShellTool()
        r = t.execute(command="echo hello")
        assert r.success
        assert "hello" in r.output

    def test_shell_cwd(self, tmp_path: Path) -> None:
        t = ShellTool()
        r = t.execute(command="pwd", cwd=str(tmp_path))
        assert r.success
        assert str(tmp_path) in r.output or tmp_path.name in r.output

    def test_shell_blocked_command(self) -> None:
        t = ShellTool()
        r = t.execute(command="rm -rf /")
        assert not r.success
        assert "blocked" in (r.error or "").lower()


class TestToolRegistry:
    def test_register_and_execute(self, tmp_path: Path) -> None:
        registry = ToolRegistry(base_dir=str(tmp_path))
        registry.register(ReadTool())
        registry.register(WriteTool())
        file_path = tmp_path / "x.txt"
        file_path.write_text("content")
        r = registry.execute("read", {"path": str(file_path)})
        assert r.success
        assert "content" in r.output

    def test_execute_unknown_tool(self) -> None:
        registry = ToolRegistry()
        registry.register(ReadTool())
        r = registry.execute("unknown_tool", {})
        assert not r.success
        assert "Unknown" in (r.error or "")

    def test_role_filtering(self) -> None:
        registry = get_default_tools(role=RoleType.RESEARCHER)
        schemas = registry.get_schemas()
        tool_names = [s["name"] for s in schemas]
        assert "read" in tool_names
        assert "shell" not in tool_names
