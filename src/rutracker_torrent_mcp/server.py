"""MCP entrypoint: registers the four torrent tools and starts the transport."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Final

import structlog
from mcp.server.fastmcp import FastMCP

from . import __version__
from .config import Settings, get_settings
from .context import AppContext, build_app_context
from .models import (
    GetMagnetLinkResponse,
    GetTopicInfoResponse,
    GetTorrentFileResponse,
    SearchTorrentsResponse,
)
from .tools import (
    get_magnet_link_impl,
    get_topic_info_impl,
    get_torrent_file_impl,
    search_torrents_impl,
)

_SUPPORTED_TRANSPORTS: Final[frozenset[str]] = frozenset({"stdio", "sse", "streamable-http"})


def _configure_logging() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )


def build_server(ctx: AppContext) -> FastMCP:
    mcp = FastMCP(
        name="rutracker-torrent-mcp",
        host=os.environ.get("MCP_HTTP_HOST", "127.0.0.1"),
        port=int(os.environ.get("MCP_HTTP_PORT", "8767")),
        instructions=(
            "Searches rutracker.org for torrents and returns .torrent files "
            "(base64-encoded) or magnet links. Use search_torrents to pick a "
            "topic, then get_torrent_file(topic_id) or get_magnet_link(topic_id). "
            "When the user pastes a topic URL directly, use get_topic_info(topic_id) "
            "to fetch just the title and forum context without downloading the file."
        ),
    )

    async def search_torrents(
        query: str,
        category: int | None = None,
        min_seeders: int = 0,
        limit: int = 10,
    ) -> SearchTorrentsResponse:
        """Search rutracker by free text. Results sorted by seeders descending."""
        return await search_torrents_impl(ctx, query, category, min_seeders, limit)

    async def get_torrent_file(topic_id: int) -> GetTorrentFileResponse:
        """Download the .torrent for `topic_id`. Returns base64-encoded bytes + filename."""
        return await get_torrent_file_impl(ctx, topic_id)

    async def get_magnet_link(topic_id: int) -> GetMagnetLinkResponse:
        """Return the magnet link parsed from the topic page."""
        return await get_magnet_link_impl(ctx, topic_id)

    async def get_topic_info(topic_id: int) -> GetTopicInfoResponse:
        """Return title, forum, size and upload date for `topic_id`. No .torrent fetch."""
        return await get_topic_info_impl(ctx, topic_id)

    mcp.tool()(search_torrents)
    mcp.tool()(get_torrent_file)
    mcp.tool()(get_magnet_link)
    mcp.tool()(get_topic_info)
    return mcp


async def _run(settings: Settings, transport: str) -> None:
    async with build_app_context(settings) as ctx:
        server = build_server(ctx)
        structlog.get_logger().info(
            "rutracker_mcp.starting", version=__version__, transport=transport
        )
        if transport == "stdio":
            await server.run_stdio_async()
        elif transport == "sse":
            await server.run_sse_async()
        else:
            await server.run_streamable_http_async()


def main() -> None:
    _configure_logging()
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()
    if transport not in _SUPPORTED_TRANSPORTS:
        raise SystemExit(
            f"Unsupported MCP_TRANSPORT={transport!r}; "
            f"expected one of {sorted(_SUPPORTED_TRANSPORTS)}"
        )
    asyncio.run(_run(get_settings(), transport))


if __name__ == "__main__":
    main()
