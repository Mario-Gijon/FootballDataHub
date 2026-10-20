"""Adquisición controlada de los tres ámbitos arbitrales de 2026/27."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from football_data_hub.core.browser_runtime import BrowserRuntimeConfig
from football_data_hub.core.browser_session import BrowserSessionManager
from football_data_hub.providers.bdfutbol.access import (
    AccessAssessment,
    AccessStatus,
    BDFutbolAccess,
)

from .models import ParsedRefereePage, RefereeScope
from .parser import REFEREES_URL, parse_referee_page

EXTRACTOR_VERSION = "0.1.0"


class RefereeAcquisitionStopped(RuntimeError):
    """La adquisición se detuvo por acceso no válido o contenido inesperado."""

    def __init__(self, assessment: AccessAssessment) -> None:
        self.assessment = assessment
        super().__init__(
            f"Adquisición de Árbitros detenida: {assessment.status}; "
            f"HTTP={assessment.http_status}; {assessment.reason or 'contenido no validado'}"
        )


@dataclass(frozen=True, slots=True)
class RefereeScopeSnapshot:
    scope: RefereeScope
    requested_url: str
    final_url: str
    captured_at_utc: str
    page_title: str
    http_status: int | None
    access: dict[str, Any]
    raw_html: str


@dataclass(frozen=True, slots=True)
class RefereeAcquisitionBundle:
    capture_id: str
    captured_at_utc: str
    pages: tuple[RefereeScopeSnapshot, ...]
    browser: dict[str, Any]
    profile_dir: Path | None
    parent_capture_id: str | None = None


def create_referee_capture_id(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"{now.strftime('%Y%m%dT%H%M%S.%fZ')}-{uuid4().hex[:8]}"


def validate_referee_structure(source_html: str) -> tuple[str, ...]:
    required = (
        'id="tab_arb"',
        'title="Fecha de nacimiento"',
        'title="Partidos"',
        'title="Tarjetas amarillas"',
        'title="Tarjetas rojas"',
        "/r/r",
    )
    return tuple(marker for marker in required if marker not in source_html)


def _access_page(
    session: BrowserSessionManager,
    *,
    url: str,
    scope: RefereeScope,
) -> RefereeScopeSnapshot:
    group_title = {"all": "Grupo II", "group1": "Grupo I", "group2": "Grupo II"}[scope]
    opened = BDFutbolAccess(session).open(
        url,
        required_markers=("2026-27",),
        required_title_markers=(group_title, "2026-27"),
        required_selectors=("#tab_arb", "#tab_arb a[href*='/r/r']"),
        document_validator=validate_referee_structure,
        settle_ms=500,
        max_wait_seconds=0,
    )
    with opened:
        if opened.assessment.status is not AccessStatus.VALID or opened.visit is None:
            raise RefereeAcquisitionStopped(opened.assessment)
        page = opened.visit.document
        source_html = page.html()
        # Parse before keeping the snapshot so a structurally wrong page is not
        # exported as an accepted referee capture.
        parse_referee_page(source_html, scope=scope, source_url=url)
        return RefereeScopeSnapshot(
            scope=scope,
            requested_url=url,
            final_url=opened.visit.final_url,
            captured_at_utc=datetime.now(timezone.utc).isoformat(),
            page_title=opened.assessment.page_title,
            http_status=opened.visit.response_status,
            access=asdict(opened.assessment),
            raw_html=source_html,
        )


def _scope_target(page: ParsedRefereePage, scope: RefereeScope) -> str:
    option = next((item for item in page.group_options if item.scope == scope), None)
    if option is None or not option.target_url:
        raise ValueError(f"El HTML inicial no ofrece una URL verificable para {scope}")
    parts = urlsplit(option.target_url)
    expected_path = {"group1": "t2026-271rf1.html", "group2": "t2026-271rf2.html"}[scope]
    if parts.scheme != "https" or parts.hostname != "www.bdfutbol.com":
        raise ValueError(f"Destino de grupo fuera de BDFutbol: {option.target_url}")
    if not parts.path.endswith(expected_path) or parse_qs(parts.query).get("tab") != ["referees"]:
        raise ValueError(f"Destino inesperado para {scope}: {option.target_url}")
    if parse_qs(parts.query).get("grups") != ["1"]:
        raise ValueError(f"El filtro de {scope} no conserva su parámetro de ámbito")
    return option.target_url


def acquire_referee_pages(
    *,
    profile_dir: Path,
    browser_executable_path: Path | None = None,
    startup_timeout_seconds: float = 35.0,
    navigation_timeout_ms: int = 45_000,
    use_xvfb: bool = True,
    capture_id: str | None = None,
    pause_seconds: float = 0.0,
) -> RefereeAcquisitionBundle:
    """Captura Todos, Grupo 1 y Grupo 2 con una sola sesión Pure CDP.

    Los selectores de grupo navegan a otra URL. Cada ámbito se visita una vez y
    la adquisición se detiene en la primera denegación o estructura inválida.
    """
    if pause_seconds < 0:
        raise ValueError("pause_seconds no puede ser negativo")
    config = BrowserRuntimeConfig(
        profile_dir=profile_dir,
        backend="seleniumbase-pure-cdp",
        browser="chromium",
        browser_executable_path=browser_executable_path,
        startup_timeout_seconds=startup_timeout_seconds,
        use_xvfb=use_xvfb,
    )
    snapshots: list[RefereeScopeSnapshot] = []
    with BrowserSessionManager(config, navigation_timeout_ms=navigation_timeout_ms) as session:
        all_page = _access_page(session, url=REFEREES_URL, scope="all")
        snapshots.append(all_page)
        parsed_all = parse_referee_page(
            all_page.raw_html, scope="all", source_url=all_page.requested_url
        )
        for scope in ("group1", "group2"):
            if pause_seconds:
                time.sleep(pause_seconds)
            url = _scope_target(parsed_all, scope)
            snapshots.append(_access_page(session, url=url, scope=scope))
        info = session.info
        browser_info = {
            "backend": info.backend if info else config.backend,
            "browser_name": info.browser_name if info else "Chromium",
            "browser_executable": info.browser_executable if info else None,
            "browser_version": info.browser_version if info else None,
            "automation_version": info.automation_version if info else None,
            "display": info.display if info else None,
            "uses_xvfb": info.uses_xvfb if info else use_xvfb,
            "xvfb_external": info.xvfb_external if info else use_xvfb,
        }
    return RefereeAcquisitionBundle(
        capture_id=capture_id or create_referee_capture_id(),
        captured_at_utc=snapshots[0].captured_at_utc,
        pages=tuple(snapshots),
        browser=browser_info,
        profile_dir=profile_dir,
    )
