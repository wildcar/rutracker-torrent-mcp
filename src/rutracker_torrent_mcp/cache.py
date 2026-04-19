"""Reused SQLite TTL cache pattern (identical to the trailer/metadata services)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
"""


class SQLiteCache:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @staticmethod
    def make_key(tool: str, args: dict[str, Any]) -> str:
        return f"{tool}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"

    async def get(self, key: str) -> dict[str, Any] | None:
        if self._conn is None:
            raise RuntimeError("SQLiteCache.open() must be awaited before use.")
        cur = await self._conn.execute(
            "SELECT value_json, expires_at FROM cache WHERE key = ?", (key,)
        )
        row = await cur.fetchone()
        if row is None:
            return None
        value_json, expires_at = row
        if datetime.fromisoformat(expires_at) <= datetime.now(UTC):
            await self._conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            await self._conn.commit()
            return None
        decoded: dict[str, Any] = json.loads(value_json)
        return decoded

    async def set(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        if self._conn is None:
            raise RuntimeError("SQLiteCache.open() must be awaited before use.")
        expires = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        await self._conn.execute(
            "INSERT OR REPLACE INTO cache(key, value_json, expires_at) VALUES (?, ?, ?)",
            (key, json.dumps(value, ensure_ascii=False), expires.isoformat()),
        )
        await self._conn.commit()
