"""Tool-level tests with respx-mocked rutracker."""

from __future__ import annotations

import base64

import httpx
import respx

from rutracker_torrent_mcp.context import AppContext
from rutracker_torrent_mcp.tools import (
    get_magnet_link_impl,
    get_torrent_file_impl,
    search_torrents_impl,
)

BASE = "https://rutracker.org"


async def test_search_torrents_ranks_and_limits(
    app_ctx: AppContext, respx_mock: respx.MockRouter, search_html: str
) -> None:
    respx_mock.get(f"{BASE}/forum/tracker.php").mock(
        return_value=httpx.Response(200, text=search_html)
    )

    resp = await search_torrents_impl(app_ctx, "Дюна", limit=2)
    assert resp.error is None
    assert len(resp.results) == 2
    # Fixture order is already seed-desc — the top result should win.
    assert resp.results[0].topic_id == 6126543
    assert resp.results[0].seeders == 1234
    assert resp.results[0].hdr is True


async def test_search_torrents_applies_min_seeders(
    app_ctx: AppContext, respx_mock: respx.MockRouter, search_html: str
) -> None:
    respx_mock.get(f"{BASE}/forum/tracker.php").mock(
        return_value=httpx.Response(200, text=search_html)
    )

    resp = await search_torrents_impl(app_ctx, "Дюна", min_seeders=100, limit=10)
    ids = {r.topic_id for r in resp.results}
    # The zero-seeder row in the fixture must be filtered out.
    assert 6300000 not in ids
    assert 6126543 in ids
    assert 6200000 in ids


async def test_search_torrents_rejects_empty_query(app_ctx: AppContext) -> None:
    resp = await search_torrents_impl(app_ctx, "   ")
    assert resp.error is not None
    assert resp.error.code == "invalid_argument"


async def test_get_torrent_file_returns_base64(
    app_ctx: AppContext, respx_mock: respx.MockRouter
) -> None:
    content = b"d8:announce30:http://tracker.example/announce"
    respx_mock.get(f"{BASE}/forum/dl.php").mock(
        return_value=httpx.Response(
            200,
            content=content,
            headers={
                "content-type": "application/x-bittorrent",
                "content-disposition": 'attachment; filename="[rutracker.org].t42.torrent"',
            },
        )
    )

    resp = await get_torrent_file_impl(app_ctx, 42)
    assert resp.error is None
    assert resp.file is not None
    assert resp.file.topic_id == 42
    assert resp.file.filename == "[rutracker.org].t42.torrent"
    assert base64.b64decode(resp.file.content_base64) == content
    assert resp.file.size_bytes == len(content)


async def test_get_torrent_file_surfaces_captcha(
    app_ctx: AppContext, respx_mock: respx.MockRouter
) -> None:
    # First call: dl.php serves an HTML page (session expired); the fallback
    # relogin attempt hits login.php, which responds with a captcha form.
    respx_mock.get(f"{BASE}/forum/dl.php").mock(
        return_value=httpx.Response(
            200,
            text='<html><body><input name="login_username"><input name="login_password">'
            '<img src="cap_sid=abc"/></body></html>',
            headers={"content-type": "text/html"},
        )
    )
    respx_mock.post(f"{BASE}/forum/login.php").mock(
        return_value=httpx.Response(
            200,
            text='<form><input name="cap_code"><input name="cap_sid"></form>',
        )
    )
    # Drop the pre-seeded session to force the relogin branch.
    app_ctx.rutracker._http.cookies.clear()

    resp = await get_torrent_file_impl(app_ctx, 42)
    assert resp.error is not None
    assert resp.error.code == "captcha_required"


async def test_get_magnet_link_parses_anchor(
    app_ctx: AppContext, respx_mock: respx.MockRouter
) -> None:
    html = (
        '<html><body><a class="magnet-link" href="magnet:?xt=urn:btih:ABC123">magnet</a>'
        "</body></html>"
    )
    respx_mock.get(f"{BASE}/forum/viewtopic.php").mock(return_value=httpx.Response(200, text=html))

    resp = await get_magnet_link_impl(app_ctx, 42)
    assert resp.error is None
    assert resp.magnet is not None
    assert resp.magnet.magnet.startswith("magnet:?xt=urn:btih:ABC123")


async def test_get_magnet_link_not_found(app_ctx: AppContext, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{BASE}/forum/viewtopic.php").mock(
        return_value=httpx.Response(200, text="<html></html>")
    )

    resp = await get_magnet_link_impl(app_ctx, 42)
    assert resp.error is not None
    assert resp.error.code == "not_found"


async def test_search_caches_second_call(
    app_ctx: AppContext, respx_mock: respx.MockRouter, search_html: str
) -> None:
    respx_mock.get(f"{BASE}/forum/tracker.php").mock(
        return_value=httpx.Response(200, text=search_html)
    )

    await search_torrents_impl(app_ctx, "Дюна")
    n = len(respx_mock.calls)
    await search_torrents_impl(app_ctx, "Дюна")
    assert len(respx_mock.calls) == n
