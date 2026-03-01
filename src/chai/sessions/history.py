"""Conversation history per team run."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .db import Database


class HistoryManager:
    """Load/save conversation history per team run."""

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db = db or Database()

    def get_history(self, session_id: str) -> List[Dict[str, Any]]:
        """Get conversation history for a session."""
        return self._db.get_messages(session_id=session_id)

    def clear_history(self, session_id: str) -> None:
        """Clear all messages for a session."""
        self._db.clear_session_messages(session_id)

    def get_recent(self, limit: int = 10, project_dir: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get recent sessions."""
        return self._db.get_recent_sessions(project_dir=project_dir, limit=limit)
