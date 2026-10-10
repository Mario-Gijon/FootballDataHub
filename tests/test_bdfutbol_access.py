from __future__ import annotations

from types import SimpleNamespace

import pytest
from football_data_hub.core.browser_session import BrowserNavigationError
from football_data_hub.providers.bdfutbol import access as mod

URL = "https://www.bdfutbol.com/es/j/j209629.html"
MARKERS = ("Morillas", "Nombre completo", "Demarcación")
VALID_BODY = "Morillas | Nombre completo | Jaime Morillas | Demarcación | Portero"
def assess(**overrides):
    inputs = dict(
        requested_url=URL, final_url=URL, http_status=200,
        page_title="Morillas, Jaime - BDFutbol", body_text=VALID_BODY,
        required_markers=MARKERS,
    )
    inputs.update(overrides)
    return mod.assess_bdfutbol_access(**inputs)


def test_success():
    result = assess()
    assert result.status is mod.AccessStatus.VALID
    assert result.accessible
    assert result.missing_markers == ()


@pytest.mark.parametrize("title,body,status", [
    ("Un momento…", "Cloudflare", 403),
    ("Just a moment...", "Checking your browser", 503),
    ("BDFutbol", "Verificación de seguridad en curso", 200),
    ("BDFutbol", "cf-challenge", 403),
])
def test_challenge(title, body, status):
    result = assess(page_title=title, body_text=body, http_status=status)
    assert result.status is mod.AccessStatus.CHALLENGE_REQUIRED


def test_different_403_not_mislabelled():
    assert assess(http_status=403).status is mod.AccessStatus.HTTP_ERROR


def test_missing_http_status_is_not_accepted_as_valid():
    result = assess(http_status=None)
    assert result.status is mod.AccessStatus.HTTP_ERROR
    assert result.reason == "No se recibió un estado HTTP"


def test_missing_marker():
    result = assess(body_text="Morillas | Nombre completo")
    assert result.status is mod.AccessStatus.INVALID_CONTENT
    assert result.missing_markers == ("Demarcación",)


def test_bad_path():
    assert assess(final_url="https://www.bdfutbol.com/es/").status is mod.AccessStatus.INVALID_URL


def test_other_host():
    assert assess(final_url="https://bdfutbol.com.evil.test/es/j/j209629.html").status is mod.AccessStatus.INVALID_URL


def test_required_markers_never_optional():
    with pytest.raises(ValueError, match="obligatorio"):
        assess(required_markers=())


def test_bdfutbol_https_only():
    assert mod.is_bdfutbol_https_url(URL)
    assert not mod.is_bdfutbol_https_url("http://www.bdfutbol.com/es/")
    assert not mod.is_bdfutbol_https_url("https://www.bdfutbol.com.evil.test/es/")
    assert not mod.is_bdfutbol_https_url("https://evil.test/?next=bdfutbol.com")


def test_query_order_is_equivalent():
    assert mod.same_resource(URL + "?manager=1&p=stats", URL + "?p=stats&manager=1")
    assert not mod.same_resource(URL + "?manager=1", URL)


class FakePage:
    url = URL
    def __init__(self, *, title="Morillas", body=VALID_BODY):
        self._title = title
        self._body = body
        self.closed = False
        self.waits = []

    def title(self):
        return self._title

    def locator(self, selector):
        assert selector == "body"
        return SimpleNamespace(inner_text=lambda **kwargs: self._body)

    def wait_for_timeout(self, milliseconds):
        self.waits.append(milliseconds)

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, page=None, *, response_status=200, error=None):
        self.page = page or FakePage()
        self.response_status = response_status
        self.error = error
        self.calls = []

    def open_page(self, url):
        self.calls.append(url)
        if self.error:
            raise self.error
        page = self.page
        status = self.response_status
        return SimpleNamespace(
            page=page, final_url=page.url, response_status=status,
            close=lambda: page.close(),
        )


def test_access_open_success():
    session = FakeSession()
    with mod.BDFutbolAccess(session).open(URL, required_markers=MARKERS, max_wait_seconds=0) as result:
        assert result.assessment.accessible
    assert session.page.closed
    assert session.page.waits == [750]


def test_access_open_checks_page_title_and_dom_markers():
    class MarkupPage(FakePage):
        def __init__(self):
            super().__init__(title="Team details | BDFutbol", body="Equipo local")

        def locator(self, selector):
            if selector == "body":
                return SimpleNamespace(inner_text=lambda **kwargs: self._body)
            if selector == "#content":
                return SimpleNamespace(
                    count=lambda: 1,
                    all_text_contents=lambda: ["Equipo local · Temporada actual"],
                )
            raise AssertionError(f"Selector inesperado: {selector}")

    session = FakeSession(MarkupPage())
    with mod.BDFutbolAccess(session).open(
        URL,
        required_markers=("Equipo local",),
        required_title_markers=("BDFutbol",),
        required_selectors=("#content",),
        required_dom_text_selector="#content",
        required_dom_text_markers=("Temporada actual",),
        max_wait_seconds=0,
    ) as result:
        assert result.assessment.accessible
        assert result.assessment.missing_selectors == ()
        assert result.assessment.missing_dom_markers == ()


def test_access_open_challenge():
    session = FakeSession(FakePage(title="Un momento…", body="Verificación de seguridad en curso"), response_status=403)
    with mod.BDFutbolAccess(session).open(URL, required_markers=MARKERS, max_wait_seconds=0) as result:
        assert result.assessment.status == mod.AccessStatus.CHALLENGE_REQUIRED
    assert session.page.closed


def test_access_navigation_error():
    session = FakeSession(error=BrowserNavigationError("sin conexión"))
    result = mod.BDFutbolAccess(session).open(URL, required_markers=MARKERS)
    assert result.assessment.status == mod.AccessStatus.NAVIGATION_ERROR
    assert result.visit is None


def test_access_rejects_other_sites_before_navigating():
    session = FakeSession()
    with pytest.raises(ValueError):
        mod.BDFutbolAccess(session).open("https://other.test", required_markers=MARKERS)
    assert session.calls == []


def test_access_invalid_timings():
    with pytest.raises(ValueError):
        mod.BDFutbolAccess(FakeSession()).open(URL, required_markers=MARKERS, settle_ms=-1)


def test_access_waits_for_transient_challenge_to_clear():
    class TransientPage(FakePage):
        def __init__(self):
            super().__init__(title="Un momento…", body="Verificación de seguridad en curso")
            self.visit = None

        def wait_for_timeout(self, milliseconds):
            super().wait_for_timeout(milliseconds)
            if milliseconds == 400:
                self._title = "Morillas - Futbolista | BDFutbol"
                self._body = VALID_BODY
                self.visit.response_status = 200

    class TransientSession(FakeSession):
        def open_page(self, url):
            visit = SimpleNamespace(
                page=self.page, final_url=url, response_status=403,
                close=lambda: self.page.close(),
            )
            self.page.visit = visit
            return visit

    page = TransientPage()
    session = TransientSession(page)
    # This fake moves directly to valid content on the next wait, no real time.
    with mod.BDFutbolAccess(session).open(
        URL, required_markers=MARKERS, max_wait_seconds=2.0,
    ) as result:
        assert result.assessment.status is mod.AccessStatus.VALID
        assert result.assessment.http_status == 200
        assert page.waits == [750, 400]


def test_access_still_reports_persistent_challenge_without_retrying():
    page = FakePage(title="Un momento…", body="Verificación de seguridad en curso")
    session = FakeSession(page, response_status=403)
    with mod.BDFutbolAccess(session).open(
        URL, required_markers=MARKERS, max_wait_seconds=0,
    ) as result:
        assert result.assessment.status is mod.AccessStatus.CHALLENGE_REQUIRED
        assert session.calls == [URL]
