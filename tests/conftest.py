"""Shared fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from rutracker_torrent_mcp.cache import SQLiteCache
from rutracker_torrent_mcp.clients.rutracker import RutrackerClient
from rutracker_torrent_mcp.config import Settings
from rutracker_torrent_mcp.context import AppContext

_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def search_html() -> str:
    return (_FIXTURES / "tracker_search.html").read_text()


@pytest_asyncio.fixture
async def settings(tmp_path: Path) -> Settings:
    return Settings(
        rutracker_login="u",
        rutracker_password="p",
        rutracker_cookies_path=tmp_path / "cookies.json",
        rutracker_base_url="https://rutracker.org",
        cache_path=tmp_path / "c.sqlite",
    )


@pytest_asyncio.fixture
async def app_ctx(settings: Settings) -> AsyncIterator[AppContext]:
    cache = SQLiteCache(settings.cache_path)
    await cache.open()
    client = RutrackerClient(
        login=settings.rutracker_login,
        password=settings.rutracker_password,
        base_url=settings.rutracker_base_url,
        cookies_path=settings.rutracker_cookies_path,
    )
    await client.open()
    # Pretend we already have an authenticated session; the respx mocks
    # never actually exercise the login endpoint in unit tests.
    client._http.cookies.set("bb_session", "test-session", domain="rutracker.org")
    try:
        yield AppContext(settings=settings, cache=cache, rutracker=client)
    finally:
        await client.aclose()
        await cache.close()
