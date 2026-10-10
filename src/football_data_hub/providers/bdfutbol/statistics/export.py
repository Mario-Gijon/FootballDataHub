"""Exportación versionada de evidencia y agregados de Estadísticas."""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import tempfile
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from football_data_hub.domain.statistics.engine import STATISTICS_ENGINE_VERSION
from football_data_hub.domain.statistics.models import CompetitionStatisticsReport

from .models import ParsedBDFutbolStatistics


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"No se puede serializar {type(value).__name__} a JSON")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, default=_json_default)
        stream.write("\n")


def export_statistics_capture(
    *,
    output_root: Path,
    capture_id: str,
    captured_at_utc: str,
    requested_url: str,
    final_url: str,
    http_status: int | None,
    page_title: str,
    browser: dict[str, Any],
    raw_html: str,
    chart_runtime: dict[str, Any],
    access: dict[str, Any],
    parsed: ParsedBDFutbolStatistics,
    report: CompetitionStatisticsReport,
    validation: dict[str, Any],
    reconciliation: dict[str, Any],
    match_dataset_reference: dict[str, Any],
) -> Path:
    """Escribe una captura nueva sin tocar exports previos.

    La escritura se prepara en un directorio temporal y se publica mediante
    rename al final. Cada fichero se abre en modo exclusivo.
    """
    if not capture_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for char in capture_id):
        raise ValueError("capture_id contiene caracteres no admitidos")
    output_root.mkdir(parents=True, exist_ok=True)
    destination = output_root / capture_id
    if destination.exists():
        raise FileExistsError(f"La captura ya existe: {destination}")
    staging = Path(tempfile.mkdtemp(prefix=f".{capture_id}.", dir=output_root))
    try:
        (staging / "raw").mkdir()
        html_digest = hashlib.sha256(raw_html.encode("utf-8")).hexdigest()
        with (staging / "raw" / "source.html").open("x", encoding="utf-8") as stream:
            stream.write(raw_html)
        _write_json(staging / "raw" / "chart_data_provider.json", chart_runtime)
        chart_digest = hashlib.sha256(
            (staging / "raw" / "chart_data_provider.json").read_bytes()
        ).hexdigest()
        portable_access = {
            **access,
            "source_snapshot": "raw/source.html",
            "chart_snapshot": "raw/chart_data_provider.json",
            "source_snapshot_sha256": html_digest,
            "chart_snapshot_sha256": chart_digest,
        }
        _write_json(staging / "raw" / "access.json", portable_access)

        capture_metadata = {
            "schema_version": 1,
            "source": "BDFutbol",
            "capture_id": capture_id,
            "captured_at_utc": captured_at_utc,
            "requested_url": requested_url,
            "final_url": final_url,
            "http_status": http_status,
            "page_title": page_title,
            "source_html_sha256": html_digest,
            "chart_data_provider_sha256": chart_digest,
            "competition": parsed.competition,
            "season": parsed.season,
            "group": parsed.group,
            "extractor_version": "0.1.0",
            "browser": browser,
            "match_dataset": match_dataset_reference,
        }
        _write_json(staging / "metadata" / "capture.json", capture_metadata)

        _write_json(
            staging / "normalized" / "exclusive_statistics.json",
            {
                "schema_version": 1,
                "source": "BDFutbol",
                "capture_id": capture_id,
                "captured_at_utc": captured_at_utc,
                "competition": parsed.competition,
                "season": parsed.season,
                "group": parsed.group,
                "scope": "competition",
                "items": {
                    "penalties": {
                        **asdict(parsed.exclusive_penalties),
                        "unit": "penalties",
                        "scope": "competition_total",
                        "source_url": parsed.source_url,
                    }
                },
            },
        )
        _write_json(
            staging / "normalized" / "derived_statistics.json",
            {
                "schema_version": 1,
                "kind": "derived_from_matches",
                "derived_at_utc": datetime.now(timezone.utc).isoformat(),
                "algorithm": "football_data_hub.domain.statistics.engine",
                "algorithm_version": STATISTICS_ENGINE_VERSION,
                "match_dataset": match_dataset_reference,
                "statistics": asdict(report.statistics),
                "records": asdict(report.records),
                "methodology": {
                    "played_match_policy": "only status=played contributes to totals",
                    "unplayed_match_policy": "excluded; not interpreted as 0-0 or draw",
                    "unknown_card_policy": "total is null if any played match lacks either team value",
                    "streak_order": "matchday, source_match_date, then numeric/source match_id",
                    "streak_gap_policy": "unplayed and incomplete rows are skipped and do not break a run; source equivalence with postponed matches is unverified",
                    "tie_policy": "retain every calculated tie; no source tie-break is inferred",
                    "penalties": "not derived or allocated to individual matches",
                },
            },
        )
        _write_json(staging / "validation" / "results.json", validation)
        _write_json(staging / "validation" / "reconciliation.json", reconciliation)
        try:
            os.rename(staging, destination)
        except FileExistsError:
            raise FileExistsError(f"La captura ya existe: {destination}") from None
        return destination
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
