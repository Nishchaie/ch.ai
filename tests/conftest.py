"""Shared test fixtures for ch.ai."""

import os
import tempfile
from pathlib import Path

import pytest

from chai.types import (
    AgentConfig,
    AutonomyLevel,
    ProviderType,
    RoleType,
    TaskSpec,
    TeamConfig,
)


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project directory with basic structure."""
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "chai.yaml").write_text(
        "team:\n  name: test-team\n  default_provider: claude_code\n"
    )
    return tmp_path


@pytest.fixture
def sample_team_config() -> TeamConfig:
    return TeamConfig(
        name="test-team",
        members={
            RoleType.LEAD: AgentConfig(
                role=RoleType.LEAD,
                autonomy_level=AutonomyLevel.HIGH,
            ),
            RoleType.BACKEND: AgentConfig(
                role=RoleType.BACKEND,
                autonomy_level=AutonomyLevel.MEDIUM,
            ),
            RoleType.QA: AgentConfig(
                role=RoleType.QA,
                autonomy_level=AutonomyLevel.MEDIUM,
            ),
        },
        max_concurrent_agents=2,
    )


@pytest.fixture
def sample_tasks() -> list[TaskSpec]:
    return [
        TaskSpec(
            id="be-api",
            title="Build API endpoints",
            role=RoleType.BACKEND,
        ),
        TaskSpec(
            id="qa-tests",
            title="Write test suite",
            role=RoleType.QA,
            dependencies=["be-api"],
        ),
    ]
