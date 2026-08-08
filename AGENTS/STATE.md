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
- Tab leak closed: the client is an async context manager and reaps stranded
  `about:blank` / challenge tabs on `open()`, never dropping below one tab.

## Next

- Monitor session lifetime; use noVNC when `manual_auth_required` (sign in) or
  `cloudflare_challenge` (solve Turnstile) is returned.
- `_parse_search` returns `size=None` for browser-backend rows — the tracker markup
  likely drifted. Worth a look; not blocking, since seeders/title/topic_id are fine.
- (when needed) Additional trackers under `clients/` (noname-club, kinozal).

## Open questions

- —

## Deferred

- —
