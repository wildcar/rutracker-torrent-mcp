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
- Loopback-only Xvfb/x11vnc/noVNC units and the browser launcher are ready for
  production deployment.
- SOCKS5 egress through `212.192.223.34` is active on the bot host.
- Harness migrated to the `agent-template` layout.

## Next

- Deploy the browser stack, complete the first login through noVNC, and verify all
  four live MCP tools.
- (when needed) Additional trackers under `clients/` (noname-club, kinozal).

## Open questions

- —

## Deferred

- —
