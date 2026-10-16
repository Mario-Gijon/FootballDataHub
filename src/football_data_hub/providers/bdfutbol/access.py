"""Diagnóstico semántico de acceso a BDFutbol, sin resolver desafíos.

No confundir un HTTP 200 con contenido válido: cada recurso exige marcadores
específicos. La verificación se limita al dominio bdfutbol.com.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import parse_qsl, urlsplit

from football_data_hub.core.browser_session import (
    BrowserNavigationError,
    BrowserSessionManager,
    PageVisit,
)


class AccessStatus(StrEnum):
    VALID = "VALID"
    CHALLENGE_REQUIRED = "CHALLENGE_REQUIRED"
    HTTP_ERROR = "HTTP_ERROR"
    INVALID_URL = "INVALID_URL"
    INVALID_CONTENT = "INVALID_CONTENT"
    NAVIGATION_ERROR = "NAVIGATION_ERROR"
    DOCUMENT_ERROR = "DOCUMENT_ERROR"


@dataclass(frozen=True, slots=True)
class AccessAssessment:
    status: AccessStatus
    requested_url: str
    final_url: str | None
    http_status: int | None
    page_title: str
    missing_markers: tuple[str, ...] = ()
    reason: str | None = None
    missing_title_markers: tuple[str, ...] = ()
    missing_selectors: tuple[str, ...] = ()
    missing_dom_markers: tuple[str, ...] = ()
    missing_dom_evidence: tuple[str, ...] = ()

    @property
    def accessible(self) -> bool:
        return self.status is AccessStatus.VALID


@dataclass(slots=True)
class BDFutbolVisit:
    assessment: AccessAssessment
    visit: PageVisit | None = None

    def close(self) -> None:
        if self.visit is not None:
            self.visit.close()

    def __enter__(self) -> BDFutbolVisit:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


_CHALLENGE_MARKERS = (
    "verificación de seguridad en curso",
    "verificación de seguridad",
    "checking your browser",
    "verify you are human",
    "verifying you are human",
    "verifica que tú no eres un bot",
    "please enable javascript and cookies to continue",
    "cf-challenge",
    "challenges.cloudflare.com",
)
_CHALLENGE_TITLES = ("un momento", "just a moment", "attention required")
_ALLOWED_HOSTS = {"www.bdfutbol.com", "bdfutbol.com"}


def is_bdfutbol_https_url(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname in _ALLOWED_HOSTS


def same_resource(requested_url: str, final_url: str) -> bool:
    original, final = urlsplit(requested_url), urlsplit(final_url)
    return (
        is_bdfutbol_https_url(requested_url)
        and is_bdfutbol_https_url(final_url)
        and original.path == final.path
        and sorted(parse_qsl(original.query, keep_blank_values=True))
        == sorted(parse_qsl(final.query, keep_blank_values=True))
    )


def contains_bdfutbol_access_challenge(
    *, page_title: str, body_text: str, http_status: int | None = None
) -> bool:
    """Expose the existing conservative challenge-marker check to storage code."""

    body = body_text.casefold()
    title = page_title.casefold().strip()
    return (
        any(marker in title for marker in _CHALLENGE_TITLES)
        or any(marker in body for marker in _CHALLENGE_MARKERS)
        or (http_status in {403, 429, 503} and "cloudflare" in body)
    )


def assess_bdfutbol_access(
    *,
    requested_url: str,
    final_url: str,
    http_status: int | None,
    page_title: str,
    body_text: str,
    required_markers: tuple[str, ...],
    required_title_markers: tuple[str, ...] = (),
    required_selectors: tuple[str, ...] = (),
    present_selectors: tuple[str, ...] = (),
    required_dom_text_selector: str | None = None,
    required_dom_text_markers: tuple[str, ...] = (),
    dom_text: str = "",
    missing_dom_evidence: tuple[str, ...] = (),
) -> AccessAssessment:
    markers = (*required_markers, *required_title_markers)
    if not required_markers or any(not marker.strip() for marker in markers):
        raise ValueError("Es obligatorio proporcionar marcadores semánticos no vacíos")
    if any(not selector.strip() for selector in required_selectors):
        raise ValueError("Los selectores estructurales no pueden estar vacíos")
    if any(not marker.strip() for marker in required_dom_text_markers):
        raise ValueError("Los marcadores DOM no pueden estar vacíos")
    if required_dom_text_markers and not (required_dom_text_selector or "").strip():
        raise ValueError("Los marcadores DOM requieren un selector de contenido")
    if not is_bdfutbol_https_url(requested_url):
        return AccessAssessment(
            AccessStatus.INVALID_URL,
            requested_url,
            final_url,
            http_status,
            page_title,
            reason="Solo se permiten URLs HTTPS de BDFutbol",
        )

    if contains_bdfutbol_access_challenge(
        page_title=page_title, body_text=body_text, http_status=http_status
    ):
        return AccessAssessment(
            AccessStatus.CHALLENGE_REQUIRED,
            requested_url,
            final_url,
            http_status,
            page_title,
            reason="Desafío de acceso detectado; no se intenta resolver",
        )
    body = body_text.casefold()
    title = page_title.casefold().strip()
    if not same_resource(requested_url, final_url):
        return AccessAssessment(
            AccessStatus.INVALID_URL,
            requested_url,
            final_url,
            http_status,
            page_title,
            reason="La URL final no coincide con la solicitada",
        )
    if http_status is None or not (200 <= http_status < 300):
        reason = (
            "No se recibió un estado HTTP"
            if http_status is None
            else f"HTTP {http_status}"
        )
        return AccessAssessment(
            AccessStatus.HTTP_ERROR,
            requested_url,
            final_url,
            http_status,
            page_title,
            reason=reason,
        )
    missing = tuple(m for m in required_markers if m.casefold() not in body)
    missing_title = tuple(
        m for m in required_title_markers if m.casefold() not in title
    )
    scoped_dom_text = dom_text.casefold()
    missing_dom = tuple(
        m for m in required_dom_text_markers if m.casefold() not in scoped_dom_text
    )
    present = set(present_selectors)
    missing_selectors = tuple(
        selector for selector in required_selectors if selector not in present
    )
    if (
        missing
        or missing_title
        or missing_selectors
        or missing_dom
        or missing_dom_evidence
    ):
        return AccessAssessment(
            AccessStatus.INVALID_CONTENT,
            requested_url,
            final_url,
            http_status,
            page_title,
            missing,
            "Faltan marcadores semánticos o estructura del recurso",
            missing_title_markers=missing_title,
            missing_selectors=missing_selectors,
            missing_dom_markers=missing_dom,
            missing_dom_evidence=missing_dom_evidence,
        )
    return AccessAssessment(
        AccessStatus.VALID,
        requested_url,
        final_url,
        http_status,
        page_title,
    )


class BDFutbolAccess:
    def __init__(self, session: BrowserSessionManager) -> None:
        self.session = session

    def open(
        self,
        url: str,
        *,
        required_markers: tuple[str, ...],
        required_title_markers: tuple[str, ...] = (),
        required_selectors: tuple[str, ...] = (),
        required_dom_text_selector: str | None = None,
        required_dom_text_markers: tuple[str, ...] = (),
        document_validator: Callable[[str], tuple[str, ...]] | None = None,
        settle_ms: int = 750,
        max_wait_seconds: float = 12.0,
    ) -> BDFutbolVisit:
        if not is_bdfutbol_https_url(url):
            raise ValueError("Solo se permiten URLs HTTPS de bdfutbol.com")
        if not required_markers or any(not m.strip() for m in required_markers):
            raise ValueError("Indica marcadores semánticos específicos del recurso")
        if any(not marker.strip() for marker in required_title_markers):
            raise ValueError("Los marcadores de título no pueden estar vacíos")
        if any(not selector.strip() for selector in required_selectors):
            raise ValueError("Los selectores estructurales no pueden estar vacíos")
        if any(not marker.strip() for marker in required_dom_text_markers):
            raise ValueError("Los marcadores DOM no pueden estar vacíos")
        if required_dom_text_markers and not (required_dom_text_selector or "").strip():
            raise ValueError("Los marcadores DOM requieren un selector de contenido")
        if settle_ms < 0 or max_wait_seconds < 0:
            raise ValueError("Los tiempos no pueden ser negativos")
        try:
            visit = self.session.open_page(url)
        except BrowserNavigationError as exc:
            return BDFutbolVisit(
                AccessAssessment(
                    AccessStatus.NAVIGATION_ERROR,
                    url,
                    None,
                    None,
                    "",
                    reason=str(exc),
                )
            )

        page = visit.document
        title = ""
        selectors_to_verify = tuple(dict.fromkeys(("body", *required_selectors)))
        try:
            if settle_ms:
                page.wait(settle_ms)
            deadline = time.monotonic() + max_wait_seconds
            while True:
                title = page.title()
                body_text = page.text("body")
                present_selectors = tuple(
                    selector
                    for selector in selectors_to_verify
                    if page.exists(selector)
                )
                dom_text = ""
                if required_dom_text_selector:
                    dom_text = " ".join(page.texts(required_dom_text_selector))
                assessment = assess_bdfutbol_access(
                    requested_url=url,
                    final_url=visit.final_url,
                    http_status=visit.response_status,
                    page_title=title,
                    body_text=body_text,
                    required_markers=required_markers,
                    required_title_markers=required_title_markers,
                    required_selectors=selectors_to_verify,
                    present_selectors=present_selectors,
                    required_dom_text_selector=required_dom_text_selector,
                    required_dom_text_markers=required_dom_text_markers,
                    dom_text=dom_text,
                )
                if document_validator and assessment.status is AccessStatus.VALID:
                    missing_evidence = document_validator(page.html())
                    if missing_evidence:
                        assessment = assess_bdfutbol_access(
                            requested_url=url,
                            final_url=visit.final_url,
                            http_status=visit.response_status,
                            page_title=title,
                            body_text=body_text,
                            required_markers=required_markers,
                            required_title_markers=required_title_markers,
                            required_selectors=selectors_to_verify,
                            present_selectors=present_selectors,
                            required_dom_text_selector=required_dom_text_selector,
                            required_dom_text_markers=required_dom_text_markers,
                            dom_text=dom_text,
                            missing_dom_evidence=missing_evidence,
                        )
                # A security challenge or denial ends this acquisition
                # immediately. The bounded wait only allows ordinary page
                # content to finish rendering; it never waits for a challenge
                # to clear or retries the network navigation.
                waiting = assessment.status is AccessStatus.INVALID_CONTENT
                if not waiting or time.monotonic() >= deadline:
                    return BDFutbolVisit(assessment=assessment, visit=visit)
                page.wait(400)
        except Exception as exc:
            visit.close()
            return BDFutbolVisit(
                AccessAssessment(
                    AccessStatus.DOCUMENT_ERROR,
                    url,
                    visit.final_url,
                    visit.response_status,
                    title,
                    reason=f"No se pudo inspeccionar el DOM: {type(exc).__name__}: {exc}",
                )
            )
