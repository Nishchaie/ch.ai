"""Provider layer for ch.ai - model integration."""

from __future__ import annotations

from typing import Any, Optional

from .base import Provider, ProviderResponse, StreamChunk, ToolCall
from .claude_code import ClaudeCodeProvider
from .codex import CodexProvider
from .anthropic_api import AnthropicAPIProvider
from .openai_api import OpenAIAPIProvider
from .custom import CustomProvider
from .rate_limiter import RateLimiter


def get_provider(
    provider_type: str,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    **kwargs: Any,
) -> Provider:
    """Factory function to create a provider by type.

    Args:
        provider_type: One of claude_code, codex, anthropic_api, openai_api, custom
        api_key: API key for the provider (required for API providers)
        model: Model name to use
        base_url: Custom API base URL (for custom provider)
        **kwargs: Additional provider-specific arguments

    Returns:
        Configured Provider instance
    """
    normalized = provider_type.lower().replace("-", "_")
    if normalized == "claude_code":
        return ClaudeCodeProvider(api_key=api_key, model=model, base_url=base_url)
    elif normalized == "codex":
        return CodexProvider(api_key=api_key, model=model, base_url=base_url)
    elif normalized == "anthropic_api":
        return AnthropicAPIProvider(api_key=api_key, model=model, base_url=base_url)
    elif normalized == "openai_api":
        return OpenAIAPIProvider(api_key=api_key, model=model, base_url=base_url)
    elif normalized == "custom":
        return CustomProvider(api_key=api_key, model=model, base_url=base_url)
    else:
        raise ValueError(f"Unknown provider type: {provider_type}")


__all__ = [
    "Provider",
    "ProviderResponse",
    "StreamChunk",
    "ToolCall",
    "RateLimiter",
    "ClaudeCodeProvider",
    "CodexProvider",
    "AnthropicAPIProvider",
    "OpenAIAPIProvider",
    "CustomProvider",
    "get_provider",
]
