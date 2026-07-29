#!/usr/bin/env bash
set -euo pipefail

: "${PLAYWRIGHT_BROWSERS_PATH:?PLAYWRIGHT_BROWSERS_PATH is required}"
: "${RUTRACKER_BROWSER_PROFILE:?RUTRACKER_BROWSER_PROFILE is required}"

browser=$(
  find "$PLAYWRIGHT_BROWSERS_PATH" -type f \
    \( -path '*/chrome-linux/chrome' -o -path '*/chrome-linux64/chrome' \) \
    -print -quit
)
[[ -n "$browser" ]] || {
  echo "Playwright Chromium executable not found in $PLAYWRIGHT_BROWSERS_PATH" >&2
  exit 1
}

exec "$browser" \
  --disable-dev-shm-usage \
  --no-sandbox \
  --no-first-run \
  --no-default-browser-check \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222 \
  --remote-allow-origins='*' \
  --user-data-dir="$RUTRACKER_BROWSER_PROFILE" \
  --proxy-server=socks5://127.0.0.1:1080 \
  --window-size=1440,900 \
  https://rutracker.org/forum/index.php
