"""Adquisición controlada de una sola vista de clasificación."""

from __future__ import annotations

import re
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

from .models import ClassificationContext, ClassificationRequest, ParsedClassification
from .navigation import apply_filters
from .parser import parse_classification_page, validate_page_structure
from .validation import validate_classification

CLASSIFICATION_URL = "https://www.bdfutbol.com/es/t/t2026-271rf2.html"
EXTRACTOR_VERSION = "0.1.0"


class AcquisitionStopped(RuntimeError):
    """La página no pasó la validación de acceso o contenido."""

    def __init__(self, assessment: AccessAssessment) -> None:
        self.assessment = assessment
        super().__init__(
            f"Adquisición detenida: {assessment.status}; HTTP={assessment.http_status}; "
            f"{assessment.reason or 'contenido no validado'}"
        )


@dataclass(frozen=True, slots=True)
class AcquisitionBundle:
    capture_id: str
    captured_at_utc: str
    raw_html: str
    page_title: str
    access: dict[str, Any]
    context: ClassificationContext
    parsed: ParsedClassification
    validation: dict[str, Any]
    browser_executable: str


def create_capture_id(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"{now.strftime('%Y%m%dT%H%M%S.%fZ')}-{uuid4().hex[:8]}"


def _redact_browser_log(path: Path) -> None:
    """Do not persist the ephemeral CDP WebSocket path printed by Chromium."""
    if not path.is_file():
        return
    content = path.read_text(encoding="utf-8", errors="replace")
    safe = re.sub(
        r"ws://127\.0\.0\.1:\d+/devtools/browser/[0-9a-f-]+",
        "ws://127.0.0.1:<port>/devtools/browser/[redacted]",
        content,
        flags=re.IGNORECASE,
    )
    if safe != content:
        path.write_text(safe, encoding="utf-8")


def acquire_classification(
    *,
    request: ClassificationRequest,
    profile_dir: Path,
    browser: str = "brave",
    browser_log_path: Path | None = None,
    capture_id: str | None = None,
) -> AcquisitionBundle:
    """Open the known page once and extract one requested table state.

    Access assessment has no challenge wait/retry. A challenge or denial raises
    ``AcquisitionStopped`` without interacting with the page.
    """
    capture_id = capture_id or create_capture_id()
    captured_at = datetime.now(timezone.utc).isoformat()
    config = BrowserRuntimeConfig(
        profile_dir=profile_dir,
        browser=browser,
        browser_log_path=browser_log_path,
    )
    bundle: AcquisitionBundle | None = None
    try:
        with BrowserSessionManager(config) as session:
            opened = BDFutbolAccess(session).open(
                CLASSIFICATION_URL,
                required_markers=("Clasificación", "Grupo II"),
                required_title_markers=("Grupo II", "2026-27"),
                required_selectors=(
                    "table#classific",
                    "#classitip",
                    "#jornada",
                    "#postposat",
                    "#filtre_dates",
                    "#vista_graf1",
                ),
                document_validator=validate_page_structure,
                settle_ms=750,
                max_wait_seconds=0,
            )
            with opened:
                assessment = opened.assessment
                if assessment.status is not AccessStatus.VALID or opened.visit is None:
                    raise AcquisitionStopped(assessment)

                page = opened.visit.page
                context = apply_filters(page, request)
                raw_html = page.content()
                parsed = parse_classification_page(raw_html, base_url=CLASSIFICATION_URL)
                validation = validate_classification(
                    parsed.standings,
                    parsed.progress,
                    played_matchdays=parsed.played_matchdays,
                )
                access = asdict(assessment)
                runtime = session.runtime
                browser_executable = runtime.browser_path if runtime else browser
                bundle = AcquisitionBundle(
                    capture_id=capture_id,
                    captured_at_utc=captured_at,
                    raw_html=raw_html,
                    page_title=assessment.page_title,
                    access=access,
                    context=context,
                    parsed=parsed,
                    validation=validation,
                    browser_executable=browser_executable,
                )
    finally:
        if browser_log_path is not None:
            _redact_browser_log(browser_log_path)
    if bundle is None:
        raise RuntimeError("La captura terminó sin resultados")
    return bundle
