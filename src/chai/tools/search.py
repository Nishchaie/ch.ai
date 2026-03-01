"""Web search tool using DuckDuckGo."""

from __future__ import annotations

from .base import Tool, ToolParameter, ToolResult


class WebSearchTool(Tool):
    """Search the web using DuckDuckGo."""

    name = "web_search"
    description = "Search the web for information. Useful for finding documentation, error solutions, or current information."
    parameters = [
        ToolParameter("query", "string", "The search query"),
        ToolParameter("max_results", "integer", "Maximum results to return (default: 5)", optional=True),
    ]
    reads_files = False
    writes_files = False

    def execute(
        self,
        query: str,
        max_results: int = 5,
        **kwargs: object,
    ) -> ToolResult:
        try:
            from ddgs import DDGS
        except ImportError:
            return ToolResult(
                success=False,
                output="",
                error="ddgs package not installed. Run: pip install ddgs",
            )

        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))

            if not results:
                return ToolResult(success=True, output="No results found")

            output_parts = []
            for i, result in enumerate(results, 1):
                title = result.get("title", "No title")
                href = result.get("href", "")
                body = result.get("body", "")
                snippet = body[:200] + "..." if len(body) > 200 else body
                output_parts.append(f"{i}. {title}")
                output_parts.append(f"   URL: {href}")
                output_parts.append(f"   {snippet}")
                output_parts.append("")

            return ToolResult(success=True, output="\n".join(output_parts))

        except Exception as e:
            return ToolResult(success=False, output="", error=f"Search failed: {e}")
