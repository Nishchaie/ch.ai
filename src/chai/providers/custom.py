"""Custom provider - OpenAI-compatible API with custom base_url (BYOM)."""

from __future__ import annotations

from typing import Any, Dict, Generator, List, Optional, Union

from .base import Provider, ProviderResponse, StreamChunk, ToolCall
from .openai_api import OpenAIAPIProvider


class CustomProvider(Provider):
    """Provider for OpenAI-compatible APIs. Wraps OpenAIAPIProvider with custom base_url."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        super().__init__(api_key, model, base_url)
        if not base_url:
            raise ValueError("Custom provider requires base_url")
        if not model:
            raise ValueError("Custom provider requires model")
        self._wrapped = OpenAIAPIProvider(
            api_key=api_key,
            model=model,
            base_url=base_url.rstrip("/") if base_url else None,
        )

    @property
    def manages_own_tools(self) -> bool:
        return False

    def chat(
        self,
        messages: List[Dict[str, Any]],
        system: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 8192,
        stream: bool = False,
    ) -> Union[ProviderResponse, Generator[StreamChunk, None, ProviderResponse]]:
        return self._wrapped.chat(
            messages=messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            stream=stream,
        )

    def make_tool_schema(self, tools: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self._wrapped.make_tool_schema(tools)

    def format_tool_result(self, tool_call_id: str, result: str) -> Dict[str, Any]:
        return self._wrapped.format_tool_result(tool_call_id, result)
