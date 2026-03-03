"""Harness: top-level runtime for ch.ai."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Generator, Optional

from ..config import ProjectConfig, get_config
from ..providers.base import Provider
from ..types import AgentConfig, AgentEvent, AutonomyLevel, ClarifyCallback, ProviderType, RoleType, TeamConfig, TeamRunResult, default_clarify
from .router import ComplexityRouter, ExecutionStrategy, RoutingResult
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
        clarify: Optional[ClarifyCallback] = None,
    ) -> None:
        self._project_dir = Path(project_dir) if project_dir else Path.cwd()
        self._config = get_config()
        self._project_config = ProjectConfig.load(str(self._project_dir))
        self._provider_factory = provider_factory or _default_provider_factory
        self._clarify = clarify or default_clarify
        self._router = ComplexityRouter()
        self._warm_provider()

    def _warm_provider(self) -> None:
        """Pre-warm the default provider in a background thread.

        For Claude Code, this starts a minimal CLI call so the session
        is ready (Node.js loaded, auth negotiated) by the time the first
        real ``chat()`` call happens.
        """
        if self._config.default_provider not in ("claude_code", "claude-code"):
            return
        try:
            provider = self._provider_factory(
                self._config.default_provider, self._config.default_model
            )
        except Exception:
            return
        if hasattr(provider, "warm"):
            provider.warm()
            self._warm_provider_instance = provider

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
            clarify=self._clarify,
        )

    def run(
        self,
        prompt: str,
        team_config: Optional[TeamConfig] = None,
        strategy_override: Optional[ExecutionStrategy] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> Generator[AgentEvent, None, TeamRunResult]:
        """Run a prompt through complexity-based routing.

        Routes to:
          DIRECT       -> single agent, no decomposition
          SMALL_TEAM   -> team decomposition, shared workspace
          FULL_PIPELINE -> team decomposition with worktrees + merge

        When no explicit team_config or project-level team is set, the
        router's suggested_roles are used to build a filtered team with
        only the roles the task actually needs.
        """
        if strategy_override:
            strategy = strategy_override
            reason = "strategy provided by caller"
            routing = None
        else:
            routing = self._router.classify(prompt)
            strategy = routing.strategy
            reason = routing.reason

        if team_config or self._project_config.team:
            team = self.create_team(team_config)
        else:
            filtered_config = self._build_filtered_team_config(routing)
            team = self.create_team(filtered_config)
        team._cancel_event = cancel_event or threading.Event()

        logger.info("Routing: %s (%s)", strategy.value, reason)

        yield AgentEvent(
            type="info",
            data={
                "routing": strategy.value,
                "reason": reason,
                "roles": [r.value for r in team.get_members().keys()],
            },
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
                if team._cancel_event.is_set():
                    gen.close()
                    break
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

    def _build_filtered_team_config(self, routing: Optional[RoutingResult]) -> TeamConfig:
        """Build a TeamConfig containing only the roles the router suggested.

        Falls back to the full default config when routing is None or
        suggested_roles is empty/unparseable.
        """
        full = self.get_default_team_config()
        if routing is None or not routing.suggested_roles:
            return full

        role_set: set[RoleType] = set()
        for name in routing.suggested_roles:
            try:
                role_set.add(RoleType(name))
            except ValueError:
                logger.warning("Router suggested unknown role %r, ignoring", name)

        if routing.strategy != ExecutionStrategy.DIRECT:
            role_set.add(RoleType.LEAD)

        filtered_members = {
            role: cfg for role, cfg in full.members.items()
            if role in role_set
        }
        if not filtered_members:
            return full

        return TeamConfig(
            name="dynamic",
            members=filtered_members,
            max_concurrent_agents=full.max_concurrent_agents,
            default_provider=full.default_provider,
            default_model=full.default_model,
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