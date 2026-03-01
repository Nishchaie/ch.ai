"""Theme system for ch.ai terminal and web UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class ThemeConfig:
    """Color configuration for roles and UI elements."""

    lead: str = "gold1"
    frontend: str = "cyan"
    backend: str = "green"
    prompt: str = "magenta"
    researcher: str = "blue"
    qa: str = "red"
    deployment: str = "yellow1"
    custom: str = "white"

    # UI elements
    success: str = "green"
    error: str = "red"
    info: str = "blue"
    warning: str = "yellow"
    muted: str = "dim"

    def get_role_color(self, role: str) -> str:
        """Get color for a role (accepts RoleType.value or name)."""
        role_lower = role.lower().replace(" ", "_")
        return getattr(self, role_lower, self.custom)


DEFAULT_THEME = ThemeConfig()

DARK_THEME = ThemeConfig(
    lead="gold3",
    frontend="cyan3",
    backend="green3",
    prompt="magenta3",
    researcher="blue3",
    qa="red3",
    deployment="yellow3",
    custom="white",
    success="green3",
    error="red3",
    info="blue3",
    warning="yellow3",
    muted="bright_black",
)

LIGHT_THEME = ThemeConfig(
    lead="dark_goldenrod",
    frontend="dark_cyan",
    backend="dark_green",
    prompt="dark_magenta",
    researcher="dark_blue",
    qa="dark_red",
    deployment="dark_orange3",
    custom="black",
    success="dark_green",
    error="dark_red",
    info="dark_blue",
    warning="dark_orange",
    muted="grey70",
)


THEMES: Dict[str, ThemeConfig] = {
    "default": DEFAULT_THEME,
    "dark": DARK_THEME,
    "light": LIGHT_THEME,
}


def get_theme(name: str) -> ThemeConfig:
    """Get a theme by name. Falls back to default if unknown."""
    return THEMES.get(name, DEFAULT_THEME)


def list_themes() -> List[str]:
    """List available theme names."""
    return list(THEMES.keys())
