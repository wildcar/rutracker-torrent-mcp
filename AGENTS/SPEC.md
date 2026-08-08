# rutracker-torrent-mcp — functional & technical specification

Source of truth for *what this server does* and *how it is built*. Cross-repo
contract lives in `../AGENTS/SPEC.md`; this document is repo-local.

## Purpose

Expose rutracker.org to the movie_handler system as MCP tools: free-text torrent
search, `.torrent` download (base64), magnet-link lookup, and lightweight topic
metadata. rutracker has **no official API**, so everything is HTML-scraped over an
authenticated cookie session. Priority 4; port 8767.

The download key the rest of the system uses is the composite `media_id`
`rt-<topic_id>` — this server only deals in raw `topic_id` (int).

## Stack

- Python ≥ 3.11, `asyncio`.
- Two selectable acquisition backends:
  - **`curl_cffi`** for ordinary cookie sessions and local development.
  - **Playwright over CDP** for Cloudflare-protected production sessions. It connects
    to an externally managed, persistent, headful Chromium profile; all protected
    navigation and torrent downloads stay inside that browser context.
- **`selectolax`** for HTML parsing.
- `pydantic` v2 + `pydantic-settings`; `structlog` (JSON); `aiosqlite` TTL cache.
- Tests: `pytest` + `pytest-asyncio` + `respx`, HTML fixtures; opt-in `integration`
  marker hits the real site. CI: `ruff` → `mypy --strict` → `pytest`.

## Tools

All tools return a `…Response` Pydantic model carrying either the payload or
`error: ToolError` (`{code, message}`). They never raise across the MCP boundary.

### `search_torrents(query, category=None, min_seeders=0, limit=10) -> SearchTorrentsResponse`

Free-text search via `GET /forum/tracker.php?nm=<query>`. **Sort is fixed: seeders
descending** (rutracker `o=10&s=2`); there is no "min seeders" query param, so the
client over-fetches (`limit * 3`) and `min_seeders` is filtered **locally** before
truncating to `limit` (1–50, else `invalid_argument`). Empty `query` →
`invalid_argument`. Each `TorrentSearchResult` carries `topic_id`, `title`,
`forum_id`/`forum_name`, `size_bytes`, `seeders`, `leechers`, `downloads`,
`registered_at` (ISO date), parsed `quality` (resolution tag, falls back to source
tag for back-compat), `source` (release type — `WEB-DL`/`BDRip`/`BDRemux`/`WEBRip`),
`hdr` flag, and absolute `url`. Cached `CACHE_TTL_SEARCH_SECONDS` (1 h).

### `get_torrent_file(topic_id) -> GetTorrentFileResponse`

Downloads `.torrent` via `/forum/dl.php?t=<topic_id>`. Returns raw bytes
**base64-encoded** in `TorrentFile` with the `Content-Disposition` filename and
decoded `size_bytes`. Requires an authed session. `topic_id <= 0` →
`invalid_argument`. Cached `CACHE_TTL_TORRENT_SECONDS` (24 h).

### `get_magnet_link(topic_id) -> GetMagnetLinkResponse`

Parses the magnet link off `viewtopic.php?t=<topic_id>`. No magnet on the page →
`not_found`. Cached at the torrent TTL.

### `get_topic_info(topic_id) -> GetTopicInfoResponse`

Cheap title + forum context from `viewtopic.php?t=<topic_id>` **without** fetching
the `.torrent`. Used when a user pastes a rutracker URL directly (bot flow: clean
title → match against `movie-metadata-mcp`). Selectors: `a#topic-title` /
`h1.maintitle a` for the (required) title; trailing `a[href*="viewforum.php?f="]`
breadcrumb for forum id/name; best-effort size + upload date. Missing title →
`not_found`. Cached at the search TTL (titles rarely change).

## Auth, cookie session & captcha

- `RUTRACKER_BACKEND=curl|playwright` selects the client. Playwright mode connects
  to `RUTRACKER_BROWSER_CDP_URL` (default `http://127.0.0.1:9222`) and never submits
  credentials itself. The operator opens the same persistent Chromium display via
  loopback-only noVNC over an SSH tunnel, completes Cloudflare/login manually, and
  closes the tab. The profile survives MCP and host restarts.
- A missing/expired Playwright browser session maps to
  `ToolError(code="manual_auth_required", …)`; automatic retries cannot solve it.
- **Challenge ≠ logout.** Cloudflare gating and a logged-out session are separate
  failures with separate codes. A response carrying `cf-mitigated: challenge` (or,
  when headers are unreadable, the `Just a moment...` title) raises
  `CloudflareChallenge` → `ToolError(code="cloudflare_challenge", …)`; only an
  actual login form — or a `401`/`403` with no challenge marker — raises
  `ManualLoginRequired` → `manual_auth_required`. The header is authoritative when
  present. Both need noVNC, but the remedies differ: the challenge needs a Turnstile
  solve while the session stays valid, so reporting it as "authentication required"
  sends the operator after a problem that isn't there. Cloudflare challenges
  `/forum/tracker.php` (search) independently of `index.php` / `viewtopic.php`,
  so search can fail while the rest of the site loads fine and the account is
  still signed in.

- Login is `POST /forum/login.php` (rate-limited, captcha-prone). On success the
  client holds a `bb_session` cookie, persisted to `RUTRACKER_COOKIES_PATH` (default
  `.cache/cookies.json`) and reused across restarts — credentials aren't re-sent
  while the cookie is valid.
- **Auto-relogin:** an authed GET that returns the login page or HTTP `401`/`403`
  (rutracker currently uses `403` for a missing/expired session on
  `/forum/tracker.php`) triggers exactly **one** silent relogin + retry. A second
  auth failure is returned as an upstream error; there is no retry loop.
- **Captcha:** when rutracker answers a fresh login with a captcha
  (`cap_sid` / `name="cap_code"` markers), the client raises `LoginCaptchaRequired`,
  which the tool layer maps to `ToolError(code="captcha_required", …)`. The captcha
  cannot be solved automatically — recovery is manual (see MEMORY).
- Error taxonomy (`clients/rutracker.py`): `RutrackerError` (base), `LoginFailed`,
  `LoginCaptchaRequired`, `NotAuthenticated`, `ManualLoginRequired`,
  `CloudflareChallenge`. `_auth_error()` in `tools.py` maps these to
  `captcha_required` / `login_failed` / `not_configured` / `manual_auth_required` /
  `cloudflare_challenge`; other failures → `upstream_error`.

- **Tab hygiene (playwright backend):** the persistent profile outlives every MCP
  process, so a client killed before `aclose()` strands its tab forever — stranded
  challenge tabs are the expensive ones, since Turnstile scripts and blob workers
  keep running. `PlaywrightRutrackerClient` is an async context manager (page closed
  on every exit path), and `open()` reaps `about:blank` and challenge-stranded tabs
  so restarts self-heal. Chromium exits with its last tab, so the reaper always
  leaves one standing.

## Parsing notes (gotchas)

- **Size parsing.** `_parse_size` uses `_SIZE_RE` over the size *cell* in search
  rows. On the **topic page** the whole-page regex once matched `<input size=5>` and
  returned `size_bytes=5` for a 75 GB release — `_parse_topic` now uses
  `_SIZE_LABELED_RE`, which only fires when the token follows a `Размер:` / `Size:`
  label. Multipliers in `_SIZE_MULT` (binary: KB=1024, …, TB=1024⁴).
- Seeders read from `b.seedmed`; `registered_at` normalised to ISO `YYYY-MM-DD`.

## Project structure

```
src/rutracker_torrent_mcp/
  server.py            # FastMCP entrypoint; registers the 4 tools; transport select
  tools.py             # *_impl tool funcs: validation, cache, error shaping
  context.py           # AppContext (settings + client + cache lifecycle)
  config.py            # Settings (pydantic-settings)
  models.py            # Pydantic tool I/O (extra="forbid")
  cache.py             # aiosqlite TTL cache (make_key/get/set)
  clients/rutracker.py # RutrackerClient: search/download/magnet/topic_info,
                        #   login, cookie persistence, HTML parsers
tests/                 # pytest + respx; HTML fixtures; integration marker
```

Package name: **`rutracker_torrent_mcp`**. Entry: `rutracker-torrent-mcp` →
`rutracker_torrent_mcp.server:main`.

## Future providers

The tool surface is tracker-agnostic. Adding noname-club / kinozal would only mean a
new file under `clients/`; tools, models, and cache stay as-is.

## Current state

All four tools implemented, tested, and wired into `server.py`. Deployed on the bot
host (systemd, `127.0.0.1:8767`). See `AGENTS/STATE.md` for the live snapshot.
