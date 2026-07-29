"""App context: rutracker client + SQLite cache."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Protocol

from .cache import SQLiteCache
from .clients.browser import PlaywrightRutrackerClient
from .clients.rutracker import RutrackerClient
from .config import Settings


class RutrackerClientProtocol(Protocol):
    async def open(self) -> None: ...

    async def aclose(self) -> None: ...

    async def search(
        self, query: str, *, category: int | None = None, limit: int = 10
    ) -> list[dict[str, Any]]: ...

    async def download_torrent(self, topic_id: int) -> tuple[str, bytes]: ...

    async def magnet_link(self, topic_id: int) -> str | None: ...

    async def topic_info(self, topic_id: int) -> dict[str, Any] | None: ...


@dataclass
class AppContext:
    settings: Settings
    cache: SQLiteCache
    rutracker: RutrackerClientProtocol


@asynccontextmanager
async def build_app_context(settings: Settings) -> AsyncIterator[AppContext]:
    cache = SQLiteCache(settings.cache_path)
    await cache.open()
    client: RutrackerClientProtocol
    if settings.rutracker_backend == "playwright":
        client = PlaywrightRutrackerClient(
            base_url=settings.rutracker_base_url,
            cdp_url=settings.rutracker_browser_cdp_url,
        )
    else:
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
