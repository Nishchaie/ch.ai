"""Base tool classes and registry with parallel execution support."""

from __future__ import annotations

import os
import concurrent.futures
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set
from threading import Lock, Condition

from ..types import RoleType


@dataclass
class ToolResult:
    """Result from a tool execution."""

    success: bool
    output: str
    error: Optional[str] = None


@dataclass
class ToolParameter:
    """Definition of a tool parameter."""

    name: str
    type: str  # string, integer, boolean, array, object
    description: str
    optional: bool = False
    default: Any = None


class Tool(ABC):
    """Abstract base class for all tools available to agents."""

    name: str
    description: str
    parameters: List[ToolParameter]
    reads_files: bool = False
    writes_files: bool = False

    @abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        ...

    def get_schema(self) -> Dict[str, Any]:
        properties: Dict[str, Any] = {}
        required: List[str] = []
        for param in self.parameters:
            properties[param.name] = {
                "type": param.type,
                "description": param.description,
            }
            if not param.optional:
                required.append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }

    def get_file_path(self, kwargs: Dict[str, Any]) -> Optional[str]:
        return kwargs.get("path") or kwargs.get("file_path")


# Role -> allowed tool names mapping
ROLE_TOOL_ACCESS: Dict[RoleType, Optional[Set[str]]] = {
    RoleType.LEAD: None,  # None means all tools
    RoleType.FRONTEND: None,
    RoleType.BACKEND: None,
    RoleType.PROMPT: {"read", "read_raw", "list_dir", "glob", "grep", "write", "edit", "web_search"},
    RoleType.RESEARCHER: {"read", "read_raw", "list_dir", "glob", "grep", "web_search"},
    RoleType.QA: {"read", "read_raw", "list_dir", "glob", "grep", "shell", "write", "edit", "browser", "review"},
    RoleType.DEPLOYMENT: None,
    RoleType.CUSTOM: None,
}


class _RWLock:
    """Reader/writer lock for per-path coordination."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._read_ready = Condition(self._lock)
        self._readers = 0

    def acquire_read(self) -> None:
        with self._lock:
            self._readers += 1

    def release_read(self) -> None:
        with self._lock:
            self._readers -= 1
            if self._readers == 0:
                self._read_ready.notify_all()

    def acquire_write(self) -> None:
        self._lock.acquire()
        while self._readers > 0:
            self._read_ready.wait()

    def release_write(self) -> None:
        self._lock.release()


class ToolRegistry:
    """Registry for tools with parallel execution and role-based access."""

    def __init__(self, base_dir: Optional[str] = None, role: Optional[RoleType] = None):
        self._tools: Dict[str, Tool] = {}
        self._file_locks: Dict[str, _RWLock] = {}
        self._lock_manager = Lock()
        self._mode: str = "execute"
        self._base_dir = base_dir or os.getcwd()
        self._role = role

        self._plan_allowed_tools = {
            "read", "read_raw", "list_dir", "glob", "grep", "web_search",
        }

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        return [name for name in self._tools if self._is_tool_allowed(name)]

    def set_mode(self, mode: str) -> None:
        self._mode = mode

    def get_mode(self) -> str:
        return self._mode

    def get_schemas(self) -> List[Dict[str, Any]]:
        schemas = []
        for name, tool in self._tools.items():
            if not self._is_tool_allowed(name):
                continue
            schemas.append(tool.get_schema())
        return schemas

    def _is_tool_allowed(self, tool_name: str) -> bool:
        if self._mode == "plan" and tool_name not in self._plan_allowed_tools:
            return False
        if self._role is not None:
            allowed = ROLE_TOOL_ACCESS.get(self._role)
            if allowed is not None and tool_name not in allowed:
                return False
        return True

    def _normalize_path(self, path: str) -> str:
        if not os.path.isabs(path):
            path = os.path.join(self._base_dir, path)
        return os.path.normpath(path)

    def _get_file_lock(self, path: str) -> _RWLock:
        normalized = self._normalize_path(path)
        with self._lock_manager:
            if normalized not in self._file_locks:
                self._file_locks[normalized] = _RWLock()
            return self._file_locks[normalized]

    def execute(self, name: str, arguments: Dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(success=False, output="", error=f"Unknown tool: {name}")
        if not self._is_tool_allowed(name):
            return ToolResult(
                success=False, output="",
                error=f"Tool '{name}' not allowed in current mode/role",
            )
        try:
            file_path = tool.get_file_path(arguments)
            if file_path and tool.writes_files:
                lock = self._get_file_lock(file_path)
                lock.acquire_write()
                try:
                    return tool.execute(**arguments)
                finally:
                    lock.release_write()
            elif file_path and tool.reads_files:
                lock = self._get_file_lock(file_path)
                lock.acquire_read()
                try:
                    return tool.execute(**arguments)
                finally:
                    lock.release_read()
            else:
                return tool.execute(**arguments)
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    def can_parallelize(self, calls: List[Dict[str, Any]]) -> List[List[int]]:
        """Group tool calls into batches that can run in parallel."""
        write_paths: Dict[int, Set[str]] = {}
        read_paths: Dict[int, Set[str]] = {}

        for i, call in enumerate(calls):
            tool = self._tools.get(call.get("name", ""))
            if not tool:
                continue
            path = tool.get_file_path(call.get("arguments", {}))
            if path:
                normalized = self._normalize_path(path)
                if tool.writes_files:
                    write_paths.setdefault(i, set()).add(normalized)
                if tool.reads_files:
                    read_paths.setdefault(i, set()).add(normalized)

        batches: List[List[int]] = []
        remaining = list(range(len(calls)))

        while remaining:
            batch: List[int] = []
            batch_write_paths: Set[str] = set()
            batch_all_paths: Set[str] = set()

            for idx in remaining:
                w_paths = write_paths.get(idx, set())
                r_paths = read_paths.get(idx, set())
                all_paths = w_paths | r_paths

                conflict = False
                if w_paths & batch_all_paths:
                    conflict = True
                if all_paths & batch_write_paths:
                    conflict = True

                if not conflict:
                    batch.append(idx)
                    batch_write_paths |= w_paths
                    batch_all_paths |= all_paths

            for idx in batch:
                remaining.remove(idx)
            batches.append(batch)

        return batches

    def execute_parallel(
        self,
        calls: List[Dict[str, Any]],
        max_workers: int = 4,
        callback: Optional[Callable[[int, ToolResult], None]] = None,
    ) -> List[ToolResult]:
        batches = self.can_parallelize(calls)
        results: List[Optional[ToolResult]] = [None] * len(calls)

        for batch in batches:
            if len(batch) == 1:
                idx = batch[0]
                call = calls[idx]
                result = self.execute(call["name"], call.get("arguments", {}))
                results[idx] = result
                if callback:
                    callback(idx, result)
            else:
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {}
                    for idx in batch:
                        call = calls[idx]
                        future = executor.submit(
                            self.execute, call["name"], call.get("arguments", {})
                        )
                        futures[future] = idx

                    for future in concurrent.futures.as_completed(futures):
                        idx = futures[future]
                        try:
                            result = future.result()
                        except Exception as e:
                            result = ToolResult(success=False, output="", error=str(e))
                        results[idx] = result
                        if callback:
                            callback(idx, result)

        return [r or ToolResult(success=False, output="", error="Not executed") for r in results]
