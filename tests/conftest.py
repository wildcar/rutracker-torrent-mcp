"""Shared fixtures.

Tests don't drive curl_cffi at the network layer — instead a FakeSession
intercepts HTTP calls and returns canned responses. Keeps tests fast and
independent of rutracker's availability.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from rutracker_torrent_mcp.cache import SQLiteCache
from rutracker_torrent_mcp.clients.rutracker import RutrackerClient
from rutracker_torrent_mcp.config import Settings
from rutracker_torrent_mcp.context import AppContext

_FIXTURES = Path(__file__).parent / "fixtures"


@dataclass
class FakeResponse:
    status_code: int = 200
    content: bytes = b""
    text: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    url: str = ""


@dataclass
class _Jar:
    """Minimal drop-in for curl_cffi's Jar — we only need the iterator
    protocol (``for c in jar``) and a ``set`` method."""

    _items: dict[str, str] = field(default_factory=dict)

    def set(self, name: str, value: str, domain: str = "") -> None:
        self._items[name] = value

    def clear(self) -> None:
        self._items.clear()

    def __iter__(self) -> Any:
        class _C:
            def __init__(self, n: str, v: str) -> None:
                self.name = n
                self.value = v

        return iter(_C(k, v) for k, v in self._items.items())


class _Cookies:
    def __init__(self) -> None:
        self.jar = _Jar()

    def set(self, name: str, value: str, domain: str = "") -> None:
        self.jar.set(name, value, domain=domain)

    def clear(self) -> None:
        self.jar.clear()


class FakeSession:
    """Enough of curl_cffi.AsyncSession for the tests we have."""

    def __init__(self) -> None:
        self.cookies = _Cookies()
        self._handlers: dict[tuple[str, str], Callable[..., FakeResponse]] = {}

    def on(self, method: str, path_substr: str, handler: Callable[..., FakeResponse]) -> None:
        self._handlers[(method.upper(), path_substr)] = handler

    async def get(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._handle("GET", url, kwargs)

    async def post(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._handle("POST", url, kwargs)

    async def close(self) -> None:
        return None

    def _handle(self, method: str, url: str, kwargs: dict[str, Any]) -> FakeResponse:
        for (m, substr), handler in self._handlers.items():
            if m == method and substr in url:
                resp = handler(url, kwargs)
                resp.url = url
                return resp
        return FakeResponse(status_code=404, url=url)


@pytest.fixture
def search_html() -> str:
    return (_FIXTURES / "tracker_search.html").read_text()


@pytest.fixture
def fake_session() -> FakeSession:
    return FakeSession()


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
async def app_ctx(settings: Settings, fake_session: FakeSession) -> AsyncIterator[AppContext]:
    cache = SQLiteCache(settings.cache_path)
    await cache.open()
    client = RutrackerClient(
        login=settings.rutracker_login,
        password=settings.rutracker_password,
        base_url=settings.rutracker_base_url,
        cookies_path=settings.rutracker_cookies_path,
        session=fake_session,  # type: ignore[arg-type]
    )
    await client.open()
    # Pretend we already hold a live session — no network-side login.
    client._session.cookies.set("bb_session", "test", domain="rutracker.org")
    try:
        yield AppContext(settings=settings, cache=cache, rutracker=client)
    finally:
        await client.aclose()
        await cache.close()
