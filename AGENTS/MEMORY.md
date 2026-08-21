# Memory

Durable repo-local facts NOT derivable from code, git, or SPEC/STATE/HISTORY. Read
at session start; append a short bullet when you learn something durable. Cross-repo
agreements live in `../AGENTS/MEMORY.md` — don't duplicate them here.

## Project facts

- **Captcha recovery (manual).** When a tool returns `captcha_required`, the captcha
  can't be solved automatically. Recover by logging into rutracker in a browser,
  exporting the `bb_session` cookie, and dropping it into the cookie jar at
  `RUTRACKER_COOKIES_PATH` (default `.cache/cookies.json`) as JSON:
  `{ "bb_session": "..." }`. On restart the client reuses it and skips login.
- **`curl_cffi`, not `httpx`.** rutracker's CDN fingerprints TLS handshakes; stock
  `httpx` hangs on `ReadTimeout`. `curl_cffi` (Chrome JA3 impersonation) is required —
  do not "simplify" the client back to `httpx`.
- **Turnstile loops while a CDP client is attached** (checkbox → spinner →
  checkbox again, forever): Cloudflare detects Playwright/CDP automation, so the
  MCP's own grace-window browser can NOT be used to solve challenges. Solve only
  in a client-free Chromium: `systemctl restart rutracker-torrent-mcp` (drops the
  attached browser), `systemctl start rutracker-browser`, solve over the
  challenge link / noVNC, `systemctl stop rutracker-browser`. The resulting
  `cf_clearance` IS honored afterwards inside the Playwright-launched browser
  (verified end-to-end 2026-08-21).
- **Topic-page size parsing must stay label-anchored.** Use `_SIZE_LABELED_RE`
  (token after `Размер:`/`Size:`) on the topic page; a whole-page regex matches stray
  `<input size=5>`-style tokens and returns garbage sizes.
