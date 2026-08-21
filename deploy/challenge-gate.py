#!/usr/bin/env python3
"""Token gate for the rutracker Cloudflare-challenge noVNC page.

nginx (rtcc.wildcar.org) routes `/enter/<token>` here and sends every other
request through `auth_request` to `/gate`. The Telegram bot mints a one-time
token into RUTRACKER_CHALLENGE_TOKEN_PATH when the MCP reports
`cloudflare_challenge` / `manual_auth_required`; a link carrying that token
gets a session cookie and a redirect to the noVNC page. Anything without a
valid cookie is rejected and nginx shows a 404, so to scanners the host
looks empty.

Stdlib only — runs under the system python3, no venv. Deliberately dumb:
the token file is the single source of truth, freshness is its mtime, and
expiry equals the MCP's manual-login grace window (the browser leaves the
display then anyway).

Env:
  RUTRACKER_CHALLENGE_TOKEN_PATH   token file (default /var/lib/rutracker-challenge/token)
  RUTRACKER_CHALLENGE_TTL_SECONDS  token/cookie lifetime (default 1800)
  RUTRACKER_CHALLENGE_GATE_PORT    loopback port (default 6079)
"""

from __future__ import annotations

import hmac
import os
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TOKEN_PATH = Path(
    os.environ.get("RUTRACKER_CHALLENGE_TOKEN_PATH", "/var/lib/rutracker-challenge/token")
)
TTL_SECONDS = int(os.environ.get("RUTRACKER_CHALLENGE_TTL_SECONDS", "1800"))
PORT = int(os.environ.get("RUTRACKER_CHALLENGE_GATE_PORT", "6079"))
COOKIE_NAME = "rt_challenge"
NOVNC_URL = "/vnc.html?autoconnect=1&resize=scale"


def current_token() -> str | None:
    """The live token, or None when there is none / it has expired."""
    try:
        stat = TOKEN_PATH.stat()
        if time.time() - stat.st_mtime > TTL_SECONDS:
            return None
        token = TOKEN_PATH.read_text(encoding="utf-8").strip()
        return token or None
    except OSError:
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "challenge-gate"

    def log_message(self, format: str, *args: object) -> None:
        # auth_request fires for every asset and websocket frame handshake;
        # default per-request logging would drown journald. /enter attempts
        # are logged explicitly below.
        pass

    def do_GET(self) -> None:
        if self.path.startswith("/enter/"):
            self._enter(self.path[len("/enter/") :])
        elif self.path == "/gate":
            self._gate()
        else:
            self._deny(404)

    def _enter(self, presented: str) -> None:
        token = current_token()
        ok = token is not None and hmac.compare_digest(presented, token)
        print(f"enter: {'accepted' if ok else 'rejected'} from {self.client_address[0]}", flush=True)
        if not ok or token is None:
            self._deny(404)
            return
        self.send_response(302)
        self.send_header(
            "Set-Cookie",
            f"{COOKIE_NAME}={token}; Path=/; Max-Age={TTL_SECONDS}; "
            "HttpOnly; Secure; SameSite=Lax",
        )
        self.send_header("Location", NOVNC_URL)
        self.end_headers()

    def _gate(self) -> None:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get(COOKIE_NAME)
        token = current_token()
        if morsel is not None and token is not None and hmac.compare_digest(morsel.value, token):
            self.send_response(204)
            self.end_headers()
        else:
            self._deny(401)

    def _deny(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"challenge-gate: listening on 127.0.0.1:{PORT}, token file {TOKEN_PATH}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
