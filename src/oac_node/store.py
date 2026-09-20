"""SQLite persistence for immutable OAC Events."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class EventStore:
    def __init__(self, path: str) -> None:
        self.path = str(Path(path))
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    event_json TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _serialize(event: Dict[str, Any]) -> str:
        return json.dumps(event, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    def put(self, event: Dict[str, Any]) -> bool:
        """Store an Event and return True only when it was newly inserted."""
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO events(event_id, event_json) VALUES (?, ?)",
                (event["id"], self._serialize(event)),
            )
            return cursor.rowcount == 1

    def get(self, event_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT event_json FROM events WHERE event_id = ?", (event_id,)
            ).fetchone()
        return None if row is None else json.loads(row[0])

    def page(self, after_seq: int, limit: int) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT seq, event_json
                FROM events
                WHERE seq > ?
                ORDER BY seq ASC
                LIMIT ?
                """,
                (after_seq, limit + 1),
            ).fetchall()
        has_more = len(rows) > limit
        visible = rows[:limit]
        events = [json.loads(row[1]) for row in visible]
        next_seq = visible[-1][0] if has_more and visible else None
        return events, next_seq

    def count(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0])

