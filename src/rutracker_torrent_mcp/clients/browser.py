"""Persistent Chromium backend for Cloudflare-protected rutracker sessions."""

from __future__ import annotations

import asyncio
import base64
from typing import Any
from urllib.parse import urlencode

from selectolax.parser import HTMLParser

from .rutracker import (
    CloudflareChallenge,
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
        connect_timeout: float = 10.0,
        connect_attempts: int = 3,
        connect_backoff: float = 2.0,
        page: Any = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._cdp_url = cdp_url
        self._timeout_ms = int(timeout * 1000)
        self._connect_timeout_ms = int(connect_timeout * 1000)
        self._connect_attempts = max(1, connect_attempts)
        self._connect_backoff = connect_backoff
        self._playwright: Any = None
        self._browser: Any = None
        self._page: Any = page
        self._owns_page = False
        self._request_lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()

    async def open(self) -> None:
        """No-op: the CDP connection is established on first tool call.

        Connecting eagerly made server startup depend on a browser that had to be
        up first — a browser restart then left the MCP wedged until it was
        restarted too. See ``_ensure_page``.
        """
        return None

    async def __aenter__(self) -> PlaywrightRutrackerClient:
        await self.open()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._detach()

    async def _ensure_page(self) -> Any:
        """Return a live working tab, connecting to Chromium if needed."""
        if self._page is not None and not _page_is_closed(self._page):
            return self._page
        async with self._connect_lock:
            if self._page is not None and not _page_is_closed(self._page):
                return self._page
            await self._detach()
            await self._connect()
            return self._page

    async def _connect(self) -> None:
        delay = self._connect_backoff
        last_error: Exception | None = None
        for attempt in range(1, self._connect_attempts + 1):
            try:
                await self._connect_once()
                return
            except Exception as exc:
                last_error = exc
                await self._detach()
                if attempt < self._connect_attempts:
                    await asyncio.sleep(delay)
                    delay *= 2
        raise RutrackerError(
            f"cannot reach the persistent Chromium at {self._cdp_url}: {last_error}"
        )

    async def _connect_once(self) -> None:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.connect_over_cdp(
            self._cdp_url,
            timeout=self._connect_timeout_ms,
        )
        if not self._browser.contexts:
            raise RutrackerError("persistent Chromium has no browser context")
        context = self._browser.contexts[0]
        self._page, self._owns_page = await _adopt_working_page(context)

    async def _detach(self) -> None:
        page, owns = self._page, self._owns_page
        self._page = None
        self._owns_page = False
        if page is not None and owns:
            try:
                await page.close()
            except Exception:
                pass
        self._browser = None
        if self._playwright is not None:
            try:
                # A driver left over from a timed-out connect can hang on stop().
                await asyncio.wait_for(self._playwright.stop(), timeout=5.0)
            except Exception:
                pass
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
            page = await self._ensure_page()
            url = self._url("/forum/dl.php", {"t": topic_id})
            result = await page.evaluate(_FETCH_SCRIPT, {"url": url})
            status = int(result["status"])
            headers = {str(k).lower(): str(v) for k, v in result["headers"].items()}
            if _is_cloudflare_challenge("", headers):
                raise CloudflareChallenge(_CHALLENGE_MESSAGE)
            if status in {401, 403}:
                raise ManualLoginRequired(_MANUAL_LOGIN_MESSAGE)
            if status >= 400:
                raise RutrackerError(f"rutracker /forum/dl.php → HTTP {status}")
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
        page = await self._ensure_page()
        try:
            response = await page.goto(
                self._url(path, params),
                wait_until="domcontentloaded",
                timeout=self._timeout_ms,
            )
            html = await page.content()
            title = await page.title()
        except Exception as exc:
            # Drop the CDP connection: a browser that died mid-navigation leaves a
            # handle that never recovers. The next call reconnects and re-reaps.
            await self._detach()
            raise RutrackerError(f"browser navigation failed for {path}: {exc}") from exc
        status = response.status if response is not None else 200
        headers = await _response_headers(response)
        if _is_cloudflare_challenge(title, headers):
            raise CloudflareChallenge(_CHALLENGE_MESSAGE)
        if _requires_manual_login(status, html):
            raise ManualLoginRequired(_MANUAL_LOGIN_MESSAGE)
        if status >= 400:
            raise RutrackerError(f"rutracker {path} → HTTP {status}")
        return str(html)

    def _url(self, path: str, params: dict[str, Any] | None = None) -> str:
        url = self._base + path
        return f"{url}?{urlencode(params)}" if params else url


_CHALLENGE_TITLE = "just a moment..."

_MANUAL_LOGIN_MESSAGE = (
    "rutracker browser session is logged out; "
    "open the persistent Chromium through noVNC and sign in"
)

_CHALLENGE_MESSAGE = (
    "rutracker is behind an interactive Cloudflare challenge; the login session "
    "may still be valid. Open the persistent Chromium through noVNC and solve the "
    "Turnstile challenge"
)


def _is_cloudflare_challenge(title: str, headers: dict[str, str]) -> bool:
    """Cloudflare gating the request, regardless of login state.

    ``cf-mitigated`` is authoritative when present; the title is the fallback for
    responses whose headers we could not read.
    """
    if headers.get("cf-mitigated", "").strip().lower() == "challenge":
        return True
    return title.strip().lower() == _CHALLENGE_TITLE


def _requires_manual_login(status: int, html: str) -> bool:
    lowered = html.lower()
    if 'name="login_username"' in lowered and 'name="login_password"' in lowered:
        return True
    return status in {401, 403}


async def _response_headers(response: Any) -> dict[str, str]:
    getter = getattr(response, "all_headers", None)
    if getter is None:
        return {}
    try:
        raw = await getter()
    except Exception:
        return {}
    return {str(k).lower(): str(v) for k, v in raw.items()}


def _page_is_closed(page: Any) -> bool:
    checker = getattr(page, "is_closed", None)
    if checker is None:
        return False
    try:
        return bool(checker())
    except Exception:
        return True


async def _adopt_working_page(context: Any) -> tuple[Any, bool]:
    """Pick the tab to work in; returns ``(page, created_by_us)``.

    Reusing the tab that is already open is what bounds the tab count: a process
    killed before ``aclose()`` can no longer strand the tab it opened, because it
    never opened one.
    """
    pages = list(getattr(context, "pages", None) or [])
    if pages:
        page, created = pages[0], False
    else:
        page, created = await context.new_page(), True
    await _reap_stranded_pages(context, keep=page)
    return page, created


async def _reap_stranded_pages(context: Any, *, keep: Any) -> None:
    """Close every tab except the working one.

    The persistent profile outlives every server process, so tabs left by earlier
    runs — or by a session restore after a SIGTERM — accumulate until the host
    runs out of memory. Loaded rutracker pages are as costly as challenge tabs, so
    the rule is by exclusion: one tab survives, everything else goes. ``keep``
    belongs to ``context``, so Chromium never loses its last tab and stays up.
    """
    for page in list(getattr(context, "pages", None) or []):
        if page is keep:
            continue
        try:
            await page.close()
        except Exception:
            continue


__all__ = ["PlaywrightRutrackerClient"]
