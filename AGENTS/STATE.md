# State

Repo-local snapshot. Overwrite each iteration. Cross-repo view in `../AGENTS/STATE.md`.

## Goal

MCP server exposing rutracker.org search + `.torrent`/magnet/topic-info to the
movie_handler bot, via authenticated HTML scraping.

## Now

- Four tools live and tested: `search_torrents`, `get_torrent_file`,
  `get_magnet_link`, `get_topic_info`.
- Selectable `curl` and persistent Playwright backends are implemented.
- The MCP owns Chromium: it launches the browser on the shared profile at the first
  tool call and stops it after 5 min idle, so nothing runs between searches. An
  operator-started `rutracker-browser.service` (manual login only, not enabled) wins
  the profile lock and is attached to over CDP instead, never shut down by us.
- Playwright mode keeps all protected requests inside one headful Chromium profile;
  missing auth returns `manual_auth_required`.
- Production runs commit `370c14a` with loopback-only Xvfb/x11vnc/noVNC/CDP;
  the persistent profile is authenticated. Verified 2026-08-13: exactly one tab
  before and after a browser restart, search + `.torrent` live through the MCP,
  and the MCP survives a browser restart without being restarted itself.
- SOCKS5 egress through `212.192.223.34` is active on the bot host; its unit is
  committed as `deploy/systemd/rutracker-proxy.service`.
- All four tools are live-verified through the browser backend; `.torrent` download
  returned a valid 47,779-byte file.
- Harness migrated to the `agent-template` layout.
- Cloudflare challenges are now reported separately from a logged-out session
  (`cloudflare_challenge` vs `manual_auth_required`), keyed off the `cf-mitigated`
  response header. Previously every Turnstile interstitial claimed the session
  needed re-authentication, which was wrong and unactionable.
- Tab growth closed by construction: the client adopts `context.pages[0]` instead
  of opening a tab, and the reaper now closes everything except that working page.
- CDP connect is lazy (first tool call) with retries + backoff; startup no longer
  depends on the browser being up, and a browser restart self-heals.
- A fatal startup error now exits non-zero (`os._exit(1)`), so `Restart=on-failure`
  actually fires instead of leaving a live process with no listening port.
- `rutracker-browser.service` is memory-capped (`MemoryHigh=768M`, `MemoryMax=1G`);
  `ExecStartPre` wipes Chromium's session-restore state and the launcher no longer
  passes a startup URL.
- Challenge solving is one tap from a phone: token-gated public noVNC at
  `rtcc.wildcar.org` (`deploy/challenge-gate.py` + `deploy/nginx/` vhost +
  `rutracker-challenge-gate.service`); the Telegram bot mints the links.

## Next

- Monitor session lifetime; solve challenges via the bot's «Пройти проверку»
  button (or the SSH-tunnel fallback) when `manual_auth_required` /
  `cloudflare_challenge` is returned.
- (when needed) Additional trackers under `clients/` (noname-club, kinozal).

## Open questions

- —

## Deferred

- —
