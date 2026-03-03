"""LLM-based routing: classifies prompt complexity via a fast model call.

Eagerly initialises API clients and warms the CLI at construction time
(inside ``Harness.__init__``), so that ``classify()`` is a single HTTP
round-trip with no import / key-lookup / client-construction overhead.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, List, Optional

from ..config import get_config

_DEVNULL = subprocess.DEVNULL

logger = logging.getLogger(__name__)

ROUTER_MODELS = {
    "anthropic": "claude-haiku-4-5",
    "openai": "gpt-4o-mini",
    "cli": "haiku",
}

_CLI_STARTUP_TIMEOUT = 25  # seconds to wait for the first CLI event (cold boot)
_CLI_RESULT_TIMEOUT = 15   # seconds after first event to wait for the result

_CLI_WARMUP_CMD = [
    "claude", "--version", "--strict-mcp-config",
]


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

    brace = clean.find("{")
    if brace > 0:
        clean = clean[brace:]
    last_brace = clean.rfind("}")
    if last_brace >= 0:
        clean = clean[: last_brace + 1]

    data = json.loads(clean)
    return RoutingResult(
        strategy=ExecutionStrategy(data["strategy"]),
        reason=data.get("reason", ""),
        suggested_roles=data.get("suggested_roles"),
    )


class ComplexityRouter:
    """Classifies prompt complexity via a fast LLM call.

    All heavy work (module imports, key resolution, client construction,
    CLI warm-up) happens in ``__init__`` so that ``classify()`` is a thin
    concurrent dispatch over pre-built clients.
    """

    def __init__(self) -> None:
        config = get_config()
        self._provider = config.default_provider

        self._anthropic_client: Any = None
        self._openai_client: Any = None
        self._cli_path: Optional[str] = None

        self._init_anthropic(config)
        self._init_openai(config)
        self._init_cli()

        self._classifiers = self._build_classifier_order()

    # ------------------------------------------------------------------
    # Eager initialisation helpers
    # ------------------------------------------------------------------

    def _init_anthropic(self, config: Any) -> None:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key and hasattr(config, "get_api_key"):
            key = config.get_api_key("anthropic_api")
        if not key:
            return
        try:
            import anthropic

            self._anthropic_client = anthropic.Anthropic(api_key=key)
        except Exception as exc:
            logger.debug("Anthropic client init skipped: %s", exc)

    def _init_openai(self, config: Any) -> None:
        key = os.environ.get("OPENAI_API_KEY")
        if not key and hasattr(config, "get_api_key"):
            key = config.get_api_key("openai_api")
        if not key:
            return
        try:
            import openai

            self._openai_client = openai.OpenAI(api_key=key)
        except Exception as exc:
            logger.debug("OpenAI client init skipped: %s", exc)

    def _init_cli(self) -> None:
        self._cli_path = shutil.which("claude")
        if not self._cli_path:
            return
        t = threading.Thread(target=self._warm_cli, daemon=True)
        t.start()

    def _warm_cli(self) -> None:
        """Background ``claude --version`` to pull the Node runtime into OS page cache."""
        try:
            subprocess.run(
                _CLI_WARMUP_CMD,
                stdin=_DEVNULL,
                capture_output=True,
                timeout=_CLI_STARTUP_TIMEOUT,
            )
        except Exception:
            pass

    def _build_classifier_order(self) -> List[Callable[[str], RoutingResult]]:
        if self._provider in ("openai_api", "codex"):
            preferred = [
                (self._openai_client, self._classify_openai),
                (self._cli_path, self._classify_cli),
                (self._anthropic_client, self._classify_anthropic),
            ]
        else:
            preferred = [
                (self._cli_path, self._classify_cli),
                (self._anthropic_client, self._classify_anthropic),
                (self._openai_client, self._classify_openai),
            ]
        return [fn for guard, fn in preferred if guard]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify(self, prompt: str) -> RoutingResult:
        if not self._classifiers:
            logger.warning("No classifiers available, using fallback heuristic")
            return self._classify_fallback(prompt)
        return self._classify_concurrent(prompt, self._classifiers)

    # ------------------------------------------------------------------
    # Concurrent dispatch
    # ------------------------------------------------------------------

    def _classify_concurrent(
        self,
        prompt: str,
        classifiers: List[Callable[[str], RoutingResult]],
    ) -> RoutingResult:
        """Fire all classifiers concurrently, return the first success."""
        errors: List[str] = []
        t0 = time.monotonic()

        with ThreadPoolExecutor(max_workers=len(classifiers)) as pool:
            future_to_name = {
                pool.submit(fn, prompt): getattr(fn, "__name__", str(fn))
                for fn in classifiers
            }

            for future in as_completed(future_to_name):
                name = future_to_name[future]
                try:
                    result = future.result()
                    elapsed = time.monotonic() - t0
                    logger.info(
                        "Routing via %s in %.1fs: %s", name, elapsed, result.strategy.value
                    )
                    pool.shutdown(wait=False, cancel_futures=True)
                    return result
                except Exception as exc:
                    msg = _short_error(exc)
                    errors.append(f"{name}: {msg}")
                    logger.warning("%s: %s", name, msg)

        elapsed = time.monotonic() - t0
        logger.warning(
            "All %d classifiers failed in %.1fs, using fallback heuristic",
            len(classifiers), elapsed,
        )
        for err in errors:
            logger.debug("  %s", err)
        return self._classify_fallback(prompt)

    # ------------------------------------------------------------------
    # Individual classifiers (use pre-built clients, no imports / lookups)
    # ------------------------------------------------------------------

    def _classify_anthropic(self, prompt: str) -> RoutingResult:
        response = self._anthropic_client.messages.create(
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
        response = self._openai_client.chat.completions.create(
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
        """Route via ``claude --print``, capturing plain-text output.

        Avoids ``--output-format=stream-json`` which requires ``--verbose``
        and adds ~15s of overhead.  Uses ``communicate(timeout=...)`` so a
        cleanup hang is bounded by the timeout rather than blocking forever.
        """
        _CLI_TOTAL_TIMEOUT = _CLI_STARTUP_TIMEOUT + _CLI_RESULT_TIMEOUT
        proc = subprocess.Popen(
            [
                self._cli_path,
                "--print",
                "--dangerously-skip-permissions",
                f"--system-prompt={_ROUTER_SYSTEM_PROMPT}",
                f"--model={ROUTER_MODELS['cli']}",
                "--max-turns=1",
                "--tools", "",
                "--strict-mcp-config",
                "--no-chrome",
                "--no-session-persistence",
                prompt,
            ],
            stdin=_DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            stdout, stderr = proc.communicate(timeout=_CLI_TOTAL_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate(timeout=2)
            if stdout and stdout.strip():
                try:
                    return _parse_routing_json(stdout.strip())
                except Exception:
                    pass
            raise TimeoutError(f"CLI did not respond within {_CLI_TOTAL_TIMEOUT}s")

        if proc.returncode != 0:
            detail = f": {stderr.strip()[:200]}" if stderr else ""
            raise RuntimeError(f"CLI exited with code {proc.returncode}{detail}")

        text = stdout.strip()
        if not text:
            detail = f" (stderr: {stderr.strip()[:200]})" if stderr else ""
            raise RuntimeError(f"CLI returned empty output{detail}")

        return _parse_routing_json(text)

    # ------------------------------------------------------------------
    # Keyword heuristic fallback
    # ------------------------------------------------------------------

    def _classify_fallback(self, prompt: str) -> RoutingResult:
        lower = prompt.lower()
        words = lower.split()
        word_set = set(words)
        build_verbs = {
            "build", "create", "implement", "design", "develop", "make", "write",
            "scaffold", "generate", "set up", "setup", "bootstrap",
        }
        scale_words = {
            "replica", "clone", "app", "application", "software", "platform",
            "system", "website", "product", "full", "complete", "entire",
            "saas", "dashboard", "portal", "marketplace", "e-commerce",
            "version", "modern", "ui", "theme", "homepage",
            "landing", "workspace", "service", "tool", "suite",
        }
        multi_domain = {
            "frontend", "backend", "database", "api", "deploy", "ci", "cd",
            "docker", "kubernetes", "infra", "migration", "auth",
            "authentication", "billing", "search", "test", "tests",
        }

        has_build = bool(build_verbs & word_set) or re.search(
            r"\b(set\s+up|build\s+me|create\s+a|make\s+a|write\s+a)\b", lower
        )
        has_scale = bool(scale_words & word_set)
        domain_count = len(multi_domain & word_set)

        like_pattern = re.search(r"\blike\s+(a\s+)?\w+", lower)
        if like_pattern:
            has_scale = True

        feature_count = lower.count(",") + lower.count(" and ") + lower.count("should")
        is_long_build = has_build and len(words) >= 20

        if not has_build and len(words) <= 10:
            return RoutingResult(
                strategy=ExecutionStrategy.DIRECT,
                reason="Short prompt without build intent (fallback)",
            )

        roles = self._infer_roles_from_keywords(lower, word_set)

        if has_build and (has_scale or domain_count >= 2 or is_long_build or feature_count >= 3):
            return RoutingResult(
                strategy=ExecutionStrategy.FULL_PIPELINE,
                reason="Build-at-scale detected (fallback)",
                suggested_roles=roles,
            )
        if has_build:
            return RoutingResult(
                strategy=ExecutionStrategy.SMALL_TEAM,
                reason="Build-intent detected (fallback)",
                suggested_roles=roles,
            )
        return RoutingResult(
            strategy=ExecutionStrategy.SMALL_TEAM,
            reason="Non-trivial prompt (fallback)",
            suggested_roles=roles,
        )

    @staticmethod
    def _infer_roles_from_keywords(lower: str, word_set: set[str]) -> List[str]:
        """Scan prompt keywords to decide which specialist roles are needed."""
        _ROLE_KEYWORDS = {
            "frontend": {
                "component", "css", "tsx", "jsx", "react", "ui", "frontend",
                "page", "layout", "style", "html", "tailwind", "vue", "svelte",
                "next", "vite", "sidebar", "navbar", "modal", "button", "form",
            },
            "backend": {
                "api", "endpoint", "server", "database", "sql", "model",
                "migration", "backend", "fastapi", "django", "flask", "express",
                "graphql", "rest", "schema", "orm", "auth", "authentication",
                "middleware", "route", "handler",
            },
            "qa": {
                "test", "tests", "testing", "spec", "assert", "coverage",
                "e2e", "integration", "unit", "pytest", "jest", "cypress",
                "playwright", "fixture", "mock",
            },
            "deployment": {
                "deploy", "docker", "ci", "cd", "pipeline", "infra",
                "kubernetes", "k8s", "terraform", "aws", "gcp", "azure",
                "nginx", "dockerfile", "compose", "helm", "monitoring",
            },
            "prompt": {
                "prompt", "llm", "gpt", "claude", "embedding", "token",
                "fine-tune", "finetune", "rag", "vector", "chain",
            },
            "researcher": {
                "research", "compare", "evaluate", "tradeoff", "analysis",
                "survey", "benchmark", "alternative", "pros", "cons",
            },
        }

        roles: List[str] = ["lead"]
        for role, keywords in _ROLE_KEYWORDS.items():
            if keywords & word_set:
                roles.append(role)

        if len(roles) == 1:
            roles.append("backend")

        return roles


def _short_error(exc: Exception) -> str:
    """Produce a concise error string, truncating subprocess timeout noise."""
    msg = str(exc)
    if len(msg) > 120:
        return msg[:117] + "..."
    return msg
