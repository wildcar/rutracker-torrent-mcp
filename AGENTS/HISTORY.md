# History

Newest first. Each entry ≤5 lines using the format defined in `AGENTS.md`.

---

## 2026-08-08 · Split Cloudflare challenge from logout; fix tab leak
- What: New `CloudflareChallenge` → `cloudflare_challenge` code, keyed off the `cf-mitigated` header; `ManualLoginRequired` now means only a real logout. Client became an async context manager and reaps stranded `about:blank`/challenge tabs on `open()`.
- Why: Search returned `manual_auth_required` while the session was valid (`logged_in_as=wildcar`, `index.php` 200) — Cloudflare was challenging `tracker.php` alone; the message sent the operator to a non-existent login problem. 11 tabs had leaked in prod, two burning CPU on stuck Turnstile.
- Files: `src/rutracker_torrent_mcp/clients/{browser,rutracker}.py`, `src/rutracker_torrent_mcp/tools.py`, `tests/test_browser.py`, `AGENTS/{SPEC,STATE,HISTORY}.md`.
- Next: `_parse_search` yields `size=None` on the browser backend — check markup drift.

## 2026-07-29 · Commit rutracker-proxy.service into deploy/systemd
- What: Added the SOCKS5-tunnel unit (host copy of `/etc/systemd/system/rutracker-proxy.service`) so `deploy/systemd/` is self-contained; `rutracker-browser.service` already `Requires=` it.
- Why: The browser unit referenced a unit that existed only on the host; no secrets involved (key path only).
- Files: `deploy/systemd/rutracker-proxy.service`, `AGENTS/{ENV,STATE,HISTORY}.md`.
- Next: —

## 2026-07-29 · Deploy and authorize persistent browser backend
- What: Deployed Chromium/Xvfb/noVNC/CDP, authenticated the profile, restricted the SSH key to forwarding, and live-tested all four tools.
- Why: Complete the Cloudflare-compatible Rutracker recovery end to end.
- Files: production systemd/env/profile; `AGENTS/STATE.md`.
- Next: Reopen noVNC only when MCP reports `manual_auth_required`.

## 2026-07-29 · Persistent Playwright backend with manual noVNC login
- What: Added a CDP Playwright client, persistent Chromium/Xvfb/noVNC units, browser-only torrent fetches, config/docs, and tests.
- Why: Cloudflare binds clearance to the real browser fingerprint, so exported cookies fail in `curl_cffi`.
- Files: `clients/browser.py`, `context.py`, `config.py`, `tools.py`, `deploy/`, `tests/test_browser.py`, docs/env.
- Next: Deploy, log in through SSH-forwarded noVNC, and live-test all MCP tools.

## 2026-07-29 · Recover expired rutracker sessions returned as HTTP 403
- What: Protected GETs now relogin once on login pages or HTTP 401/403; concurrent failures share the refreshed cookie and a second 403 stops.
- Why: `/forum/tracker.php` changed expired-session behavior from a login form to HTTP 403, breaking torrent search.
- Files: `clients/rutracker.py`, `tests/test_tools.py`, `tests/test_parsing.py`, `README.md`, `AGENTS/{SPEC,STATE,HISTORY}.md`.
- Next: Deploy on the bot host and verify a live search refreshes the stale cookie.

## 2026-06-23 · Migrate to agent-template harness
- What: Added `AGENTS.md`, `CLAUDE.md` pointer, `AGENTS/{SPEC,STATE,HISTORY,MEMORY,ENV}.md`, `docs/adr/TEMPLATE.md`; folded `history.md`/`env.md`.
- Why: Adopt the standard workspace harness; keep repo-local context authoritative inside the repo.
- Files: `AGENTS.md`, `CLAUDE.md`, `AGENTS/*`, `docs/adr/TEMPLATE.md`; removed `history.md` (`env.md` absent).
- Next: Resume feature work under the new structure.

## 2026-04-26 · Anchor topic-page size parser on the «Размер» label
- What: Added `_SIZE_LABELED_RE`; `_parse_topic` now requires a `Размер:`/`Size:` label before the size token.
- Why: Whole-page `_SIZE_RE` matched stray `B`/`KB`/… tokens (CSS, scripts) → `size_bytes=5` for a 75 GB release.
- Files: `clients/rutracker.py`.
- Next: `_parse_search` untouched (already scopes to the size cell).

## 2026-04-26 · `get_topic_info(topic_id)` tool
- What: New `RutrackerClient.topic_info` + `TopicInfo`/`GetTopicInfoResponse` models + `get_topic_info_impl`; wired as 4th MCP tool.
- Why: Bot needs cheap topic title + forum context (no `.torrent`) when a user pastes a rutracker URL — feeds the composite media-id pipeline.
- Files: `clients/rutracker.py`, `models.py`, `tools.py`, `server.py`, `tests/fixtures/tracker_topic.html`.
- Next: Title required → `not_found`; same caching/auth-error shaping as the other tools.
