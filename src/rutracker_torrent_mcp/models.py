"""Tool-surface models — independent of rutracker's HTML layout."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)


class ToolError(_Base):
    """Structured error envelope returned to the caller."""

    code: str = Field(..., description="Stable machine-readable error code.")
    message: str = Field(..., description="Human-readable explanation (English).")


class TorrentSearchResult(_Base):
    """One row from a tracker search — enough to render a pick-list and
    re-request the .torrent file."""

    topic_id: int = Field(
        ..., description="rutracker topic id; use with get_torrent_file/get_magnet_link."
    )
    title: str = Field(..., description="Raw release title from the tracker.")
    forum_id: int | None = Field(None, description="rutracker forum id (category).")
    forum_name: str | None = Field(None, description="Human-readable category name.")
    size_bytes: int = Field(
        0, description="File size in bytes, 0 if the tracker didn't report one."
    )
    seeders: int = Field(0, ge=0, description="Seed count at the time of the query.")
    leechers: int = Field(0, ge=0, description="Leecher count at the time of the query.")
    downloads: int = Field(
        0, ge=0, description="Total completed downloads reported by the tracker."
    )
    registered_at: str | None = Field(
        None, description="ISO-8601 upload date (YYYY-MM-DD), if parseable."
    )
    # Parsed hints (not a replacement for the full title — the bot shows these
    # on buttons and keeps the raw title in the list description).
    quality: str | None = Field(
        None,
        description=(
            "Resolution tag parsed from the title (e.g. '2160p', '1080p', '720p'). "
            "Returns the source tag when no resolution is found, for backwards-compat."
        ),
    )
    source: str | None = Field(
        None,
        description=(
            "Release type parsed from the title (e.g. 'WEB-DL', 'BDRip', 'BDRemux', 'WEBRip')."
        ),
    )
    hdr: bool = Field(False, description="True when the release is HDR / Dolby Vision.")
    url: str = Field(..., description="Absolute URL to the topic page.")


class SearchTorrentsResponse(_Base):
    results: list[TorrentSearchResult] = Field(default_factory=list)
    error: ToolError | None = None


class TorrentFile(_Base):
    """Base64-encoded .torrent file bundled with its canonical filename."""

    topic_id: int
    filename: str = Field(..., description="Filename the tracker suggests (Content-Disposition).")
    content_base64: str = Field(..., description="Base64-encoded raw .torrent bytes.")
    size_bytes: int = Field(..., ge=0, description="Decoded .torrent length in bytes.")


class GetTorrentFileResponse(_Base):
    file: TorrentFile | None = None
    error: ToolError | None = None


class MagnetLink(_Base):
    topic_id: int
    magnet: str


class GetMagnetLinkResponse(_Base):
    magnet: MagnetLink | None = None
    error: ToolError | None = None
