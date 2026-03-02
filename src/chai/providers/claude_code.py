"""Claude Code CLI provider - wraps the claude command-line tool.

All CLI calls use ``--output-format=stream-json --verbose`` and Popen
so output is flushed per-event.  The process is killed as soon as the
``result`` event arrives, avoiding the CLI's cleanup hang.

Startup overhead is minimised by:
- caching the binary path in ``__init__``
- adding ``--strict-mcp-config``, ``--no-chrome``, ``--no-session-persistence``
- capturing the CLI ``session_id`` and reusing it with ``--resume``
- providing a ``warm()`` method for background pre-initialisation
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
from typing import Any, Dict, Generator, List, Optional, Union

from .base import Provider, ProviderResponse, StreamChunk, _active_providers

logger = logging.getLogger(__name__)


class ClaudeCodeProvider(Provider):
    """Provider that wraps the Claude Code CLI. The CLI manages its own tools."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        cwd: Optional[str] = None,
    ):
        super().__init__(api_key, model, base_url)
        self._timeout = 600
        self._cwd = cwd
        self._active_proc: Optional[subprocess.Popen] = None
        self._cancelled = False
        self._session_id: Optional[str] = None

        self._binary_path: Optional[str] = shutil.which("claude")
        if not self._binary_path:
            logger.warning("claude CLI not found on PATH at provider init time")

    @property
    def manages_own_tools(self) -> bool:
        return True

    def cancel(self) -> None:
        """Kill the active subprocess immediately."""
        self._cancelled = True
        proc = self._active_proc
        if proc and proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass

    def reset_session(self) -> None:
        """Clear the cached session so the next call starts fresh."""
        self._session_id = None

    # ------------------------------------------------------------------
    # CLI warm-up
    # ------------------------------------------------------------------

    def warm(self) -> None:
        """Pre-warm the CLI with a minimal call in the background.

        Captures a ``session_id`` so the first real ``chat()`` call can
        ``--resume`` instead of booting from scratch.
        """
        if not self._binary_path:
            return

        def _warmup() -> None:
            try:
                proc = subprocess.Popen(
                    [
                        self._binary_path,
                        "--print",
                        "--dangerously-skip-permissions",
                        "--model=haiku",
                        "--output-format=stream-json",
                        "--verbose",
                        "--max-turns=1",
                        "--strict-mcp-config",
                        "--no-chrome",
                        "--no-session-persistence",
                        "--system-prompt=Respond with only: OK",
                        "warm",
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=self._cwd,
                    env={**os.environ},
                )
                for line in proc.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if evt.get("type") == "system" and evt.get("subtype") == "init":
                        sid = evt.get("session_id")
                        if sid and not self._session_id:
                            self._session_id = sid
                    if evt.get("type") == "result":
                        break
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
            except Exception:
                pass

        t = threading.Thread(target=_warmup, daemon=True)
        t.start()

    # ------------------------------------------------------------------
    # Prompt extraction
    # ------------------------------------------------------------------

    def _extract_prompt(self, messages: List[Dict[str, Any]]) -> str:
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
        return prompt

    # ------------------------------------------------------------------
    # Argument building
    # ------------------------------------------------------------------

    def _build_args(self, system: str, model: str, prompt: str) -> List[str]:
        binary = self._binary_path
        if not binary:
            raise FileNotFoundError(
                "Claude Code CLI not found. Install it with: npm install -g @anthropic-ai/claude-code"
            )

        args = [
            binary,
            "--print",
            "--dangerously-skip-permissions",
            f"--model={model}",
            "--output-format=stream-json",
            "--verbose",
            "--strict-mcp-config",
            "--no-chrome",
            "--no-session-persistence",
        ]

        if self._session_id:
            args.extend(["--resume", self._session_id])
            args.append(f"--append-system-prompt={system}")
        else:
            args.append(f"--system-prompt={system}")

        args.append(prompt)
        return args

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: List[Dict[str, Any]],
        system: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 8192,
        stream: bool = False,
    ) -> Union[ProviderResponse, Generator[StreamChunk, None, ProviderResponse]]:
        self._cancelled = False
        model = self.model or "claude-sonnet-4-6"
        prompt = self._extract_prompt(messages)

        if stream:
            return self._stream_chat(system, model, prompt)

        gen = self._stream_chat(system, model, prompt)
        try:
            while True:
                next(gen)
        except StopIteration as e:
            return e.value if e.value is not None else ProviderResponse(text="")

    # ------------------------------------------------------------------
    # Streaming implementation (single path for both stream=True/False)
    # ------------------------------------------------------------------

    def _stream_chat(
        self, system: str, model: str, prompt: str
    ) -> Generator[StreamChunk, None, ProviderResponse]:
        """Stream events from the CLI and kill the process on result."""
        args = self._build_args(system, model, prompt)
        stderr_lines: List[str] = []

        try:
            proc = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self._cwd,
                env={**os.environ},
            )
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"Claude Code CLI binary not found: {self._binary_path}"
            ) from e

        self._active_proc = proc
        _active_providers.add(self)

        def _drain_stderr() -> None:
            assert proc.stderr is not None
            for line in proc.stderr:
                stderr_lines.append(line)

        stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        stderr_thread.start()

        final_result = ""
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                if self._cancelled:
                    break

                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type", "")

                if msg_type == "system" and data.get("subtype") == "init":
                    sid = data.get("session_id")
                    if sid:
                        self._session_id = sid

                elif msg_type == "assistant":
                    for block in data.get("message", {}).get("content", []):
                        if block.get("type") == "tool_use":
                            yield StreamChunk(
                                type="tool_call_start",
                                data={
                                    "name": block.get("name", "?"),
                                    "input": block.get("input", {}),
                                },
                            )

                elif msg_type == "result":
                    final_result = data.get("result", "")
                    break

        finally:
            self._active_proc = None
            _active_providers.discard(self)
            proc.kill()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            stderr_thread.join(timeout=2)

        if self._cancelled:
            return ProviderResponse(text="", stop_reason="cancelled")

        return ProviderResponse(text=final_result, stop_reason="end_turn")

    # ------------------------------------------------------------------
    # Tool schema (CLI manages its own)
    # ------------------------------------------------------------------

    def make_tool_schema(self, tools: Dict[str, Any]) -> List[Dict[str, Any]]:
        return []
