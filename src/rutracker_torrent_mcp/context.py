"""App context: rutracker client + SQLite cache."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from .cache import SQLiteCache
from .clients.rutracker import RutrackerClient
from .config import Settings


@dataclass
class AppContext:
    settings: Settings
    cache: SQLiteCache
    rutracker: RutrackerClient


@asynccontextmanager
async def build_app_context(settings: Settings) -> AsyncIterator[AppContext]:
    cache = SQLiteCache(settings.cache_path)
    await cache.open()
    client = RutrackerClient(
        login=settings.rutracker_login,
        password=settings.rutracker_password,
        base_url=settings.rutracker_base_url,
        cookies_path=settings.rutracker_cookies_path,
        proxy_url=settings.rutracker_proxy_url,
    )
    await client.open()
    try:
        yield AppContext(settings=settings, cache=cache, rutracker=client)
    finally:
        await client.aclose()
        await cache.close()
