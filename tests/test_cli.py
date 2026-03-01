"""Tests for CLI commands."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from chai.cli import cli


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
