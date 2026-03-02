"""Tests for ComplexityRouter (provider-aware LLM routing)."""

from __future__ import annotations

import json
import subprocess
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from chai.core.router import ComplexityRouter, ExecutionStrategy, RoutingResult, _parse_routing_json


@pytest.fixture
def router() -> ComplexityRouter:
    return ComplexityRouter()


def _mock_anthropic_response(strategy: str, reason: str, roles: Any = None) -> MagicMock:
    """Build a mock Anthropic API response."""
    payload = {"strategy": strategy, "reason": reason, "suggested_roles": roles}
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps(payload)
    response = MagicMock()
    response.content = [block]
    return response


def _mock_openai_response(strategy: str, reason: str, roles: Any = None) -> MagicMock:
    """Build a mock OpenAI API response."""
    payload = {"strategy": strategy, "reason": reason, "suggested_roles": roles}
    message = MagicMock()
    message.content = json.dumps(payload)
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _mock_cli_result(strategy: str, reason: str, roles: Any = None) -> subprocess.CompletedProcess:
    """Build a mock subprocess.run result from Claude Code CLI."""
    payload = {"strategy": strategy, "reason": reason, "suggested_roles": roles}
    return subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps(payload), stderr=""
    )


class TestCLIRouting:
    """Tests the Claude Code CLI path (tried first for claude_code provider)."""

    @patch("shutil.which", return_value="/usr/local/bin/claude")
    @patch("subprocess.run")
    def test_cli_routes_small_team(
        self, mock_run: MagicMock, mock_which: MagicMock, router: ComplexityRouter
    ) -> None:
        mock_run.return_value = _mock_cli_result(
            "small_team", "Moderate task", ["backend", "qa"]
        )
        result = router.classify("add a search endpoint with tests")
        assert result.strategy == ExecutionStrategy.SMALL_TEAM
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "claude"
        assert "--print" in args

    @patch("shutil.which", return_value="/usr/local/bin/claude")
    @patch("subprocess.run")
    def test_cli_passes_haiku_model(
        self, mock_run: MagicMock, mock_which: MagicMock, router: ComplexityRouter
    ) -> None:
        mock_run.return_value = _mock_cli_result("direct", "Simple fix")
        router.classify("fix a typo")
        args = mock_run.call_args[0][0]
        assert any("claude-haiku-4-5" in a for a in args)


class TestAnthropicAPIRouting:
    """Tests the Anthropic API path (fallback when CLI unavailable)."""

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    @patch("anthropic.Anthropic")
    @patch("shutil.which", return_value=None)
    def test_anthropic_fallback_routes_direct(
        self, mock_which: MagicMock, mock_cls: MagicMock, router: ComplexityRouter
    ) -> None:
        mock_cls.return_value.messages.create.return_value = _mock_anthropic_response(
            "direct", "Simple question"
        )
        result = router.classify("what does this function do?")
        assert result.strategy == ExecutionStrategy.DIRECT
        assert result.reason == "Simple question"

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    @patch("anthropic.Anthropic")
    @patch("shutil.which", return_value=None)
    def test_anthropic_fallback_routes_full_pipeline(
        self, mock_which: MagicMock, mock_cls: MagicMock, router: ComplexityRouter
    ) -> None:
        mock_cls.return_value.messages.create.return_value = _mock_anthropic_response(
            "full_pipeline",
            "Building a complete application",
            ["lead", "frontend", "backend", "qa"],
        )
        result = router.classify("Build me a workday replacement")
        assert result.strategy == ExecutionStrategy.FULL_PIPELINE
        assert result.suggested_roles is not None


class TestOpenAIRouting:
    """Tests the OpenAI API path (tried first for openai_api/codex providers)."""

    @patch("chai.config.get_config")
    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    @patch("openai.OpenAI")
    def test_openai_tried_first_for_openai_provider(
        self, mock_cls: MagicMock, mock_config: MagicMock, router: ComplexityRouter
    ) -> None:
        mock_config.return_value.default_provider = "openai_api"
        mock_config.return_value.get_api_key.return_value = "test-key"
        mock_cls.return_value.chat.completions.create.return_value = _mock_openai_response(
            "full_pipeline", "Complex app", ["lead", "frontend", "backend"]
        )
        result = router.classify("Build me a SaaS platform")
        assert result.strategy == ExecutionStrategy.FULL_PIPELINE
        mock_cls.return_value.chat.completions.create.assert_called_once()

    @patch("chai.config.get_config")
    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    @patch("openai.OpenAI")
    def test_openai_tried_first_for_codex_provider(
        self, mock_cls: MagicMock, mock_config: MagicMock, router: ComplexityRouter
    ) -> None:
        mock_config.return_value.default_provider = "codex"
        mock_config.return_value.get_api_key.return_value = "test-key"
        mock_cls.return_value.chat.completions.create.return_value = _mock_openai_response(
            "direct", "Simple task"
        )
        result = router.classify("fix a typo in README")
        assert result.strategy == ExecutionStrategy.DIRECT

    @patch("chai.config.get_config")
    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    @patch("openai.OpenAI")
    def test_openai_uses_gpt4o_mini(
        self, mock_cls: MagicMock, mock_config: MagicMock, router: ComplexityRouter
    ) -> None:
        mock_config.return_value.default_provider = "openai_api"
        mock_config.return_value.get_api_key.return_value = "test-key"
        mock_cls.return_value.chat.completions.create.return_value = _mock_openai_response(
            "direct", "Simple"
        )
        router.classify("check logs")
        call_kwargs = mock_cls.return_value.chat.completions.create.call_args
        assert call_kwargs[1]["model"] == "gpt-4o-mini" or call_kwargs.kwargs["model"] == "gpt-4o-mini"


class TestFallbackHeuristic:
    """Tests the last-resort heuristic when no LLM routing is available."""

    def _force_fallback(self, router: ComplexityRouter, prompt: str) -> RoutingResult:
        with patch.object(router, "_classify_cli", side_effect=FileNotFoundError("no cli")), \
             patch.object(router, "_classify_anthropic", side_effect=ValueError("no key")), \
             patch.object(router, "_classify_openai", side_effect=ValueError("no key")):
            return router.classify(prompt)

    def test_short_prompt_direct(self, router: ComplexityRouter) -> None:
        result = self._force_fallback(router, "check the logs")
        assert result.strategy == ExecutionStrategy.DIRECT

    def test_build_verb_small_team(self, router: ComplexityRouter) -> None:
        result = self._force_fallback(router, "build a new login page")
        assert result.strategy == ExecutionStrategy.SMALL_TEAM

    def test_build_at_scale_full_pipeline(self, router: ComplexityRouter) -> None:
        result = self._force_fallback(
            router, "build me a replica of workday the hr software"
        )
        assert result.strategy == ExecutionStrategy.FULL_PIPELINE
        assert result.suggested_roles is not None

    def test_long_prompt_small_team(self, router: ComplexityRouter) -> None:
        result = self._force_fallback(
            router, "add a search endpoint to the API that filters users by name and returns paginated results"
        )
        assert result.strategy == ExecutionStrategy.SMALL_TEAM


class TestParseRoutingJSON:
    def test_plain_json(self) -> None:
        r = _parse_routing_json('{"strategy": "direct", "reason": "Simple"}')
        assert r.strategy == ExecutionStrategy.DIRECT

    def test_json_with_markdown_fences(self) -> None:
        r = _parse_routing_json('```json\n{"strategy": "full_pipeline", "reason": "Complex"}\n```')
        assert r.strategy == ExecutionStrategy.FULL_PIPELINE

    def test_whitespace_padding(self) -> None:
        r = _parse_routing_json('  \n{"strategy": "small_team", "reason": "Moderate"}\n  ')
        assert r.strategy == ExecutionStrategy.SMALL_TEAM


class TestRoutingResult:
    def test_fields(self) -> None:
        r = RoutingResult(
            strategy=ExecutionStrategy.FULL_PIPELINE,
            reason="Complex task",
            suggested_roles=["frontend", "backend"],
        )
        assert r.strategy == ExecutionStrategy.FULL_PIPELINE
        assert r.suggested_roles == ["frontend", "backend"]

    def test_defaults(self) -> None:
        r = RoutingResult(strategy=ExecutionStrategy.DIRECT, reason="Simple")
        assert r.suggested_roles is None
