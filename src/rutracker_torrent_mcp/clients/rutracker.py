"""rutracker.org client.

No official API — everything is HTML scraping over a cookie session. The
endpoints we hit:

- ``POST /forum/login.php``                — form login.
- ``GET  /forum/tracker.php?nm=<query>``   — search; returns a table of
  topics with topic_id / title / forum / size / seeders / leechers /
  downloads / date.
- ``GET  /forum/viewtopic.php?t=<id>``     — topic page; used to extract
  the magnet link and the posted .torrent link.
- ``GET  /forum/dl.php?t=<id>``            — downloads the .torrent
  file (requires an authenticated session).

The server stores the session cookie on disk (``cookies.json``) so a
restart doesn't trigger a relogin — rutracker rate-limits login attempts
and occasionally responds with a captcha to fresh sessions, so reusing a
good cookie matters.

A structured :class:`LoginCaptchaRequired` is raised when rutracker
returns the captcha form. The tool layer turns it into a
``ToolError(code='captcha_required', ...)`` so the caller (the Telegram
bot, today) can surface a clear instruction to the operator.
"""

from __future__ import annotations

import asyncio
import json
import re
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

import httpx
from selectolax.parser import HTMLParser, Node


class RutrackerError(Exception):
    """Base class for all rutracker-client errors."""


class LoginFailed(RutrackerError):
    """Credentials were rejected by rutracker."""


class LoginCaptchaRequired(RutrackerError):
    """rutracker asked for a captcha — we can't solve it automatically."""


class NotAuthenticated(RutrackerError):
    """The operation needs an authenticated session and no valid cookie
    is available."""


_SIZE_RE = re.compile(r"(\d+(?:[\.,]\d+)?)\s*(B|KB|MB|GB|TB)", re.IGNORECASE)
_SIZE_MULT = {"b": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3, "tb": 1024**4}
_QUALITY_RE = re.compile(r"\b(2160p|1080p|720p|480p|HDTVRip|BDRip|WEB-?DL|WEBRip)\b", re.IGNORECASE)
_HDR_RE = re.compile(r"\b(HDR|HDR10\+?|Dolby\s?Vision|DV)\b", re.IGNORECASE)
_DATE_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_DISPO_FILENAME_RE = re.compile(r"filename\*?=(?:UTF-8''|\")?([^\";]+)")


class RutrackerClient:
    """Async rutracker scraper.

    Create one instance per process and share it. It owns an ``httpx``
    client plus a cookie file — both closed by :meth:`aclose`.
    """

    def __init__(
        self,
        *,
        login: str | None,
        password: str | None,
        base_url: str,
        cookies_path: Path,
        proxy_url: str | None = None,
        http: httpx.AsyncClient | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._login = login
        self._password = password
        self._base = base_url.rstrip("/")
        self._cookies_path = cookies_path
        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept-Language": "ru,en;q=0.8",
        }
        self._http = http or httpx.AsyncClient(
            base_url=self._base,
            headers=self._headers,
            timeout=timeout,
            proxy=proxy_url,
            follow_redirects=True,
        )
        self._owns_http = http is None
        self._login_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    async def open(self) -> None:
        self._load_cookies()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def search(
        self,
        query: str,
        *,
        category: int | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search by free text; returns up to ``limit`` raw rows.

        Sort is fixed: seeders descending (rutracker ``o=10&s=2``).
        """
        params: dict[str, Any] = {"nm": query, "o": 10, "s": 2}
        if category is not None:
            params["f"] = category

        html = await self._authed_get_html("/forum/tracker.php", params=params)
        rows = _parse_search(html, base_url=self._base)
        return rows[:limit]

    async def download_torrent(self, topic_id: int) -> tuple[str, bytes]:
        """Fetch the raw .torrent bytes for ``topic_id``.

        Returns ``(filename, content_bytes)``.
        """
        resp = await self._authed_get(
            "/forum/dl.php", params={"t": topic_id}, accept_redirect_to_login=False
        )
        ctype = resp.headers.get("content-type", "").lower()
        if "x-bittorrent" not in ctype and not resp.content.startswith(b"d"):
            raise RutrackerError(
                f"dl.php for topic {topic_id} returned {ctype!r}; probably not authorised"
            )
        filename = _parse_disposition_filename(resp.headers.get("content-disposition", ""))
        if not filename:
            filename = f"[rutracker.org].t{topic_id}.torrent"
        return filename, resp.content

    async def magnet_link(self, topic_id: int) -> str | None:
        """Extract the magnet link from the topic page."""
        html = await self._authed_get_html("/forum/viewtopic.php", params={"t": topic_id})
        tree = HTMLParser(html)
        for node in tree.css("a.magnet-link"):
            href = node.attributes.get("href")
            if href and href.startswith("magnet:"):
                return href
        # Fallback: some skins put the link inside an attribute rather than href.
        m = re.search(r"(magnet:\?xt=urn:btih:[A-Za-z0-9:%&=+\-\.\w]+)", html)
        return m.group(1) if m else None

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------
    async def ensure_session(self) -> None:
        """Make sure we have a usable login cookie, logging in if not."""
        if self._http.cookies.get("bb_session"):
            return
        async with self._login_lock:
            if self._http.cookies.get("bb_session"):
                return
            await self._do_login()

    async def _do_login(self) -> None:
        if not self._login or not self._password:
            raise NotAuthenticated("RUTRACKER_LOGIN / RUTRACKER_PASSWORD are not configured.")
        data = {
            "login_username": self._login,
            "login_password": self._password,
            "login": "\u0412\u0445\u043e\u0434",  # "Вход" — button label value rutracker expects
        }
        resp = await self._http.post("/forum/login.php", data=data)
        if _looks_like_captcha(resp.text):
            raise LoginCaptchaRequired(
                "rutracker returned a captcha on login; log in manually in a "
                "browser and drop the bb_session cookie into RUTRACKER_COOKIES_PATH."
            )
        if not self._http.cookies.get("bb_session"):
            raise LoginFailed("rutracker rejected the credentials (no bb_session cookie set).")
        self._save_cookies()

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    async def _authed_get_html(self, path: str, *, params: dict[str, Any] | None = None) -> str:
        resp = await self._authed_get(path, params=params)
        return resp.text

    async def _authed_get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        accept_redirect_to_login: bool = True,
    ) -> httpx.Response:
        await self.ensure_session()
        resp = await self._http.get(path, params=params)
        if _is_login_page(resp) and accept_redirect_to_login:
            # Cookie expired between persistence and use — relogin once.
            self._http.cookies.clear()
            async with self._login_lock:
                await self._do_login()
            resp = await self._http.get(path, params=params)
        resp.raise_for_status()
        return resp

    # ------------------------------------------------------------------
    # Cookie persistence
    # ------------------------------------------------------------------
    def _load_cookies(self) -> None:
        if not self._cookies_path.is_file():
            return
        try:
            raw = json.loads(self._cookies_path.read_text())
        except (OSError, json.JSONDecodeError):
            return
        for name, value in raw.items():
            self._http.cookies.set(name, str(value), domain=_domain(self._base))

    def _save_cookies(self) -> None:
        self._cookies_path.parent.mkdir(parents=True, exist_ok=True)
        jar = {c.name: c.value for c in self._http.cookies.jar if c.value is not None}
        tmp = self._cookies_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(jar))
        tmp.replace(self._cookies_path)


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------


def _parse_search(html: str, *, base_url: str) -> list[dict[str, Any]]:
    tree = HTMLParser(html)
    table = tree.css_first("#tor-tbl")
    if table is None:
        return []
    out: list[dict[str, Any]] = []
    for row in table.css("tr.tCenter.hl-tr"):
        parsed = _parse_row(row, base_url=base_url)
        if parsed is not None:
            out.append(parsed)
    return out


def _parse_row(row: Node, *, base_url: str) -> dict[str, Any] | None:
    title_link = row.css_first("a.tLink")
    if title_link is None:
        return None
    href = title_link.attributes.get("href") or ""
    tid_match = re.search(r"t=(\d+)", href)
    if tid_match is None:
        return None
    topic_id = int(tid_match.group(1))
    title = _clean_text(title_link.text())

    forum_link = row.css_first("a.gen.f")
    forum_id: int | None = None
    forum_name: str | None = None
    if forum_link is not None:
        forum_name = _clean_text(forum_link.text())
        f_match = re.search(r"f=(\d+)", forum_link.attributes.get("href") or "")
        if f_match:
            forum_id = int(f_match.group(1))

    # rutracker renders size as ``<u>EXACT_BYTES</u>HUMAN``; prefer the
    # exact byte count inside <u> to avoid mis-parsing the concatenated text.
    size_node = row.css_first("td.tor-size")
    size_bytes = 0
    if size_node is not None:
        exact = size_node.css_first("u")
        if exact is not None and exact.text().strip().isdigit():
            size_bytes = int(exact.text().strip())
        else:
            size_bytes = _parse_size(size_node.text())
    seeders = _to_int(_first_text(row, "b.seedmed"))
    leechers = _to_int(_first_text(row, "td.leechmed b"))
    downloads = _to_int(_first_text(row, "td.number-format"))

    date_node = row.css_first("td.t-data:last-child p") or row.css_first("td:last-child p")
    registered_at = _parse_date(date_node.text() if date_node else "")

    quality = _match_first(_QUALITY_RE, title)
    hdr = bool(_HDR_RE.search(title))

    url = f"{base_url}/forum/viewtopic.php?t={topic_id}"

    return {
        "topic_id": topic_id,
        "title": title,
        "forum_id": forum_id,
        "forum_name": forum_name,
        "size_bytes": size_bytes,
        "seeders": max(seeders, 0),
        "leechers": max(leechers, 0),
        "downloads": max(downloads, 0),
        "registered_at": registered_at,
        "quality": quality,
        "hdr": hdr,
        "url": url,
    }


def _first_text(root: Node, selector: str) -> str:
    node = root.css_first(selector)
    return node.text() if node is not None else ""


def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _to_int(s: str) -> int:
    m = re.search(r"-?\d+", (s or "").replace(" ", "").replace("\xa0", ""))
    return int(m.group(0)) if m else 0


def _parse_size(s: str) -> int:
    m = _SIZE_RE.search(s.replace(",", "."))
    if not m:
        return 0
    value = float(m.group(1))
    unit = m.group(2).lower()
    return int(value * _SIZE_MULT[unit])


def _parse_date(s: str) -> str | None:
    m = _DATE_RE.search(s)
    if not m:
        return None
    y, mo, d = m.groups()
    return f"{y}-{int(mo):02d}-{int(d):02d}"


def _match_first(regex: re.Pattern[str], s: str) -> str | None:
    m = regex.search(s)
    return m.group(1) if m else None


def _is_login_page(resp: httpx.Response) -> bool:
    if "login.php" in str(resp.url):
        return True
    return 'name="login_username"' in resp.text and 'name="login_password"' in resp.text


def _looks_like_captcha(html: str) -> bool:
    lowered = html.lower()
    return "cap_sid" in lowered or 'name="cap_code"' in lowered or "captcha" in lowered


def _domain(base_url: str) -> str:
    # Crude host extraction — good enough for cookie scoping.
    without_scheme = base_url.split("://", 1)[-1]
    return without_scheme.split("/", 1)[0]


def _parse_disposition_filename(value: str) -> str:
    m = _DISPO_FILENAME_RE.search(value or "")
    if not m:
        return ""
    raw = m.group(1).strip('"')
    try:
        # Many responses send filename percent-encoded under UTF-8''.
        from urllib.parse import unquote

        return unquote(raw)
    except Exception:
        return raw


__all__ = [
    "LoginCaptchaRequired",
    "LoginFailed",
    "NotAuthenticated",
    "RutrackerClient",
    "RutrackerError",
    "SimpleCookie",
    "_parse_search",
    "_parse_size",
]
