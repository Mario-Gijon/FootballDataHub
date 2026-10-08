from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from football_data_hub.core import browser_session as mod
from football_data_hub.core.browser_runtime import BrowserRuntimeConfig


class FakePage:
    def __init__(self, *, fail=False):
        self.url = "https://www.bdfutbol.com/es/j/j209629.html"
        self.closed = False
        self.fail = fail
        self.timeout = None

    def set_default_navigation_timeout(self, timeout):
        self.timeout = timeout

    def goto(self, url, **kwargs):
        if self.fail:
            raise RuntimeError("falló conexión")
        self.url = url
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
    runtime = Mock(cdp_url="http://127.0.0.1:9224")
    runtime.close = Mock()
    playwright = FakePlaywright(error=cdp_error)
    monkeypatch.setattr(mod, "start_browser", lambda config: runtime)
    monkeypatch.setattr(mod, "sync_playwright", lambda: SimpleNamespace(start=lambda: playwright))
    config = BrowserRuntimeConfig(tmp_path / "profile")
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
    page = session.open_page("https://www.bdfutbol.com/").page
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
