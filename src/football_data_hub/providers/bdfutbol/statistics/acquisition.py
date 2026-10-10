"""Captura controlada de la pestaña Estadísticas con Pure CDP existente."""

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

from .models import ParsedBDFutbolStatistics
from .parser import STATISTICS_URL, parse_statistics_page, validate_statistics_page_html

EXTRACTOR_VERSION = "0.1.0"


class StatisticsAcquisitionStopped(RuntimeError):
    """La visita no validó acceso o el contenido deportivo esperado."""

    def __init__(self, assessment: AccessAssessment) -> None:
        self.assessment = assessment
        super().__init__(
            f"Adquisición de Estadísticas detenida: {assessment.status}; "
            f"HTTP={assessment.http_status}; {assessment.reason or 'contenido no validado'}"
        )


@dataclass(frozen=True, slots=True)
class StatisticsAcquisitionBundle:
    capture_id: str
    captured_at_utc: str
    requested_url: str
    final_url: str
    http_status: int | None
    page_title: str
    raw_html: str
    chart_runtime: dict[str, Any]
    access: dict[str, Any]
    browser: dict[str, Any]
    profile_dir: Path
    parsed: ParsedBDFutbolStatistics


def create_statistics_capture_id(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"{now.strftime('%Y%m%dT%H%M%S.%fZ')}-{uuid4().hex[:8]}"


def _valid_html_structure(source_html: str) -> tuple[str, ...]:
    return validate_statistics_page_html(source_html)


def acquire_statistics_page(
    *,
    profile_dir: Path,
    browser_executable_path: Path | None = None,
    startup_timeout_seconds: float = 35.0,
    navigation_timeout_ms: int = 45_000,
    use_xvfb: bool = True,
) -> StatisticsAcquisitionBundle:
    """Navega una vez a Estadísticas; se detiene en desafío o contenido inválido."""
    config = BrowserRuntimeConfig(
        profile_dir=profile_dir,
        backend="seleniumbase-pure-cdp",
        browser="chromium",
        browser_executable_path=browser_executable_path,
        startup_timeout_seconds=startup_timeout_seconds,
        use_xvfb=use_xvfb,
    )
    with BrowserSessionManager(config, navigation_timeout_ms=navigation_timeout_ms) as session:
        opened = BDFutbolAccess(session).open(
            STATISTICS_URL,
            required_markers=(
                "1ª RFEF",
                "Grupo II",
                "2026-27",
                "Penaltis pitados",
                "Penaltis marcados",
                "Penaltis fallados",
                "Expulsiones",
                "Máxima victoria local",
            ),
            required_title_markers=("Grupo II", "2026-27"),
            required_selectors=(".tab-divs.pt-3", "#grf_stats", "table.taula_estil"),
            document_validator=_valid_html_structure,
            settle_ms=750,
            max_wait_seconds=5,
        )
        with opened:
            if opened.assessment.status is not AccessStatus.VALID or opened.visit is None:
                raise StatisticsAcquisitionStopped(opened.assessment)
            page = opened.visit.document
            source_html = page.html()
            chart_runtime = page.evaluate(_CHART_RUNTIME_EXPRESSION)
            if not isinstance(chart_runtime, dict):
                raise ValueError("AmCharts no devolvió el objeto de gráfico esperado")
            parsed = parse_statistics_page(
                source_html,
                chart_runtime,
                source_url=STATISTICS_URL,
            )
            info = session.info
            captured_at = datetime.now(timezone.utc)
            return StatisticsAcquisitionBundle(
                capture_id=create_statistics_capture_id(captured_at),
                captured_at_utc=captured_at.isoformat(),
                requested_url=STATISTICS_URL,
                final_url=opened.visit.final_url,
                http_status=opened.visit.response_status,
                page_title=opened.assessment.page_title,
                raw_html=source_html,
                chart_runtime=chart_runtime,
                access=asdict(opened.assessment),
                browser={
                    "backend": info.backend if info else config.backend,
                    "browser_name": info.browser_name if info else "Chromium",
                    "browser_executable": info.browser_executable if info else None,
                    "browser_version": info.browser_version if info else None,
                    "automation_version": info.automation_version if info else None,
                    "display": info.display if info else None,
                    "uses_xvfb": info.uses_xvfb if info else use_xvfb,
                    "xvfb_external": info.xvfb_external if info else use_xvfb,
                },
                profile_dir=profile_dir,
                parsed=parsed,
            )


_CHART_RUNTIME_EXPRESSION = r"""(() => {
  const candidates = (window.AmCharts?.charts || []).map((chart, index) => ({
    chart,
    index,
    graphs: chart.graphs || []
  }));
  const selected = candidates.find(({ graphs }) =>
    ['VG', 'VTG', 'VTV'].every((field) => graphs.some((graph) => graph.valueField === field))
  );
  if (!selected) return { error: 'No se encontró el gráfico con VG, VTG y VTV' };
  const { chart, index, graphs } = selected;
  return {
    library: 'amCharts',
    chart_index: index,
    chart_type: chart.type || null,
    category_field: chart.categoryField || null,
    graph_fields: graphs.map((graph) => ({
      title: graph.title,
      value_field: graph.valueField,
      line_color: graph.lineColor
    })),
    data_provider: chart.dataProvider || []
  };
})()"""
