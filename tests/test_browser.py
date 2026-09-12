from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from rutracker_torrent_mcp.clients.browser import (
    PlaywrightRutrackerClient,
    _adopt_working_page,
    _clear_session_restore,
    _reap_stranded_pages,
)
from rutracker_torrent_mcp.clients.rutracker import (
    CloudflareChallenge,
    LoginCaptchaRequired,
    ManualLoginRequired,
    RutrackerError,
)


@dataclass
class FakeBrowserResponse:
    status: int = 200
    headers: dict[str, str] | None = None

    async def all_headers(self) -> dict[str, str]:
        return dict(self.headers or {})


class FakePage:
    def __init__(
        self,
        *,
        html: str,
        title: str = "RuTracker.org",
        status: int = 200,
        headers: dict[str, str] | None = None,
        url: str = "https://rutracker.org/forum/index.php",
    ) -> None:
        self.html = html
        self.page_title = title
        self.status = status
        self.headers = headers
        self.url = url
        self.urls: list[str] = []
        self.closed = False
        self.fetch_result: dict[str, Any] | None = None

    async def goto(self, url: str, **kwargs: Any) -> FakeBrowserResponse:
        self.urls.append(url)
        return FakeBrowserResponse(self.status, self.headers)

    async def content(self) -> str:
        return self.html

    async def title(self) -> str:
        return self.page_title

    async def evaluate(self, script: str, arg: dict[str, str]) -> dict[str, Any]:
        assert "fetch" in script
        assert arg["url"].startswith("https://rutracker.org/forum/dl.php")
        assert self.fetch_result is not None
        return self.fetch_result

    async def close(self) -> None:
        self.closed = True

    def is_closed(self) -> bool:
        return self.closed


async def test_browser_search_uses_persistent_page(search_html: str) -> None:
    page = FakePage(html=search_html)
    client = PlaywrightRutrackerClient(
        base_url="https://rutracker.org",
        cdp_url="http://unused",
        page=page,
    )

    rows = await client.search("Dune", limit=1)

    assert len(rows) == 1
    assert "tracker.php?" in page.urls[0]
    assert "nm=Dune" in page.urls[0]


async def test_browser_reports_challenge_not_logout_for_cloudflare() -> None:
    """A Turnstile interstitial must not be reported as a logged-out session."""
    page = FakePage(
        html="<html></html>",
        title="Just a moment...",
        status=403,
        headers={"cf-mitigated": "challenge"},
    )
    client = PlaywrightRutrackerClient(
        base_url="https://rutracker.org",
        cdp_url="http://unused",
        page=page,
    )

    with pytest.raises(CloudflareChallenge):
        await client.search("Dune")


async def test_browser_trusts_cf_mitigated_over_title() -> None:
    """The header is authoritative even when the title looks like a normal page."""
    page = FakePage(
        html="<html></html>",
        title="Трекер",
        status=403,
        headers={"cf-mitigated": "challenge"},
    )
    client = PlaywrightRutrackerClient(
        base_url="https://rutracker.org",
        cdp_url="http://unused",
        page=page,
    )

    with pytest.raises(CloudflareChallenge):
        await client.search("Dune")


async def test_browser_reports_logout_for_login_form() -> None:
    page = FakePage(
        html='<html><form><input name="login_username"><input name="login_password"></form></html>',
    )
    client = PlaywrightRutrackerClient(
        base_url="https://rutracker.org",
        cdp_url="http://unused",
        page=page,
    )

    with pytest.raises(ManualLoginRequired):
        await client.search("Dune")


async def test_browser_download_reports_challenge_from_headers() -> None:
    page = FakePage(html="<html><body>topic</body></html>")
    page.fetch_result = {
        "status": 403,
        "headers": {"cf-mitigated": "challenge", "content-type": "text/html"},
        "body": "",
    }
    client = PlaywrightRutrackerClient(
        base_url="https://rutracker.org",
        cdp_url="http://unused",
        page=page,
    )

    with pytest.raises(CloudflareChallenge):
        await client.download_torrent(42)


async def test_browser_download_stays_inside_page_context() -> None:
    page = FakePage(html="<html><body>topic</body></html>")
    torrent = b"d4:infod4:name4:testee"
    page.fetch_result = {
        "status": 200,
        "headers": {
            "content-type": "application/x-bittorrent",
            "content-disposition": 'attachment; filename="test.torrent"',
        },
        "body": base64.b64encode(torrent).decode(),
    }
    client = PlaywrightRutrackerClient(
        base_url="https://rutracker.org",
        cdp_url="http://unused",
        page=page,
    )

    filename, content = await client.download_torrent(42)

    assert filename == "test.torrent"
    assert content == torrent


class FakeContext:
    def __init__(self, pages: list[FakePage]) -> None:
        self.pages = pages
        self.opened = 0

    async def new_page(self) -> FakePage:
        self.opened += 1
        page = FakePage(html="", url="about:blank", title="")
        self.pages.append(page)
        return page

    def alive(self) -> list[FakePage]:
        return [p for p in self.pages if not p.closed]


async def test_reaper_closes_every_tab_but_the_working_one() -> None:
    """Loaded rutracker tabs are as costly as challenge tabs — only one survives."""
    keep = FakePage(html="", url="https://rutracker.org/forum/index.php")
    topic = FakePage(html="", url="https://rutracker.org/forum/viewtopic.php?t=1")
    blank = FakePage(html="", url="about:blank", title="")
    stuck = FakePage(
        html="",
        url="https://rutracker.org/forum/tracker.php?nm=x",
        title="Just a moment...",
    )
    ctx = FakeContext([keep, topic, blank, stuck])

    await _reap_stranded_pages(ctx, keep=keep)

    assert ctx.alive() == [keep]


async def test_adopt_reuses_the_open_tab() -> None:
    """No new tab per process — that is what bounds the tab count."""
    first = FakePage(html="", url="https://rutracker.org/forum/index.php")
    extra = FakePage(html="", url="about:blank", title="")
    ctx = FakeContext([first, extra])

    page, created = await _adopt_working_page(ctx)

    assert page is first
    assert created is False
    assert ctx.opened == 0
    assert ctx.alive() == [first]


async def test_adopt_opens_a_tab_only_when_none_exists() -> None:
    ctx = FakeContext([])

    page, created = await _adopt_working_page(ctx)

    assert created is True
    assert ctx.alive() == [page]


async def test_client_leaves_the_adopted_tab_open() -> None:
    """A tab we did not open is not ours to close — the browser keeps it."""
    page = FakePage(html="<html></html>", title="Just a moment...", status=403)
    client = PlaywrightRutrackerClient(
        base_url="https://rutracker.org",
        cdp_url="http://unused",
        page=page,
    )

    with pytest.raises(CloudflareChallenge):
        async with client:
            await client.search("Dune")

    assert not page.closed


class FakeProcess:
    """Stands in for the spawned Chromium subprocess."""

    def __init__(self) -> None:
        self.returncode: int | None = None

    def terminate(self) -> None:
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode or 0

    @property
    def alive(self) -> bool:
        return self.returncode is None


class FakeBrowserConnection:
    """The connect_over_cdp handle: close() only disconnects."""

    def __init__(self) -> None:
        self.disconnected = False

    async def close(self) -> None:
        self.disconnected = True


def _spawning_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    idle_timeout: float,
    manual_login_grace: float = 60.0,
    html: str = "<html></html>",
    title: str = "RuTracker.org",
    status: int = 200,
) -> tuple[PlaywrightRutrackerClient, list[FakeProcess]]:
    """A client whose `_connect_once` stands in for spawn + connect_over_cdp.

    Mimics production semantics: the process survives a detach, and a new one
    is spawned only when the previous one is gone.
    """
    client = PlaywrightRutrackerClient(
        base_url="https://rutracker.org",
        cdp_url="http://127.0.0.1:9222",
        profile_dir=Path("/nonexistent/profile"),
        idle_timeout=idle_timeout,
        manual_login_grace=manual_login_grace,
        connect_attempts=1,
        connect_backoff=0.0,
    )
    processes: list[FakeProcess] = []

    async def fake_connect() -> None:
        if client._process is None or client._process.returncode is not None:
            client._process = FakeProcess()
            processes.append(client._process)
        client._browser = FakeBrowserConnection()
        client._page = FakePage(html=html, title=title, status=status)

    monkeypatch.setattr(client, "_connect_once", fake_connect)
    return client, processes


async def test_idle_browser_is_shut_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing should run between searches — the profile keeps the session."""
    client, processes = _spawning_client(monkeypatch, idle_timeout=0.05)

    await client.topic_info(1)
    assert processes[0].alive

    await asyncio.sleep(0.2)
    assert not processes[0].alive
    assert client._process is None


async def test_next_call_respawns_after_an_idle_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, processes = _spawning_client(monkeypatch, idle_timeout=0.05)

    await client.topic_info(1)
    await asyncio.sleep(0.2)
    await client.topic_info(1)

    assert len(processes) == 2
    assert processes[1].alive
    await client.aclose()


async def test_challenge_detaches_the_client_but_keeps_the_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Turnstile loops while a CDP client is attached — hand over a clean browser."""
    client, processes = _spawning_client(
        monkeypatch,
        idle_timeout=0.05,
        html="<html></html>",
        title="Just a moment...",
        status=403,
    )

    with pytest.raises(CloudflareChallenge):
        await client.search("Dune")

    # the client is gone, the process is not
    assert client._page is None
    assert client._browser is None
    assert processes[0].alive

    # ...and it survives well past the ordinary idle timeout
    await asyncio.sleep(0.2)
    assert processes[0].alive
    await client.aclose()


async def test_manual_login_detaches_the_client_but_keeps_the_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, processes = _spawning_client(
        monkeypatch,
        idle_timeout=0.05,
        html='<html><form><input name="login_username"><input name="login_password"></form></html>',
    )

    with pytest.raises(ManualLoginRequired):
        await client.search("Dune")

    assert client._browser is None
    await asyncio.sleep(0.2)
    assert processes[0].alive
    await client.aclose()


async def test_grace_expiry_kills_the_detached_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The hand-over window is finite; nothing runs forever."""
    client, processes = _spawning_client(
        monkeypatch,
        idle_timeout=0.05,
        manual_login_grace=0.2,
        title="Just a moment...",
        status=403,
    )

    with pytest.raises(CloudflareChallenge):
        await client.search("Dune")

    await asyncio.sleep(0.5)
    assert not processes[0].alive
    assert client._process is None


async def test_reconnect_during_grace_reuses_the_same_browser(
    monkeypatch: pytest.MonkeyPatch, search_html: str
) -> None:
    """After the operator solves the challenge, the retry must not respawn."""
    client, processes = _spawning_client(
        monkeypatch,
        idle_timeout=60.0,
        title="Just a moment...",
        status=403,
    )

    with pytest.raises(CloudflareChallenge):
        await client.search("Dune")

    # the operator solved it; the next call re-attaches to the same process
    async def solved_connect() -> None:
        client._browser = FakeBrowserConnection()
        client._page = FakePage(html=search_html)

    monkeypatch.setattr(client, "_connect_once", solved_connect)

    assert len(await client.search("Dune", limit=1)) == 1
    assert len(processes) == 1
    assert processes[0].alive
    await client.aclose()


def test_spawn_command_mirrors_run_browser_sh() -> None:
    client = PlaywrightRutrackerClient(
        base_url="https://rutracker.org",
        cdp_url="http://127.0.0.1:9222",
        profile_dir=Path("/var/lib/rutracker-browser/profile"),
        browser_proxy="socks5://127.0.0.1:1080",
    )

    command = client._spawn_command("/opt/chromium/chrome")

    assert command[0] == "/opt/chromium/chrome"
    assert "--no-sandbox" in command
    assert "--remote-debugging-address=127.0.0.1" in command
    assert "--remote-debugging-port=9222" in command
    assert "--remote-allow-origins=*" in command
    assert "--user-data-dir=/var/lib/rutracker-browser/profile" in command
    assert "--proxy-server=socks5://127.0.0.1:1080" in command


def test_spawn_command_omits_proxy_when_unset() -> None:
    client = PlaywrightRutrackerClient(
        base_url="https://rutracker.org",
        cdp_url="http://127.0.0.1:9333",
        profile_dir=Path("/p"),
    )

    command = client._spawn_command("/bin/chrome")

    assert "--remote-debugging-port=9333" in command
    assert not any(arg.startswith("--proxy-server") for arg in command)


async def test_attached_browser_is_never_shut_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """A browser we merely attached to belongs to the operator, not to us."""
    page = FakePage(html="<html></html>")
    client = PlaywrightRutrackerClient(
        base_url="https://rutracker.org",
        cdp_url="http://127.0.0.1:9222",
        profile_dir=Path("/nonexistent/profile"),
        idle_timeout=0.05,
        connect_attempts=1,
        connect_backoff=0.0,
    )

    async def fake_connect() -> None:
        client._page = page  # attached over CDP: `_launched` stays None

    monkeypatch.setattr(client, "_connect_once", fake_connect)

    await client.topic_info(1)
    await asyncio.sleep(0.2)

    assert not page.closed
    assert client._idle_task is None


async def test_clear_session_restore_drops_crash_state(tmp_path: Path) -> None:
    default = tmp_path / "Default"
    (default / "Sessions").mkdir(parents=True)
    (default / "Sessions" / "Session_1").write_text("x")
    (default / "Preferences").write_text(
        '{"profile":{"exit_type":"Crashed","exited_cleanly":false}}'
    )

    _clear_session_restore(tmp_path)

    assert not (default / "Sessions").exists()
    prefs = json.loads((default / "Preferences").read_text())["profile"]
    assert prefs == {"exit_type": "Normal", "exited_cleanly": True}


async def test_connect_retries_then_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    client = PlaywrightRutrackerClient(
        base_url="https://rutracker.org",
        cdp_url="http://127.0.0.1:9222",
        connect_attempts=3,
        connect_backoff=0.0,
    )
    attempts = 0

    async def failing_connect() -> None:
        nonlocal attempts
        attempts += 1
        raise OSError("connection refused")

    monkeypatch.setattr(client, "_connect_once", failing_connect)

    with pytest.raises(RutrackerError, match="cannot reach the persistent Chromium"):
        await client.search("Dune")

    assert attempts == 3


async def test_connect_is_lazy_and_recovers_on_a_later_call(
    monkeypatch: pytest.MonkeyPatch, search_html: str
) -> None:
    """`open()` must not touch the browser; the first tool call connects."""
    client = PlaywrightRutrackerClient(
        base_url="https://rutracker.org",
        cdp_url="http://127.0.0.1:9222",
        connect_attempts=1,
        connect_backoff=0.0,
    )
    attempts = 0

    async def flaky_connect() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("browser not up yet")
        client._page = FakePage(html=search_html)

    monkeypatch.setattr(client, "_connect_once", flaky_connect)

    await client.open()
    assert attempts == 0

    with pytest.raises(RutrackerError):
        await client.search("Dune")

    assert len(await client.search("Dune", limit=1)) == 1


_LOGIN_FORM = '<html><form><input name="login_username"><input name="login_password"></form></html>'
_CAPTCHA_FORM = (
    '<html><form><input name="login_username"><input name="login_password">'
    '<input name="cap_code_abc"></form></html>'
)


class FakeLocator:
    """Enough of the Playwright locator API for the login form.

    ``forms`` is how many login forms the page renders — rutracker renders two
    (top-bar + page form), the ambiguity that strict-mode selectors trip over —
    and only the last one is visible, so the client has to pick it.
    """

    def __init__(self, page: LoginFakePage, selector: str, *, index: int | None = None) -> None:
        self._page = page
        self._selector = selector
        self._index = index

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self._page, selector, index=self._index)

    @property
    def first(self) -> FakeLocator:
        return FakeLocator(self._page, self._selector, index=self._index or 0)

    def nth(self, index: int) -> FakeLocator:
        return FakeLocator(self._page, self._selector, index=index)

    async def count(self) -> int:
        return self._page.forms if "form:has" in self._selector else 1

    async def is_visible(self) -> bool:
        return self._index == self._page.forms - 1

    async def fill(self, value: str, **kwargs: Any) -> None:
        assert self._index is not None, "a bare selector would be ambiguous"
        self._page.filled[self._selector] = value

    async def click(self, **kwargs: Any) -> None:
        assert self._index is not None, "a bare selector would be ambiguous"
        self._page.submits += 1
        self._page.html = self._page.after_login


class LoginFakePage(FakePage):
    """A page that serves the login form until the form is actually submitted."""

    def __init__(
        self,
        *,
        after_login: str,
        login_page: str = _LOGIN_FORM,
        forms: int = 2,
        **kwargs: Any,
    ) -> None:
        super().__init__(html=login_page, **kwargs)
        self.after_login = after_login
        self.forms = forms
        self.filled: dict[str, str] = {}
        self.submits = 0

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector)

    async def wait_for_load_state(self, state: str, **kwargs: Any) -> None:
        return None


def _credentialled(page: FakePage) -> PlaywrightRutrackerClient:
    return PlaywrightRutrackerClient(
        base_url="https://rutracker.org",
        cdp_url="http://unused",
        login="user",
        password="secret",
        page=page,
    )


async def test_logged_out_session_signs_itself_back_in(search_html: str) -> None:
    page = LoginFakePage(after_login=search_html)
    client = _credentialled(page)

    results = await client.search("Dune")

    assert results
    assert page.submits == 1
    assert page.filled == {
        'input[name="login_username"]': "user",
        'input[name="login_password"]': "secret",
    }
    assert any("login.php" in url for url in page.urls)


async def test_login_that_does_not_take_hands_over_to_the_operator() -> None:
    # The form comes back after the submit — credentials rejected, or the
    # session is refused for a reason the form cannot fix.
    page = LoginFakePage(after_login=_LOGIN_FORM)
    client = _credentialled(page)

    with pytest.raises(ManualLoginRequired):
        await client.search("Dune")
    assert page.submits == 1  # exactly one attempt, then the human


async def test_no_reachable_login_form_hands_over() -> None:
    # Every form hidden — nothing a human could type into either.
    page = LoginFakePage(after_login=_LOGIN_FORM, forms=0)
    client = _credentialled(page)

    with pytest.raises(ManualLoginRequired):
        await client.search("Dune")
    assert page.submits == 0


async def test_login_captcha_is_reported_as_such() -> None:
    page = LoginFakePage(after_login=_LOGIN_FORM, login_page=_CAPTCHA_FORM)
    client = _credentialled(page)

    with pytest.raises(LoginCaptchaRequired):
        await client.search("Dune")
    assert page.submits == 0  # nothing to submit — the captcha is unsolvable here


async def test_download_retries_once_behind_a_fresh_login() -> None:
    torrent = b"d4:infod4:name4:testee"
    page = LoginFakePage(after_login="<html><body>topic</body></html>")
    page.html = "<html><body>topic</body></html>"  # the topic page itself is fine
    page.fetch_result = {
        "status": 403,
        "headers": {"content-type": "text/html"},
        "body": "",
    }

    async def _fetch_after_login(script: str, arg: dict[str, str]) -> dict[str, Any]:
        if page.submits:
            return {
                "status": 200,
                "headers": {
                    "content-type": "application/x-bittorrent",
                    "content-disposition": 'attachment; filename="test.torrent"',
                },
                "body": base64.b64encode(torrent).decode(),
            }
        return dict(page.fetch_result or {})

    page.evaluate = _fetch_after_login  # type: ignore[method-assign]
    client = _credentialled(page)

    filename, content = await client.download_torrent(42)

    assert (filename, content) == ("test.torrent", torrent)
    assert page.submits == 1
