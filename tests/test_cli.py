"""Tests for CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from chai.cli import cli, _build_augmented_prompt, _extract_run_summary
from chai.types import AgentEvent, RoleType, TaskSpec, TaskStatus, TeamRunResult


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_cli_help(runner: CliRunner) -> None:
    """CLI help works."""
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "ch.ai" in result.output


def test_init_help(runner: CliRunner) -> None:
    """chai init help works."""
    result = runner.invoke(cli, ["init", "--help"])
    assert result.exit_code == 0


def test_run_help(runner: CliRunner) -> None:
    """chai run help works."""
    result = runner.invoke(cli, ["run", "--help"])
    assert result.exit_code == 0
    assert "prompt" in result.output.lower()


def test_agent_help(runner: CliRunner) -> None:
    """chai agent help works."""
    result = runner.invoke(cli, ["agent", "--help"])
    assert result.exit_code == 0
    assert "role" in result.output.lower()


def test_team_help(runner: CliRunner) -> None:
    """chai team help works."""
    result = runner.invoke(cli, ["team", "--help"])
    assert result.exit_code == 0


def test_team_create_help(runner: CliRunner) -> None:
    """chai team create help works."""
    result = runner.invoke(cli, ["team", "create", "--help"])
    assert result.exit_code == 0


def test_team_status_help(runner: CliRunner) -> None:
    """chai team status help works."""
    result = runner.invoke(cli, ["team", "status", "--help"])
    assert result.exit_code == 0


def test_plan_help(runner: CliRunner) -> None:
    """chai plan help works."""
    result = runner.invoke(cli, ["plan", "--help"])
    assert result.exit_code == 0


def test_plan_create_help(runner: CliRunner) -> None:
    """chai plan create help works."""
    result = runner.invoke(cli, ["plan", "create", "--help"])
    assert result.exit_code == 0


def test_plan_run_help(runner: CliRunner) -> None:
    """chai plan run help works."""
    result = runner.invoke(cli, ["plan", "run", "--help"])
    assert result.exit_code == 0


def test_plan_status_help(runner: CliRunner) -> None:
    """chai plan status help works."""
    result = runner.invoke(cli, ["plan", "status", "--help"])
    assert result.exit_code == 0


def test_config_help(runner: CliRunner) -> None:
    """chai config help works."""
    result = runner.invoke(cli, ["config", "--help"])
    assert result.exit_code == 0


def test_config_show_help(runner: CliRunner) -> None:
    """chai config show help works."""
    result = runner.invoke(cli, ["config", "show", "--help"])
    assert result.exit_code == 0


def test_config_set_help(runner: CliRunner) -> None:
    """chai config set help works."""
    result = runner.invoke(cli, ["config", "set", "--help"])
    assert result.exit_code == 0


def test_quality_help(runner: CliRunner) -> None:
    """chai quality help works."""
    result = runner.invoke(cli, ["quality", "--help"])
    assert result.exit_code == 0


def test_garden_help(runner: CliRunner) -> None:
    """chai garden help works."""
    result = runner.invoke(cli, ["garden", "--help"])
    assert result.exit_code == 0


def test_api_help(runner: CliRunner) -> None:
    """chai api help works."""
    result = runner.invoke(cli, ["api", "--help"])
    assert result.exit_code == 0
    assert "host" in result.output or "port" in result.output


def test_interactive_help(runner: CliRunner) -> None:
    """chai interactive help works."""
    result = runner.invoke(cli, ["interactive", "--help"])
    assert result.exit_code == 0


def test_init_creates_files(runner: CliRunner) -> None:
    """chai init creates chai.yaml and AGENTS.md."""
    import os

    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0
        assert os.path.exists("chai.yaml")
        assert os.path.exists("AGENTS.md")
        assert os.path.exists("docs/exec-plans")


def test_config_show(runner: CliRunner) -> None:
    """chai config show runs without error."""
    result = runner.invoke(cli, ["config", "show"])
    assert result.exit_code == 0
    assert "default_provider" in result.output or "config" in result.output.lower()


# ===================================================================
# Interactive Mode Tests
# ===================================================================

def _make_mock_harness(result: TeamRunResult | None = None):
    """Create a mock Harness that yields one event and returns result."""
    if result is None:
        result = TeamRunResult(
            tasks=[TaskSpec(id="t1", title="Test task", role=RoleType.BACKEND, status=TaskStatus.COMPLETED)],
            duration_seconds=5.0,
        )

    mock_harness = MagicMock()

    def fake_run(prompt, strategy_override=None, cancel_event=None):
        yield AgentEvent(type="info", data={"routing": "direct", "reason": "test"})
        return result

    mock_harness.run = MagicMock(side_effect=fake_run)

    routing_result = MagicMock()
    routing_result.strategy = "direct"
    mock_harness._router = MagicMock()
    mock_harness._router.classify = MagicMock(return_value=routing_result)
    mock_harness.create_team = MagicMock()

    return mock_harness


class TestInteractiveMode:
    """Tests for the interactive REPL mode."""

    def test_plain_text_triggers_run(self, runner: CliRunner) -> None:
        mock_harness = _make_mock_harness()
        with patch("chai.core.harness.Harness", return_value=mock_harness), \
             patch("chai.ui.terminal.TerminalUI") as mock_ui_cls:
            mock_ui = MagicMock()
            mock_ui_cls.return_value = mock_ui
            result = runner.invoke(cli, ["interactive"], input="hello world\n/quit\n")

        assert result.exit_code == 0
        mock_harness.run.assert_called_once()
        call_args = mock_harness.run.call_args
        assert "hello world" in call_args[0][0] or "hello world" in str(call_args)

    def test_run_command_dispatches(self, runner: CliRunner) -> None:
        mock_harness = _make_mock_harness()
        with patch("chai.core.harness.Harness", return_value=mock_harness), \
             patch("chai.ui.terminal.TerminalUI") as mock_ui_cls:
            mock_ui_cls.return_value = MagicMock()
            result = runner.invoke(cli, ["interactive"], input="/run fix the bug\n/quit\n")

        assert result.exit_code == 0
        mock_harness.run.assert_called_once()
        call_args = mock_harness.run.call_args
        assert "fix the bug" in call_args[0][0] or "fix the bug" in str(call_args)

    def test_run_command_no_args_shows_usage(self, runner: CliRunner) -> None:
        mock_harness = _make_mock_harness()
        with patch("chai.core.harness.Harness", return_value=mock_harness), \
             patch("chai.ui.terminal.TerminalUI") as mock_ui_cls:
            mock_ui_cls.return_value = MagicMock()
            result = runner.invoke(cli, ["interactive"], input="/run\n/quit\n")

        assert result.exit_code == 0
        assert "Usage" in result.output
        mock_harness.run.assert_not_called()

    def test_quit_exits(self, runner: CliRunner) -> None:
        with patch("chai.core.harness.Harness", return_value=MagicMock()), \
             patch("chai.ui.terminal.TerminalUI") as mock_ui_cls:
            mock_ui_cls.return_value = MagicMock()
            result = runner.invoke(cli, ["interactive"], input="/quit\n")

        assert result.exit_code == 0
        assert "Goodbye" in result.output

    def test_help_lists_commands(self, runner: CliRunner) -> None:
        with patch("chai.core.harness.Harness", return_value=MagicMock()), \
             patch("chai.ui.terminal.TerminalUI") as mock_ui_cls:
            mock_ui_cls.return_value = MagicMock()
            result = runner.invoke(cli, ["interactive"], input="/help\n/quit\n")

        assert result.exit_code == 0
        assert "/run" in result.output
        assert "/plan" in result.output
        assert "/history" in result.output
        assert "/new" in result.output
        assert "/clear" in result.output
        assert "/quit" in result.output

    def test_history_empty_session(self, runner: CliRunner) -> None:
        with patch("chai.core.harness.Harness", return_value=MagicMock()), \
             patch("chai.ui.terminal.TerminalUI") as mock_ui_cls:
            mock_ui_cls.return_value = MagicMock()
            result = runner.invoke(cli, ["interactive"], input="/history\n/quit\n")

        assert result.exit_code == 0
        assert "No runs" in result.output

    def test_history_shows_runs(self, runner: CliRunner) -> None:
        mock_harness = _make_mock_harness()
        with patch("chai.core.harness.Harness", return_value=mock_harness), \
             patch("chai.ui.terminal.TerminalUI") as mock_ui_cls:
            mock_ui_cls.return_value = MagicMock()
            result = runner.invoke(cli, ["interactive"], input="do something\n/history\n/quit\n")

        assert result.exit_code == 0
        assert "do something" in result.output

    def test_new_clears_session(self, runner: CliRunner) -> None:
        mock_harness = _make_mock_harness()
        with patch("chai.core.harness.Harness", return_value=mock_harness), \
             patch("chai.ui.terminal.TerminalUI") as mock_ui_cls:
            mock_ui_cls.return_value = MagicMock()
            result = runner.invoke(cli, ["interactive"], input="do something\n/new\n/history\n/quit\n")

        assert result.exit_code == 0
        assert "New session started" in result.output
        assert "No runs" in result.output

    def test_clear_clears_context(self, runner: CliRunner) -> None:
        mock_harness = _make_mock_harness()
        with patch("chai.core.harness.Harness", return_value=mock_harness), \
             patch("chai.ui.terminal.TerminalUI") as mock_ui_cls:
            mock_ui_cls.return_value = MagicMock()
            result = runner.invoke(cli, ["interactive"], input="do something\n/clear\n/history\n/quit\n")

        assert result.exit_code == 0
        assert "context cleared" in result.output
        assert "No runs" in result.output

    def test_exception_during_run_does_not_crash(self, runner: CliRunner) -> None:
        mock_harness = MagicMock()

        def failing_run(prompt, strategy_override=None, cancel_event=None):
            raise RuntimeError("Simulated failure")

        mock_harness.run = MagicMock(side_effect=failing_run)
        mock_harness._router = MagicMock()
        routing = MagicMock()
        routing.strategy = "direct"
        mock_harness._router.classify = MagicMock(return_value=routing)

        with patch("chai.core.harness.Harness", return_value=mock_harness), \
             patch("chai.ui.terminal.TerminalUI") as mock_ui_cls:
            mock_ui = MagicMock()
            mock_ui.format_error = lambda msg: f"[red]{msg}[/red]"
            mock_ui_cls.return_value = mock_ui
            result = runner.invoke(cli, ["interactive"], input="cause error\n/quit\n")

        assert result.exit_code == 0
        assert "Simulated failure" in result.output
        assert "Goodbye" in result.output

    def test_context_accumulates_across_runs(self, runner: CliRunner) -> None:
        call_prompts = []
        run_result = TeamRunResult(
            tasks=[TaskSpec(id="t1", title="Test task", role=RoleType.BACKEND, status=TaskStatus.COMPLETED)],
            duration_seconds=3.0,
        )

        mock_harness = MagicMock()

        def fake_run(prompt, strategy_override=None, cancel_event=None):
            call_prompts.append(prompt)
            yield AgentEvent(type="info", data={"routing": "direct", "reason": "test"})
            return run_result

        mock_harness.run = MagicMock(side_effect=fake_run)
        routing = MagicMock()
        routing.strategy = "direct"
        mock_harness._router = MagicMock()
        mock_harness._router.classify = MagicMock(return_value=routing)

        with patch("chai.core.harness.Harness", return_value=mock_harness), \
             patch("chai.ui.terminal.TerminalUI") as mock_ui_cls:
            mock_ui_cls.return_value = MagicMock()
            result = runner.invoke(
                cli, ["interactive"],
                input="add auth middleware\nfix the login bug\n/quit\n",
            )

        assert result.exit_code == 0
        assert len(call_prompts) == 2
        assert call_prompts[0] == "add auth middleware"
        assert "[Session history" in call_prompts[1]
        assert "add auth middleware" in call_prompts[1]
        assert "fix the login bug" in call_prompts[1]

    def test_unknown_command_shows_hint(self, runner: CliRunner) -> None:
        with patch("chai.core.harness.Harness", return_value=MagicMock()), \
             patch("chai.ui.terminal.TerminalUI") as mock_ui_cls:
            mock_ui_cls.return_value = MagicMock()
            result = runner.invoke(cli, ["interactive"], input="/foobar\n/quit\n")

        assert result.exit_code == 0
        assert "Unknown command" in result.output

    def test_empty_input_is_noop(self, runner: CliRunner) -> None:
        mock_harness = MagicMock()
        with patch("chai.core.harness.Harness", return_value=mock_harness), \
             patch("chai.ui.terminal.TerminalUI") as mock_ui_cls:
            mock_ui_cls.return_value = MagicMock()
            result = runner.invoke(cli, ["interactive"], input="\n\n/quit\n")

        assert result.exit_code == 0
        mock_harness.run.assert_not_called()


class TestBuildAugmentedPrompt:
    """Tests for the _build_augmented_prompt helper."""

    def test_empty_context_returns_raw(self) -> None:
        assert _build_augmented_prompt("do something", []) == "do something"

    def test_single_entry(self) -> None:
        ctx = [{"prompt": "add auth", "outcome": "auth task [completed]"}]
        result = _build_augmented_prompt("fix login", ctx)
        assert "[Session history" in result
        assert "add auth" in result
        assert "fix login" in result
        assert "[Current request]" in result

    def test_truncates_long_outcomes(self) -> None:
        ctx = [{"prompt": "big task", "outcome": "x" * 2000}]
        result = _build_augmented_prompt("next task", ctx)
        assert len(result) < 1000

    def test_multiple_entries(self) -> None:
        ctx = [
            {"prompt": "step 1", "outcome": "done 1"},
            {"prompt": "step 2", "outcome": "done 2"},
        ]
        result = _build_augmented_prompt("step 3", ctx)
        assert "1. User: \"step 1\"" in result
        assert "2. User: \"step 2\"" in result
        assert "step 3" in result


class TestExtractRunSummary:
    """Tests for the _extract_run_summary helper."""

    def test_none_result(self) -> None:
        entry = _extract_run_summary("my prompt", None)
        assert entry["prompt"] == "my prompt"
        assert "failed" in entry["outcome"].lower() or "cancelled" in entry["outcome"].lower()

    def test_completed_result(self) -> None:
        result = TeamRunResult(
            tasks=[
                TaskSpec(id="t1", title="Auth task", role=RoleType.BACKEND, status=TaskStatus.COMPLETED),
            ],
            duration_seconds=10.0,
        )
        entry = _extract_run_summary("add auth", result)
        assert entry["prompt"] == "add auth"
        assert "Auth task" in entry["outcome"]
        assert "completed" in entry["outcome"]
        assert "10.0s" in entry["outcome"]

    def test_truncates_long_task_result(self) -> None:
        task = TaskSpec(id="t1", title="Big task", role=RoleType.BACKEND, status=TaskStatus.COMPLETED)
        task.result = "x" * 2000
        result = TeamRunResult(tasks=[task], duration_seconds=1.0)
        entry = _extract_run_summary("big", result)
        assert len(entry["outcome"]) < 600
