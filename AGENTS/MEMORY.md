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
  checkbox again, forever): Cloudflare detects Playwright/CDP automation. That is
  why the browser client spawns Chromium as a plain subprocess and disconnects
  on challenge/auth errors instead of using `launch_persistent_context` (whose
  browser dies with its client and can never be handed over client-free) — do
  not "simplify" it back. A `cf_clearance` earned in a client-free browser IS
  honored after the client re-attaches (verified end-to-end 2026-08-21).
- **Topic-page size parsing must stay label-anchored.** Use `_SIZE_LABELED_RE`
  (token after `Размер:`/`Size:`) on the topic page; a whole-page regex matches stray
  `<input size=5>`-style tokens and returns garbage sizes.
