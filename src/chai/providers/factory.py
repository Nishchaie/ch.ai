"""Provider factory - resolve ProviderType to Provider instance."""

from __future__ import annotations

from typing import Callable, Optional

from .base import Provider
from ..config import get_config


def create_provider(provider_type: str, model: Optional[str] = None) -> Provider:
    """Create a Provider instance for the given type and model."""
    config = get_config()
    api_key = config.get_api_key(provider_type)
    model = model or config.default_model

    if provider_type == "claude_code":
        from .claude_code import ClaudeCodeProvider
        return ClaudeCodeProvider(api_key=api_key, model=model)
    elif provider_type == "codex":
        from .codex import CodexProvider
        return CodexProvider(api_key=api_key, model=model)
    elif provider_type == "anthropic_api":
        from .anthropic_api import AnthropicAPIProvider
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY required for anthropic_api provider")
        return AnthropicAPIProvider(api_key=api_key, model=model)
    elif provider_type == "openai_api":
        try:
            from .openai_api import OpenAIAPIProvider
        except ImportError:
            raise NotImplementedError("OpenAI API provider not yet implemented")
        if not api_key:
            raise ValueError("OPENAI_API_KEY required for openai_api provider")
        return OpenAIAPIProvider(api_key=api_key, model=model)
    elif provider_type == "custom":
        from .custom import CustomProvider
        if not config.custom_base_url or not config.custom_model:
            raise ValueError("custom_base_url and custom_model required for custom provider")
        return CustomProvider(
            api_key=api_key,
            model=config.custom_model,
            base_url=config.custom_base_url,
        )
    else:
        raise ValueError(f"Unknown provider: {provider_type}")
