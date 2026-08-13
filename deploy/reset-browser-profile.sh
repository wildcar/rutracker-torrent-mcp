#!/usr/bin/env bash
# Drop Chromium's session-restore state before every start.
#
# systemd stops the browser with SIGTERM, which Chromium records as a crash
# (`exit_type: Crashed`). On the next start it restores every tab it had open, so
# tabs accumulate across restarts until the host runs out of memory.
set -euo pipefail

: "${RUTRACKER_BROWSER_PROFILE:?RUTRACKER_BROWSER_PROFILE is required}"

profile="$RUTRACKER_BROWSER_PROFILE"
[[ -d "$profile" ]] || exit 0

rm -rf "$profile"/Default/Sessions "$profile"/Default/"Session Storage"

prefs="$profile/Default/Preferences"
if [[ -f "$prefs" ]]; then
  sed -i \
    -e 's/"exit_type":"[^"]*"/"exit_type":"Normal"/g' \
    -e 's/"exited_cleanly":false/"exited_cleanly":true/g' \
    "$prefs"
fi
