# State

Repo-local snapshot. Overwrite each iteration. Cross-repo view in `../AGENTS/STATE.md`.

## Goal

MCP server exposing rutracker.org search + `.torrent`/magnet/topic-info to the
movie_handler bot, via authenticated HTML scraping.

## Now

- Four tools live and tested: `search_torrents`, `get_torrent_file`,
  `get_magnet_link`, `get_topic_info`.
- Protected GETs treat a login page or HTTP `401`/`403` as an expired session,
  refresh `bb_session` once under a lock, and retry exactly once.
- Deployed on the bot host as a systemd unit, bound `127.0.0.1:8767`.
- Harness migrated to the `agent-template` layout.

## Next

- (when needed) Additional trackers under `clients/` (noname-club, kinozal).

## Open questions

- —

## Deferred

- —
