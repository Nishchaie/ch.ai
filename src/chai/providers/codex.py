"""Codex CLI provider - wraps the codex command-line tool."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Union

from .base import Provider, ProviderResponse


class CodexProvider(Provider):
    """Provider that wraps the Codex CLI. The CLI manages its own tools."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        super().__init__(api_key, model, base_url)
        self._binary = "codex"
        self._timeout = 300

    @property
    def manages_own_tools(self) -> bool:
        return True

    def _ensure_binary(self) -> None:
        if not shutil.which(self._binary):
            raise RuntimeError(
                "Codex CLI not found. Install it from: https://github.com/openai/codex"
            )

    def chat(
        self,
        messages: List[Dict[str, Any]],
        system: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 8192,
        stream: bool = False,
    ) -> Union[ProviderResponse, Any]:
        self._ensure_binary()
        model = self.model or "codex-1"

        # Build prompt from messages
        prompt_parts: List[str] = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                content = "".join(text_parts)
            if role == "user" and content:
                prompt_parts.append(content)
        prompt = "\n\n".join(prompt_parts) if prompt_parts else ""

        if not prompt:
            raise ValueError("No user message in prompt")

        args = [
            self._binary,
            f"--model={model}",
            "--approval-mode=full-auto",
            "--quiet",
            prompt,
        ]

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                env={**__import__("os").environ},
            )
        except subprocess.TimeoutExpired as e:
            raise TimeoutError(
                f"Codex CLI timed out after {self._timeout} seconds"
            ) from e
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"Codex CLI binary not found: {self._binary}"
            ) from e

        if result.returncode != 0:
            stderr = result.stderr.strip() if result.stderr else "Unknown error"
            raise RuntimeError(
                f"Codex CLI failed (exit {result.returncode}): {stderr}"
            )

        stdout = result.stdout.strip()
        if not stdout:
            raise RuntimeError("Codex CLI produced no output")

        # Codex may output raw text or JSON - try to parse
        try:
            data = json.loads(stdout)
            if isinstance(data, dict):
                text = data.get("text", data.get("content", data.get("response", "")))
            else:
                text = stdout
        except json.JSONDecodeError:
            text = stdout

        return ProviderResponse(text=text, stop_reason="end_turn")

    def make_tool_schema(self, tools: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Codex manages its own tools - return empty list."""
        return []
