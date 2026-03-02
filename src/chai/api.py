"""FastAPI server for ch.ai web frontend."""

from __future__ import annotations

import asyncio
import json
import queue as std_queue
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import get_config
from .state import get_project_dir, get_tasks as get_shared_tasks, save_run, tasks_from_result
from .types import AgentEvent, RoleType

# Captured at startup so all endpoints use the correct project directory,
# even if the server process later changes cwd.
_project_dir: str = str(Path.cwd())


# ---------------------------------------------------------------------------
# Run broadcaster -- bridges CLI-initiated runs to frontend WebSocket clients
# ---------------------------------------------------------------------------

class RunBroadcaster:
    """Manages active runs and broadcasts events to WebSocket subscribers.

    Each run has an event buffer (for late-joining clients) and a set of
    asyncio.Queue subscribers that receive events in real-time.
    """

    def __init__(self) -> None:
        self._runs: Dict[str, Dict[str, Any]] = {}

    def register(self, run_id: str, prompt: str, source: str = "cli") -> None:
        self._runs[run_id] = {
            "prompt": prompt,
            "source": source,
            "status": "running",
            "started_at": time.time(),
            "events": [],
            "subscribers": [],
        }

    async def push_event(self, run_id: str, event: Dict[str, Any]) -> None:
        run = self._runs.get(run_id)
        if not run:
            return
        run["events"].append(event)
        for q in run["subscribers"]:
            await q.put(event)

    def complete(self, run_id: str) -> None:
        run = self._runs.get(run_id)
        if run:
            run["status"] = "completed"

    def subscribe(self, run_id: str) -> tuple[asyncio.Queue, List[Dict[str, Any]]]:
        """Return (queue, buffered_events). The caller must call unsubscribe when done."""
        run = self._runs.get(run_id)
        if not run:
            return asyncio.Queue(), []
        q: asyncio.Queue = asyncio.Queue()
        run["subscribers"].append(q)
        return q, list(run["events"])

    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None:
        run = self._runs.get(run_id)
        if run:
            try:
                run["subscribers"].remove(q)
            except ValueError:
                pass

    def active_runs(self) -> List[Dict[str, Any]]:
        return [
            {
                "run_id": rid,
                "prompt": r["prompt"],
                "source": r["source"],
                "status": r["status"],
                "started_at": r["started_at"],
                "event_count": len(r["events"]),
            }
            for rid, r in self._runs.items()
            if r["status"] == "running"
        ]

    def has_run(self, run_id: str) -> bool:
        return run_id in self._runs


_broadcaster = RunBroadcaster()


class RunRequest(BaseModel):
    prompt: str
    project_dir: Optional[str] = None


def _resolve_project_dir(override: Optional[str] = None) -> str:
    if override:
        return override
    if _project_dir and Path(_project_dir).joinpath("chai.yaml").exists():
        return _project_dir
    saved = get_project_dir()
    if saved and Path(saved).joinpath("chai.yaml").exists():
        return saved
    return _project_dir


def _provider_factory(provider_type: str, model: Optional[str] = None):
    """Create provider instance."""
    try:
        from .providers.factory import create_provider
        return create_provider(provider_type, model)
    except ImportError:
        from .providers.anthropic_api import AnthropicAPIProvider
        cfg = get_config()
        key = cfg.get_api_key(provider_type)
        if provider_type == "anthropic_api" and key:
            return AnthropicAPIProvider(api_key=key, model=model or cfg.default_model)
        raise


def _event_to_dict(evt: AgentEvent) -> Dict[str, Any]:
    return {
        "type": evt.type,
        "data": evt.data,
        "role": evt.role.value if evt.role else None,
        "task_id": evt.task_id,
    }


app = FastAPI(
    title="ch.ai API",
    description="AI engineering team harness API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory store for team runs (production would use Redis/DB)
_active_runs: Dict[str, Any] = {}


def _get_teams(project_dir: Optional[str] = None) -> List[Dict]:
    """Get configured teams from project config, falling back to harness defaults."""
    resolved = _resolve_project_dir(project_dir)
    try:
        from .config import ProjectConfig
        pc = ProjectConfig.load(resolved)
        if pc.team:
            return [{
                "name": pc.team.name,
                "members": {r.value: {"provider": ac.provider.value, "model": ac.model} for r, ac in pc.team.members.items()},
            }]
    except Exception:
        pass
    try:
        from .core.harness import Harness
        harness = Harness(project_dir=resolved, provider_factory=_provider_factory)
        tc = harness.get_default_team_config()
        return [{
            "name": tc.name,
            "members": {r.value: {"provider": ac.provider.value, "model": ac.model} for r, ac in tc.members.items()},
        }]
    except Exception:
        pass
    return [{"name": "default", "members": {}}]


@app.get("/api/health")
async def health() -> Dict[str, str]:
    """Health check."""
    return {"status": "ok", "service": "ch.ai", "project_dir": _resolve_project_dir()}


@app.get("/api/teams")
async def list_teams() -> List[Dict]:
    """List configured teams."""
    return _get_teams()


def _run_harness_sync(prompt: str, project_dir: Optional[str] = None) -> tuple[List[Dict], Optional[Any]]:
    """Run harness synchronously, return (events, result)."""
    from .core.harness import Harness
    factory = lambda p, m: _provider_factory(p, m)
    harness = Harness(project_dir=_resolve_project_dir(project_dir), provider_factory=factory)
    gen = harness.run(prompt)
    events: List[Dict] = []
    result = None
    try:
        while True:
            evt = next(gen)
            events.append(_event_to_dict(evt))
    except StopIteration as e:
        result = e.value
    return events, result


@app.post("/api/teams/{name}/run")
async def start_team_run(name: str, req: RunRequest) -> Dict[str, Any]:
    """Start a team run. Returns run_id for streaming."""
    import uuid
    run_id = str(uuid.uuid4())
    try:
        events, result = await asyncio.to_thread(_run_harness_sync, req.prompt, req.project_dir)
        _store_tasks_from_result(result, prompt=req.prompt, events_count=len(events))
        _active_runs[run_id] = {
            "events": events,
            "result": {"tasks": get_shared_tasks()},
        }
        return {"run_id": run_id, "status": "completed", "events": len(events)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/teams/{name}/status")
async def team_status(name: str) -> Dict:
    """Get team status."""
    try:
        from .core.harness import Harness
        factory = lambda p, m: _provider_factory(p, m)
        harness = Harness(project_dir=_resolve_project_dir(), provider_factory=factory)
        team = harness.create_team()
        return team.get_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _store_tasks_from_result(result: Any, prompt: str = "", events_count: int = 0) -> None:
    """Save tasks from a TeamRunResult into shared state on disk."""
    tasks = tasks_from_result(result)
    if tasks:
        save_run(
            project_dir=_resolve_project_dir(),
            tasks=tasks,
            prompt=prompt,
            events_count=events_count,
        )


def _handle_incremental_state(evt_dict: Dict[str, Any], prompt: str, project_dir: str) -> None:
    """Persist task state incrementally so the TaskBoard sees live updates."""
    from .state import save_tasks_initial, update_task_status

    data = evt_dict.get("data") if isinstance(evt_dict.get("data"), dict) else {}
    evt_type = evt_dict.get("type")

    if evt_type == "info" and isinstance(data.get("tasks"), list):
        tasks = data["tasks"]
        if tasks and isinstance(tasks[0], dict):
            save_tasks_initial(project_dir=project_dir, tasks=tasks, prompt=prompt)
    elif evt_type == "status":
        if data.get("task_started"):
            update_task_status(str(data["task_started"]), "in_progress")
        elif data.get("task_completed"):
            update_task_status(str(data["task_completed"]), "completed")
    elif evt_type == "error" and evt_dict.get("task_id"):
        update_task_status(str(evt_dict["task_id"]), "failed")


def _stream_harness(prompt: str, out_queue: std_queue.Queue, project_dir: Optional[str] = None) -> None:
    """Run harness and put events into thread-safe queue."""
    resolved_dir = _resolve_project_dir(project_dir)
    Path(resolved_dir).mkdir(parents=True, exist_ok=True)
    try:
        from .core.harness import Harness
        factory = lambda p, m: _provider_factory(p, m)
        harness = Harness(project_dir=resolved_dir, provider_factory=factory)
        gen = harness.run(prompt)
        result = None
        try:
            while True:
                evt = next(gen)
                evt_dict = _event_to_dict(evt)
                out_queue.put(evt_dict)
                _handle_incremental_state(evt_dict, prompt, resolved_dir)
        except StopIteration as e:
            result = e.value
        _store_tasks_from_result(result, prompt=prompt)
        out_queue.put({"type": "done", "data": {}})
    except Exception as e:
        out_queue.put({"type": "error", "data": str(e)})


@app.websocket("/api/teams/{name}/stream")
async def stream_team_events(websocket: WebSocket, name: str) -> None:
    """Stream agent events as JSON over WebSocket."""
    await websocket.accept()
    try:
        data = await websocket.receive_text()
        payload = json.loads(data) if data else {}
        prompt = payload.get("prompt", "")
        project_dir = payload.get("project_dir")
        if not prompt:
            await websocket.send_json({"type": "error", "data": "Missing prompt"})
            return
        out_queue: std_queue.Queue = std_queue.Queue()
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, _stream_harness, prompt, out_queue, project_dir)
        while True:
            try:
                evt = await asyncio.to_thread(out_queue.get, True, 1.0)
            except std_queue.Empty:
                await asyncio.sleep(0.1)
                continue
            if evt.get("type") == "done":
                await websocket.send_json(evt)
                break
            if evt.get("type") == "error":
                await websocket.send_json(evt)
                break
            await websocket.send_json(evt)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "data": str(e)})
        except Exception:
            pass


@app.get("/api/tasks")
async def list_tasks() -> List[Dict]:
    """Return tasks from the most recent run (persisted to ~/.chai/state.json)."""
    return get_shared_tasks()


# ---------------------------------------------------------------------------
# CLI run ingestion & subscription endpoints
# ---------------------------------------------------------------------------

@app.get("/api/runs/active")
async def active_runs() -> List[Dict]:
    """List currently running CLI-initiated (or API-initiated) runs."""
    return _broadcaster.active_runs()


@app.websocket("/api/runs/ingest")
async def ingest_run_events(websocket: WebSocket) -> None:
    """Accept a WebSocket from the CLI that pushes run events.

    Protocol (CLI sends JSON messages):
      {"action":"start", "run_id":"<uuid>", "prompt":"<text>"}
      {"action":"event", "run_id":"<id>", "event":{type, data, role, task_id}}
      {"action":"done",  "run_id":"<id>"}
    """
    await websocket.accept()
    current_run_id: Optional[str] = None
    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            action = msg.get("action")

            if action == "start":
                current_run_id = msg["run_id"]
                _broadcaster.register(current_run_id, msg.get("prompt", ""), source="cli")
            elif action == "event" and current_run_id:
                await _broadcaster.push_event(current_run_id, msg.get("event", {}))
            elif action == "done" and current_run_id:
                done_evt = {"type": "done", "data": {}}
                await _broadcaster.push_event(current_run_id, done_evt)
                _broadcaster.complete(current_run_id)
                break
    except WebSocketDisconnect:
        if current_run_id:
            _broadcaster.complete(current_run_id)
    except Exception:
        if current_run_id:
            _broadcaster.complete(current_run_id)


@app.websocket("/api/runs/{run_id}/stream")
async def stream_run_events(websocket: WebSocket, run_id: str) -> None:
    """Frontend subscribes here to receive events from a CLI-initiated run.

    Replays buffered events first, then streams live events until done.
    """
    if not _broadcaster.has_run(run_id):
        await websocket.close(code=4004, reason="Run not found")
        return
    await websocket.accept()
    q, buffered = _broadcaster.subscribe(run_id)
    try:
        for evt in buffered:
            await websocket.send_json(evt)
            if evt.get("type") == "done":
                return
        while True:
            evt = await q.get()
            await websocket.send_json(evt)
            if evt.get("type") == "done":
                break
    except WebSocketDisconnect:
        pass
    finally:
        _broadcaster.unsubscribe(run_id, q)


@app.get("/api/plans")
async def list_plans() -> List[Dict]:
    """List execution plans."""
    try:
        from .orchestration.planner import ExecutionPlanManager
        mgr = ExecutionPlanManager()
        plans_dir = Path(_resolve_project_dir()) / "docs" / "exec-plans"
        if not plans_dir.is_dir():
            return []
        plans = []
        for p in plans_dir.glob("*.md"):
            plan_dict, tasks, err = mgr.load_plan(str(p))
            if plan_dict:
                plans.append({
                    "path": str(p),
                    "filename": p.name,
                    "title": plan_dict.get("title", p.stem),
                    "task_count": len(tasks) if tasks else 0,
                })
        return plans
    except Exception:
        return []


@app.get("/api/plans/{filename}")
async def get_plan_detail(filename: str) -> Dict:
    """Get full plan detail including tasks."""
    try:
        from .orchestration.planner import ExecutionPlanManager
        mgr = ExecutionPlanManager()
        plans_dir = Path(_resolve_project_dir()) / "docs" / "exec-plans"
        plan_path = plans_dir / filename
        if not plan_path.exists():
            raise HTTPException(status_code=404, detail="Plan not found")
        plan_dict, tasks, err = mgr.load_plan(str(plan_path))
        if err or not plan_dict:
            raise HTTPException(status_code=400, detail=err or "Failed to parse plan")
        return {
            "filename": filename,
            "title": plan_dict.get("title", plan_path.stem),
            "description": plan_dict.get("description", ""),
            "tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "description": t.description,
                    "role": t.role.value if hasattr(t.role, "value") else str(t.role),
                    "status": t.status.value if hasattr(t.status, "value") else str(t.status),
                    "dependencies": list(t.dependencies) if t.dependencies else [],
                    "acceptance_criteria": list(t.acceptance_criteria) if t.acceptance_criteria else [],
                }
                for t in (tasks or [])
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/quality")
async def quality_scores() -> Dict:
    """Get quality scores."""
    try:
        from .quality.scorer import get_quality_scores
        return get_quality_scores()
    except ImportError:
        return {"overall": {"score": 0.0, "grade": "N/A"}}


@app.get("/api/project-dir")
async def project_dir_endpoint() -> Dict:
    """Return the resolved project directory."""
    return {"project_dir": _resolve_project_dir()}


@app.get("/api/config")
async def api_config() -> Dict:
    """Get current config (sanitized)."""
    cfg = get_config()
    return {
        "default_provider": cfg.default_provider,
        "default_model": cfg.default_model,
        "theme": cfg.theme,
        "max_concurrent_agents": cfg.max_concurrent_agents,
        "project_dir": _resolve_project_dir(),
    }


def serve(host: str = "127.0.0.1", port: int = 8000, project_dir: Optional[str] = None) -> None:
    """Run the API server."""
    global _project_dir
    if project_dir:
        _project_dir = project_dir
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    serve()
