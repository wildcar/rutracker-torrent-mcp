# History

Newest first. Each entry ≤5 lines using the format defined in `AGENTS.md`.

---

## 2026-08-21 · Turnstile-loop root cause: attached CDP client
- What: documented that Turnstile loops while Playwright/CDP is attached; challenge flow corrected to restart-MCP → `rutracker-browser.service` → solve → stop; deferred a detachable-browser refactor.
- Why: first live run of the challenge link looped in the MCP's grace-window browser; solving in a client-free Chromium passed, and the `cf_clearance` was honored by the Playwright browser afterwards (verified via `search_torrents` over HTTP).
- Files: `AGENTS/{MEMORY,ENV,STATE,HISTORY}.md`.
- Next: detachable self-launched browser (see Deferred).

---

## 2026-08-21 · Token-gated public noVNC for challenge solving
- What: `deploy/challenge-gate.py` (loopback token gate, stdlib), `rutracker-challenge-gate.service`, and nginx vhost `rtcc.wildcar.org` fronting noVNC via `auth_request`; unauthorized → 404.
- Why: Turnstile solving needed an operator SSH tunnel; now the Telegram bot hands admins a one-time 30-min link that works from a phone.
- Files: `deploy/challenge-gate.py`, `deploy/systemd/rutracker-challenge-gate.service`, `deploy/nginx/rtcc.wildcar.org.conf`, `AGENTS/{ENV,STATE,HISTORY}.md`, `README.md`.
- Next: —

---

## 2026-08-13 · MCP owns Chromium: launch on demand, stop when idle
- What: `launch_persistent_context` on the shared profile when `RUTRACKER_BROWSER_PROFILE` is set, closed after 5 min idle (30 min grace after an auth/challenge error); attach over CDP first so an operator's browser wins the profile lock. `rutracker-browser.service` demoted to a manual-login aid (no `[Install]`, `Restart=no`, disabled); MCP drop-in gains `DISPLAY`/profile/proxy env, `PrivateTmp=false` and the memory cap; MCP unit committed.
- Why: The browser is only needed during a request — session + `cf_clearance` live in the profile — so an around-the-clock headful Chromium was the OOM risk and forced `Requires=` on a second unit.
- Files: `src/rutracker_torrent_mcp/{clients/browser.py,config.py,context.py}`, `deploy/systemd/*`, `tests/test_browser.py`, `.env.example`, `README.md`, `AGENTS/{SPEC,ENV,STATE,HISTORY}.md`.
- Next: —

## 2026-08-13 · Deploy the OOM fixes to the bot host
- What: `370c14a` live on `r1117636`: unit copied to `/etc/systemd/system`, `daemon-reload`, browser + MCP restarted. Verified 1 tab before/after a browser restart (was 3), `MemoryMax=1G` on the cgroup, live search + 13 KB `.torrent` through `127.0.0.1:8767`, and reconnect after a browser restart with the MCP untouched.
- Why: The 18:24 OOM fixes are only worth anything on the host.
- Files: production `/etc/systemd/system/rutracker-browser.service`, `/opt/rutracker-torrent-mcp`; `AGENTS/{STATE,HISTORY}.md`.
- Next: Watch tab count and cgroup memory over the next few searches.

## 2026-08-13 · Bound Chromium: adopt one tab, lazy connect, memory cap
- What: Client adopts `context.pages[0]` (closes it only if it created it); reaper closes every tab but the working one; CDP connect moved to first tool call with retries/backoff; fatal startup errors `os._exit(1)`; browser unit gets `MemoryHigh/MemoryMax` + a session-restore wipe in `ExecStartPre`, launcher drops its startup URL.
- Why: 18:24 the host OOMed on 50 tabs in the persistent Chromium; the MCP then died at 18:25:50 on a 30 s `connect_over_cdp` timeout but stayed alive with no listening port, so systemd reported `active (running)` and never restarted it.
- Files: `src/rutracker_torrent_mcp/{clients/browser.py,config.py,context.py,server.py}`, `deploy/{run-browser.sh,reset-browser-profile.sh,systemd/rutracker-browser.service}`, `tests/test_browser.py`, `.env.example`, `AGENTS/{SPEC,ENV,STATE,HISTORY}.md`.
- Next: Deploy on the bot host; consider letting the MCP own Chromium via `launch_persistent_context` (STATE → Deferred).

## 2026-08-08 · Split Cloudflare challenge from logout; fix tab leak
- What: New `CloudflareChallenge` → `cloudflare_challenge` code, keyed off the `cf-mitigated` header; `ManualLoginRequired` now means only a real logout. Client became an async context manager and reaps stranded `about:blank`/challenge tabs on `open()`.
- Why: Search returned `manual_auth_required` while the session was valid (`logged_in_as=wildcar`, `index.php` 200) — Cloudflare was challenging `tracker.php` alone; the message sent the operator to a non-existent login problem. 11 tabs had leaked in prod, two burning CPU on stuck Turnstile.
- Files: `src/rutracker_torrent_mcp/clients/{browser,rutracker}.py`, `src/rutracker_torrent_mcp/tools.py`, `tests/test_browser.py`, `AGENTS/{SPEC,STATE,HISTORY}.md`.
- Next: —

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
