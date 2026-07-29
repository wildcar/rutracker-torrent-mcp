# Environment

Repo-local environment notes. Cross-repo host facts, deploy commands, and
credentials layout live in `../AGENTS/ENV.md` — read that for hosts (dev box, bot
host `homesrv`, media host) and the prod cheat-sheet. This file lists only what is
specific to `rutracker-torrent-mcp`.

## Deploy target

Bot host (`homesrv`), systemd unit under user `movie`, bound to `127.0.0.1:8767`
(HTTP+SSE behind the shared `MCP_AUTH_TOKEN`). Local dev runs over `stdio`.

## Env variables

| Name | Required | Default | Notes |
|---|:-:|---|---|
| `RUTRACKER_LOGIN` | ✅ | — | rutracker username. |
| `RUTRACKER_PASSWORD` | ✅ | — | rutracker password. |
| `RUTRACKER_COOKIES_PATH` |  | `.cache/cookies.json` | Persisted `bb_session` cookie jar (JSON). Manual captcha-recovery drop point — see `MEMORY.md`. |
| `RUTRACKER_PROXY_URL` |  | — | Optional SOCKS5/HTTP proxy if the host can't reach rutracker directly. |
| `RUTRACKER_BASE_URL` |  | `https://rutracker.org` | Override to a mirror (`.net`/`.nl`) only as a fallback. |
| `RUTRACKER_BACKEND` |  | `curl` | `curl` or persistent `playwright` browser backend. |
| `RUTRACKER_BROWSER_CDP_URL` |  | `http://127.0.0.1:9222` | CDP endpoint used by the Playwright backend. |
| `MCP_AUTH_TOKEN` | for HTTP | — | Bearer token shared with the bot. |
| `MCP_TRANSPORT` |  | `stdio` | `stdio` \| `sse` \| `streamable-http`. |
| `MCP_HTTP_HOST` |  | `127.0.0.1` | Bind host for HTTP transports. |
| `MCP_HTTP_PORT` |  | `8767` | Bind port for HTTP transports. |
| `CACHE_PATH` |  | `.cache/rutracker.sqlite` | aiosqlite TTL cache. |
| `CACHE_TTL_SEARCH_SECONDS` |  | `3600` | `search_torrents` / `get_topic_info` TTL. |
| `CACHE_TTL_TORRENT_SECONDS` |  | `86400` | `.torrent` / magnet TTL. |

Never commit a real `.env`, `.cache/`, the cookie jar, or `*.sqlite` — all
gitignored. `.env.example` ships placeholders + obtain-instructions.

## Run & verify

```bash
uv sync
uv run python -m rutracker_torrent_mcp.server            # stdio
uv run pytest && uv run ruff check && uv run mypy src
uv run pytest -m integration                             # opt-in; needs real creds
npx @modelcontextprotocol/inspector uv run python -m rutracker_torrent_mcp.server
```

## Manual browser login

Production Chromium uses a persistent profile and exposes noVNC on loopback only.
Forward it from an operator workstation:

```bash
ssh -L 6080:127.0.0.1:6080 keeper@208.92.227.90
```

Open `http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=scale`, complete the
Cloudflare check, and log in to rutracker. MCP uses a separate tab in that same
profile. No VNC/CDP port may be exposed publicly.
