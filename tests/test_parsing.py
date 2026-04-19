"""Pure HTML-parsing tests — no HTTP mocking needed."""

from __future__ import annotations

from rutracker_torrent_mcp.clients.rutracker import _parse_search, _parse_size


def test_parse_size_gigabytes() -> None:
    assert _parse_size("20.83 GB") == int(20.83 * 1024**3)
    assert _parse_size("4,50 GB") == int(4.50 * 1024**3)
    assert _parse_size("700 MB") == 700 * 1024**2


def test_parse_size_malformed() -> None:
    assert _parse_size("") == 0
    assert _parse_size("n/a") == 0


def test_parse_search_extracts_three_rows(search_html: str) -> None:
    rows = _parse_search(search_html, base_url="https://rutracker.org")
    assert len(rows) == 3
    by_id = {r["topic_id"]: r for r in rows}

    top = by_id[6126543]
    assert "Дюна" in top["title"] and "Dune" in top["title"]
    assert top["forum_id"] == 187
    assert top["forum_name"] == "Зарубежное кино"
    assert top["seeders"] == 1234
    assert top["leechers"] == 56
    assert top["downloads"] == 12345
    assert top["quality"] == "1080p"
    assert top["hdr"] is True
    assert top["size_bytes"] == 22369438290  # exact value from fixture's <u> tag
    assert top["registered_at"] == "2021-10-22"
    assert top["url"].endswith("viewtopic.php?t=6126543")

    mid = by_id[6200000]
    assert mid["quality"] == "WEB-DL"  # our regex captures WEB-DL before 720p
    assert mid["hdr"] is False

    uhd = by_id[6300000]
    assert uhd["quality"] == "2160p"
    assert uhd["hdr"] is True
    assert uhd["seeders"] == 0
