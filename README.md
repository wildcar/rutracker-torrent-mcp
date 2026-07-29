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
relogins once and retries. This applies both to login-page responses and to
HTTP `401`/`403`, which rutracker uses for missing or expired sessions.

### `get_magnet_link(topic_id)`

Parses the magnet link off the topic page.

### `get_topic_info(topic_id)`

Fetches topic metadata — title, forum, size, registered date, and the
canonical topic URL — **without** downloading the `.torrent`. Used to resolve
a pasted rutracker topic URL into a release the metadata flow can match.

## Captcha / login

Production can use `RUTRACKER_BACKEND=playwright`. In this mode MCP connects to
a persistent headful Chromium over loopback CDP; search, topic pages, magnets and
`.torrent` downloads all stay inside the same browser context. Initial login and
future Cloudflare challenges are completed manually through loopback-only noVNC:

```bash
ssh -L 6080:127.0.0.1:6080 keeper@208.92.227.90
```

Then open `http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=scale`. The Chromium
profile survives service and host restarts. A session requiring operator action
returns `manual_auth_required`.

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
expired cookie triggers one silent relogin attempt; the request is retried once
and never loops.

## Env variables

| Name | Required | Default | Notes |
|---|:-:|---|---|
| `RUTRACKER_LOGIN` | ✅ | — | rutracker username. |
| `RUTRACKER_PASSWORD` | ✅ | — | rutracker password. |
| `RUTRACKER_COOKIES_PATH` |  | `.cache/cookies.json` | Persisted cookie jar. |
| `RUTRACKER_PROXY_URL` |  | — | Optional SOCKS5/HTTP proxy. |
| `RUTRACKER_BASE_URL` |  | `https://rutracker.org` | Override to a mirror if needed. |
| `RUTRACKER_BACKEND` |  | `curl` | `curl` or persistent `playwright`. |
| `RUTRACKER_BROWSER_CDP_URL` |  | `http://127.0.0.1:9222` | Persistent Chromium CDP endpoint. |
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
