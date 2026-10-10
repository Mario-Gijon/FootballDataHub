from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from football_data_hub.core import browser_session as mod
from football_data_hub.core.browser_runtime import BrowserProfileInUse, BrowserRuntimeConfig


class FakePage:
    def __init__(self, *, fail=False):
        self.url = "https://www.bdfutbol.com/es/j/j209629.html"
        self.closed = False
        self.fail = fail
        self.timeout = None
        self.listeners = {}
        self.main_frame = object()

    def set_default_navigation_timeout(self, timeout):
        self.timeout = timeout

    def on(self, name, callback):
        self.listeners.setdefault(name, []).append(callback)

    def emit_main_document_response(self, status):
        response = SimpleNamespace(
            request=SimpleNamespace(is_navigation_request=lambda: True),
            frame=self.main_frame,
            status=status,
        )
        for callback in self.listeners.get("response", []):
            callback(response)

    def goto(self, url, **kwargs):
        if self.fail:
            raise RuntimeError("falló conexión")
        self.url = url
        self.emit_main_document_response(200)
        return SimpleNamespace(status=200)

    def close(self):
        self.closed = True


class FakeContext:
    def __init__(self):
        self.pages = []
        self.fail_page = False

    def new_page(self):
        page = FakePage(fail=self.fail_page)
        self.pages.append(page)
        return page


class FakePlaywright:
    def __init__(self, context=None, error=None):
        self.context = context or FakeContext()
        self.browser = Mock()
        self.browser.contexts = [self.context]
        self.browser.close = Mock()
        self.chromium = Mock()
        self.chromium.connect_over_cdp = Mock(return_value=self.browser, side_effect=error)
        self.stopped = False

    def stop(self):
        self.stopped = True


def manager(monkeypatch, tmp_path, *, cdp_error=None):
    runtime = Mock(cdp_url="http://127.0.0.1:9224", browser_path="/usr/bin/brave")
    runtime.close = Mock()
    playwright = FakePlaywright(error=cdp_error)
    monkeypatch.setattr(mod, "start_browser", lambda config: runtime)
    monkeypatch.setattr(
        mod,
        "_playwright_api",
        lambda: (lambda: SimpleNamespace(start=lambda: playwright), RuntimeError),
    )
    config = BrowserRuntimeConfig(
        tmp_path / "profile", backend="playwright-cdp", browser="brave"
    )
    return mod.BrowserSessionManager(config), runtime, playwright


def test_requires_start(tmp_path):
    session = mod.BrowserSessionManager(BrowserRuntimeConfig(tmp_path / "profile"))
    with pytest.raises(mod.BrowserSessionError, match="start"):
        session.open_page("https://www.bdfutbol.com/")


def test_lifecycle(monkeypatch, tmp_path):
    session, runtime, playwright = manager(monkeypatch, tmp_path)
    with session as active:
        assert active.ready
        assert active.cdp_url == "http://127.0.0.1:9224"
        with active.open_page("https://www.bdfutbol.com/es/j/j209629.html") as visit:
            assert visit.response_status == 200
            assert visit.final_url.endswith("j209629.html")
        assert playwright.context.pages[-1].closed
    assert runtime.close.call_count == 1
    assert playwright.stopped
    assert not session.ready


def test_double_start_rejected(monkeypatch, tmp_path):
    session, _, _ = manager(monkeypatch, tmp_path)
    session.start()
    try:
        with pytest.raises(mod.BrowserSessionError, match="ya está iniciada"):
            session.start()
    finally:
        session.close()


def test_session_cleans_unclosed_visits(monkeypatch, tmp_path):
    session, _, playwright = manager(monkeypatch, tmp_path)
    session.start()
    page = session.open_page("https://www.bdfutbol.com/").document._page
    assert not page.closed
    session.close()
    assert page.closed
    session.close()


def test_navigation_failure_closes_page(monkeypatch, tmp_path):
    session, _, playwright = manager(monkeypatch, tmp_path)
    session.start()
    playwright.context.fail_page = True
    try:
        with pytest.raises(mod.BrowserNavigationError):
            session.open_page("https://www.bdfutbol.com/")
        assert playwright.context.pages[-1].closed
    finally:
        session.close()


def test_cdp_connection_error_rolls_back(monkeypatch, tmp_path):
    session, runtime, playwright = manager(monkeypatch, tmp_path, cdp_error=RuntimeError("CDP roto"))
    with pytest.raises(mod.BrowserSessionError, match="CDP"):
        session.start()
    runtime.close.assert_called_once()
    assert playwright.stopped
    assert not session.ready


def test_missing_context_rolls_back(monkeypatch, tmp_path):
    session, runtime, playwright = manager(monkeypatch, tmp_path)
    playwright.browser.contexts = []
    with pytest.raises(mod.BrowserSessionError, match="contexto"):
        session.start()
    runtime.close.assert_called_once()


def test_invalid_timeouts(tmp_path):
    with pytest.raises(ValueError):
        mod.BrowserSessionManager(BrowserRuntimeConfig(tmp_path / "p"), cdp_timeout_ms=0)


def test_main_frame_navigation_updates_http_status(monkeypatch, tmp_path):
    session, _, playwright = manager(monkeypatch, tmp_path)
    with session:
        with session.open_page("https://www.bdfutbol.com/es/j/j209629.html") as visit:
            assert visit.response_status == 200
            visit.document._page.emit_main_document_response(403)
            assert visit.response_status == 403
            visit.document._page.emit_main_document_response(200)
            assert visit.response_status == 200


def test_subresource_response_does_not_change_status(monkeypatch, tmp_path):
    session, _, _ = manager(monkeypatch, tmp_path)
    with session:
        with session.open_page("https://www.bdfutbol.com/es/j/j209629.html") as visit:
            response = SimpleNamespace(
                request=SimpleNamespace(is_navigation_request=lambda: False),
                frame=visit.document._page.main_frame,
                status=403,
            )
            for callback in visit.document._page.listeners["response"]:
                callback(response)
            assert visit.response_status == 200


class FakeTab:
    def __init__(self):
        self.url = "about:blank"

    async def get(self, url):
        self.url = url


class FakePureCDPBrowser:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.tabs = [FakeTab()]
        self.page = self.tabs[0]
        self.loop = asyncio.new_event_loop()
        self.driver = SimpleNamespace(_process_pid=None)
        self.closed = False
        self.response_status = 200

    def open_new_tab(self, _url, switch_to=True):
        self.tabs.append(FakeTab())
        if switch_to:
            self.page = self.tabs[-1]

    def get_active_tab(self):
        return self.page

    def switch_to_tab(self, tab):
        self.page = tab

    def get_title(self):
        return "Local browser page"

    def get_page_source(self, include_shadow_dom=False):
        return "<html><body><h1>Local</h1></body></html>"

    def get_text(self, _selector):
        return "body text"

    def evaluate(self, expression):
        if expression == "window.location.href":
            return self.page.url
        if "performance.getEntriesByType" in expression:
            return self.response_status
        if ".length" in expression:
            return 1
        if "?.value" in expression:
            return "01/01/2026"
        if "querySelector(" in expression:
            return True
        if "querySelectorAll" in expression:
            return {"a": "Option A"}
        return True

    def close_active_tab(self):
        self.tabs.remove(self.page)
        if self.tabs:
            self.page = self.tabs[0]

    def quit(self):
        self.closed = True
        self.loop.close()


def test_pure_cdp_backend_uses_generic_document_and_preserves_profile(monkeypatch, tmp_path):
    from football_data_hub.core import browser_session as session_mod

    executable = tmp_path / "chromium"
    executable.write_text("binary placeholder", encoding="utf-8")
    browser = FakePureCDPBrowser()
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(session_mod, "_seleniumbase_browser", lambda **kwargs: browser)
    monkeypatch.setattr(session_mod, "_browser_version", lambda _path: "Chromium test")
    profile = tmp_path / "persistent-chromium-profile"
    config = BrowserRuntimeConfig(
        profile,
        backend="seleniumbase-pure-cdp",
        browser_executable_path=executable,
    )

    with session_mod.BrowserSessionManager(config) as session:
        assert session.info.backend == "seleniumbase-pure-cdp"
        assert session.info.browser_version == "Chromium test"
        with session.open_page("https://example.test/") as visit:
            assert visit.response_status == 200
            assert visit.document.title() == "Local browser page"
            assert "<h1>Local</h1>" in visit.document.html()
            assert visit.document.text("body") == "body text"
            assert visit.document.exists("#expected")
            assert visit.document.option_map("#filter") == {"a": "Option A"}
            visit.document.select("#filter", "a")
            visit.document.fill("#date", "01/01/2026")
            assert visit.document.value("#date") == "01/01/2026"
            assert visit.document.evaluate("window.location.href") == "https://example.test/"
    assert browser.closed
    assert profile.is_dir()
    assert not session.ready


def test_pure_cdp_requires_external_display(monkeypatch, tmp_path):
    from football_data_hub.core import browser_session as session_mod

    monkeypatch.delenv("DISPLAY", raising=False)
    session = session_mod.BrowserSessionManager(
        BrowserRuntimeConfig(tmp_path / "profile", backend="seleniumbase-pure-cdp")
    )
    with pytest.raises(session_mod.BrowserSessionError, match="xvfb-run"):
        session.start()
    assert not (tmp_path / "profile").exists()


def test_pure_cdp_profile_lock_prevents_concurrent_sessions(monkeypatch, tmp_path):
    from football_data_hub.core import browser_session as session_mod

    executable = tmp_path / "chromium"
    executable.write_text("binary placeholder", encoding="utf-8")
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(session_mod, "_seleniumbase_browser", lambda **kwargs: FakePureCDPBrowser())
    monkeypatch.setattr(session_mod, "_browser_version", lambda _path: "Chromium test")
    config = BrowserRuntimeConfig(
        tmp_path / "profile",
        backend="seleniumbase-pure-cdp",
        browser_executable_path=executable,
    )
    first = session_mod.BrowserSessionManager(config).start()
    try:
        second = session_mod.BrowserSessionManager(config)
        with pytest.raises(BrowserProfileInUse):
            second.start()
    finally:
        first.close()


def test_pure_cdp_preserves_unknown_http_status(monkeypatch, tmp_path):
    from football_data_hub.core import browser_session as session_mod

    executable = tmp_path / "chromium"
    executable.write_text("binary placeholder", encoding="utf-8")
    browser = FakePureCDPBrowser()
    browser.response_status = None
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(session_mod, "_seleniumbase_browser", lambda **kwargs: browser)
    monkeypatch.setattr(session_mod, "_browser_version", lambda _path: "Chromium test")
    config = BrowserRuntimeConfig(
        tmp_path / "profile",
        backend="seleniumbase-pure-cdp",
        browser_executable_path=executable,
    )
    with session_mod.BrowserSessionManager(config) as session:
        with session.open_page("https://example.test/") as visit:
            assert visit.response_status is None
