"""Browser tool for Chrome DevTools Protocol integration - validate web apps."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

from .base import Tool, ToolParameter, ToolResult


class BrowserTool(Tool):
    """Basic Chrome DevTools Protocol integration for validating web apps."""

    name = "browser"
    description = (
        "Interact with a web browser via Chrome DevTools Protocol. "
        "Methods: navigate(url), screenshot(), get_dom_snapshot(). "
        "Requires Chrome running with --remote-debugging-port=9222."
    )
    parameters = [
        ToolParameter("action", "string", "One of: navigate, screenshot, get_dom_snapshot"),
        ToolParameter("url", "string", "URL to navigate to (for navigate action)", optional=True),
    ]
    reads_files = False
    writes_files = False

    DEFAULT_CDP_URL = "http://127.0.0.1:9222"

    def _run_async(self, coro: Any) -> Any:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)

    def execute(
        self,
        action: str,
        url: Optional[str] = None,
        **kwargs: object,
    ) -> ToolResult:
        try:
            if action == "navigate":
                if not url:
                    return ToolResult(
                        success=False,
                        output="",
                        error="navigate action requires url parameter",
                    )
                return self._navigate(url)
            elif action == "screenshot":
                return self._screenshot()
            elif action == "get_dom_snapshot":
                return self._get_dom_snapshot()
            else:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Unknown action: {action}. Use: navigate, screenshot, get_dom_snapshot",
                )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Browser tool failed: {e}. Ensure Chrome is running with --remote-debugging-port=9222",
            )

    def _navigate(self, url: str) -> ToolResult:
        result = self._run_async(self._cdp_navigate(url))
        return result

    def _screenshot(self) -> ToolResult:
        result = self._run_async(self._cdp_screenshot())
        return result

    def _get_dom_snapshot(self) -> ToolResult:
        result = self._run_async(self._cdp_dom_snapshot())
        return result

    async def _get_ws_url(self) -> str:
        import httpx

        async with httpx.AsyncClient() as client:
            r = await client.get(f"{self.DEFAULT_CDP_URL}/json/list")
            if r.status_code != 200:
                raise RuntimeError(
                    f"Cannot connect to Chrome DevTools at {self.DEFAULT_CDP_URL}. "
                    "Start Chrome with: google-chrome --remote-debugging-port=9222"
                )
            pages = r.json()
            if not pages:
                raise RuntimeError("No browser pages found")
            ws_url = pages[0].get("webSocketDebuggerUrl")
            if not ws_url:
                raise RuntimeError("No WebSocket URL in Chrome response")
            return ws_url

    async def _cdp_send(
        self, ws: Any, method: str, params: Optional[dict] = None
    ) -> dict:
        msg_id = 1
        req = {"id": msg_id, "method": method}
        if params:
            req["params"] = params
        await ws.send(json.dumps(req))
        resp = await ws.recv()
        data = json.loads(resp)
        if "error" in data:
            raise RuntimeError(data["error"].get("message", str(data["error"])))
        return data.get("result", {})

    async def _cdp_navigate(self, url: str) -> ToolResult:
        import websockets

        ws_url = await self._get_ws_url()
        try:
            async with websockets.connect(ws_url) as ws:
                await self._cdp_send(ws, "Page.enable")
                result = await self._cdp_send(ws, "Page.navigate", {"url": url})
                load_state = result.get("loaderId", "")
                # Wait briefly for load
                await asyncio.sleep(1)
                return ToolResult(
                    success=True,
                    output=f"Navigated to {url}",
                )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )

    async def _cdp_screenshot(self) -> ToolResult:
        import websockets

        ws_url = await self._get_ws_url()
        async with websockets.connect(ws_url) as ws:
            await self._cdp_send(ws, "Page.enable")
            result = await self._cdp_send(ws, "Page.captureScreenshot")
            b64 = result.get("data", "")
            if b64:
                return ToolResult(
                    success=True,
                    output=f"Screenshot captured (base64, {len(b64)} chars). Save with: echo '{b64[:100]}...' | base64 -d > screenshot.png",
                )
            return ToolResult(success=False, output="", error="Screenshot capture returned no data")

    async def _cdp_dom_snapshot(self) -> ToolResult:
        import websockets

        ws_url = await self._get_ws_url()
        async with websockets.connect(ws_url) as ws:
            await self._cdp_send(ws, "DOM.enable")
            result = await self._cdp_send(ws, "DOM.getDocument", {"depth": 3})
            # Simplify: just return a summary of the DOM structure
            doc = result.get("root", {})
            node_type = doc.get("nodeType", 0)
            child_count = len(doc.get("children", []))
            doc_type = doc.get("nodeName", "Document")
            summary = f"DOM snapshot: {doc_type} node, {child_count} top-level children"
            return ToolResult(success=True, output=summary)
