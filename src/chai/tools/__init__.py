"""Tool system for ch.ai - agent capabilities."""

from __future__ import annotations

from typing import Optional

from .base import Tool, ToolParameter, ToolRegistry, ToolResult
from .filesystem import (
    ReadTool,
    ReadRawTool,
    WriteTool,
    EditTool,
    GlobTool,
    ListDirTool,
)
from .grep import GrepTool
from .shell import ShellTool
from .search import WebSearchTool
from .browser import BrowserTool
from .review import CodeReviewTool

from ..types import RoleType


def get_default_tools(
    base_dir: Optional[str] = None,
    role: Optional[RoleType] = None,
) -> ToolRegistry:
    """Create a ToolRegistry with all tools, filtered by role.

    Args:
        base_dir: Base directory for resolving relative paths
        role: Role to filter tools for (None = all tools for role)

    Returns:
        ToolRegistry with all tools registered, filtered by role
    """
    registry = ToolRegistry(base_dir=base_dir, role=role)

    registry.register(ReadTool())
    registry.register(ReadRawTool())
    registry.register(WriteTool())
    registry.register(EditTool())
    registry.register(GlobTool())
    registry.register(ListDirTool())
    registry.register(GrepTool())
    registry.register(ShellTool())
    registry.register(WebSearchTool())
    registry.register(BrowserTool())
    registry.register(CodeReviewTool())

    return registry


__all__ = [
    "Tool",
    "ToolParameter",
    "ToolRegistry",
    "ToolResult",
    "ReadTool",
    "ReadRawTool",
    "WriteTool",
    "EditTool",
    "GlobTool",
    "ListDirTool",
    "GrepTool",
    "ShellTool",
    "WebSearchTool",
    "BrowserTool",
    "CodeReviewTool",
    "get_default_tools",
]
