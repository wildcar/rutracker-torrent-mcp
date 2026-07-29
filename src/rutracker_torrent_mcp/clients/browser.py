"""Persistent Chromium backend for Cloudflare-protected rutracker sessions."""

from __future__ import annotations

import asyncio
import base64
from typing import Any
from urllib.parse import urlencode

from selectolax.parser import HTMLParser

from .rutracker import (
    ManualLoginRequired,
    RutrackerError,
    _parse_disposition_filename,
    _parse_search,
    _parse_topic,
)

_FETCH_SCRIPT = """
async ({url}) => {
  const response = await fetch(url, {credentials: "include"});
  const bytes = new Uint8Array(await response.arrayBuffer());
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 32768) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768));
  }
  return {
    status: response.status,
    headers: Object.fromEntries(response.headers.entries()),
    body: btoa(binary),
  };
}
"""


class PlaywrightRutrackerClient:
    """Drive an externally managed persistent Chromium over CDP."""

    def __init__(
        self,
        *,
        base_url: str,
        cdp_url: str,
        timeout: float = 30.0,
        page: Any = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._cdp_url = cdp_url
        self._timeout_ms = int(timeout * 1000)
        self._playwright: Any = None
        self._browser: Any = None
        self._page: Any = page
        self._request_lock = asyncio.Lock()

    async def open(self) -> None:
        if self._page is not None:
            return
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.connect_over_cdp(
                self._cdp_url,
                timeout=self._timeout_ms,
            )
            if not self._browser.contexts:
                raise RutrackerError("persistent Chromium has no browser context")
            self._page = await self._browser.contexts[0].new_page()
        except Exception:
            await self._playwright.stop()
            self._playwright = None
            raise

    async def aclose(self) -> None:
        if self._page is not None:
            try:
                await self._page.close()
            except Exception:
                pass
        self._page = None
        self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def search(
        self,
        query: str,
        *,
        category: int | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"nm": query, "o": 10, "s": 2}
        if category is not None:
            params["f"] = category
        html = await self._navigate_html("/forum/tracker.php", params=params)
        return _parse_search(html, base_url=self._base)[:limit]

    async def download_torrent(self, topic_id: int) -> tuple[str, bytes]:
        async with self._request_lock:
            await self._navigate_html_locked("/forum/viewtopic.php", params={"t": topic_id})
            assert self._page is not None
            url = self._url("/forum/dl.php", {"t": topic_id})
            result = await self._page.evaluate(_FETCH_SCRIPT, {"url": url})
            status = int(result["status"])
            if status in {401, 403}:
                raise ManualLoginRequired(_MANUAL_LOGIN_MESSAGE)
            if status >= 400:
                raise RutrackerError(f"rutracker /forum/dl.php → HTTP {status}")
            headers = {str(k).lower(): str(v) for k, v in result["headers"].items()}
            content = base64.b64decode(result["body"])
            ctype = headers.get("content-type", "").lower()
            if "x-bittorrent" not in ctype and not content.startswith(b"d"):
                raise ManualLoginRequired(_MANUAL_LOGIN_MESSAGE)
            filename = _parse_disposition_filename(headers.get("content-disposition", ""))
            return filename or f"[rutracker.org].t{topic_id}.torrent", content

    async def magnet_link(self, topic_id: int) -> str | None:
        html = await self._navigate_html("/forum/viewtopic.php", params={"t": topic_id})
        tree = HTMLParser(html)
        for node in tree.css("a.magnet-link"):
            href = node.attributes.get("href")
            if href and href.startswith("magnet:"):
                return href
        return None

    async def topic_info(self, topic_id: int) -> dict[str, Any] | None:
        html = await self._navigate_html("/forum/viewtopic.php", params={"t": topic_id})
        return _parse_topic(html, topic_id=topic_id, base_url=self._base)

    async def _navigate_html(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> str:
        async with self._request_lock:
            return await self._navigate_html_locked(path, params=params)

    async def _navigate_html_locked(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> str:
        if self._page is None:
            raise RutrackerError("PlaywrightRutrackerClient.open() must be awaited before use")
        try:
            response = await self._page.goto(
                self._url(path, params),
                wait_until="domcontentloaded",
                timeout=self._timeout_ms,
            )
            html = await self._page.content()
            title = await self._page.title()
        except Exception as exc:
            raise RutrackerError(f"browser navigation failed for {path}: {exc}") from exc
        status = response.status if response is not None else 200
        if _requires_manual_login(status, title, html):
            raise ManualLoginRequired(_MANUAL_LOGIN_MESSAGE)
        if status >= 400:
            raise RutrackerError(f"rutracker {path} → HTTP {status}")
        return str(html)

    def _url(self, path: str, params: dict[str, Any] | None = None) -> str:
        url = self._base + path
        return f"{url}?{urlencode(params)}" if params else url


_MANUAL_LOGIN_MESSAGE = (
    "rutracker browser session requires manual authentication; "
    "open the persistent Chromium through noVNC and complete Cloudflare/login"
)


def _requires_manual_login(status: int, title: str, html: str) -> bool:
    lowered = html.lower()
    return (
        status in {401, 403}
        or title.strip().lower() == "just a moment..."
        or ('name="login_username"' in lowered and 'name="login_password"' in lowered)
    )


__all__ = ["PlaywrightRutrackerClient"]
