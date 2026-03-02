"""Anthropic API provider - direct integration with Claude via Python SDK."""

from __future__ import annotations

import json
from typing import Any, Dict, Generator, List, Optional, Union

from .base import Provider, ProviderResponse, StreamChunk, ToolCall
from .rate_limiter import RateLimiter


class AnthropicAPIProvider(Provider):
    """Provider for Anthropic Claude API. ch.ai manages the tool loop."""

    RATE_LIMIT = 50  # Requests per minute for tier 1

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        super().__init__(api_key, model, base_url)
        if not self.api_key:
            raise ValueError("Anthropic API requires api_key")
        self._model = self.model or "claude-sonnet-4-6"
        self.rate_limiter = RateLimiter(
            max_requests=self.RATE_LIMIT, window_seconds=60.0
        )

    @property
    def manages_own_tools(self) -> bool:
        return False

    def _get_client(self):  # type: ignore
        import anthropic

        return anthropic.Anthropic(api_key=self.api_key)

    def _convert_messages(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Convert ch.ai message format to Anthropic API format."""
        result: List[Dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if isinstance(content, str):
                result.append({"role": role, "content": content})
                continue

            if isinstance(content, list):
                # Tool results and tool_use blocks
                blocks: List[Dict[str, Any]] = []
                for block in content:
                    if block.get("type") == "text":
                        blocks.append({"type": "text", "text": block.get("text", "")})
                    elif block.get("type") == "tool_use":
                        blocks.append({
                            "type": "tool_use",
                            "id": block.get("id", ""),
                            "name": block.get("name", ""),
                            "input": block.get("input", {}),
                        })
                    elif block.get("type") == "tool_result":
                        blocks.append({
                            "type": "tool_result",
                            "tool_use_id": block.get("tool_use_id", ""),
                            "content": block.get("content", ""),
                        })
                if blocks:
                    result.append({"role": role, "content": blocks})
        return result

    def chat(
        self,
        messages: List[Dict[str, Any]],
        system: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 8192,
        stream: bool = False,
    ) -> Union[ProviderResponse, Generator[StreamChunk, None, ProviderResponse]]:
        self.rate_limiter.acquire()

        client = self._get_client()
        api_messages = self._convert_messages(messages)

        kwargs: Dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": api_messages,
        }
        if tools:
            kwargs["tools"] = tools

        if stream:
            return self._stream(client, kwargs)
        return self._chat_sync(client, kwargs)

    def _chat_sync(
        self, client: Any, kwargs: Dict[str, Any]
    ) -> ProviderResponse:
        response = client.messages.create(**kwargs)
        return self._parse_response(response)

    def _stream(
        self, client: Any, kwargs: Dict[str, Any]
    ) -> Generator[StreamChunk, None, ProviderResponse]:
        text_buffer = ""
        tool_calls: List[ToolCall] = []
        current_tool: Optional[Dict[str, Any]] = None
        stop_reason: Optional[str] = None
        usage: Optional[Dict[str, int]] = None

        with client.messages.stream(**kwargs) as stream:
            for event in stream:
                if event.type == "content_block_start":
                    block = event.content_block
                    if hasattr(block, "type") and getattr(block, "type") == "tool_use":
                        current_tool = {
                            "id": getattr(block, "id", ""),
                            "name": getattr(block, "name", ""),
                            "input": "",
                        }
                        yield StreamChunk(type="tool_call_start", data=current_tool)
                elif event.type == "content_block_delta":
                    delta = event.delta
                    if hasattr(delta, "type"):
                        if getattr(delta, "type") == "text_delta":
                            text = getattr(delta, "text", "")
                            text_buffer += text
                            yield StreamChunk(type="text", data=text)
                        elif getattr(delta, "type") == "input_json_delta":
                            if current_tool:
                                current_tool["input"] += getattr(
                                    delta, "partial_json", ""
                                )
                elif event.type == "content_block_stop":
                    if current_tool:
                        try:
                            args = json.loads(current_tool["input"])
                        except json.JSONDecodeError:
                            args = {}
                        tool_calls.append(
                            ToolCall(
                                id=current_tool["id"],
                                name=current_tool["name"],
                                arguments=args,
                            )
                        )
                        yield StreamChunk(type="tool_call_end", data=current_tool)
                    current_tool = None
                elif event.type == "message_delta":
                    if hasattr(event, "delta") and event.delta:
                        stop_reason = getattr(event.delta, "stop_reason", None)
                elif event.type == "message_stop":
                    if hasattr(event, "usage") and event.usage:
                        usage = {
                            "input_tokens": getattr(event.usage, "input_tokens", 0),
                            "output_tokens": getattr(
                                event.usage, "output_tokens", 0
                            ),
                        }

        return ProviderResponse(
            text=text_buffer,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            usage=usage,
        )

    def _parse_response(self, response: Any) -> ProviderResponse:
        text = ""
        tool_calls: List[ToolCall] = []

        for block in response.content:
            if getattr(block, "type", "") == "text":
                text += getattr(block, "text", "")
            elif getattr(block, "type", "") == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=getattr(block, "id", ""),
                        name=getattr(block, "name", ""),
                        arguments=getattr(block, "input", {}) or {},
                    )
                )

        usage = None
        if hasattr(response, "usage") and response.usage:
            usage = {
                "input_tokens": getattr(response.usage, "input_tokens", 0),
                "output_tokens": getattr(response.usage, "output_tokens", 0),
            }

        return ProviderResponse(
            text=text,
            tool_calls=tool_calls,
            stop_reason=getattr(response, "stop_reason", None),
            usage=usage,
        )

    def make_tool_schema(self, tools: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Convert ch.ai tool schemas to Anthropic format."""
        result: List[Dict[str, Any]] = []
        for name, tool_info in tools.items():
            if isinstance(tool_info, dict) and "input_schema" in tool_info:
                schema = tool_info["input_schema"]
                properties = schema.get("properties", {})
                required = schema.get("required", [])
            else:
                properties = tool_info.get("parameters", {})
                required = [
                    k for k, v in properties.items()
                    if not v.get("optional", False)
                ]
            result.append({
                "name": name,
                "description": tool_info.get("description", ""),
                "input_schema": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            })
        return result

    def format_tool_result(self, tool_call_id: str, result: str) -> Dict[str, Any]:
        return {
            "type": "tool_result",
            "tool_use_id": tool_call_id,
            "content": result,
        }
