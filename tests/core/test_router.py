"""Tests for ComplexityRouter (provider-aware LLM routing with eager init)."""

from __future__ import annotations

import json
import subprocess
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from chai.core.router import ComplexityRouter, ExecutionStrategy, RoutingResult, _parse_routing_json


def _mock_config(provider: str = "claude_code") -> MagicMock:
    cfg = MagicMock()
    cfg.default_provider = provider
    cfg.get_api_key.return_value = None
    return cfg


def _mock_anthropic_response(strategy: str, reason: str, roles: Any = None) -> MagicMock:
    payload = {"strategy": strategy, "reason": reason, "suggested_roles": roles}
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps(payload)
    response = MagicMock()
    response.content = [block]
    return response


def _mock_openai_response(strategy: str, reason: str, roles: Any = None) -> MagicMock:
    payload = {"strategy": strategy, "reason": reason, "suggested_roles": roles}
    message = MagicMock()
    message.content = json.dumps(payload)
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _mock_cli_proc(strategy: str, reason: str, roles: Any = None, returncode: int = 0) -> MagicMock:
    """Build a mock Popen whose communicate() returns a JSON routing response."""
    payload = {"strategy": strategy, "reason": reason, "suggested_roles": roles}
    text = json.dumps(payload)

    proc = MagicMock()
    proc.communicate.return_value = (text, "")
    proc.returncode = returncode
    proc.poll.return_value = returncode
    return proc


def _make_router(**overrides: Any) -> ComplexityRouter:
    """Build a ComplexityRouter with all external deps mocked.

    By default: no CLI, no API keys, claude_code provider.
    Pass overrides to enable specific paths.
    """
    provider = overrides.get("provider", "claude_code")
    cli_path = overrides.get("cli_path", None)
    anthropic_key = overrides.get("anthropic_key", None)
    openai_key = overrides.get("openai_key", None)

    key_map = {}
    if anthropic_key:
        key_map["anthropic_api"] = anthropic_key
    if openai_key:
        key_map["openai_api"] = openai_key

    cfg = _mock_config(provider)
    cfg.get_api_key.side_effect = lambda k: key_map.get(k)

    with patch("chai.core.router.get_config", return_value=cfg), \
         patch("shutil.which", return_value=cli_path), \
         patch("subprocess.run"), \
         patch.dict("os.environ", {}, clear=False):
        return ComplexityRouter()


class TestCLIRouting:
    """Tests the Claude Code CLI path (uses Popen with communicate)."""

    def test_cli_routes_small_team(self) -> None:
        with patch("chai.core.router.get_config", return_value=_mock_config()), \
             patch("shutil.which", return_value="/usr/local/bin/claude"), \
             patch("subprocess.run"), \
             patch("subprocess.Popen") as mock_popen:
            router = ComplexityRouter()
            mock_popen.return_value = _mock_cli_proc(
                "small_team", "Moderate task", ["backend", "qa"]
            )
            result = router.classify("add a search endpoint with tests")

        assert result.strategy == ExecutionStrategy.SMALL_TEAM
        args = mock_popen.call_args[0][0]
        assert args[0] == "/usr/local/bin/claude"
        assert "--print" in args

    def test_cli_passes_haiku_model(self) -> None:
        with patch("chai.core.router.get_config", return_value=_mock_config()), \
             patch("shutil.which", return_value="/usr/local/bin/claude"), \
             patch("subprocess.run"), \
             patch("subprocess.Popen") as mock_popen:
            router = ComplexityRouter()
            mock_popen.return_value = _mock_cli_proc("direct", "Simple fix")
            router.classify("fix a typo")

        args = mock_popen.call_args[0][0]
        assert any("haiku" in str(a) for a in args)

    def test_cli_uses_plain_text_not_stream_json(self) -> None:
        with patch("chai.core.router.get_config", return_value=_mock_config()), \
             patch("shutil.which", return_value="/usr/local/bin/claude"), \
             patch("subprocess.run"), \
             patch("subprocess.Popen") as mock_popen:
            router = ComplexityRouter()
            mock_popen.return_value = _mock_cli_proc("direct", "Simple")
            router.classify("test")

        args = mock_popen.call_args[0][0]
        assert "--output-format=stream-json" not in args
        assert "--verbose" not in args

    def test_cli_error_includes_stderr(self) -> None:
        proc = _mock_cli_proc("direct", "Simple")
        proc.returncode = 1
        proc.communicate.return_value = ("", "Something went wrong")

        with patch("chai.core.router.get_config", return_value=_mock_config()), \
             patch("shutil.which", return_value="/usr/local/bin/claude"), \
             patch("subprocess.run"), \
             patch("subprocess.Popen", return_value=proc):
            router = ComplexityRouter()
            with pytest.raises(RuntimeError, match="Something went wrong"):
                router._classify_cli("test")

    def test_cli_warm_up_runs_on_init(self) -> None:
        with patch("chai.core.router.get_config", return_value=_mock_config()), \
             patch("shutil.which", return_value="/usr/local/bin/claude"), \
             patch("subprocess.run"):
            router = ComplexityRouter()
            import time
            time.sleep(0.1)

        assert router._cli_path == "/usr/local/bin/claude"


class TestAnthropicAPIRouting:
    """Tests the Anthropic API path."""

    def test_anthropic_routes_direct(self) -> None:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_anthropic_response(
            "direct", "Simple question"
        )

        with patch("chai.core.router.get_config", return_value=_mock_config()), \
             patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}), \
             patch("shutil.which", return_value=None), \
             patch("anthropic.Anthropic", return_value=mock_client), \
             patch("subprocess.run"):
            router = ComplexityRouter()

        result = router.classify("what does this function do?")
        assert result.strategy == ExecutionStrategy.DIRECT
        assert result.reason == "Simple question"

    def test_anthropic_routes_full_pipeline(self) -> None:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_anthropic_response(
            "full_pipeline",
            "Building a complete application",
            ["lead", "frontend", "backend", "qa"],
        )

        with patch("chai.core.router.get_config", return_value=_mock_config()), \
             patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}), \
             patch("shutil.which", return_value=None), \
             patch("anthropic.Anthropic", return_value=mock_client), \
             patch("subprocess.run"):
            router = ComplexityRouter()

        result = router.classify("Build me a workday replacement")
        assert result.strategy == ExecutionStrategy.FULL_PIPELINE
        assert result.suggested_roles is not None


class TestOpenAIRouting:
    """Tests the OpenAI API path."""

    def test_openai_tried_first_for_openai_provider(self) -> None:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            "full_pipeline", "Complex app", ["lead", "frontend", "backend"]
        )

        cfg = _mock_config("openai_api")
        with patch("chai.core.router.get_config", return_value=cfg), \
             patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), \
             patch("shutil.which", return_value=None), \
             patch("openai.OpenAI", return_value=mock_client), \
             patch("subprocess.run"):
            router = ComplexityRouter()

        result = router.classify("Build me a SaaS platform")
        assert result.strategy == ExecutionStrategy.FULL_PIPELINE
        mock_client.chat.completions.create.assert_called_once()

    def test_openai_tried_first_for_codex_provider(self) -> None:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            "direct", "Simple task"
        )

        cfg = _mock_config("codex")
        with patch("chai.core.router.get_config", return_value=cfg), \
             patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), \
             patch("shutil.which", return_value=None), \
             patch("openai.OpenAI", return_value=mock_client), \
             patch("subprocess.run"):
            router = ComplexityRouter()

        result = router.classify("fix a typo in README")
        assert result.strategy == ExecutionStrategy.DIRECT

    def test_openai_uses_gpt4o_mini(self) -> None:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            "direct", "Simple"
        )

        cfg = _mock_config("openai_api")
        with patch("chai.core.router.get_config", return_value=cfg), \
             patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), \
             patch("shutil.which", return_value=None), \
             patch("openai.OpenAI", return_value=mock_client), \
             patch("subprocess.run"):
            router = ComplexityRouter()

        router.classify("check logs")
        call_kwargs = mock_client.chat.completions.create.call_args
        assert call_kwargs[1]["model"] == "gpt-4o-mini" or call_kwargs.kwargs["model"] == "gpt-4o-mini"


class TestFallbackHeuristic:
    """Tests the keyword heuristic (called directly -- no LLM needed)."""

    def _router(self) -> ComplexityRouter:
        return _make_router()

    def test_short_prompt_direct(self) -> None:
        result = self._router()._classify_fallback("check the logs")
        assert result.strategy == ExecutionStrategy.DIRECT

    def test_build_verb_small_team(self) -> None:
        result = self._router()._classify_fallback("build a new login page")
        assert result.strategy == ExecutionStrategy.SMALL_TEAM

    def test_build_at_scale_full_pipeline(self) -> None:
        result = self._router()._classify_fallback(
            "build me a replica of workday the hr software"
        )
        assert result.strategy == ExecutionStrategy.FULL_PIPELINE
        assert result.suggested_roles is not None

    def test_build_modern_version_full_pipeline(self) -> None:
        result = self._router()._classify_fallback(
            "build me a mordern version of workday, it should be snappy, "
            "the UI theme should be like chatGPT, there should be a search bar "
            "like chat gpt on the homepage, to answer action all the things, "
            "and also all the tradional flows"
        )
        assert result.strategy == ExecutionStrategy.FULL_PIPELINE

    def test_long_build_with_many_features_full_pipeline(self) -> None:
        result = self._router()._classify_fallback(
            "create a project management tool with kanban boards, "
            "time tracking, team collaboration, notifications, "
            "and a mobile responsive dashboard with dark mode"
        )
        assert result.strategy == ExecutionStrategy.FULL_PIPELINE

    def test_long_prompt_small_team(self) -> None:
        result = self._router()._classify_fallback(
            "add a search endpoint to the API that filters users by name and returns paginated results"
        )
        assert result.strategy == ExecutionStrategy.SMALL_TEAM

    def test_no_classifiers_falls_back(self) -> None:
        """classify() returns fallback when no classifiers are available."""
        router = _make_router()
        assert router._classifiers == []
        result = router.classify("build a new login page")
        assert result.strategy == ExecutionStrategy.SMALL_TEAM
        assert "fallback" in result.reason


class TestEagerInit:
    """Tests that __init__ pre-builds the right classifier list."""

    def test_cli_only(self) -> None:
        router = _make_router(cli_path="/usr/local/bin/claude")
        assert len(router._classifiers) == 1
        assert router._classifiers[0].__name__ == "_classify_cli"

    def test_anthropic_only(self) -> None:
        with patch("anthropic.Anthropic"):
            router = _make_router(anthropic_key="sk-test")
        assert len(router._classifiers) == 1
        assert router._classifiers[0].__name__ == "_classify_anthropic"

    def test_openai_only(self) -> None:
        with patch("openai.OpenAI"):
            router = _make_router(openai_key="sk-test")
        assert len(router._classifiers) == 1
        assert router._classifiers[0].__name__ == "_classify_openai"

    def test_all_available_claude_provider(self) -> None:
        with patch("anthropic.Anthropic"), patch("openai.OpenAI"):
            router = _make_router(
                cli_path="/usr/local/bin/claude",
                anthropic_key="sk-ant",
                openai_key="sk-oai",
            )
        assert len(router._classifiers) == 3
        names = [fn.__name__ for fn in router._classifiers]
        assert names == ["_classify_cli", "_classify_anthropic", "_classify_openai"]

    def test_all_available_openai_provider(self) -> None:
        with patch("anthropic.Anthropic"), patch("openai.OpenAI"):
            router = _make_router(
                provider="openai_api",
                cli_path="/usr/local/bin/claude",
                anthropic_key="sk-ant",
                openai_key="sk-oai",
            )
        names = [fn.__name__ for fn in router._classifiers]
        assert names == ["_classify_openai", "_classify_cli", "_classify_anthropic"]

    def test_empty_when_nothing_available(self) -> None:
        router = _make_router()
        assert router._classifiers == []


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
