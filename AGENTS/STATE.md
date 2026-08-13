# State

Repo-local snapshot. Overwrite each iteration. Cross-repo view in `../AGENTS/STATE.md`.

## Goal

MCP server exposing rutracker.org search + `.torrent`/magnet/topic-info to the
movie_handler bot, via authenticated HTML scraping.

## Now

- Four tools live and tested: `search_torrents`, `get_torrent_file`,
  `get_magnet_link`, `get_topic_info`.
- Selectable `curl` and persistent Playwright/CDP backends are implemented.
- Playwright mode keeps all protected requests inside one headful Chromium profile;
  missing auth returns `manual_auth_required`.
- Production runs commit `b33bb74` with loopback-only Xvfb/x11vnc/noVNC/CDP;
  the persistent profile is authenticated.
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

## Next

- **Deploy the 2026-08-13 OOM fixes** on the bot host: `git pull --ff-only` in
  `/opt/rutracker-torrent-mcp`, `systemctl daemon-reload`, restart
  `rutracker-browser` and the MCP unit; confirm one tab and a capped cgroup.
- Monitor session lifetime; use noVNC when `manual_auth_required` (sign in) or
  `cloudflare_challenge` (solve Turnstile) is returned.
- (when needed) Additional trackers under `clients/` (noname-club, kinozal).

## Open questions

- —

## Deferred

- **Let the MCP own Chromium** via `launch_persistent_context` on the same profile,
  started on demand and stopped when idle. The browser is only needed during a
  search — the session and `cf_clearance` live in the on-disk profile (cookies valid
  into 2027). That would retire `rutracker-browser.service` and the `Requires=`, and
  remove the orphaned-tab class entirely. Caveat: manual login on
  `ManualLoginRequired` goes through VNC and needs a live browser, so keep the unit
  around for manual starts.
