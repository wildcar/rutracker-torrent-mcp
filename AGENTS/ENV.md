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
| `RUTRACKER_BROWSER_CONNECT_TIMEOUT_SECONDS` |  | `10` | Per-attempt CDP connect timeout (connect is lazy, on first tool call). |
| `RUTRACKER_BROWSER_CONNECT_ATTEMPTS` |  | `3` | CDP connect attempts before the call fails. |
| `RUTRACKER_BROWSER_CONNECT_BACKOFF_SECONDS` |  | `2` | Delay before the 2nd attempt; doubles each retry. |
| `RUTRACKER_BROWSER_PROFILE` |  | — | Chromium profile dir. Set ⇒ the MCP launches the browser itself and stops it when idle. Unset ⇒ attach-only over CDP. |
| `RUTRACKER_BROWSER_EXECUTABLE_PATH` |  | — | Chromium binary; default resolves through `PLAYWRIGHT_BROWSERS_PATH`. |
| `RUTRACKER_BROWSER_PROXY_URL` |  | — | Proxy for the launched browser (prod: `socks5://127.0.0.1:1080`). |
| `RUTRACKER_BROWSER_IDLE_TIMEOUT_SECONDS` |  | `300` | Idle time before a self-launched browser is shut down. |
| `RUTRACKER_BROWSER_MANUAL_LOGIN_GRACE_SECONDS` |  | `1800` | Keep-alive after `manual_auth_required` / `cloudflare_challenge`, so the operator can fix it over noVNC. |

Production also needs `DISPLAY=:99`, `HOME=/var/lib/rutracker-browser/home` and
`PLAYWRIGHT_BROWSERS_PATH=/var/lib/rutracker-browser/playwright` in the MCP unit —
all set by `deploy/systemd/rutracker-torrent-mcp-playwright.conf`, which also turns
`PrivateTmp` off (Xvfb's socket lives in the host `/tmp`).
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

The MCP starts Chromium on demand and stops it when idle, so most of the time no
browser is running. To sign in or solve a Turnstile:

```bash
sudo systemctl start rutracker-browser   # not enabled; manual login only
# …sign in through noVNC…
sudo systemctl stop rutracker-browser    # hand the profile back to the MCP
```

On `cloudflare_challenge` / `manual_auth_required` the MCP **disconnects its CDP
client** and leaves its spawned Chromium on the display for the grace window —
Turnstile loops while any CDP client is attached (see `MEMORY.md`), so the
hand-over browser is deliberately client-free. Just open the challenge link (or
noVNC) and solve; the next tool call re-attaches to the same process. The
`rutracker-browser.service` unit is only needed when the display is empty (the
grace window lapsed). While the unit runs it holds the profile lock and the MCP
attaches to it instead of spawning its own, so stop it when done.

Starting the unit while the MCP's browser is up is a no-op: Chromium sees the
single-instance lock, logs `Opening in existing browser session` and exits, leaving
the unit `inactive`. That's expected — the browser you want is already on the
display.

Production Chromium uses a persistent profile and exposes noVNC on loopback only.
Ubuntu 24.04 AppArmor blocks the downloaded Chromium user-namespace sandbox, so
the launcher uses `--no-sandbox`; containment is provided by the dedicated `movie`
account plus `NoNewPrivileges`, `ProtectSystem=strict`, and narrow writable paths.
The bot host exits through the loopback SOCKS tunnel to `keeper@212.192.223.34`
(`deploy/systemd/rutracker-proxy.service`, `-D 127.0.0.1:1080`, key at
`/var/lib/rutracker-proxy/id_ed25519`); the dedicated SSH key is restricted to
port forwarding on that host. Host drop-in `rutracker-torrent-mcp.service.d/proxy.conf` uses
`Wants=` + `After=` (not `Requires=`): a failing tunnel (e.g. changed host key after a
reinstall → `known_hosts` must be re-pinned, and the `.pub` re-added to the remote
`authorized_keys`) must not restart the MCP in a loop.
Two ways in:

1. **Telegram button (primary).** On `cloudflare_challenge` / `manual_auth_required`
   the bot mints a one-time token into `/var/lib/rutracker-challenge/token` and
   sends admins a «Пройти проверку» button → `https://rtcc.wildcar.org/enter/<token>`.
   nginx (`deploy/nginx/rtcc.wildcar.org.conf`) fronts loopback noVNC and asks
   `rutracker-challenge-gate.service` (`deploy/challenge-gate.py`, 127.0.0.1:6079)
   to validate the token/cookie via `auth_request`; everything unauthorized is a
   404. Token TTL 1800 s = the MCP's manual-login grace window.
2. **SSH fallback** from an operator workstation:

```bash
ssh -L 6080:127.0.0.1:6080 keeper@208.92.227.90
```

Open `http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=scale`, complete the
Cloudflare check, and log in to rutracker. MCP uses a separate tab in that same
profile. VNC 5901 / noVNC 6080 / CDP 9222 stay loopback-only — the only public
face is the token-gated nginx vhost.
