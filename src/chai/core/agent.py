"""Agent runner: executes tasks via Provider + ToolRegistry."""

from __future__ import annotations

from typing import Any, Dict, Generator, List, Optional

from ..providers.base import Provider, ProviderResponse, StreamChunk, ToolCall
from ..tools.base import ToolRegistry
from ..types import AgentConfig, AgentEvent, RoleType, TaskSpec
from .role import RoleDefinition


def _tool_activity_summary(name: str, tool_input: Dict[str, Any]) -> str:
    """Build a short human-readable description from a tool call."""
    path = (
        tool_input.get("file_path")
        or tool_input.get("path")
        or tool_input.get("filename")
        or tool_input.get("file")
    )
    if path:
        return f"{name}: {path}"
    cmd = tool_input.get("command") or tool_input.get("cmd")
    if cmd:
        short = cmd if len(cmd) <= 60 else cmd[:57] + "..."
        return f"{name}: {short}"
    pattern = tool_input.get("pattern") or tool_input.get("query") or tool_input.get("regex")
    if pattern:
        return f"{name}: {pattern}"
    return name


class AgentRunner:
    """Wraps a Provider + ToolRegistry for a specific role. Runs task execution loops."""

    def __init__(
        self,
        role: RoleDefinition,
        provider: Provider,
        tools: ToolRegistry,
        config: AgentConfig,
        context: Optional[str] = None,
    ) -> None:
        self._role = role
        self._provider = provider
        self._tools = tools
        self._config = config
        self._context = context or ""

    def run(self, task: TaskSpec) -> Generator[AgentEvent, None, str]:
        """Execute a task. Yields events during execution, returns final result."""
        task_desc = f"{task.title}\n{task.description}".strip()
        if task.acceptance_criteria:
            task_desc += "\n\nAcceptance criteria:\n" + "\n".join(f"- {c}" for c in task.acceptance_criteria)

        system_prompt = self._config.system_prompt_override or self._role.system_prompt_template
        system_prompt = system_prompt.replace("{task}", task_desc)
        if self._context:
            system_prompt += f"\n\nRelevant context:\n{self._context}"

        if self._provider.manages_own_tools:
            result = yield from self._run_cli_mode(task, system_prompt)
            return result
        result = yield from self._run_api_loop(task, system_prompt)
        return result

    def _run_cli_mode(self, task: TaskSpec, system_prompt: str) -> Generator[AgentEvent, None, str]:
        """For CLI-wrapped providers: stream tool activity, return result without text dump."""
        prompt = f"Execute this task:\n\n{task.title}\n{task.description}"
        if task.acceptance_criteria:
            prompt += "\n\nAcceptance criteria: " + "; ".join(task.acceptance_criteria)

        messages: List[Dict[str, Any]] = [{"role": "user", "content": prompt}]
        raw = self._provider.chat(
            messages=messages,
            system=system_prompt,
            tools=None,
            max_tokens=8192,
            stream=True,
        )

        response: ProviderResponse
        if hasattr(raw, "__next__") or hasattr(raw, "__iter__") and not isinstance(raw, (str, dict, ProviderResponse)):
            gen = iter(raw)
            try:
                while True:
                    chunk = next(gen)
                    if isinstance(chunk, StreamChunk) and chunk.type == "tool_call_start":
                        tool_data = chunk.data if isinstance(chunk.data, dict) else {}
                        summary = _tool_activity_summary(
                            tool_data.get("name", "?"),
                            tool_data.get("input", {}),
                        )
                        yield AgentEvent(
                            type="activity",
                            data={"message": summary},
                            role=self._role.role_type,
                            task_id=task.id,
                        )
            except StopIteration as e:
                response = e.value if e.value is not None else ProviderResponse(text="")
        else:
            response = raw

        result = response.text or ""
        return result

    def _run_api_loop(self, task: TaskSpec, system_prompt: str) -> Generator[AgentEvent, None, str]:
        """For direct API providers: chat -> tool_calls -> execute -> feed back -> repeat."""
        messages: List[Dict[str, Any]] = [
            {"role": "user", "content": f"Execute this task:\n\n{task.title}\n{task.description}"}
        ]
        if task.acceptance_criteria:
            messages[-1]["content"] += "\n\nAcceptance criteria:\n" + "\n".join(f"- {c}" for c in task.acceptance_criteria)

        tool_schemas = self._tools.get_schemas()
        tools_formatted = self._provider.make_tool_schema({s["name"]: s for s in tool_schemas}) if tool_schemas else None

        max_iter = self._config.max_iterations
        last_error: Optional[str] = None
        consecutive_failures = 0

        for iteration in range(max_iter):
            yield AgentEvent(type="status", data={"iteration": iteration + 1}, role=self._role.role_type, task_id=task.id)

            raw = self._provider.chat(
                messages=messages,
                system=system_prompt,
                tools=tools_formatted,
                max_tokens=8192,
                stream=False,
            )

            response: ProviderResponse
            if hasattr(raw, "__iter__") and not isinstance(raw, (str, dict)):
                try:
                    it = iter(raw)
                    while True:
                        next(it)
                except StopIteration as e:
                    response = e.value if e.value is not None else ProviderResponse(text="")
            else:
                response = raw

            if response.text:
                yield AgentEvent(type="text", data=response.text, role=self._role.role_type, task_id=task.id)

            if not response.tool_calls:
                return response.text or ""

            messages.append(self._provider.format_assistant_message(response))
            tool_results: List[Dict[str, Any]] = []

            calls = [
                {"name": tc.name, "arguments": tc.arguments}
                for tc in response.tool_calls
            ]
            for tc in response.tool_calls:
                yield AgentEvent(type="tool_call", data={"name": tc.name, "args": tc.arguments}, role=self._role.role_type, task_id=task.id)

            exec_results = self._tools.execute_parallel(calls)

            for tc, tr in zip(response.tool_calls, exec_results):
                yield AgentEvent(type="tool_result", data={"success": tr.success, "output": tr.output}, role=self._role.role_type, task_id=task.id)
                tool_results.append(self._provider.format_tool_result(tc.id, tr.output if tr.success else f"Error: {tr.error or tr.output}"))

                if not tr.success:
                    consecutive_failures += 1
                    last_error = tr.error or tr.output
                    if consecutive_failures >= 3:
                        yield AgentEvent(type="error", data=last_error, role=self._role.role_type, task_id=task.id)
                        return last_error or "Tool execution failed repeatedly"
                else:
                    consecutive_failures = 0

            messages.append({"role": "user", "content": tool_results})

        yield AgentEvent(type="error", data=last_error or "Max iterations reached", role=self._role.role_type, task_id=task.id)
        return last_error or "Max iterations reached"
