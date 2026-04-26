"""Tool-level tests backed by a FakeSession (no real HTTP)."""

from __future__ import annotations

import base64

from rutracker_torrent_mcp.context import AppContext
from rutracker_torrent_mcp.tools import (
    get_magnet_link_impl,
    get_topic_info_impl,
    get_torrent_file_impl,
    search_torrents_impl,
)

from .conftest import FakeResponse, FakeSession


def _tracker(html: str) -> tuple[str, object]:
    return ("/forum/tracker.php", lambda url, kw: FakeResponse(200, b"", html, {}, url))


async def test_search_torrents_ranks_and_limits(
    app_ctx: AppContext, fake_session: FakeSession, search_html: str
) -> None:
    fake_session.on(
        "GET", "/forum/tracker.php", lambda url, kw: FakeResponse(200, b"", search_html)
    )

    resp = await search_torrents_impl(app_ctx, "Дюна", limit=2)
    assert resp.error is None
    assert len(resp.results) == 2
    assert resp.results[0].topic_id == 6126543
    assert resp.results[0].seeders == 1234
    assert resp.results[0].hdr is True


async def test_search_torrents_applies_min_seeders(
    app_ctx: AppContext, fake_session: FakeSession, search_html: str
) -> None:
    fake_session.on(
        "GET", "/forum/tracker.php", lambda url, kw: FakeResponse(200, b"", search_html)
    )

    resp = await search_torrents_impl(app_ctx, "Дюна", min_seeders=100, limit=10)
    ids = {r.topic_id for r in resp.results}
    assert 6300000 not in ids
    assert 6126543 in ids
    assert 6200000 in ids


async def test_search_torrents_rejects_empty_query(app_ctx: AppContext) -> None:
    resp = await search_torrents_impl(app_ctx, "   ")
    assert resp.error is not None
    assert resp.error.code == "invalid_argument"


async def test_get_torrent_file_returns_base64(
    app_ctx: AppContext, fake_session: FakeSession
) -> None:
    content = b"d8:announce30:http://tracker.example/announce"
    fake_session.on(
        "GET",
        "/forum/dl.php",
        lambda url, kw: FakeResponse(
            200,
            content,
            "",
            {
                "content-type": "application/x-bittorrent",
                "content-disposition": 'attachment; filename="[rutracker.org].t42.torrent"',
            },
        ),
    )

    resp = await get_torrent_file_impl(app_ctx, 42)
    assert resp.error is None
    assert resp.file is not None
    assert resp.file.topic_id == 42
    assert resp.file.filename == "[rutracker.org].t42.torrent"
    assert base64.b64decode(resp.file.content_base64) == content
    assert resp.file.size_bytes == len(content)


async def test_get_torrent_file_surfaces_captcha(
    app_ctx: AppContext, fake_session: FakeSession
) -> None:
    # dl.php serves the login page (session expired). Relogin attempt lands
    # on a captcha form → LoginCaptchaRequired → ToolError(captcha_required).
    login_html = (
        '<html><body><input name="login_username"><input name="login_password">'
        '<img src="cap_sid=abc"/></body></html>'
    )
    fake_session.on(
        "GET",
        "/forum/dl.php",
        lambda url, kw: FakeResponse(200, b"", login_html, {"content-type": "text/html"}),
    )
    fake_session.on(
        "POST",
        "/forum/login.php",
        lambda url, kw: FakeResponse(
            200, b"", '<form><input name="cap_code"><input name="cap_sid"></form>', {}
        ),
    )
    # Drop the pre-seeded session so the relogin path runs.
    app_ctx.rutracker._session.cookies.clear()

    resp = await get_torrent_file_impl(app_ctx, 42)
    assert resp.error is not None
    assert resp.error.code == "captcha_required"


async def test_get_magnet_link_parses_anchor(
    app_ctx: AppContext, fake_session: FakeSession
) -> None:
    html = (
        '<html><body><a class="magnet-link" href="magnet:?xt=urn:btih:ABC123">magnet</a>'
        "</body></html>"
    )
    fake_session.on("GET", "/forum/viewtopic.php", lambda url, kw: FakeResponse(200, b"", html))

    resp = await get_magnet_link_impl(app_ctx, 42)
    assert resp.error is None
    assert resp.magnet is not None
    assert resp.magnet.magnet.startswith("magnet:?xt=urn:btih:ABC123")


async def test_get_magnet_link_not_found(app_ctx: AppContext, fake_session: FakeSession) -> None:
    fake_session.on(
        "GET", "/forum/viewtopic.php", lambda url, kw: FakeResponse(200, b"", "<html></html>")
    )

    resp = await get_magnet_link_impl(app_ctx, 42)
    assert resp.error is not None
    assert resp.error.code == "not_found"


async def test_get_topic_info_parses_title_and_forum(
    app_ctx: AppContext, fake_session: FakeSession
) -> None:
    from pathlib import Path

    html = (Path(__file__).parent / "fixtures" / "tracker_topic.html").read_text()
    fake_session.on("GET", "/forum/viewtopic.php", lambda url, kw: FakeResponse(200, b"", html))

    resp = await get_topic_info_impl(app_ctx, 6843582)
    assert resp.error is None
    assert resp.topic is not None
    assert resp.topic.topic_id == 6843582
    assert "Дюна" in resp.topic.title
    assert resp.topic.forum_id == 187
    assert resp.topic.forum_name == "Зарубежное кино"
    assert resp.topic.size_bytes > 70 * 1024**3
    assert resp.topic.registered_at == "2024-04-15"
    assert resp.topic.url.endswith("?t=6843582")


async def test_get_topic_info_rejects_bad_id(app_ctx: AppContext) -> None:
    resp = await get_topic_info_impl(app_ctx, 0)
    assert resp.error is not None
    assert resp.error.code == "invalid_argument"


async def test_get_topic_info_not_found(app_ctx: AppContext, fake_session: FakeSession) -> None:
    fake_session.on(
        "GET", "/forum/viewtopic.php", lambda url, kw: FakeResponse(200, b"", "<html></html>")
    )
    resp = await get_topic_info_impl(app_ctx, 42)
    assert resp.error is not None
    assert resp.error.code == "not_found"


async def test_search_caches_second_call(
    app_ctx: AppContext, fake_session: FakeSession, search_html: str
) -> None:
    calls: list[int] = []

    def handler(url: str, kw: object) -> FakeResponse:
        calls.append(1)
        return FakeResponse(200, b"", search_html)

    fake_session.on("GET", "/forum/tracker.php", handler)

    await search_torrents_impl(app_ctx, "Дюна")
    first = len(calls)
    await search_torrents_impl(app_ctx, "Дюна")
    assert len(calls) == first  # cache hit, no new network call
