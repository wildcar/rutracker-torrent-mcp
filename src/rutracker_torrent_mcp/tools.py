"""MCP tool implementations.

Three tools:

- ``search_torrents(query, category=None, min_seeders=0, limit=10)``
- ``get_torrent_file(topic_id)`` — returns the .torrent bytes base64-encoded
- ``get_magnet_link(topic_id)``

Captcha / login failures bubble up as structured :class:`ToolError` with
a stable ``code`` so the calling bot can render a specific instruction
to the operator.
"""

from __future__ import annotations

import base64

import structlog

from .clients.rutracker import (
    LoginCaptchaRequired,
    LoginFailed,
    NotAuthenticated,
    RutrackerError,
)
from .context import AppContext
from .models import (
    GetMagnetLinkResponse,
    GetTopicInfoResponse,
    GetTorrentFileResponse,
    MagnetLink,
    SearchTorrentsResponse,
    ToolError,
    TopicInfo,
    TorrentFile,
    TorrentSearchResult,
)

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# search_torrents
# ---------------------------------------------------------------------------


async def search_torrents_impl(
    ctx: AppContext,
    query: str,
    category: int | None = None,
    min_seeders: int = 0,
    limit: int = 10,
) -> SearchTorrentsResponse:
    if not query or not query.strip():
        return SearchTorrentsResponse(
            error=ToolError(code="invalid_argument", message="`query` must not be empty.")
        )
    if limit < 1 or limit > 50:
        return SearchTorrentsResponse(
            error=ToolError(code="invalid_argument", message="`limit` must be between 1 and 50.")
        )

    cache_args = {"q": query, "c": category, "ms": min_seeders, "l": limit}
    cache_key = ctx.cache.make_key("search_torrents", cache_args)
    if (cached := await ctx.cache.get(cache_key)) is not None:
        return SearchTorrentsResponse.model_validate(cached)

    try:
        # Ask rutracker for the top ``limit`` by seeders and filter locally
        # since the tracker has no "min seeders" query parameter.
        raw_rows = await ctx.rutracker.search(query, category=category, limit=limit * 3)
    except (LoginCaptchaRequired, LoginFailed, NotAuthenticated) as exc:
        return SearchTorrentsResponse(error=_auth_error(exc))
    except RutrackerError as exc:
        return SearchTorrentsResponse(
            error=ToolError(code="upstream_error", message=f"rutracker search failed: {exc}")
        )
    except Exception as exc:
        log.warning("rutracker.search_failed", error=str(exc))
        return SearchTorrentsResponse(
            error=ToolError(code="upstream_error", message=f"rutracker search failed: {exc}")
        )

    rows = [r for r in raw_rows if r["seeders"] >= min_seeders][:limit]
    results = [TorrentSearchResult(**r) for r in rows]
    response = SearchTorrentsResponse(results=results)
    await ctx.cache.set(
        cache_key, response.model_dump(mode="json"), ctx.settings.cache_ttl_search_seconds
    )
    return response


# ---------------------------------------------------------------------------
# get_torrent_file
# ---------------------------------------------------------------------------


async def get_torrent_file_impl(ctx: AppContext, topic_id: int) -> GetTorrentFileResponse:
    if topic_id <= 0:
        return GetTorrentFileResponse(
            error=ToolError(
                code="invalid_argument", message="`topic_id` must be a positive integer."
            )
        )

    cache_key = ctx.cache.make_key("get_torrent_file", {"t": topic_id})
    if (cached := await ctx.cache.get(cache_key)) is not None:
        return GetTorrentFileResponse.model_validate(cached)

    try:
        filename, content = await ctx.rutracker.download_torrent(topic_id)
    except (LoginCaptchaRequired, LoginFailed, NotAuthenticated) as exc:
        return GetTorrentFileResponse(error=_auth_error(exc))
    except RutrackerError as exc:
        return GetTorrentFileResponse(
            error=ToolError(code="upstream_error", message=f"rutracker download failed: {exc}")
        )

    payload = TorrentFile(
        topic_id=topic_id,
        filename=filename,
        content_base64=base64.b64encode(content).decode("ascii"),
        size_bytes=len(content),
    )
    response = GetTorrentFileResponse(file=payload)
    await ctx.cache.set(
        cache_key, response.model_dump(mode="json"), ctx.settings.cache_ttl_torrent_seconds
    )
    return response


# ---------------------------------------------------------------------------
# get_magnet_link
# ---------------------------------------------------------------------------


async def get_magnet_link_impl(ctx: AppContext, topic_id: int) -> GetMagnetLinkResponse:
    if topic_id <= 0:
        return GetMagnetLinkResponse(
            error=ToolError(
                code="invalid_argument", message="`topic_id` must be a positive integer."
            )
        )

    cache_key = ctx.cache.make_key("get_magnet_link", {"t": topic_id})
    if (cached := await ctx.cache.get(cache_key)) is not None:
        return GetMagnetLinkResponse.model_validate(cached)

    try:
        magnet = await ctx.rutracker.magnet_link(topic_id)
    except (LoginCaptchaRequired, LoginFailed, NotAuthenticated) as exc:
        return GetMagnetLinkResponse(error=_auth_error(exc))
    except RutrackerError as exc:
        return GetMagnetLinkResponse(
            error=ToolError(code="upstream_error", message=f"rutracker topic fetch failed: {exc}")
        )

    if not magnet:
        return GetMagnetLinkResponse(
            error=ToolError(code="not_found", message=f"No magnet link on topic {topic_id}.")
        )

    response = GetMagnetLinkResponse(magnet=MagnetLink(topic_id=topic_id, magnet=magnet))
    await ctx.cache.set(
        cache_key, response.model_dump(mode="json"), ctx.settings.cache_ttl_torrent_seconds
    )
    return response


# ---------------------------------------------------------------------------
# get_topic_info
# ---------------------------------------------------------------------------


async def get_topic_info_impl(ctx: AppContext, topic_id: int) -> GetTopicInfoResponse:
    if topic_id <= 0:
        return GetTopicInfoResponse(
            error=ToolError(
                code="invalid_argument", message="`topic_id` must be a positive integer."
            )
        )

    cache_key = ctx.cache.make_key("get_topic_info", {"t": topic_id})
    if (cached := await ctx.cache.get(cache_key)) is not None:
        return GetTopicInfoResponse.model_validate(cached)

    try:
        raw = await ctx.rutracker.topic_info(topic_id)
    except (LoginCaptchaRequired, LoginFailed, NotAuthenticated) as exc:
        return GetTopicInfoResponse(error=_auth_error(exc))
    except RutrackerError as exc:
        return GetTopicInfoResponse(
            error=ToolError(code="upstream_error", message=f"rutracker topic fetch failed: {exc}")
        )

    if raw is None:
        return GetTopicInfoResponse(
            error=ToolError(
                code="not_found",
                message=f"No parseable title on topic {topic_id} (removed or restricted?).",
            )
        )

    response = GetTopicInfoResponse(topic=TopicInfo(**raw))
    # Topic title rarely changes; reuse the search-cache TTL bucket so we
    # don't hammer rutracker on retries.
    await ctx.cache.set(
        cache_key, response.model_dump(mode="json"), ctx.settings.cache_ttl_search_seconds
    )
    return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth_error(exc: Exception) -> ToolError:
    """Translate an authentication-path exception into a stable tool error."""
    if isinstance(exc, LoginCaptchaRequired):
        return ToolError(
            code="captcha_required",
            message=(
                "rutracker is requesting a captcha. Log in manually in a browser, "
                "copy the bb_session cookie and place it in the server's cookie jar "
                "(RUTRACKER_COOKIES_PATH)."
            ),
        )
    if isinstance(exc, NotAuthenticated):
        return ToolError(
            code="not_configured",
            message="rutracker credentials are not configured (RUTRACKER_LOGIN / RUTRACKER_PASSWORD).",
        )
    if isinstance(exc, LoginFailed):
        return ToolError(
            code="login_failed",
            message="rutracker rejected the supplied credentials.",
        )
    return ToolError(code="upstream_error", message=str(exc))


__all__ = [
    "get_magnet_link_impl",
    "get_topic_info_impl",
    "get_torrent_file_impl",
    "search_torrents_impl",
]
