"""Capture and normalize the BDFutbol Group II Statistics tab, online or offline."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from football_data_hub.domain.classification.validation import validate_match_set
from football_data_hub.domain.statistics.engine import calculate_competition_statistics
from football_data_hub.domain.statistics.models import CompetitionContext
from football_data_hub.providers.bdfutbol.classification.match_io import load_match_dataset
from football_data_hub.providers.bdfutbol.classification.matches import extract_matches
from football_data_hub.providers.bdfutbol.classification.parser import parse_classification_page
from football_data_hub.providers.bdfutbol.statistics.acquisition import (
    StatisticsAcquisitionStopped,
    acquire_statistics_page,
)
from football_data_hub.providers.bdfutbol.statistics.export import export_statistics_capture
from football_data_hub.providers.bdfutbol.statistics.parser import (
    STATISTICS_URL,
    parse_statistics_page,
    validate_statistics_page_html,
)
from football_data_hub.providers.bdfutbol.statistics.validation import (
    build_match_alignment_report,
    build_reconciliation_report,
    validate_statistics,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATCHES = Path(
    "data/exports/bdfutbol/group2_classification/derived-res01-20261010T102656Z/"
    "normalized/matches.json"
)
DEFAULT_EXPORT_ROOT = Path("data/exports/bdfutbol/group2_statistics")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_offline_capture(
    snapshot: Path, chart_snapshot: Path, access_report: Path
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    access = json.loads(access_report.read_text(encoding="utf-8"))
    chart = json.loads(chart_snapshot.read_text(encoding="utf-8"))
    source_html = snapshot.read_text(encoding="utf-8")
    access_status = access.get("access", {}).get("status", access.get("status"))
    if access_status != "VALID":
        raise ValueError("El informe offline no contiene estado de acceso VALID")
    if access.get("http_status") != 200:
        raise ValueError("La captura offline no registra HTTP 200")
    if access.get("requested_url") != STATISTICS_URL or access.get("final_url") != STATISTICS_URL:
        raise ValueError("La captura no corresponde a la URL exacta de Estadísticas")
    if chart.get("source_url") != STATISTICS_URL:
        raise ValueError("El gráfico no corresponde a la URL de Estadísticas")
    if access.get("capture_id") != chart.get("capture_id"):
        raise ValueError("El HTML y el gráfico tienen capture_id diferentes")
    if access.get("captured_at_utc") != chart.get("captured_at_utc"):
        raise ValueError("El HTML y el gráfico tienen timestamps diferentes")
    if access.get("source_snapshot_sha256") != hashlib.sha256(snapshot.read_bytes()).hexdigest():
        raise ValueError("El hash HTML no coincide con el informe de captura")
    if access.get("chart_snapshot_sha256") != hashlib.sha256(chart_snapshot.read_bytes()).hexdigest():
        raise ValueError("El hash del gráfico no coincide con el informe de captura")
    return source_html, chart, access


def _match_reference(metadata: dict[str, Any], path: Path) -> dict[str, Any]:
    try:
        display_path = path.resolve().relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError:
        display_path = str(path.resolve())
    return {
        "path": display_path,
        "sha256": _sha256(path),
        "source_capture_id": metadata.get("source_capture_id"),
        "source_captured_at_utc": metadata.get("source_captured_at_utc"),
        "counts": json.loads(path.read_text(encoding="utf-8")).get("counts", {}),
        "schema_version": json.loads(path.read_text(encoding="utf-8")).get("schema_version"),
    }


def _align_current_source_matches(
    raw_html: str,
    source_url: str,
    captured_at: datetime,
    match_metadata: dict[str, Any],
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    source_snapshot = Path(str(match_metadata.get("source_snapshot", "")))
    if not source_snapshot.is_absolute():
        source_snapshot = REPOSITORY_ROOT / source_snapshot
    if not source_snapshot.is_file():
        return (), {
            "status": "unavailable",
            "reason": "El snapshot original de Clasificación que aporta el catálogo no está disponible",
        }
    expected_hash = match_metadata.get("source_snapshot_sha256")
    if expected_hash and _sha256(source_snapshot) != expected_hash:
        return (), {
            "status": "unavailable",
            "reason": "El hash del snapshot de Clasificación no coincide con matches.json",
        }
    try:
        classification = parse_classification_page(
            source_snapshot.read_text(encoding="utf-8"),
            base_url=str(match_metadata.get("url")),
        )
        _, source_matches = extract_matches(
            raw_html,
            classification,
            base_url=source_url,
            captured_at=captured_at,
        )
    except ValueError as exc:
        return (), {
            "status": "unavailable",
            "reason": f"No se pudieron comparar los fixtures embebidos: {exc}",
        }
    return source_matches, {"status": "ready"}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--matches",
        type=Path,
        default=Path(os.environ.get("FDH_GROUP2_MATCHES", str(DEFAULT_MATCHES))),
        help="Ruta al dataset existente normalized/matches.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(os.environ.get("FDH_STATISTICS_EXPORT_ROOT", str(DEFAULT_EXPORT_ROOT))),
        help="Raíz de los exports versionados",
    )
    parser.add_argument("--snapshot", type=Path, help="HTML previamente capturado")
    parser.add_argument("--chart-snapshot", type=Path, help="JSON del dataProvider de AmCharts")
    parser.add_argument("--access-report", type=Path, help="Metadatos/hash de la captura offline")
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path(os.environ.get("FDH_BDFUTOL_PROFILE", "~/.football-data-hub-chromium-pure-cdp")).expanduser(),
        help="Perfil para Pure CDP; usado solo en adquisición online",
    )
    parser.add_argument("--browser-executable", type=Path, help="Ejecutable Chromium opcional")
    parser.add_argument("--navigation-timeout-ms", type=int, default=45_000)
    parser.add_argument("--startup-timeout-seconds", type=float, default=35.0)
    parser.add_argument("--no-xvfb", action="store_true", help="No solicitar Xvfb externo")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    offline_args = (args.snapshot, args.chart_snapshot, args.access_report)
    if any(offline_args) and not all(offline_args):
        raise SystemExit("El modo offline requiere --snapshot, --chart-snapshot y --access-report")
    matches_path = args.matches.expanduser().resolve()
    if not matches_path.is_file():
        raise SystemExit(f"No existe el dataset de partidos: {matches_path}")
    dataset_metadata, teams, matches = load_match_dataset(matches_path)
    match_dataset_reference = _match_reference(dataset_metadata, matches_path)
    match_validation = validate_match_set(
        teams, matches, expected_teams=20, expected_rounds=38, fixtures_per_round=10
    )

    if all(offline_args):
        snapshot = args.snapshot.expanduser().resolve()
        chart_path = args.chart_snapshot.expanduser().resolve()
        access_path = args.access_report.expanduser().resolve()
        raw_html, chart_runtime, access = _load_offline_capture(
            snapshot, chart_path, access_path
        )
        capture_id = str(access["capture_id"])
        captured_at = str(access["captured_at_utc"])
        requested_url = str(access["requested_url"])
        final_url = str(access["final_url"])
        http_status = access.get("http_status")
        page_title = str(access.get("page_title", ""))
        browser = access.get("browser", {})
        access_metadata = access
    else:
        try:
            bundle = acquire_statistics_page(
                profile_dir=args.profile.expanduser(),
                browser_executable_path=args.browser_executable,
                startup_timeout_seconds=args.startup_timeout_seconds,
                navigation_timeout_ms=args.navigation_timeout_ms,
                use_xvfb=not args.no_xvfb,
            )
        except StatisticsAcquisitionStopped as exc:
            print(str(exc), file=sys.stderr)
            return 2
        raw_html = bundle.raw_html
        chart_runtime = bundle.chart_runtime
        parsed = bundle.parsed
        capture_id = bundle.capture_id
        captured_at = bundle.captured_at_utc
        requested_url = bundle.requested_url
        final_url = bundle.final_url
        http_status = bundle.http_status
        page_title = bundle.page_title
        browser = bundle.browser
        access_metadata = {
            **bundle.access,
            "status": getattr(bundle.access.get("status"), "value", bundle.access.get("status")),
            "capture_id": capture_id,
            "captured_at_utc": captured_at,
            "browser": browser,
            "html_valid": True,
            "chart_valid": True,
            "source_snapshot_sha256": hashlib.sha256(raw_html.encode("utf-8")).hexdigest(),
        }

    structure_errors = validate_statistics_page_html(raw_html)
    if structure_errors:
        raise SystemExit("HTML rechazado: " + "; ".join(structure_errors))
    parsed = parse_statistics_page(raw_html, chart_runtime, source_url=STATISTICS_URL)
    if (dataset_metadata.get("competition"), dataset_metadata.get("season"), dataset_metadata.get("group")) != (
        parsed.competition, parsed.season, parsed.group
    ):
        raise SystemExit("El dataset de Resultados no corresponde a competición/temporada/grupo")

    context = CompetitionContext(parsed.competition, parsed.season, parsed.group)
    calculated = calculate_competition_statistics(teams, matches, context)
    published_validation = validate_statistics(parsed)
    validation = {
        "schema_version": 1,
        "valid": match_validation["valid"] and published_validation["valid"],
        "statistics_source": published_validation,
        "match_dataset": match_validation,
        "source_page": {
            "http_status": http_status,
            "requested_url": requested_url,
            "final_url": final_url,
            "title": page_title,
            "access_status": access_metadata.get("status"),
            "html_structure_errors": list(structure_errors),
            "chart_points": len(parsed.chart.points),
        },
    }
    if not validation["valid"]:
        raise SystemExit("Validación fallida; no se ha publicado ningún export")

    captured_datetime = datetime.fromisoformat(captured_at)
    current_matches, source_parse_status = _align_current_source_matches(
        raw_html, parsed.source_url, captured_datetime, dataset_metadata
    )
    alignment = (
        build_match_alignment_report(current_matches, matches)
        if source_parse_status["status"] == "ready"
        else source_parse_status
    )
    reconciliation = build_reconciliation_report(
        parsed,
        calculated,
        teams,
        matches,
        match_alignment=alignment,
        statistics_capture={"capture_id": capture_id, "captured_at_utc": captured_at},
        match_dataset=dataset_metadata,
    )
    export_path = export_statistics_capture(
        output_root=(REPOSITORY_ROOT / args.output_root).expanduser()
        if not args.output_root.is_absolute()
        else args.output_root.expanduser(),
        capture_id=capture_id,
        captured_at_utc=captured_at,
        requested_url=requested_url,
        final_url=final_url,
        http_status=http_status,
        page_title=page_title,
        browser=browser,
        raw_html=raw_html,
        chart_runtime=chart_runtime,
        access=access_metadata,
        parsed=parsed,
        report=calculated,
        validation=validation,
        reconciliation=reconciliation,
        match_dataset_reference=match_dataset_reference,
    )
    print(f"Export validado: {export_path}")
    print(
        f"Origen partidos: {len(matches)} fixtures, "
        f"{calculated.statistics.played_matches} disputados; "
        f"alineación con página Estadísticas: {alignment.get('status')}"
    )
    print(
        f"Récords {len(calculated.records.match_records)}; "
        f"rachas {len(calculated.records.streaks)}; "
        f"puntos del gráfico {len(parsed.chart.points)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
