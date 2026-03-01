"""SQLite storage for sessions, messages, team runs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

try:
    import aiosqlite
    AIOSQLITE_AVAILABLE = True
except ImportError:
    AIOSQLITE_AVAILABLE = False

DB_DIR = Path.home() / ".chai"
DB_FILE = DB_DIR / "sessions.db"


class Database:
    """SQLite storage for sessions, messages, team runs. Uses aiosqlite with sync wrappers."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = str(db_path or DB_FILE)
        DB_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._current_session_id: Optional[str] = None
        if not AIOSQLITE_AVAILABLE:
            raise RuntimeError("aiosqlite is required for Database")

    def _run(self, coro) -> Any:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)

    async def _init_schema(self, conn: Any) -> None:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                project_dir TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS team_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                prompt TEXT NOT NULL,
                result TEXT,
                duration REAL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_dir)"
        )
        await conn.commit()

    def create_session(self, project_dir: Optional[str] = None) -> str:
        """Create a new session. Returns session ID."""
        project_dir = project_dir or os.getcwd()
        now = datetime.now().isoformat()
        session_id = hashlib.sha256(f"{project_dir}:{now}".encode()).hexdigest()[:16]

        async def _create() -> None:
            async with aiosqlite.connect(self._db_path) as conn:
                await self._init_schema(conn)
                await conn.execute(
                    "INSERT INTO sessions (id, project_dir, created_at) VALUES (?, ?, ?)",
                    (session_id, project_dir, now),
                )
                await conn.commit()

        self._run(_create())
        self._current_session_id = session_id
        return session_id

    def save_message(
        self,
        role: str,
        content: str,
        session_id: Optional[str] = None,
    ) -> None:
        """Save a message to a session."""
        sid = session_id or self._current_session_id
        if not sid:
            sid = self.create_session()
        now = datetime.now().isoformat()
        if isinstance(content, dict):
            content = json.dumps(content, ensure_ascii=False)

        async def _save() -> None:
            async with aiosqlite.connect(self._db_path) as conn:
                await conn.execute(
                    "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                    (sid, role, content, now),
                )
                await conn.commit()

        self._run(_save())

    def get_messages(
        self,
        session_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get messages for a session (chronological)."""
        sid = session_id or self._current_session_id
        if not sid:
            return []

        async def _get() -> List[Dict[str, Any]]:
            async with aiosqlite.connect(self._db_path) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute(
                    "SELECT id, session_id, role, content, timestamp FROM messages "
                    "WHERE session_id = ? ORDER BY id ASC LIMIT ?",
                    (sid, limit),
                )
                rows = await cursor.fetchall()
                return [
                    {
                        "id": r[0],
                        "session_id": r[1],
                        "role": r[2],
                        "content": r[3],
                        "timestamp": r[4],
                    }
                    for r in rows
                ]

        return self._run(_get())

    def save_team_run(
        self,
        prompt: str,
        result: str,
        duration: float,
        session_id: Optional[str] = None,
    ) -> int:
        """Save a team run. Returns row id."""
        sid = session_id or self._current_session_id
        if not sid:
            sid = self.create_session()
        now = datetime.now().isoformat()

        async def _save() -> int:
            async with aiosqlite.connect(self._db_path) as conn:
                cursor = await conn.execute(
                    "INSERT INTO team_runs (session_id, prompt, result, duration, timestamp) VALUES (?, ?, ?, ?, ?)",
                    (sid, prompt, result, duration, now),
                )
                await conn.commit()
                return cursor.lastrowid or 0

        return self._run(_save())

    def clear_session_messages(self, session_id: str) -> None:
        """Delete all messages for a session."""
        async def _clear() -> None:
            async with aiosqlite.connect(self._db_path) as conn:
                await conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
                await conn.commit()
        self._run(_clear())

    def get_recent_sessions(self, project_dir: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent sessions, optionally filtered by project_dir."""
        async def _get() -> List[Dict[str, Any]]:
            async with aiosqlite.connect(self._db_path) as conn:
                conn.row_factory = aiosqlite.Row
                if project_dir:
                    cursor = await conn.execute(
                        "SELECT id, project_dir, created_at FROM sessions "
                        "WHERE project_dir = ? ORDER BY created_at DESC LIMIT ?",
                        (project_dir, limit),
                    )
                else:
                    cursor = await conn.execute(
                        "SELECT id, project_dir, created_at FROM sessions "
                        "ORDER BY created_at DESC LIMIT ?",
                        (limit,),
                    )
                rows = await cursor.fetchall()
                return [
                    {"id": r[0], "project_dir": r[1], "created_at": r[2]}
                    for r in rows
                ]

        return self._run(_get())

    def rewrite_session_with_summary(
        self,
        session_id: str,
        head_messages: List[Dict[str, Any]],
        tail_messages: List[Dict[str, Any]],
        summary_content: str,
    ) -> None:
        """Rewrite session messages: head + summary + tail."""
        async def _rewrite() -> None:
            async with aiosqlite.connect(self._db_path) as conn:
                await conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
                now = datetime.now().isoformat()
                all_msgs = list(head_messages) + [{"role": "user", "content": summary_content}] + list(tail_messages)
                for m in all_msgs:
                    role = m.get("role", "user")
                    content = m.get("content", "")
                    if not isinstance(content, str):
                        content = json.dumps(content, ensure_ascii=False)
                    await conn.execute(
                        "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                        (session_id, role, content, now),
                    )
                await conn.commit()

        self._run(_rewrite())
