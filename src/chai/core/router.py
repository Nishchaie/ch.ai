"""LLM-based routing: classifies prompt complexity via a fast model call."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

ROUTER_MODELS = {
    "anthropic": "claude-haiku-4-5",
    "openai": "gpt-4o-mini",
}


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


_ROUTER_SYSTEM_PROMPT = """\
You are a task complexity classifier for an AI engineering team harness.

Given a user's prompt, decide which execution strategy to use. There are exactly three:

1. "direct" — Single agent, no task decomposition.
   Use for: questions, explanations, single-file edits, fixing a typo, renaming a \
variable, adding a comment, formatting code, running a command, checking logs, \
inspecting state. Anything a single developer could do in a few minutes without \
needing to coordinate.

2. "small_team" — 2–4 agents working in a shared workspace with task decomposition.
   Use for: moderate features touching a few files or modules, adding an API endpoint \
with tests, refactoring a module, tasks that benefit from planning but don't need \
isolated workspaces.

3. "full_pipeline" — Full team with task graph, parallel worktrees, and merge.
   Use for: large features spanning frontend + backend + tests, building whole \
applications or platforms from scratch, multi-domain work (UI + API + database + \
deployment), major rewrites or migrations, anything where the user is asking for \
a complete product or system.

Rules:
- Be decisive. When in doubt between two strategies, pick the more complex one — \
it is better to over-resource than under-resource.
- A short prompt does NOT mean a simple task. "Build me X" is always complex.
- Judge by the SCOPE of work, not the length of the prompt.

Respond with ONLY a JSON object. No markdown fences, no explanation outside the JSON:
{"strategy": "direct" | "small_team" | "full_pipeline", "reason": "<one sentence>", \
"suggested_roles": ["role1", ...] | null}

suggested_roles may include: lead, frontend, backend, prompt, researcher, qa, deployment.
Only include for small_team/full_pipeline. Set null for direct."""


def _parse_routing_json(text: str) -> RoutingResult:
    """Parse the JSON response from either API or CLI into a RoutingResult."""
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    data = json.loads(clean)
    return RoutingResult(
        strategy=ExecutionStrategy(data["strategy"]),
        reason=data.get("reason", ""),
        suggested_roles=data.get("suggested_roles"),
    )


class ComplexityRouter:
    """Classifies prompt complexity via a fast LLM call.

    Adapts to the user's configured provider:
      - claude_code / anthropic_api: Claude CLI -> Anthropic API -> OpenAI API -> heuristic
      - codex / openai_api:          OpenAI API -> Claude CLI -> Anthropic API -> heuristic
      - custom:                      all three APIs attempted -> heuristic
    """

    def classify(self, prompt: str) -> RoutingResult:
        from ..config import get_config
        provider = get_config().default_provider

        if provider in ("openai_api", "codex"):
            attempts: List[Callable[[str], RoutingResult]] = [
                self._classify_openai, self._classify_cli, self._classify_anthropic,
            ]
        else:
            attempts = [
                self._classify_cli, self._classify_anthropic, self._classify_openai,
            ]

        for attempt in attempts:
            try:
                return attempt(prompt)
            except Exception as exc:
                name = getattr(attempt, "__name__", type(attempt).__name__)
                logger.warning("%s: %s", name, exc)

        logger.warning("LLM routing unavailable, using fallback heuristic")
        return self._classify_fallback(prompt)

    def _classify_anthropic(self, prompt: str) -> RoutingResult:
        """Route via Anthropic Python SDK."""
        import anthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            from ..config import get_config
            api_key = get_config().get_api_key("anthropic_api")
        if not api_key:
            raise ValueError("No Anthropic API key")

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=ROUTER_MODELS["anthropic"],
            max_tokens=256,
            system=_ROUTER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        text = ""
        for block in response.content:
            if getattr(block, "type", "") == "text":
                text += getattr(block, "text", "")

        return _parse_routing_json(text)

    def _classify_openai(self, prompt: str) -> RoutingResult:
        """Route via OpenAI Python SDK."""
        import openai

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            from ..config import get_config
            api_key = get_config().get_api_key("openai_api")
        if not api_key:
            raise ValueError("No OpenAI API key")

        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=ROUTER_MODELS["openai"],
            max_tokens=256,
            messages=[
                {"role": "system", "content": _ROUTER_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )

        text = response.choices[0].message.content or ""
        return _parse_routing_json(text)

    def _classify_cli(self, prompt: str) -> RoutingResult:
        """Route via Claude Code CLI — works without an API key."""
        if not shutil.which("claude"):
            raise FileNotFoundError("claude CLI not found")

        result = subprocess.run(
            [
                "claude",
                "--print",
                "--dangerously-skip-permissions",
                f"--system-prompt={_ROUTER_SYSTEM_PROMPT}",
                f"--model={ROUTER_MODELS['anthropic']}",
                "--output-format=text",
                prompt,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ},
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"claude CLI failed (exit {result.returncode}): "
                f"{(result.stderr or '').strip()}"
            )

        return _parse_routing_json(result.stdout)

    def _classify_fallback(self, prompt: str) -> RoutingResult:
        """Keyword-based fallback when neither API nor CLI is available."""
        words = prompt.lower().split()
        word_set = set(words)
        build_verbs = {"build", "create", "implement", "design", "develop", "make", "write"}
        scale_words = {
            "replica", "clone", "app", "application", "software", "platform",
            "system", "website", "product", "full", "complete", "entire",
            "saas", "dashboard", "portal",
        }

        has_build = bool(build_verbs & word_set)
        has_scale = bool(scale_words & word_set)

        if not has_build and len(words) <= 10:
            return RoutingResult(
                strategy=ExecutionStrategy.DIRECT,
                reason="Short prompt without build intent (fallback)",
            )
        if has_build and has_scale:
            return RoutingResult(
                strategy=ExecutionStrategy.FULL_PIPELINE,
                reason="Build-at-scale detected (fallback)",
                suggested_roles=["lead", "frontend", "backend", "qa"],
            )
        if has_build:
            return RoutingResult(
                strategy=ExecutionStrategy.SMALL_TEAM,
                reason="Build-intent detected (fallback)",
            )
        return RoutingResult(
            strategy=ExecutionStrategy.SMALL_TEAM,
            reason="Non-trivial prompt (fallback)",
        )
