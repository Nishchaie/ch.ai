"""Tests for Team creation and member management.

Note: run_task is not tested here because it requires a real provider.
"""

import pytest

from chai.config import ProjectConfig, StackConfig
from chai.core.team import Team
from chai.types import (
    AgentConfig,
    AutonomyLevel,
    ProviderType,
    RoleType,
    TeamConfig,
    TeamState,
)


@pytest.fixture
def project_config() -> ProjectConfig:
    return ProjectConfig()


class TestTeam:
    """Test Team creation and member management."""

    def test_team_creation(self, project_config: ProjectConfig) -> None:
        config = TeamConfig(
            name="test-team",
            members={
                RoleType.LEAD: AgentConfig(role=RoleType.LEAD),
                RoleType.BACKEND: AgentConfig(role=RoleType.BACKEND),
            },
        )
        team = Team(config=config, project_config=project_config)
        assert team.state == TeamState.IDLE
        assert team.get_members()[RoleType.LEAD].role == RoleType.LEAD

    def test_add_member(self, project_config: ProjectConfig) -> None:
        config = TeamConfig(name="test", members={})
        team = Team(config=config, project_config=project_config)
        assert len(team.get_members()) == 0
        team.add_member(AgentConfig(role=RoleType.LEAD))
        assert RoleType.LEAD in team.get_members()
        team.add_member(AgentConfig(role=RoleType.LEAD, autonomy_level=AutonomyLevel.HIGH))
        assert team.get_members()[RoleType.LEAD].autonomy_level == AutonomyLevel.HIGH

    def test_remove_member(self, project_config: ProjectConfig) -> None:
        config = TeamConfig(
            name="test",
            members={
                RoleType.LEAD: AgentConfig(role=RoleType.LEAD),
                RoleType.BACKEND: AgentConfig(role=RoleType.BACKEND),
            },
        )
        team = Team(config=config, project_config=project_config)
        assert RoleType.BACKEND in team.get_members()
        team.remove_member(RoleType.BACKEND)
        assert RoleType.BACKEND not in team.get_members()
        assert RoleType.LEAD in team.get_members()

    def test_get_status(self, project_config: ProjectConfig) -> None:
        config = TeamConfig(
            name="test-team",
            members={
                RoleType.LEAD: AgentConfig(role=RoleType.LEAD, provider=ProviderType.CLAUDE_CODE),
                RoleType.QA: AgentConfig(role=RoleType.QA),
            },
            max_concurrent_agents=3,
        )
        team = Team(config=config, project_config=project_config)
        status = team.get_status()
        assert status["state"] == "idle"
        assert status["name"] == "test-team"
        assert status["max_concurrent_agents"] == 3
        assert "lead" in status["members"]
        assert "qa" in status["members"]


class TestClarifyStack:
    """Test the _clarify_stack mechanism."""

    def test_clarify_skipped_when_explicit(self) -> None:
        """When stack._explicit is True, clarify callback is never called."""
        stack = StackConfig(frontend="Vue 3", _explicit=True)
        pc = ProjectConfig(stack=stack)
        config = TeamConfig(
            name="test",
            members={RoleType.FRONTEND: AgentConfig(role=RoleType.FRONTEND)},
        )
        calls: list[str] = []

        def spy_clarify(question: str, default: str = "", field: str = "") -> str:
            calls.append(field)
            return default

        team = Team(config=config, project_config=pc, clarify=spy_clarify)
        team._clarify_stack()
        assert calls == [], "Clarify should not fire when stack is explicit"

    def test_clarify_fires_when_not_explicit(self) -> None:
        """When stack._explicit is False, clarify is called for each team role."""
        pc = ProjectConfig()
        config = TeamConfig(
            name="test",
            members={
                RoleType.FRONTEND: AgentConfig(role=RoleType.FRONTEND),
                RoleType.BACKEND: AgentConfig(role=RoleType.BACKEND),
            },
        )
        calls: list[str] = []

        def spy_clarify(question: str, default: str = "", field: str = "") -> str:
            calls.append(field)
            return default

        team = Team(config=config, project_config=pc, clarify=spy_clarify)
        team._clarify_stack()
        assert "stack.frontend" in calls
        assert "stack.backend" in calls

    def test_clarify_updates_prompts_on_change(self) -> None:
        """When the user provides different values, role prompts get rebuilt."""
        pc = ProjectConfig()
        config = TeamConfig(
            name="test",
            members={RoleType.FRONTEND: AgentConfig(role=RoleType.FRONTEND)},
        )

        def override_clarify(question: str, default: str = "", field: str = "") -> str:
            if field == "stack.frontend":
                return "Svelte, TypeScript"
            return default

        team = Team(config=config, project_config=pc, clarify=override_clarify)
        team._clarify_stack()

        fe = team._role_registry.get_role(RoleType.FRONTEND)
        assert "Svelte" in fe.system_prompt_template
        assert "React" not in fe.system_prompt_template
