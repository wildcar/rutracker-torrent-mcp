from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import pytest

from rutracker_torrent_mcp.clients.browser import PlaywrightRutrackerClient
from rutracker_torrent_mcp.clients.rutracker import ManualLoginRequired


@dataclass
class FakeBrowserResponse:
    status: int = 200


class FakePage:
    def __init__(self, *, html: str, title: str = "RuTracker.org", status: int = 200) -> None:
        self.html = html
        self.page_title = title
        self.status = status
        self.urls: list[str] = []
        self.fetch_result: dict[str, Any] | None = None

    async def goto(self, url: str, **kwargs: Any) -> FakeBrowserResponse:
        self.urls.append(url)
        return FakeBrowserResponse(self.status)

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
        return None


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


async def test_browser_surfaces_manual_login_for_cloudflare() -> None:
    page = FakePage(html="<html></html>", title="Just a moment...", status=403)
    client = PlaywrightRutrackerClient(
        base_url="https://rutracker.org",
        cdp_url="http://unused",
        page=page,
    )

    with pytest.raises(ManualLoginRequired):
        await client.search("Dune")


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
