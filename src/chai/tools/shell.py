"""Shell command execution tool."""

from __future__ import annotations

import os
import subprocess
from typing import Optional

from .base import Tool, ToolParameter, ToolResult


class ShellTool(Tool):
    """Execute shell commands."""

    name = "shell"
    description = "Execute a shell command in the terminal. Use for running builds, tests, git commands, etc."
    parameters = [
        ToolParameter("command", "string", "The shell command to execute"),
        ToolParameter("cwd", "string", "Working directory for the command", optional=True),
        ToolParameter("timeout", "integer", "Timeout in seconds (default: 30)", optional=True),
        ToolParameter("background", "boolean", "Run command in background (default: false)", optional=True),
    ]
    reads_files = False
    writes_files = False

    BLOCKED_PATTERNS = [
        "rm -rf /",
        "rm -rf /*",
        "sudo rm -rf",
        ":(){:|:&};:",
        "mkfs",
        "dd if=/dev/zero of=/dev/",
        "> /dev/sda",
    ]

    def _is_blocked(self, command: str) -> bool:
        cmd_lower = command.lower().strip()
        for pattern in self.BLOCKED_PATTERNS:
            if pattern.lower() in cmd_lower:
                return True
        return False

    def execute(
        self,
        command: str,
        cwd: Optional[str] = None,
        timeout: int = 30,
        background: bool = False,
        **kwargs: object,
    ) -> ToolResult:
        try:
            if self._is_blocked(command):
                return ToolResult(
                    success=False,
                    output="",
                    error="Command blocked for safety reasons",
                )

            if cwd:
                cwd = os.path.expanduser(cwd)
                if not os.path.isdir(cwd):
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Working directory not found: {cwd}",
                    )
            else:
                cwd = os.getcwd()

            if background:
                proc = subprocess.Popen(
                    command,
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=cwd,
                    start_new_session=True,
                    env={**os.environ, "TERM": "dumb"},
                )
                return ToolResult(
                    success=True,
                    output=f"Started background process (PID {proc.pid})",
                )

            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env={**os.environ, "TERM": "dumb"},
            )

            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            combined = (stdout + "\n" + stderr).strip() if stderr else stdout.strip()

            if proc.returncode == 0:
                return ToolResult(success=True, output=combined or "(no output)")
            return ToolResult(
                success=False,
                output=combined,
                error=f"Command exited with code {proc.returncode}",
            )

        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error=f"Command timed out after {timeout} seconds",
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))
