"""Base provider interface for all model integrations."""

from __future__ import annotations

import weakref
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional, Set, Union

_active_providers: Set["Provider"] = set()


def cancel_active_providers() -> None:
    """Kill all active provider subprocesses. Called from signal handlers."""
    for provider in list(_active_providers):
        try:
            provider.cancel()
        except Exception:
            pass


@dataclass
class ToolCall:
    """Represents a tool call requested by the model."""

    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class StreamChunk:
    """A chunk of streamed response from a provider."""

    type: str  # text, tool_call_start, tool_call_delta, tool_call_end
    data: Any


@dataclass
class ProviderResponse:
    """Complete response from a provider API call."""

    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    stop_reason: Optional[str] = None
    usage: Optional[Dict[str, int]] = None


class Provider(ABC):
    """Abstract base class for all AI providers.

    Two modes exist behind this interface:
    - CLI-wrapped (Claude Code, Codex): the external CLI handles tool execution
    - Direct API (Anthropic, OpenAI, Custom): ch.ai manages the agent loop
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

    @property
    @abstractmethod
    def manages_own_tools(self) -> bool:
        """Whether this provider manages its own tool execution (CLI-wrapped mode).

        If True, the harness sends a prompt and collects the final result.
        If False, the harness manages the tool call loop.
        """
        ...

    @abstractmethod
    def chat(
        self,
        messages: List[Dict[str, Any]],
        system: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 8192,
        stream: bool = False,
    ) -> Union[ProviderResponse, Generator[StreamChunk, None, ProviderResponse]]:
        """Send a chat request.

        For CLI-wrapped providers, tools param is ignored (the CLI has its own).
        For direct API providers, tools are formatted per provider spec.
        """
        ...

    @abstractmethod
    def make_tool_schema(self, tools: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Convert tool definitions to provider-specific schema format."""
        ...

    def cancel(self) -> None:
        """Cancel any active work. Subclasses with subprocesses should override."""

    def format_tool_result(self, tool_call_id: str, result: str) -> Dict[str, Any]:
        return {
            "type": "tool_result",
            "tool_use_id": tool_call_id,
            "content": result,
        }

    def format_assistant_message(self, response: ProviderResponse) -> Dict[str, Any]:
        content: List[Dict[str, Any]] = []
        if response.text:
            content.append({"type": "text", "text": response.text})
        for tc in response.tool_calls:
            content.append({
                "type": "tool_use",
                "id": tc.id,
                "name": tc.name,
                "input": tc.arguments,
            })
        return {"role": "assistant", "content": content}
