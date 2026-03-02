"""Tests for ComplexityRouter (LLM-based with CLI fallback)."""

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


def _mock_api_response(strategy: str, reason: str, roles: Any = None) -> MagicMock:
    """Build a mock Anthropic API response."""
    payload = {"strategy": strategy, "reason": reason, "suggested_roles": roles}
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps(payload)
    response = MagicMock()
    response.content = [block]
    return response


def _mock_cli_result(strategy: str, reason: str, roles: Any = None) -> subprocess.CompletedProcess:
    """Build a mock subprocess.run result from Claude Code CLI."""
    payload = {"strategy": strategy, "reason": reason, "suggested_roles": roles}
    return subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps(payload), stderr=""
    )


class TestAPIRouting:
    """Tests the Anthropic API path."""

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    @patch("anthropic.Anthropic")
    def test_simple_prompt_routes_direct(self, mock_cls: MagicMock, router: ComplexityRouter) -> None:
        mock_cls.return_value.messages.create.return_value = _mock_api_response(
            "direct", "Simple question"
        )
        result = router.classify("what does this function do?")
        assert result.strategy == ExecutionStrategy.DIRECT
        assert result.reason == "Simple question"

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    @patch("anthropic.Anthropic")
    def test_build_prompt_routes_full_pipeline(self, mock_cls: MagicMock, router: ComplexityRouter) -> None:
        mock_cls.return_value.messages.create.return_value = _mock_api_response(
            "full_pipeline",
            "Building a complete application",
            ["lead", "frontend", "backend", "qa"],
        )
        result = router.classify("Build me a workday replacement")
        assert result.strategy == ExecutionStrategy.FULL_PIPELINE
        assert result.suggested_roles is not None


class TestCLIRouting:
    """Tests the Claude Code CLI fallback path."""

    @patch.dict("os.environ", {}, clear=True)
    @patch("shutil.which", return_value="/usr/local/bin/claude")
    @patch("subprocess.run")
    def test_cli_fallback_on_no_api_key(
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

    @patch.dict("os.environ", {}, clear=True)
    @patch("shutil.which", return_value="/usr/local/bin/claude")
    @patch("subprocess.run")
    def test_cli_passes_haiku_model(
        self, mock_run: MagicMock, mock_which: MagicMock, router: ComplexityRouter
    ) -> None:
        mock_run.return_value = _mock_cli_result("direct", "Simple fix")
        router.classify("fix a typo")
        args = mock_run.call_args[0][0]
        assert any("claude-haiku-4-5" in a for a in args)


class TestFallbackHeuristic:
    """Tests the last-resort heuristic when neither API nor CLI is available."""

    def _classify_with_heuristic(self, router: ComplexityRouter, prompt: str) -> RoutingResult:
        with patch.object(router, "_classify_api", side_effect=ValueError("no key")), \
             patch.object(router, "_classify_cli", side_effect=FileNotFoundError("no cli")):
            return router.classify(prompt)

    def test_short_prompt_direct(self, router: ComplexityRouter) -> None:
        result = self._classify_with_heuristic(router, "check the logs")
        assert result.strategy == ExecutionStrategy.DIRECT

    def test_build_verb_small_team(self, router: ComplexityRouter) -> None:
        result = self._classify_with_heuristic(router, "build a new login page")
        assert result.strategy == ExecutionStrategy.SMALL_TEAM

    def test_build_at_scale_full_pipeline(self, router: ComplexityRouter) -> None:
        result = self._classify_with_heuristic(
            router, "build me a replica of workday the hr software"
        )
        assert result.strategy == ExecutionStrategy.FULL_PIPELINE
        assert result.suggested_roles is not None

    def test_long_prompt_small_team(self, router: ComplexityRouter) -> None:
        result = self._classify_with_heuristic(
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
