"""Complexity-based routing: classifies prompts to select execution strategy."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class ExecutionStrategy(str, Enum):
    DIRECT = "direct"
    SMALL_TEAM = "small_team"
    FULL_PIPELINE = "full_pipeline"


@dataclass
class RoutingResult:
    """Output of the complexity router."""

    strategy: ExecutionStrategy
    reason: str
    suggested_roles: Optional[List[str]] = None


# Patterns that suggest a simple, single-agent task
_SIMPLE_PATTERNS = [
    r"\bfix\b.*\b(typo|bug|error|issue|warning)\b",
    r"\b(rename|delete|remove)\b.*\b(file|variable|function|method|class|import)\b",
    r"\bupdate\b.*\b(version|dependency|dep|package)\b",
    r"\b(what|how|why|where|when|explain|describe|show)\b",
    r"\b(read|check|look at|inspect)\b",
    r"\bformat\b",
    r"\badd\s+(a\s+)?comment",
    r"\bchange\s+(the\s+)?(name|label|title|text|string|message|color|colour)",
]

# Patterns that suggest a complex, multi-agent task
_COMPLEX_PATTERNS = [
    r"\b(implement|build|create|design)\b.*\b(system|architecture|feature|module|service|pipeline)\b",
    r"\b(refactor|rewrite|restructure|overhaul|migrate)\b",
    r"\b(full|complete|end.to.end|e2e)\b.*\b(test|implementation|feature|system|auth)\b",
    r"\bmulti.?(step|phase|stage)\b",
    r"\b(frontend|backend|api|database|ui)\b.*\b(and|&|plus|with)\b.*\b(frontend|backend|api|database|ui)\b",
    r"\bcross.?cutting\b",
]

# File-extension patterns that suggest which domain is involved
_FRONTEND_INDICATORS = re.compile(
    r"\.(tsx|jsx|css|scss|html)\b|frontend|component|react|next|vite|tailwind",
    re.IGNORECASE,
)
_BACKEND_INDICATORS = re.compile(
    r"\.(py|go|rs|java)\b|backend|api|server|database|fastapi|django|flask|endpoint",
    re.IGNORECASE,
)

# Word-count thresholds
_SHORT_PROMPT = 30
_LONG_PROMPT = 120


class ComplexityRouter:
    """Heuristic classifier that picks an execution strategy without an LLM call.

    Scoring:
        - Start at 0.
        - Short prompt and simple-pattern matches pull toward DIRECT.
        - Long prompt, multi-domain references, and complex-pattern matches
          push toward FULL_PIPELINE.
        - Everything in between maps to SMALL_TEAM.
    """

    def classify(self, prompt: str) -> RoutingResult:
        words = prompt.split()
        word_count = len(words)
        prompt_lower = prompt.lower()
        score = 0  # negative = simple, positive = complex

        # --- length signal ---
        if word_count <= _SHORT_PROMPT:
            score -= 2
        elif word_count >= _LONG_PROMPT:
            score += 2

        # --- pattern matching ---
        for pat in _SIMPLE_PATTERNS:
            if re.search(pat, prompt_lower):
                score -= 2
                break

        for pat in _COMPLEX_PATTERNS:
            if re.search(pat, prompt_lower):
                score += 3
                break

        # --- multi-domain signal ---
        has_frontend = bool(_FRONTEND_INDICATORS.search(prompt))
        has_backend = bool(_BACKEND_INDICATORS.search(prompt))
        if has_frontend and has_backend:
            score += 2

        # --- explicit multi-file references (e.g. paths separated by commas/and) ---
        file_refs = re.findall(r"[\w/\\]+\.\w{1,5}", prompt)
        if len(file_refs) >= 4:
            score += 2
        elif len(file_refs) >= 2:
            score += 1

        # --- decide ---
        if score <= -1:
            return RoutingResult(
                strategy=ExecutionStrategy.DIRECT,
                reason="Simple task — direct single-agent execution",
            )
        if score >= 3:
            suggested = []
            if has_frontend:
                suggested.append("frontend")
            if has_backend:
                suggested.append("backend")
            suggested.append("qa")
            return RoutingResult(
                strategy=ExecutionStrategy.FULL_PIPELINE,
                reason="Complex multi-step task — full team with worktrees",
                suggested_roles=suggested or None,
            )
        return RoutingResult(
            strategy=ExecutionStrategy.SMALL_TEAM,
            reason="Moderate task — team decomposition without worktrees",
        )
