"""Persistent Chromium backend for Cloudflare-protected rutracker sessions."""

from __future__ import annotations

import asyncio
import base64
import re
import shutil
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

import structlog
from selectolax.parser import HTMLParser

from .rutracker import (
    CloudflareChallenge,
    LoginCaptchaRequired,
    ManualLoginRequired,
    RutrackerError,
    _parse_disposition_filename,
    _parse_search,
    _parse_topic,
)

log = structlog.get_logger(__name__)

_FETCH_SCRIPT = """
async ({url}) => {
  const response = await fetch(url, {credentials: "include"});
  const bytes = new Uint8Array(await response.arrayBuffer());
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 32768) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768));
  }
  return {
    status: response.status,
    headers: Object.fromEntries(response.headers.entries()),
    body: btoa(binary),
  };
}
"""


class PlaywrightRutrackerClient:
    """Drive a persistent Chromium — one we spawn ourselves, or an existing one.

    With ``profile_dir`` set the client owns the browser process: it spawns
    Chromium on that profile at the first request (as a plain subprocess serving
    the CDP port — the same command line as ``deploy/run-browser.sh``) and kills
    it once idle, so nothing runs between searches. An already-running browser
    (the operator started the unit to log in through VNC) is attached over CDP
    instead and never shut down — it isn't ours to close, and the profile takes
    only one process at a time.

    A logged-out session is re-authenticated in the browser itself when
    credentials are configured — the form login costs one navigation and saves
    the operator a VNC round trip. Only what the form cannot solve (a captcha,
    rejected credentials, a Cloudflare challenge) still reaches a human.

    The CDP connection is always ``connect_over_cdp`` and therefore severable:
    on an auth/challenge error the client disconnects but leaves the process on
    the display for the manual-login grace window, because Turnstile fails in a
    loop while any CDP client is attached (Cloudflare detects automation). The
    next tool call re-attaches.
    """

    def __init__(
        self,
        *,
        base_url: str,
        cdp_url: str,
        timeout: float = 30.0,
        connect_timeout: float = 10.0,
        connect_attempts: int = 3,
        connect_backoff: float = 2.0,
        profile_dir: Path | None = None,
        executable_path: str | None = None,
        browser_proxy: str | None = None,
        idle_timeout: float = 300.0,
        manual_login_grace: float = 1800.0,
        login: str | None = None,
        password: str | None = None,
        page: Any = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._cdp_url = cdp_url
        parsed = urlparse(cdp_url)
        self._cdp_host = parsed.hostname or "127.0.0.1"
        self._cdp_port = parsed.port or 9222
        self._timeout_ms = int(timeout * 1000)
        self._connect_timeout = connect_timeout
        self._connect_timeout_ms = int(connect_timeout * 1000)
        self._connect_attempts = max(1, connect_attempts)
        self._connect_backoff = connect_backoff
        self._profile_dir = profile_dir
        self._executable_path = executable_path
        self._browser_proxy = browser_proxy
        self._idle_timeout = idle_timeout
        self._manual_login_grace = manual_login_grace
        self._login = login
        self._password = password
        self._playwright: Any = None
        self._browser: Any = None
        self._process: Any = None
        self._page: Any = page
        self._owns_page = False
        self._idle_deadline = 0.0
        self._idle_task: asyncio.Task[None] | None = None
        self._request_lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()

    async def open(self) -> None:
        """No-op: the CDP connection is established on first tool call.

        Connecting eagerly made server startup depend on a browser that had to be
        up first — a browser restart then left the MCP wedged until it was
        restarted too. See ``_ensure_page``.
        """
        return None

    async def __aenter__(self) -> PlaywrightRutrackerClient:
        await self.open()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        task, self._idle_task = self._idle_task, None
        if task is not None:
            task.cancel()
        await self._detach()
        await self._shutdown_process()

    def _touch(self) -> None:
        """Push the idle deadline out; never pull it in (see the operator grace)."""
        self._idle_deadline = max(self._idle_deadline, time.monotonic() + self._idle_timeout)
        self._arm_idle_watchdog()

    async def _release_for_operator(self) -> None:
        """Free the browser for a human: drop the CDP client, keep the process.

        Turnstile fails in a loop while any CDP client is attached (Cloudflare
        detects automation), so keeping the browser up is not enough — the
        operator needs a client-free one. Our own process stays on the display
        for the manual-login grace window; the next tool call re-attaches. A
        browser we merely attached to is left alone the same way — the client
        drops either way.
        """
        await self._detach()
        if self._process is None:
            return
        self._idle_deadline = max(self._idle_deadline, time.monotonic() + self._manual_login_grace)
        self._arm_idle_watchdog()

    def _arm_idle_watchdog(self) -> None:
        if self._process is None or self._idle_timeout <= 0:
            return
        if self._idle_task is None or self._idle_task.done():
            self._idle_task = asyncio.create_task(self._idle_watchdog())

    async def _idle_watchdog(self) -> None:
        """Kill a self-spawned browser once nothing has used it for a while.

        The browser is only needed during a request — the session and
        `cf_clearance` live in the on-disk profile.
        """
        while True:
            remaining = self._idle_deadline - time.monotonic()
            if remaining > 0:
                await asyncio.sleep(remaining)
                continue
            async with self._request_lock:
                if time.monotonic() < self._idle_deadline:
                    continue
                if self._process is not None:
                    await self._detach()
                    await self._shutdown_process()
                return

    async def _ensure_page(self) -> Any:
        """Return a live working tab, connecting to Chromium if needed."""
        if self._page is not None and not _page_is_closed(self._page):
            return self._page
        async with self._connect_lock:
            if self._page is not None and not _page_is_closed(self._page):
                return self._page
            await self._detach()
            await self._connect()
            return self._page

    async def _connect(self) -> None:
        delay = self._connect_backoff
        last_error: Exception | None = None
        for attempt in range(1, self._connect_attempts + 1):
            try:
                await self._connect_once()
                return
            except Exception as exc:
                last_error = exc
                await self._detach()
                if attempt < self._connect_attempts:
                    await asyncio.sleep(delay)
                    delay *= 2
        raise RutrackerError(
            f"cannot reach the persistent Chromium at {self._cdp_url}: {last_error}"
        )

    async def _connect_once(self) -> None:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        try:
            # Whatever serves the CDP port wins: an operator signing in through
            # VNC holds the profile, and our own spawned browser outlives the
            # connection across the operator grace window.
            await self._attach_over_cdp()
            return
        except Exception:
            if self._profile_dir is None:
                raise
        await self._spawn_browser()
        await self._attach_over_cdp()

    async def _attach_over_cdp(self) -> None:
        self._browser = await self._playwright.chromium.connect_over_cdp(
            self._cdp_url,
            timeout=self._connect_timeout_ms,
        )
        if not self._browser.contexts:
            raise RutrackerError("persistent Chromium has no browser context")
        context = self._browser.contexts[0]
        self._page, self._owns_page = await _adopt_working_page(context)

    async def _spawn_browser(self) -> None:
        """Start Chromium as a plain subprocess serving the CDP port.

        Deliberately NOT ``launch_persistent_context``: a Playwright-launched
        browser dies with its client, so it could never be handed over to the
        operator client-free. This is the exact command line of
        ``deploy/run-browser.sh``, and the profile behaves the same either way.
        """
        assert self._profile_dir is not None
        # A previous process that stopped serving CDP is wedged — replace it.
        await self._shutdown_process()
        _clear_session_restore(self._profile_dir)
        executable = self._executable_path or str(self._playwright.chromium.executable_path)
        self._process = await asyncio.create_subprocess_exec(
            *self._spawn_command(executable),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await self._wait_for_cdp()

    def _spawn_command(self, executable: str) -> list[str]:
        assert self._profile_dir is not None
        command = [
            executable,
            *_CHROMIUM_ARGS,
            f"--remote-debugging-address={self._cdp_host}",
            f"--remote-debugging-port={self._cdp_port}",
            "--remote-allow-origins=*",
            f"--user-data-dir={self._profile_dir}",
        ]
        if self._browser_proxy:
            command.append(f"--proxy-server={self._browser_proxy}")
        return command

    async def _wait_for_cdp(self) -> None:
        """Block until the spawned Chromium accepts connections on the CDP port."""
        deadline = time.monotonic() + self._connect_timeout
        while True:
            if self._process is not None and self._process.returncode is not None:
                raise RutrackerError(
                    f"spawned Chromium exited with code {self._process.returncode} "
                    "before serving CDP (single-instance lock held elsewhere?)"
                )
            try:
                _, writer = await asyncio.open_connection(self._cdp_host, self._cdp_port)
            except OSError:
                if time.monotonic() >= deadline:
                    raise RutrackerError(
                        f"spawned Chromium did not open {self._cdp_url} within "
                        f"{self._connect_timeout:.0f}s"
                    ) from None
                await asyncio.sleep(0.2)
                continue
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return

    async def _shutdown_process(self) -> None:
        """Kill our spawned Chromium. Session-restore junk from the SIGTERM is
        cleared on the next spawn (see ``_clear_session_restore``)."""
        process, self._process = self._process, None
        if process is None or process.returncode is not None:
            return
        try:
            process.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except TimeoutError:
            process.kill()
            await process.wait()

    async def _detach(self) -> None:
        """Drop the CDP client. Never kills the browser — ours keeps running
        until ``_shutdown_process``; the operator's is not ours to stop."""
        page, owns = self._page, self._owns_page
        self._page = None
        self._owns_page = False
        if page is not None and owns:
            try:
                await page.close()
            except Exception:
                pass
        if self._browser is not None:
            try:
                # close() on a connect_over_cdp browser only disconnects.
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright is not None:
            try:
                # A driver left over from a timed-out connect can hang on stop().
                await asyncio.wait_for(self._playwright.stop(), timeout=5.0)
            except Exception:
                pass
            self._playwright = None

    async def search(
        self,
        query: str,
        *,
        category: int | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"nm": query, "o": 10, "s": 2}
        if category is not None:
            params["f"] = category
        html = await self._navigate_html("/forum/tracker.php", params=params)
        return _parse_search(html, base_url=self._base)[:limit]

    async def download_torrent(self, topic_id: int) -> tuple[str, bytes]:
        async with self._request_lock:
            try:
                await self._navigate_html_locked("/forum/viewtopic.php", params={"t": topic_id})
                try:
                    return await self._download_torrent_locked(topic_id)
                except ManualLoginRequired:
                    # dl.php can reject a session the topic page still accepted
                    # (it is the one endpoint that insists on a fresh login).
                    if not await self._auto_login():
                        raise
                    return await self._download_torrent_locked(topic_id)
            except (CloudflareChallenge, ManualLoginRequired):
                await self._release_for_operator()
                raise
            finally:
                self._touch()

    async def _download_torrent_locked(self, topic_id: int) -> tuple[str, bytes]:
        page = await self._ensure_page()
        url = self._url("/forum/dl.php", {"t": topic_id})
        result = await page.evaluate(_FETCH_SCRIPT, {"url": url})
        status = int(result["status"])
        headers = {str(k).lower(): str(v) for k, v in result["headers"].items()}
        if _is_cloudflare_challenge("", headers):
            raise CloudflareChallenge(_CHALLENGE_MESSAGE)
        if status in {401, 403}:
            raise ManualLoginRequired(_MANUAL_LOGIN_MESSAGE)
        if status >= 400:
            raise RutrackerError(f"rutracker /forum/dl.php → HTTP {status}")
        content = base64.b64decode(result["body"])
        ctype = headers.get("content-type", "").lower()
        if "x-bittorrent" not in ctype and not content.startswith(b"d"):
            raise ManualLoginRequired(_MANUAL_LOGIN_MESSAGE)
        filename = _parse_disposition_filename(headers.get("content-disposition", ""))
        return filename or f"[rutracker.org].t{topic_id}.torrent", content

    async def magnet_link(self, topic_id: int) -> str | None:
        html = await self._navigate_html("/forum/viewtopic.php", params={"t": topic_id})
        tree = HTMLParser(html)
        for node in tree.css("a.magnet-link"):
            href = node.attributes.get("href")
            if href and href.startswith("magnet:"):
                return href
        return None

    async def topic_info(self, topic_id: int) -> dict[str, Any] | None:
        html = await self._navigate_html("/forum/viewtopic.php", params={"t": topic_id})
        return _parse_topic(html, topic_id=topic_id, base_url=self._base)

    async def _navigate_html(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> str:
        async with self._request_lock:
            try:
                return await self._navigate_html_locked(path, params=params)
            except (CloudflareChallenge, ManualLoginRequired):
                await self._release_for_operator()
                raise
            finally:
                self._touch()

    async def _navigate_html_locked(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        allow_login: bool = True,
    ) -> str:
        page = await self._ensure_page()
        try:
            response = await page.goto(
                self._url(path, params),
                wait_until="domcontentloaded",
                timeout=self._timeout_ms,
            )
            html = await page.content()
            title = await page.title()
        except Exception as exc:
            # Drop the CDP connection: a browser that died mid-navigation leaves a
            # handle that never recovers. The next call reconnects and re-reaps.
            await self._detach()
            raise RutrackerError(f"browser navigation failed for {path}: {exc}") from exc
        status = response.status if response is not None else 200
        headers = await _response_headers(response)
        if _is_cloudflare_challenge(title, headers):
            raise CloudflareChallenge(_CHALLENGE_MESSAGE)
        if _requires_manual_login(status, html):
            # One shot at the form, then hand over: a second failure means the
            # form is not what stands in the way (captcha, bad credentials).
            if allow_login and await self._auto_login():
                return await self._navigate_html_locked(path, params=params, allow_login=False)
            raise ManualLoginRequired(_MANUAL_LOGIN_MESSAGE)
        if status >= 400:
            raise RutrackerError(f"rutracker {path} → HTTP {status}")
        return str(html)

    async def _auto_login(self) -> bool:
        """Sign in through ``/forum/login.php`` in the browser. Returns success.

        False means "could not even try" — no credentials, no form on the page,
        or a navigation that fell over; the caller then hands the browser to a
        human. A captcha or a Cloudflare gate raises instead, because those name
        the obstacle precisely and the tool layer maps them to their own codes.
        """
        if not self._login or not self._password:
            return False
        page = await self._ensure_page()
        try:
            await page.goto(
                self._url("/forum/login.php"),
                wait_until="domcontentloaded",
                timeout=self._timeout_ms,
            )
            title = await page.title()
            if _is_cloudflare_challenge(title, {}):
                raise CloudflareChallenge(_CHALLENGE_MESSAGE)
            if _looks_like_login_captcha(await page.content()):
                raise LoginCaptchaRequired(_LOGIN_CAPTCHA_MESSAGE)
            form = await _visible_login_form(page)
            if form is None:
                log.warning("browser.auto_login_no_form", url=getattr(page, "url", None))
                return False
            await form.locator(_LOGIN_USER_SELECTOR).first.fill(
                self._login, timeout=self._timeout_ms
            )
            await form.locator(_LOGIN_PASSWORD_SELECTOR).first.fill(
                self._password, timeout=self._timeout_ms
            )
            await form.locator(_LOGIN_SUBMIT_SELECTOR).first.click(timeout=self._timeout_ms)
            await page.wait_for_load_state("domcontentloaded", timeout=self._timeout_ms)
            html = await page.content()
            title = await page.title()
        except (CloudflareChallenge, LoginCaptchaRequired):
            raise
        except Exception as exc:
            # A redesigned form, a navigation timeout, a field we cannot reach —
            # all of them mean the same thing here: the operator takes over. It
            # is logged because from the outside it is indistinguishable from a
            # session that was never going to be fixable.
            log.warning("browser.auto_login_failed", error=str(exc))
            return False
        if _is_cloudflare_challenge(title, {}):
            raise CloudflareChallenge(_CHALLENGE_MESSAGE)
        if _looks_like_login_captcha(html):
            raise LoginCaptchaRequired(_LOGIN_CAPTCHA_MESSAGE)
        signed_in = not _requires_manual_login(200, html)
        log.info("browser.auto_login", signed_in=signed_in)
        return signed_in

    def _url(self, path: str, params: dict[str, Any] | None = None) -> str:
        url = self._base + path
        return f"{url}?{urlencode(params)}" if params else url


_CHALLENGE_TITLE = "just a moment..."

_LOGIN_USER_SELECTOR = 'input[name="login_username"]'
_LOGIN_PASSWORD_SELECTOR = 'input[name="login_password"]'
_LOGIN_SUBMIT_SELECTOR = 'input[name="login"]'
# rutracker renders the credentials twice — the top-bar quick login and the
# page's own form — so every bare selector matches two elements and Playwright
# refuses to act on an ambiguous match. Scope to one form, and to the one a
# human would actually use: the visible one.
_LOGIN_FORM_SELECTOR = 'form:has(input[name="login_username"]):has(input[name="login_password"])'


async def _visible_login_form(page: Any) -> Any:
    """The visible login form on the page, or None when there is none."""
    forms = page.locator(_LOGIN_FORM_SELECTOR)
    for index in range(await forms.count()):
        form = forms.nth(index)
        try:
            if await form.locator(_LOGIN_USER_SELECTOR).first.is_visible():
                return form
        except Exception:
            continue
    return None


def _looks_like_login_captcha(html: str) -> bool:
    """Stricter than the curl backend's check: the word "captcha" alone shows up
    in rutracker's own markup, and a false positive here would send the operator
    after a captcha that is not on the page."""
    lowered = html.lower()
    # The answer field is named per-session — «cap_code_<sid>» — so the prefix
    # is what identifies it.
    return "cap_sid" in lowered or 'name="cap_code' in lowered


# Mirrors deploy/run-browser.sh: the same profile has to behave the same way
# whether the operator starts Chromium or we launch it.
_CHROMIUM_ARGS: tuple[str, ...] = (
    "--disable-dev-shm-usage",
    "--no-sandbox",  # AppArmor blocks the downloaded Chromium's userns sandbox
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-session-crashed-bubble",
    "--hide-crash-restore-bubble",
    "--window-size=1440,900",
)


def _clear_session_restore(profile_dir: Path) -> None:
    """Drop session-restore state so a killed browser doesn't come back with tabs.

    Python twin of ``deploy/reset-browser-profile.sh``, for the profile we launch
    ourselves: a SIGKILLed Chromium leaves ``exit_type: Crashed`` behind and would
    otherwise restore every tab it had open.
    """
    default = profile_dir / "Default"
    for path in (default / "Sessions", default / "Session Storage"):
        shutil.rmtree(path, ignore_errors=True)
    prefs = default / "Preferences"
    try:
        raw = prefs.read_text(encoding="utf-8")
    except OSError:
        return
    patched = re.sub(r'"exit_type":"[^"]*"', '"exit_type":"Normal"', raw)
    patched = patched.replace('"exited_cleanly":false', '"exited_cleanly":true')
    if patched != raw:
        try:
            prefs.write_text(patched, encoding="utf-8")
        except OSError:
            pass


_LOGIN_CAPTCHA_MESSAGE = (
    "rutracker asked for a captcha on login; sign in manually through the challenge link or noVNC"
)

_MANUAL_LOGIN_MESSAGE = (
    "rutracker browser session is logged out; open the Chromium display through "
    "the challenge link or noVNC and sign in. The browser is kept on the display "
    "with no automation attached for the grace window after this error"
)

_CHALLENGE_MESSAGE = (
    "rutracker is behind an interactive Cloudflare challenge; the login session "
    "may still be valid. Open the Chromium display through the challenge link or "
    "noVNC and solve the Turnstile. The browser is kept on the display with no "
    "automation attached for the grace window after this error"
)


def _is_cloudflare_challenge(title: str, headers: dict[str, str]) -> bool:
    """Cloudflare gating the request, regardless of login state.

    ``cf-mitigated`` is authoritative when present; the title is the fallback for
    responses whose headers we could not read.
    """
    if headers.get("cf-mitigated", "").strip().lower() == "challenge":
        return True
    return title.strip().lower() == _CHALLENGE_TITLE


def _requires_manual_login(status: int, html: str) -> bool:
    lowered = html.lower()
    if 'name="login_username"' in lowered and 'name="login_password"' in lowered:
        return True
    return status in {401, 403}


async def _response_headers(response: Any) -> dict[str, str]:
    getter = getattr(response, "all_headers", None)
    if getter is None:
        return {}
    try:
        raw = await getter()
    except Exception:
        return {}
    return {str(k).lower(): str(v) for k, v in raw.items()}


def _page_is_closed(page: Any) -> bool:
    checker = getattr(page, "is_closed", None)
    if checker is None:
        return False
    try:
        return bool(checker())
    except Exception:
        return True


async def _adopt_working_page(context: Any) -> tuple[Any, bool]:
    """Pick the tab to work in; returns ``(page, created_by_us)``.

    Reusing the tab that is already open is what bounds the tab count: a process
    killed before ``aclose()`` can no longer strand the tab it opened, because it
    never opened one.
    """
    pages = list(getattr(context, "pages", None) or [])
    if pages:
        page, created = pages[0], False
    else:
        page, created = await context.new_page(), True
    await _reap_stranded_pages(context, keep=page)
    return page, created


async def _reap_stranded_pages(context: Any, *, keep: Any) -> None:
    """Close every tab except the working one.

    The persistent profile outlives every server process, so tabs left by earlier
    runs — or by a session restore after a SIGTERM — accumulate until the host
    runs out of memory. Loaded rutracker pages are as costly as challenge tabs, so
    the rule is by exclusion: one tab survives, everything else goes. ``keep``
    belongs to ``context``, so Chromium never loses its last tab and stays up.
    """
    for page in list(getattr(context, "pages", None) or []):
        if page is keep:
            continue
        try:
            await page.close()
        except Exception:
            continue


__all__ = ["PlaywrightRutrackerClient"]
