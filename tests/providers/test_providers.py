"""Tests for provider factory and providers."""

from __future__ import annotations

import pytest

from chai.providers import (
    get_provider,
    ClaudeCodeProvider,
    CodexProvider,
    AnthropicAPIProvider,
    OpenAIAPIProvider,
    CustomProvider,
    RateLimiter,
)


class TestProviderFactory:
    def test_get_provider_claude_code(self) -> None:
        p = get_provider("claude_code", model="claude-1")
        assert isinstance(p, ClaudeCodeProvider)
        assert p.manages_own_tools is True

    def test_get_provider_claude_code_normalized(self) -> None:
        p = get_provider("claude-code", model="x")
        assert isinstance(p, ClaudeCodeProvider)

    def test_get_provider_codex(self) -> None:
        p = get_provider("codex", model="codex-1")
        assert isinstance(p, CodexProvider)
        assert p.manages_own_tools is True

    def test_get_provider_anthropic_api(self) -> None:
        p = get_provider("anthropic_api", api_key="sk-test", model="claude-1")
        assert isinstance(p, AnthropicAPIProvider)
        assert p.manages_own_tools is False

    def test_get_provider_anthropic_requires_key(self) -> None:
        with pytest.raises(ValueError, match="api_key"):
            get_provider("anthropic_api", model="claude-1")

    def test_get_provider_openai_api(self) -> None:
        p = get_provider("openai_api", api_key="sk-test", model="gpt-4")
        assert isinstance(p, OpenAIAPIProvider)
        assert p.manages_own_tools is False

    def test_get_provider_openai_requires_key(self) -> None:
        with pytest.raises(ValueError, match="api_key"):
            get_provider("openai_api", model="gpt-4")

    def test_get_provider_custom(self) -> None:
        p = get_provider(
            "custom",
            api_key="sk-x",
            model="my-model",
            base_url="https://api.example.com/v1",
        )
        assert isinstance(p, CustomProvider)
        assert p.manages_own_tools is False

    def test_get_provider_custom_requires_base_url(self) -> None:
        with pytest.raises(ValueError, match="base_url"):
            get_provider("custom", api_key="x", model="m")

    def test_get_provider_custom_requires_model(self) -> None:
        with pytest.raises(ValueError, match="model"):
            get_provider("custom", api_key="x", base_url="https://x.com")

    def test_get_provider_unknown(self) -> None:
        with pytest.raises(ValueError, match="Unknown provider"):
            get_provider("unknown_provider")


class TestClaudeCodeProvider:
    def test_construction(self) -> None:
        p = ClaudeCodeProvider(model="claude-1")
        assert p.model == "claude-1"
        assert p.manages_own_tools is True

    def test_make_tool_schema_empty(self) -> None:
        p = ClaudeCodeProvider()
        assert p.make_tool_schema({"read": {}}) == []


class TestCodexProvider:
    def test_construction(self) -> None:
        p = CodexProvider(model="codex-1")
        assert p.model == "codex-1"
        assert p.manages_own_tools is True

    def test_make_tool_schema_empty(self) -> None:
        p = CodexProvider()
        assert p.make_tool_schema({"read": {}}) == []


class TestRateLimiter:
    def test_acquire_does_not_block_when_under_limit(self) -> None:
        r = RateLimiter(max_requests=10, window_seconds=60.0)
        for _ in range(5):
            r.acquire()

    def test_acquire_respects_limit(self) -> None:
        """With max_requests=2, two acquires succeed; third blocks until window slides."""
        import time

        r = RateLimiter(max_requests=2, window_seconds=0.5)
        r.acquire()
        r.acquire()
        # Third acquire will block ~0.5s until oldest request expires
        start = time.time()
        r.acquire()
        elapsed = time.time() - start
        assert elapsed >= 0.4  # Should have waited for window
