"""Claude Code CLI provider - wraps the claude command-line tool."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from typing import Any, Dict, Generator, List, Optional, Union

from .base import Provider, ProviderResponse, StreamChunk, _active_providers


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
        self._binary = "claude"
        self._timeout = 600
        self._cwd = cwd
        self._active_proc: Optional[subprocess.Popen] = None
        self._cancelled = False

    @property
    def manages_own_tools(self) -> bool:
        return True

    def cancel(self) -> None:
        """Kill the active subprocess immediately."""
        self._cancelled = True
        proc = self._active_proc
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    def _ensure_binary(self) -> None:
        if not shutil.which(self._binary):
            raise RuntimeError(
                f"Claude Code CLI not found. Install it with: npm install -g @anthropic-ai/claude-code"
            )

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

    def _build_args(self, system: str, model: str, prompt: str, output_format: str = "json") -> List[str]:
        args = [
            self._binary,
            "--print",
            "--dangerously-skip-permissions",
            f"--system-prompt={system}",
            f"--model={model}",
            f"--output-format={output_format}",
        ]
        if output_format == "stream-json":
            args.append("--verbose")
        args.append(prompt)
        return args

    def chat(
        self,
        messages: List[Dict[str, Any]],
        system: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 8192,
        stream: bool = False,
    ) -> Union[ProviderResponse, Generator[StreamChunk, None, ProviderResponse]]:
        self._ensure_binary()
        self._cancelled = False
        model = self.model or "claude-sonnet-4-6"
        prompt = self._extract_prompt(messages)

        if stream:
            return self._stream_chat(system, model, prompt)
        return self._blocking_chat(system, model, prompt)

    def _blocking_chat(self, system: str, model: str, prompt: str) -> ProviderResponse:
        args = self._build_args(system, model, prompt, output_format="json")

        _active_providers.add(self)
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
            self._active_proc = proc
            stdout, stderr = proc.communicate(timeout=self._timeout)
        except subprocess.TimeoutExpired:
            if self._active_proc:
                self._active_proc.kill()
                self._active_proc.wait()
            raise TimeoutError(
                f"Claude Code CLI timed out after {self._timeout} seconds"
            )
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"Claude Code CLI binary not found: {self._binary}"
            ) from e
        finally:
            self._active_proc = None
            _active_providers.discard(self)

        if self._cancelled:
            raise RuntimeError("Cancelled by user")

        if proc.returncode != 0:
            err = stderr.strip() if stderr else "Unknown error"
            raise RuntimeError(
                f"Claude Code CLI failed (exit {proc.returncode}): {err}"
            )

        stdout = stdout.strip()
        if not stdout:
            raise RuntimeError("Claude Code CLI produced no output")

        return self._parse_json_result(stdout)

    def _stream_chat(
        self, system: str, model: str, prompt: str
    ) -> Generator[StreamChunk, None, ProviderResponse]:
        """Stream events from the CLI using --output-format=stream-json and Popen."""
        args = self._build_args(system, model, prompt, output_format="stream-json")
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
                f"Claude Code CLI binary not found: {self._binary}"
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
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type", "")

                if msg_type == "assistant":
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

        finally:
            self._active_proc = None
            _active_providers.discard(self)
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            stderr_thread.join(timeout=2)

        if self._cancelled:
            return ProviderResponse(text="", stop_reason="cancelled")

        if proc.returncode and proc.returncode != 0:
            err = "".join(stderr_lines).strip() or "Unknown error"
            raise RuntimeError(
                f"Claude Code CLI failed (exit {proc.returncode}): {err}"
            )

        return ProviderResponse(text=final_result, stop_reason="end_turn")

    def _parse_json_result(self, stdout: str) -> ProviderResponse:
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Claude Code CLI output was not valid JSON: {e}") from e

        text = ""
        if isinstance(data, str):
            text = data
        elif isinstance(data, dict):
            text = data.get("result", "") or data.get("text", "") or data.get("content", "") or data.get("response", "")
            if not text and "output" in data:
                text = data["output"] if isinstance(data["output"], str) else ""
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "text" in item:
                    text += item.get("text", "")

        return ProviderResponse(text=text or stdout, stop_reason="end_turn")

    def make_tool_schema(self, tools: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Claude Code manages its own tools - return empty list."""
        return []
