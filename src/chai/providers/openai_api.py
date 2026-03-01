"""OpenAI API provider - direct integration via Python SDK."""

from __future__ import annotations

import json
from typing import Any, Dict, Generator, List, Optional, Union

from .base import Provider, ProviderResponse, StreamChunk, ToolCall


class OpenAIAPIProvider(Provider):
    """Provider for OpenAI API. ch.ai manages the tool loop."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        super().__init__(api_key, model, base_url)
        if not self.api_key:
            raise ValueError("OpenAI API requires api_key")
        self._model = self.model or "gpt-4o"
        self._base_url = base_url

    @property
    def manages_own_tools(self) -> bool:
        return False

    def _get_client(self):  # type: ignore
        import openai

        kwargs: Dict[str, Any] = {"api_key": self.api_key}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        return openai.OpenAI(**kwargs)

    def _convert_messages(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Convert ch.ai message format to OpenAI format."""
        result: List[Dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if isinstance(content, str):
                result.append({"role": role, "content": content})
                continue

            if isinstance(content, list):
                if content and content[0].get("type") == "tool_result":
                    for block in content:
                        result.append({
                            "role": "tool",
                            "tool_call_id": block.get("tool_use_id", ""),
                            "content": block.get("content", ""),
                        })
                    continue

                text_parts: List[str] = []
                tool_calls_list: List[Dict[str, Any]] = []
                for block in content:
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        tool_calls_list.append({
                            "id": block.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": block.get("name", ""),
                                "arguments": json.dumps(block.get("input", {})),
                            },
                        })

                out: Dict[str, Any] = {"role": role}
                if text_parts:
                    out["content"] = "".join(text_parts)
                else:
                    out["content"] = None
                if tool_calls_list:
                    out["tool_calls"] = tool_calls_list
                result.append(out)
        return result

    def chat(
        self,
        messages: List[Dict[str, Any]],
        system: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 8192,
        stream: bool = False,
    ) -> Union[ProviderResponse, Generator[StreamChunk, None, ProviderResponse]]:
        client = self._get_client()
        api_messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system}
        ]
        api_messages.extend(self._convert_messages(messages))

        kwargs: Dict[str, Any] = {
            "model": self._model,
            "messages": api_messages,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        kwargs["stream"] = stream

        if stream:
            return self._stream(client, kwargs)
        return self._chat_sync(client, kwargs)

    def _chat_sync(
        self, client: Any, kwargs: Dict[str, Any]
    ) -> ProviderResponse:
        response = client.chat.completions.create(**kwargs)
        return self._parse_response(response)

    def _parse_response(self, response: Any) -> ProviderResponse:
        choice = response.choices[0] if response.choices else None
        if not choice:
            return ProviderResponse(text="")

        message = choice.message
        text = message.content or ""
        tool_calls: List[ToolCall] = []

        for tc in getattr(message, "tool_calls", []) or []:
            func = getattr(tc, "function", None)
            if func is None:
                continue
            args_str = getattr(func, "arguments", "{}") or "{}"
            try:
                args = json.loads(args_str)
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(
                ToolCall(
                    id=getattr(tc, "id", ""),
                    name=getattr(func, "name", ""),
                    arguments=args,
                )
            )

        usage = None
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                "completion_tokens": getattr(response.usage, "completion_tokens", 0),
            }

        return ProviderResponse(
            text=text,
            tool_calls=tool_calls,
            stop_reason=getattr(choice, "finish_reason", None),
            usage=usage,
        )

    def _stream(
        self, client: Any, kwargs: Dict[str, Any]
    ) -> Generator[StreamChunk, None, ProviderResponse]:
        text_buffer = ""
        tool_calls_buffer: Dict[int, Dict[str, Any]] = {}
        stop_reason: Optional[str] = None
        usage: Optional[Dict[str, int]] = None

        stream = client.chat.completions.create(**kwargs)
        for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta

            if delta.content:
                text_buffer += delta.content
                yield StreamChunk(type="text", data=delta.content)

            if hasattr(delta, "tool_calls") and delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = getattr(tc, "index", 0)
                    if idx not in tool_calls_buffer:
                        tool_calls_buffer[idx] = {
                            "id": getattr(tc, "id", ""),
                            "name": "",
                            "arguments": "",
                        }
                    if hasattr(tc, "function") and tc.function:
                        func = tc.function
                        if hasattr(func, "name") and func.name:
                            tool_calls_buffer[idx]["name"] = func.name
                        if hasattr(func, "arguments") and func.arguments:
                            tool_calls_buffer[idx]["arguments"] += func.arguments

            if choice.finish_reason:
                stop_reason = choice.finish_reason
            if hasattr(chunk, "usage") and chunk.usage:
                usage = {
                    "prompt_tokens": getattr(chunk.usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(chunk.usage, "completion_tokens", 0),
                }

        tool_calls = []
        for tc in tool_calls_buffer.values():
            try:
                args = json.loads(tc["arguments"]) if tc["arguments"] else {}
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(
                ToolCall(id=tc["id"], name=tc["name"], arguments=args)
            )

        return ProviderResponse(
            text=text_buffer,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            usage=usage,
        )

    def make_tool_schema(self, tools: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Convert ch.ai tool schemas to OpenAI function format."""
        result: List[Dict[str, Any]] = []
        for name, tool_info in tools.items():
            if isinstance(tool_info, dict) and "input_schema" in tool_info:
                schema = tool_info["input_schema"]
                params = {
                    "type": "object",
                    "properties": schema.get("properties", {}),
                    "required": schema.get("required", []),
                }
            else:
                properties = tool_info.get("parameters", {})
                required = [
                    k for k, v in properties.items()
                    if not v.get("optional", False)
                ]
                params = {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                }
            result.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool_info.get("description", ""),
                    "parameters": params,
                },
            })
        return result

    def format_tool_result(self, tool_call_id: str, result: str) -> Dict[str, Any]:
        return {
            "type": "tool_result",
            "tool_use_id": tool_call_id,
            "content": result,
        }
