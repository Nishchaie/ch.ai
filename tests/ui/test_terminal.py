"""Smoke tests for TerminalUI."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from chai.types import AgentEvent, RoleType, TaskSpec, TaskStatus
from chai.ui.terminal import TerminalUI


@pytest.fixture
def ui() -> TerminalUI:
    """TerminalUI with mocked console."""
    console = MagicMock()
    return TerminalUI(console=console)


def test_print_welcome(ui: TerminalUI) -> None:
    """print_welcome does not crash."""
    ui.print_welcome("anthropic_api", "claude-sonnet-4-5-20250929")
    assert ui.console.print.called


def test_print_event_text(ui: TerminalUI) -> None:
    """print_event handles text type."""
    evt = AgentEvent(type="text", data="Hello", role=RoleType.BACKEND)
    ui.print_event(evt)
    assert ui.console.print.called


def test_print_event_error(ui: TerminalUI) -> None:
    """print_event handles error type."""
    evt = AgentEvent(type="error", data="Something went wrong")
    ui.print_event(evt)
    assert ui.console.print.called


def test_print_event_status(ui: TerminalUI) -> None:
    """print_event handles status type."""
    evt = AgentEvent(type="status", data={"phase": "planning"})
    ui.print_event(evt)
    assert ui.console.print.called


def test_print_team_status(ui: TerminalUI) -> None:
    """print_team_status does not crash."""
    status = {
        "state": "idle",
        "members": {
            "lead": {"provider": "claude_code", "model": None, "autonomy": "high"},
            "backend": {"provider": "anthropic_api", "model": "claude-3", "autonomy": "medium"},
        },
    }
    ui.print_team_status(status)
    assert ui.console.print.called


def test_print_task_board(ui: TerminalUI) -> None:
    """print_task_board does not crash."""
    tasks = [
        TaskSpec(id="1", title="Task A", status=TaskStatus.PENDING, role=RoleType.BACKEND),
        TaskSpec(id="2", title="Task B", status=TaskStatus.IN_PROGRESS, role=RoleType.FRONTEND),
        TaskSpec(id="3", title="Task C", status=TaskStatus.COMPLETED, role=RoleType.QA),
    ]
    ui.print_task_board(tasks)
    assert ui.console.print.called


def test_print_quality_scores(ui: TerminalUI) -> None:
    """print_quality_scores does not crash."""
    scores = {
        "frontend": {"score": 0.8, "grade": "B"},
        "backend": {"score": 0.9, "grade": "A"},
    }
    ui.print_quality_scores(scores)
    assert ui.console.print.called


def test_format_helpers(ui: TerminalUI) -> None:
    """format_error, format_info, format_success return styled strings."""
    assert "[red]" in ui.format_error("err")
    assert "[blue]" in ui.format_info("info")
    assert "[green]" in ui.format_success("ok")
