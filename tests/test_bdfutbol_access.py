from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup

from football_data_hub.collectors.bdfutbol_player import (
    _VIEW_MARKERS,
    _VIEW_REQUIRED_SELECTORS,
    _VIEW_TITLE_MARKERS,
)
from football_data_hub.core.browser_session import BrowserNavigationError
from football_data_hub.parsers.player_pages import missing_profile_field_evidence
from football_data_hub.providers.bdfutbol import access as mod

URL = "https://www.bdfutbol.com/es/j/j209629.html"
MARKERS = ("Morillas", "Nombre completo", "Demarcación")
VALID_BODY = "Morillas | Nombre completo | Jaime Morillas | Demarcación | Portero"
PROFILE_BODY_MARKERS = ("Trayectoria",)
PROFILE_TITLE_MARKERS = ("Futbolista",)
PROFILE_SELECTORS = ("h1", ".traject")
PROFILE_FIELD_EVIDENCE = ("Nombre completo", "Demarcación")

SYNTHETIC_PROFILE_HTML = """<!doctype html><html><head>
<title>Manu Pedreño - Futbolista | BDFutbol</title></head><body>
<h1>Manu Pedreño</h1><a>Trayectoria</a>
<div class="hero"><div class="d-none d-md-block">
  <div class="float-left"><div>Nombre completo</div>
    <div class="font-weight-bold">Antonio Manuel Moñino Pedreño</div></div>
  <div class="float-left"><div>Demarcación</div><div>Delantero</div></div>
</div></div><table class="traject"><tr><th>Temp</th></tr></table>
</body></html>"""


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


def test_profile_title_marker_with_error_content_is_incomplete():
    # Fixture sintético de contrato; no representa HTML observado de j23751.
    result = assess(
        page_title="Manu Pedreño - Futbolista | BDFutbol",
        body_text="Página de error sin datos de jugador",
        required_markers=PROFILE_BODY_MARKERS,
        required_title_markers=PROFILE_TITLE_MARKERS,
        required_selectors=PROFILE_SELECTORS,
        present_selectors=(),
        missing_dom_evidence=PROFILE_FIELD_EVIDENCE,
    )
    assert result.http_status == 200
    assert result.status is mod.AccessStatus.INVALID_CONTENT
    assert result.missing_markers == PROFILE_BODY_MARKERS
    assert result.missing_title_markers == ()
    assert result.missing_selectors == PROFILE_SELECTORS
    assert result.missing_dom_evidence == PROFILE_FIELD_EVIDENCE


def test_synthetic_profile_accepts_futbolista_in_title_but_not_body() -> None:
    # Fixture sintético basado en el contrato y la evidencia manual aportada;
    # no se usa como evidencia de la estructura real de j23751.
    body = "Trayectoria"
    assert "Futbolista" not in body
    assert "Nombre completo" not in body
    assert "Demarcación" not in body
    missing_evidence = missing_profile_field_evidence(SYNTHETIC_PROFILE_HTML)
    assert missing_evidence == ()
    result = assess(
        page_title="Manu Pedreño, Antonio Manuel Moñino Pedreño - Futbolista | BDFutbol",
        body_text=body,
        required_markers=PROFILE_BODY_MARKERS,
        required_title_markers=PROFILE_TITLE_MARKERS,
        required_selectors=PROFILE_SELECTORS,
        present_selectors=PROFILE_SELECTORS,
        missing_dom_evidence=missing_evidence,
    )
    assert result.status is mod.AccessStatus.VALID
    assert result.missing_markers == ()
    assert result.missing_title_markers == ()
    assert result.missing_selectors == ()
    assert result.missing_dom_evidence == ()


def test_profile_title_alone_does_not_accept_incorrect_http_200_content() -> None:
    result = assess(
        page_title="Manu Pedreño - Futbolista | BDFutbol",
        body_text="Página no encontrada",
        required_markers=PROFILE_BODY_MARKERS,
        required_title_markers=PROFILE_TITLE_MARKERS,
        required_selectors=PROFILE_SELECTORS,
        present_selectors=(),
        missing_dom_evidence=PROFILE_FIELD_EVIDENCE,
    )
    assert result.status is mod.AccessStatus.INVALID_CONTENT
    assert result.missing_markers == PROFILE_BODY_MARKERS
    assert result.missing_selectors == PROFILE_SELECTORS
    assert result.missing_dom_evidence == PROFILE_FIELD_EVIDENCE


def test_profile_with_fields_but_without_trajectory_structure_is_incomplete() -> None:
    result = assess(
        page_title="Manu Pedreño - Futbolista | BDFutbol",
        body_text="Trayectoria",
        required_markers=PROFILE_BODY_MARKERS,
        required_title_markers=PROFILE_TITLE_MARKERS,
        required_selectors=PROFILE_SELECTORS,
        present_selectors=("h1",),
    )
    assert result.status is mod.AccessStatus.INVALID_CONTENT
    assert result.missing_markers == ()
    assert result.missing_selectors == (".traject",)
    assert result.missing_dom_evidence == ()


def test_profile_challenge_is_rejected_before_semantic_content() -> None:
    result = assess(
        page_title="Just a moment...",
        body_text="Checking your browser",
        http_status=403,
        required_markers=PROFILE_BODY_MARKERS,
        required_title_markers=PROFILE_TITLE_MARKERS,
        required_selectors=PROFILE_SELECTORS,
    )
    assert result.status is mod.AccessStatus.CHALLENGE_REQUIRED


def test_profile_final_url_for_another_player_is_rejected() -> None:
    result = assess(
        final_url="https://www.bdfutbol.com/es/j/j100160.html",
        required_markers=PROFILE_BODY_MARKERS,
        required_title_markers=PROFILE_TITLE_MARKERS,
        required_selectors=PROFILE_SELECTORS,
        present_selectors=PROFILE_SELECTORS,
        missing_dom_evidence=(),
    )
    assert result.status is mod.AccessStatus.INVALID_URL


def test_real_morillas_snapshots_pass_all_four_view_access_contracts() -> None:
    raw_root = Path(__file__).resolve().parents[1] / "data/raw/bdfutbol/luna_audit/20261008T121250.991672Z"
    snapshot_names = {
        "profile": "player_profile_morillas",
        "statistics": "player_stats_morillas",
        "matches": "player_matches_morillas",
        "rivals": "player_rivals_morillas",
    }
    for view, snapshot_name in snapshot_names.items():
        snapshot = raw_root / snapshot_name
        metadata = json.loads((snapshot / "metadata.json").read_text(encoding="utf-8"))
        html = (snapshot / "rendered.html").read_text(encoding="utf-8")
        soup = BeautifulSoup(html, "lxml")
        present = tuple(
            selector for selector in _VIEW_REQUIRED_SELECTORS.get(view, ())
            if soup.select_one(selector) is not None
        )
        assessment = mod.assess_bdfutbol_access(
            requested_url=metadata["requested_url"],
            final_url=metadata["final_url"],
            http_status=metadata["http_status"],
            page_title=soup.title.get_text(" ", strip=True) if soup.title else "",
            body_text=soup.get_text(" ", strip=True),
            required_markers=_VIEW_MARKERS[view],
            required_title_markers=_VIEW_TITLE_MARKERS.get(view, ()),
            required_selectors=_VIEW_REQUIRED_SELECTORS.get(view, ()),
            present_selectors=present,
            missing_dom_evidence=(
                missing_profile_field_evidence(html) if view == "profile" else ()
            ),
        )
        assert assessment.status is mod.AccessStatus.VALID, view


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


def test_access_open_profile_checks_title_body_and_dom_structure():
    class ProfilePage(FakePage):
        def __init__(self):
            super().__init__(
                title="Manu Pedreño - Futbolista | BDFutbol",
                body="Trayectoria",
            )

        def locator(self, selector):
            if selector == "body":
                return SimpleNamespace(inner_text=lambda **kwargs: self._body)
            if selector in PROFILE_SELECTORS:
                return SimpleNamespace(count=lambda: 1)
            raise AssertionError(f"Selector inesperado: {selector}")

        def content(self):
            return SYNTHETIC_PROFILE_HTML

    session = FakeSession(ProfilePage())
    with mod.BDFutbolAccess(session).open(
        URL,
        required_markers=PROFILE_BODY_MARKERS,
        required_title_markers=PROFILE_TITLE_MARKERS,
        required_selectors=PROFILE_SELECTORS,
        document_validator=missing_profile_field_evidence,
        max_wait_seconds=0,
    ) as result:
        assert result.assessment.status is mod.AccessStatus.VALID


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
