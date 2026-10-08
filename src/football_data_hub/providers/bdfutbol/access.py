"""Diagnóstico semántico de acceso a BDFutbol, sin resolver desafíos.

No confundir un HTTP 200 con contenido válido: cada recurso exige marcadores
específicos. La verificación se limita al dominio bdfutbol.com.
"""

from __future__ import annotations

import time
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


@dataclass(frozen=True, slots=True)
class AccessAssessment:
    status: AccessStatus
    requested_url: str
    final_url: str | None
    http_status: int | None
    page_title: str
    missing_markers: tuple[str, ...] = ()
    reason: str | None = None

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


def assess_bdfutbol_access(
    *,
    requested_url: str,
    final_url: str,
    http_status: int | None,
    page_title: str,
    body_text: str,
    required_markers: tuple[str, ...],
) -> AccessAssessment:
    if not required_markers or any(not m.strip() for m in required_markers):
        raise ValueError("Es obligatorio proporcionar marcadores semánticos no vacíos")
    if not is_bdfutbol_https_url(requested_url):
        return AccessAssessment(
            AccessStatus.INVALID_URL, requested_url, final_url, http_status,
            page_title, reason="Solo se permiten URLs HTTPS de BDFutbol",
        )

    body = body_text.casefold()
    title = page_title.casefold().strip()
    is_challenge = (
        any(x in title for x in _CHALLENGE_TITLES)
        or any(x in body for x in _CHALLENGE_MARKERS)
        or (http_status in {403, 429, 503} and "cloudflare" in body)
    )
    if is_challenge:
        return AccessAssessment(
            AccessStatus.CHALLENGE_REQUIRED, requested_url, final_url,
            http_status, page_title, reason="Desafío de acceso detectado; no se intenta resolver",
        )
    if not same_resource(requested_url, final_url):
        return AccessAssessment(
            AccessStatus.INVALID_URL, requested_url, final_url,
            http_status, page_title, reason="La URL final no coincide con la solicitada",
        )
    if http_status is not None and not (200 <= http_status < 300):
        return AccessAssessment(
            AccessStatus.HTTP_ERROR, requested_url, final_url,
            http_status, page_title, reason=f"HTTP {http_status}",
        )
    missing = tuple(m for m in required_markers if m.casefold() not in body)
    if missing:
        return AccessAssessment(
            AccessStatus.INVALID_CONTENT, requested_url, final_url,
            http_status, page_title, missing,
            "No aparecen todos los marcadores del recurso",
        )
    return AccessAssessment(
        AccessStatus.VALID, requested_url, final_url, http_status, page_title,
    )


class BDFutbolAccess:
    def __init__(self, session: BrowserSessionManager) -> None:
        self.session = session

    def open(
        self,
        url: str,
        *,
        required_markers: tuple[str, ...],
        settle_ms: int = 750,
        max_wait_seconds: float = 12.0,
    ) -> BDFutbolVisit:
        if not is_bdfutbol_https_url(url):
            raise ValueError("Solo se permiten URLs HTTPS de bdfutbol.com")
        if not required_markers or any(not m.strip() for m in required_markers):
            raise ValueError("Indica marcadores semánticos específicos del recurso")
        if settle_ms < 0 or max_wait_seconds < 0:
            raise ValueError("Los tiempos no pueden ser negativos")
        try:
            visit = self.session.open_page(url)
        except BrowserNavigationError as exc:
            return BDFutbolVisit(AccessAssessment(
                AccessStatus.NAVIGATION_ERROR, url, None, None, "", reason=str(exc),
            ))

        page = visit.page
        if settle_ms:
            page.wait_for_timeout(settle_ms)
        deadline = time.monotonic() + max_wait_seconds
        while True:
            try:
                title = page.title()
                body_text = page.locator("body").inner_text(timeout=3000)
                assessment = assess_bdfutbol_access(
                    requested_url=url,
                    final_url=visit.final_url,
                    http_status=visit.response_status,
                    page_title=title,
                    body_text=body_text,
                    required_markers=required_markers,
                )
            except Exception:
                visit.close()
                raise
            # Cloudflare can show an intermediate challenge which the browser
            # completes on its own. Observe briefly; never click CAPTCHA,
            # reload the challenge, or attempt to bypass it.
            waiting = assessment.status in {
                AccessStatus.INVALID_CONTENT,
                AccessStatus.CHALLENGE_REQUIRED,
            }
            if not waiting or time.monotonic() >= deadline:
                return BDFutbolVisit(assessment=assessment, visit=visit)
            page.wait_for_timeout(400)
