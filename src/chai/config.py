"""Global configuration management for ch.ai."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv

from .types import AgentConfig, AutonomyLevel, ProviderType, RoleType, TeamConfig

load_dotenv()

CONFIG_DIR = Path.home() / ".chai"
CONFIG_FILE = CONFIG_DIR / "config.json"

PROVIDER_MODELS: Dict[str, List[str]] = {
    "claude_code": [
        "claude-sonnet-4-6",
        "claude-opus-4-6",
        "claude-sonnet-4-5-20250929",
    ],
    "codex": ["codex-1"],
    "anthropic_api": [
        "claude-sonnet-4-6",
        "claude-opus-4-6",
        "claude-sonnet-4-5-20250929",
        "claude-opus-4-5-20251101",
    ],
    "openai_api": [
        "gpt-5.2",
        "gpt-5.2-codex",
    ],
    "custom": [],
}


@dataclass
class ValidationConfig:
    run_tests: bool = True
    test_command: Optional[str] = None
    run_linter: bool = True
    boot_app: bool = False
    boot_command: Optional[str] = None
    health_check_url: Optional[str] = None
    browser_checks: bool = False
    max_fix_iterations: int = 3


@dataclass
class SelfImprovementConfig:
    update_principles_after_run: bool = True
    garbage_collect_schedule: str = "manual"
    track_quality_scores: bool = True


@dataclass
class StackConfig:
    """Per-role tech stack labels injected into system prompts."""

    frontend: str = "React, TypeScript"
    backend: str = "Python, FastAPI"
    qa: str = "pytest"
    deployment: str = "Python venv + npm dev"
    prompt: str = ""
    researcher: str = ""
    _explicit: bool = False


@dataclass
class ProjectConfig:
    """Per-project config loaded from chai.yaml."""

    team: Optional[TeamConfig] = None
    stack: StackConfig = field(default_factory=StackConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    self_improvement: SelfImprovementConfig = field(default_factory=SelfImprovementConfig)

    @classmethod
    def load(cls, project_dir: Optional[str] = None) -> "ProjectConfig":
        base = Path(project_dir) if project_dir else Path.cwd()
        config_path = base / "chai.yaml"
        if not config_path.exists():
            return cls()

        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}

        config = cls()

        if "team" in raw:
            t = raw["team"]
            members: Dict[RoleType, AgentConfig] = {}
            for role_str, agent_raw in t.get("members", {}).items():
                role = RoleType(role_str)
                members[role] = AgentConfig(
                    role=role,
                    provider=ProviderType(agent_raw.get("provider", "claude_code")),
                    model=agent_raw.get("model"),
                    autonomy_level=AutonomyLevel(agent_raw.get("autonomy", "medium")),
                    allowed_tools=agent_raw.get("allowed_tools"),
                    max_iterations=agent_raw.get("max_iterations", 50),
                )
            config.team = TeamConfig(
                name=t.get("name", "default"),
                members=members,
                max_concurrent_agents=t.get("max_concurrent_agents", 4),
                default_provider=ProviderType(t.get("default_provider", "claude_code")),
                default_model=t.get("default_model"),
                workspace_mode=t.get("workspace_mode", "worktree"),
            )

        if "validation" in raw:
            v = raw["validation"]
            config.validation = ValidationConfig(
                run_tests=v.get("run_tests", True),
                test_command=v.get("test_command"),
                run_linter=v.get("run_linter", True),
                boot_app=v.get("boot_app", False),
                boot_command=v.get("boot_command"),
                health_check_url=v.get("health_check_url"),
                browser_checks=v.get("browser_checks", False),
                max_fix_iterations=v.get("max_fix_iterations", 3),
            )

        if "self_improvement" in raw:
            si = raw["self_improvement"]
            config.self_improvement = SelfImprovementConfig(
                update_principles_after_run=si.get("update_principles_after_run", True),
                garbage_collect_schedule=si.get("garbage_collect_schedule", "manual"),
                track_quality_scores=si.get("track_quality_scores", True),
            )

        if "stack" in raw:
            s = raw["stack"]
            config.stack = StackConfig(
                frontend=s.get("frontend", "React, TypeScript"),
                backend=s.get("backend", "Python, FastAPI"),
                qa=s.get("qa", "pytest"),
                deployment=s.get("deployment", "Python venv + npm dev"),
                prompt=s.get("prompt", ""),
                researcher=s.get("researcher", ""),
                _explicit=True,
            )

        return config


@dataclass
class Config:
    """Global ch.ai configuration persisted in ~/.chai/config.json."""

    default_provider: str = "claude_code"
    default_model: str = "claude-sonnet-4-6"
    verbose: bool = False
    theme: str = "default"
    keys: Dict[str, str] = field(default_factory=dict)
    max_concurrent_agents: int = 4
    context_compact_threshold: float = 0.8
    context_keep_head_ratio: float = 0.2
    context_keep_tail_ratio: float = 0.2
    context_compact_cooldown_messages: int = 8
    context_compact_min_messages: int = 12
    context_reserved_output_tokens: int = 8192
    context_compact_max_tokens: int = 2048
    context_model_limits: Dict[str, int] = field(default_factory=dict)

    # Custom provider settings
    custom_base_url: Optional[str] = None
    custom_model: Optional[str] = None

    def get_api_key(self, provider: Optional[str] = None) -> Optional[str]:
        provider = provider or self.default_provider
        if provider in self.keys and self.keys[provider]:
            return self.keys[provider]
        env_map = {
            "anthropic_api": "ANTHROPIC_API_KEY",
            "openai_api": "OPENAI_API_KEY",
            "custom": "CUSTOM_API_KEY",
        }
        env_var = env_map.get(provider)
        if env_var:
            return os.environ.get(env_var)
        return None

    def get_models(self, provider: Optional[str] = None) -> List[str]:
        provider = provider or self.default_provider
        return PROVIDER_MODELS.get(provider, [])

    def set_api_key(self, provider: str, key: str) -> None:
        self.keys[provider] = key
        self.save()

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "default_provider": self.default_provider,
            "default_model": self.default_model,
            "verbose": self.verbose,
            "theme": self.theme,
            "keys": self.keys,
            "max_concurrent_agents": self.max_concurrent_agents,
            "context_compact_threshold": self.context_compact_threshold,
            "context_keep_head_ratio": self.context_keep_head_ratio,
            "context_keep_tail_ratio": self.context_keep_tail_ratio,
            "context_compact_cooldown_messages": self.context_compact_cooldown_messages,
            "context_compact_min_messages": self.context_compact_min_messages,
            "context_reserved_output_tokens": self.context_reserved_output_tokens,
            "context_compact_max_tokens": self.context_compact_max_tokens,
            "context_model_limits": self.context_model_limits,
            "custom_base_url": self.custom_base_url,
            "custom_model": self.custom_model,
        }
        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls) -> "Config":
        config = cls()
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE) as f:
                    data = json.load(f)
                for k, v in data.items():
                    if hasattr(config, k):
                        setattr(config, k, v)
            except (json.JSONDecodeError, IOError):
                pass
        return config


_config: Optional[Config] = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config.load()
    return _config


def reload_config() -> Config:
    global _config
    _config = Config.load()
    return _config
