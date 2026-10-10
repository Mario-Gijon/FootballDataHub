"""Adquisición de una única página Destacados con Pure CDP existente."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from football_data_hub.core.browser_runtime import BrowserRuntimeConfig
from football_data_hub.core.browser_session import BrowserSessionManager
from football_data_hub.providers.bdfutbol.access import (
    AccessAssessment,
    AccessStatus,
    BDFutbolAccess,
)

from .models import ParsedTop
from .parser import TOP_URL, parse_top_page
from .validation import validate_top_data

EXTRACTOR_VERSION = "0.1.0"


class TopAcquisitionStopped(RuntimeError):
    """La página no pasó la evaluación de acceso y contenido."""

    def __init__(self, assessment: AccessAssessment) -> None:
        self.assessment = assessment
        super().__init__(
            f"Adquisición de Destacados detenida: {assessment.status}; "
            f"HTTP={assessment.http_status}; {assessment.reason or 'contenido no validado'}"
        )


@dataclass(frozen=True, slots=True)
class TopAcquisitionBundle:
    capture_id: str
    captured_at_utc: str
    raw_html: str
    page_title: str
    access: dict[str, Any]
    browser: dict[str, Any]
    parsed: ParsedTop
    validation: dict[str, Any]


def create_top_capture_id(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"{now.strftime('%Y%m%dT%H%M%S.%fZ')}-{uuid4().hex[:8]}"


def validate_top_structure(source_html: str) -> tuple[str, ...]:
    required = (
        'id="tipdest"',
        'id="jugs1"',
        'id="jugs2"',
        'id="jugs3"',
        'id="jugs4"',
        'id="jugs8"',
        'id="jugs9"',
        'id="tab_estran"',
        'id="paisos_destacats"',
        "const DESTACATS_JS",
    )
    return tuple(marker for marker in required if marker not in source_html)


def acquire_top(
    *,
    team_catalog: list[dict[str, Any]],
    profile_dir: Path,
    browser: str = "chromium",
    browser_executable_path: Path | None = None,
    startup_timeout_seconds: float = 35.0,
    navigation_timeout_ms: int = 45_000,
    use_xvfb: bool = True,
    capture_id: str | None = None,
) -> TopAcquisitionBundle:
    """Open Destacados once; never retries or interacts with challenges."""
    capture_id = capture_id or create_top_capture_id()
    config = BrowserRuntimeConfig(
        profile_dir=profile_dir,
        backend="seleniumbase-pure-cdp",
        browser=browser,
        browser_executable_path=browser_executable_path,
        startup_timeout_seconds=startup_timeout_seconds,
        use_xvfb=use_xvfb,
    )
    with BrowserSessionManager(config, navigation_timeout_ms=navigation_timeout_ms) as session:
        opened = BDFutbolAccess(session).open(
            TOP_URL,
            required_markers=("Extranjeros", "Goles"),
            required_title_markers=("Grupo II", "2026-27"),
            required_selectors=(
                "#tipdest", "#jugs1 table", "#jugs2 table", "#jugs3 table",
                "#jugs4 table", "#jugs8 table", "#jugs9 table",
                "table#tab_estran", "#paisos_destacats",
            ),
            document_validator=validate_top_structure,
            settle_ms=750,
            max_wait_seconds=0,
        )
        with opened:
            if opened.assessment.status is not AccessStatus.VALID or opened.visit is None:
                raise TopAcquisitionStopped(opened.assessment)
            page = opened.visit.document
            source_html = page.html()
            parsed = parse_top_page(source_html, team_catalog=team_catalog)
            validation = validate_top_data(parsed)
            if not validation["valid"]:
                raise ValueError(f"Validación de Destacados fallida: {validation['issues']}")
            info = session.info
            return TopAcquisitionBundle(
                capture_id=capture_id,
                captured_at_utc=datetime.now(timezone.utc).isoformat(),
                raw_html=source_html,
                page_title=opened.assessment.page_title,
                access=asdict(opened.assessment),
                browser={
                    "backend": info.backend if info else config.backend,
                    "browser_name": info.browser_name if info else browser,
                    "browser_executable": info.browser_executable if info else None,
                    "browser_version": info.browser_version if info else None,
                    "automation_version": info.automation_version if info else None,
                    "display": info.display if info else None,
                    "uses_xvfb": info.uses_xvfb if info else use_xvfb,
                    "xvfb_external": info.xvfb_external if info else use_xvfb,
                },
                parsed=parsed,
                validation=validation,
            )
