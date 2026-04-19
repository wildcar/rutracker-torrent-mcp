# rutracker-torrent-mcp

MCP server that searches **rutracker.org** and downloads `.torrent` files. No
official API — everything is scraped over an authenticated cookie session.

## Tools

### `search_torrents(query, category=None, min_seeders=0, limit=10)`

Free-text search. Sort order is fixed (**seeders descending**); `min_seeders`
filters locally after the tracker reply. Returns up to `limit` rows (cap 50).
Each row carries `topic_id`, title, forum, size, seeders, leechers, downloads,
registered date, parsed quality (`1080p`, `2160p`, `WEB-DL`, …), and an
`hdr` flag.

### `get_torrent_file(topic_id)`

Downloads the `.torrent` via `/forum/dl.php?t=...`. Returns the raw bytes
**base64-encoded** along with the filename the tracker suggests. An
authenticated session is required; if the current cookie expired the client
relogins once and retries.

### `get_magnet_link(topic_id)`

Parses the magnet link off the topic page.

## Captcha / login

rutracker sometimes responds to a fresh login with a captcha. The tool layer
translates that into a structured error:

```json
{ "error": { "code": "captcha_required", "message": "..." } }
```

Workaround: log in manually in a browser, export the `bb_session` cookie, and
drop it into `RUTRACKER_COOKIES_PATH` (default `.cache/cookies.json`) as a
small JSON map:

```json
{ "bb_session": "..." }
```

On restart the client reuses the cookie and never asks for credentials. An
expired cookie triggers one silent relogin attempt.

## Env variables

| Name | Required | Default | Notes |
|---|:-:|---|---|
| `RUTRACKER_LOGIN` | ✅ | — | rutracker username. |
| `RUTRACKER_PASSWORD` | ✅ | — | rutracker password. |
| `RUTRACKER_COOKIES_PATH` |  | `.cache/cookies.json` | Persisted cookie jar. |
| `RUTRACKER_PROXY_URL` |  | — | Optional SOCKS5/HTTP proxy. |
| `RUTRACKER_BASE_URL` |  | `https://rutracker.org` | Override to a mirror if needed. |
| `MCP_AUTH_TOKEN` | for HTTP | — | Bearer token shared with the bot. |
| `MCP_TRANSPORT` |  | `stdio` | One of `stdio`, `sse`, `streamable-http`. |
| `MCP_HTTP_HOST` |  | `127.0.0.1` | Bind host for HTTP transports. |
| `MCP_HTTP_PORT` |  | `8767` | Bind port for HTTP transports. |
| `CACHE_TTL_SEARCH_SECONDS` |  | `3600` | Cache lifetime for `search_torrents`. |
| `CACHE_TTL_TORRENT_SECONDS` |  | `86400` | Cache lifetime for `.torrent`/magnet. |

## Future providers

The MCP surface is tracker-agnostic — the `Trailer`-style `source` field is
absent because the current signature only needs one tracker, but the
`clients/` module is the only place that would need a new file to add
another tracker (noname-club, kinozal, …). Tools, models, and cache keep as
they are.

## Tests

```bash
uv run pytest                 # unit tests, HTML fixtures + respx
uv run pytest -m integration  # opt-in, hits the real rutracker.org
```
