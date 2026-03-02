"""Harness: top-level runtime for ch.ai."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, Generator, Optional

from ..config import ProjectConfig, get_config
from ..providers.base import Provider
from ..types import AgentConfig, AgentEvent, AutonomyLevel, ProviderType, RoleType, TeamConfig, TeamRunResult
from .router import ComplexityRouter, ExecutionStrategy
from .team import Team

logger = logging.getLogger(__name__)


def _default_provider_factory(provider_type: str, model: Optional[str] = None) -> Provider:
    """Resolve ProviderType to Provider instance. Raises if not available."""
    raise NotImplementedError(
        f"No provider implementation for {provider_type}. "
        "Concrete providers (Anthropic, OpenAI, etc.) must be wired in."
    )


class Harness:
    """Top-level runtime: loads config, creates teams, runs prompts."""

    def __init__(
        self,
        project_dir: Optional[str] = None,
        provider_factory: Optional[Callable[[str, Optional[str]], Provider]] = None,
    ) -> None:
        self._project_dir = Path(project_dir) if project_dir else Path.cwd()
        self._config = get_config()
        self._project_config = ProjectConfig.load(str(self._project_dir))
        self._provider_factory = provider_factory or _default_provider_factory
        self._router = ComplexityRouter()

    def create_team(self, config: Optional[TeamConfig] = None) -> Team:
        """Create a team. Auto-configures from project if config not provided."""
        team_config = config or self.get_default_team_config()
        if self._project_config.team and not config:
            team_config = self._project_config.team
        return Team(
            config=team_config,
            project_config=self._project_config,
            project_dir=str(self._project_dir),
            provider_factory=self._provider_factory,
        )

    def run(
        self,
        prompt: str,
        team_config: Optional[TeamConfig] = None,
        strategy_override: Optional[ExecutionStrategy] = None,
    ) -> Generator[AgentEvent, None, TeamRunResult]:
        """Run a prompt through complexity-based routing.

        Routes to:
          DIRECT       -> single agent, no decomposition
          SMALL_TEAM   -> team decomposition, shared workspace
          FULL_PIPELINE -> team decomposition with worktrees + merge
        """
        team = self.create_team(team_config)

        routing = self._router.classify(prompt)
        strategy = strategy_override or routing.strategy
        logger.info("Routing: %s (%s)", strategy.value, routing.reason)

        yield AgentEvent(
            type="info",
            data={"routing": strategy.value, "reason": routing.reason},
        )

        if strategy == ExecutionStrategy.DIRECT:
            gen = team.run_direct(prompt)
        elif strategy == ExecutionStrategy.FULL_PIPELINE:
            gen = team.run_task(prompt, use_worktrees=True)
        else:
            gen = team.run_task(prompt, use_worktrees=False)

        result: Optional[TeamRunResult] = None
        try:
            while True:
                evt = next(gen)
                yield evt
        except StopIteration as e:
            result = e.value
        return result or TeamRunResult(tasks=[], events=[])

    def get_default_team_config(self) -> TeamConfig:
        """Sensible defaults: Lead + all 6 specialist roles."""
        return TeamConfig(
            name="default",
            members={
                RoleType.LEAD: AgentConfig(
                    role=RoleType.LEAD,
                    provider=ProviderType.CLAUDE_CODE,
                    model="claude-opus-4-6",
                    autonomy_level=AutonomyLevel.HIGH,
                ),
                RoleType.FRONTEND: AgentConfig(
                    role=RoleType.FRONTEND,
                    provider=ProviderType.CLAUDE_CODE,
                ),
                RoleType.BACKEND: AgentConfig(
                    role=RoleType.BACKEND,
                    provider=ProviderType.CLAUDE_CODE,
                ),
                RoleType.PROMPT: AgentConfig(
                    role=RoleType.PROMPT,
                    provider=ProviderType.CLAUDE_CODE,
                ),
                RoleType.RESEARCHER: AgentConfig(
                    role=RoleType.RESEARCHER,
                    provider=ProviderType.CLAUDE_CODE,
                ),
                RoleType.QA: AgentConfig(
                    role=RoleType.QA,
                    provider=ProviderType.CLAUDE_CODE,
                ),
                RoleType.DEPLOYMENT: AgentConfig(
                    role=RoleType.DEPLOYMENT,
                    provider=ProviderType.CLAUDE_CODE,
                ),
            },
            max_concurrent_agents=self._config.max_concurrent_agents,
            default_provider=ProviderType(self._config.default_provider),
            default_model=self._config.default_model,
        )

    def status(self) -> Dict[str, Any]:
        """Return harness status (project, config, default team info)."""
        team = self.create_team()
        return {
            "project_dir": str(self._project_dir),
            "default_provider": self._config.default_provider,
            "default_model": self._config.default_model,
            "team": team.get_status(),
        }