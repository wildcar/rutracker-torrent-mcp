from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import pytest

from rutracker_torrent_mcp.clients.browser import (
    PlaywrightRutrackerClient,
    _reap_stranded_pages,
)
from rutracker_torrent_mcp.clients.rutracker import (
    CloudflareChallenge,
    ManualLoginRequired,
)


@dataclass
class FakeBrowserResponse:
    status: int = 200
    headers: dict[str, str] | None = None

    async def all_headers(self) -> dict[str, str]:
        return dict(self.headers or {})


class FakePage:
    def __init__(
        self,
        *,
        html: str,
        title: str = "RuTracker.org",
        status: int = 200,
        headers: dict[str, str] | None = None,
        url: str = "https://rutracker.org/forum/index.php",
    ) -> None:
        self.html = html
        self.page_title = title
        self.status = status
        self.headers = headers
        self.url = url
        self.urls: list[str] = []
        self.closed = False
        self.fetch_result: dict[str, Any] | None = None

    async def goto(self, url: str, **kwargs: Any) -> FakeBrowserResponse:
        self.urls.append(url)
        return FakeBrowserResponse(self.status, self.headers)

    async def content(self) -> str:
        return self.html

    async def title(self) -> str:
        return self.page_title

    async def evaluate(self, script: str, arg: dict[str, str]) -> dict[str, Any]:
        assert "fetch" in script
        assert arg["url"].startswith("https://rutracker.org/forum/dl.php")
        assert self.fetch_result is not None
        return self.fetch_result

    async def close(self) -> None:
        self.closed = True


async def test_browser_search_uses_persistent_page(search_html: str) -> None:
    page = FakePage(html=search_html)
    client = PlaywrightRutrackerClient(
        base_url="https://rutracker.org",
        cdp_url="http://unused",
        page=page,
    )

    rows = await client.search("Dune", limit=1)

    assert len(rows) == 1
    assert "tracker.php?" in page.urls[0]
    assert "nm=Dune" in page.urls[0]


async def test_browser_reports_challenge_not_logout_for_cloudflare() -> None:
    """A Turnstile interstitial must not be reported as a logged-out session."""
    page = FakePage(
        html="<html></html>",
        title="Just a moment...",
        status=403,
        headers={"cf-mitigated": "challenge"},
    )
    client = PlaywrightRutrackerClient(
        base_url="https://rutracker.org",
        cdp_url="http://unused",
        page=page,
    )

    with pytest.raises(CloudflareChallenge):
        await client.search("Dune")


async def test_browser_trusts_cf_mitigated_over_title() -> None:
    """The header is authoritative even when the title looks like a normal page."""
    page = FakePage(
        html="<html></html>",
        title="Трекер",
        status=403,
        headers={"cf-mitigated": "challenge"},
    )
    client = PlaywrightRutrackerClient(
        base_url="https://rutracker.org",
        cdp_url="http://unused",
        page=page,
    )

    with pytest.raises(CloudflareChallenge):
        await client.search("Dune")


async def test_browser_reports_logout_for_login_form() -> None:
    page = FakePage(
        html='<html><form><input name="login_username"><input name="login_password"></form></html>',
    )
    client = PlaywrightRutrackerClient(
        base_url="https://rutracker.org",
        cdp_url="http://unused",
        page=page,
    )

    with pytest.raises(ManualLoginRequired):
        await client.search("Dune")


async def test_browser_download_reports_challenge_from_headers() -> None:
    page = FakePage(html="<html><body>topic</body></html>")
    page.fetch_result = {
        "status": 403,
        "headers": {"cf-mitigated": "challenge", "content-type": "text/html"},
        "body": "",
    }
    client = PlaywrightRutrackerClient(
        base_url="https://rutracker.org",
        cdp_url="http://unused",
        page=page,
    )

    with pytest.raises(CloudflareChallenge):
        await client.download_torrent(42)


async def test_browser_download_stays_inside_page_context() -> None:
    page = FakePage(html="<html><body>topic</body></html>")
    torrent = b"d4:infod4:name4:testee"
    page.fetch_result = {
        "status": 200,
        "headers": {
            "content-type": "application/x-bittorrent",
            "content-disposition": 'attachment; filename="test.torrent"',
        },
        "body": base64.b64encode(torrent).decode(),
    }
    client = PlaywrightRutrackerClient(
        base_url="https://rutracker.org",
        cdp_url="http://unused",
        page=page,
    )

    filename, content = await client.download_torrent(42)

    assert filename == "test.torrent"
    assert content == torrent


class FakeContext:
    def __init__(self, pages: list[FakePage]) -> None:
        self.pages = pages

    def alive(self) -> list[FakePage]:
        return [p for p in self.pages if not p.closed]


async def test_reaper_closes_stranded_challenge_and_blank_tabs() -> None:
    keep = FakePage(html="", url="https://rutracker.org/forum/index.php")
    topic = FakePage(html="", url="https://rutracker.org/forum/viewtopic.php?t=1")
    blank = FakePage(html="", url="about:blank", title="")
    stuck = FakePage(
        html="",
        url="https://rutracker.org/forum/tracker.php?nm=x",
        title="Just a moment...",
    )
    ctx = FakeContext([keep, topic, blank, stuck])

    await _reap_stranded_pages(ctx)

    assert blank.closed and stuck.closed
    assert not keep.closed and not topic.closed


async def test_reaper_never_closes_the_last_tab() -> None:
    """Chromium exits with its last tab — the persistent browser must survive."""
    only = FakePage(html="", url="about:blank", title="")
    ctx = FakeContext([only])

    await _reap_stranded_pages(ctx)

    assert not only.closed


async def test_reaper_leaves_one_tab_when_all_are_stranded() -> None:
    pages = [FakePage(html="", url="about:blank", title="") for _ in range(4)]
    ctx = FakeContext(pages)

    await _reap_stranded_pages(ctx)

    assert len(ctx.alive()) == 1


async def test_client_context_manager_closes_page_on_error() -> None:
    page = FakePage(html="<html></html>", title="Just a moment...", status=403)
    client = PlaywrightRutrackerClient(
        base_url="https://rutracker.org",
        cdp_url="http://unused",
        page=page,
    )

    with pytest.raises(CloudflareChallenge):
        async with client:
            await client.search("Dune")

    assert page.closed
