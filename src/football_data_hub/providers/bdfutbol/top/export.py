"""Exportación inmutable por captura de Destacados en JSON y HTML."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .acquisition import EXTRACTOR_VERSION, TopAcquisitionBundle
from .parser import TOP_URL


def create_run_directory(output_root: Path, capture_id: str) -> Path:
    run_dir = output_root.expanduser() / capture_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")


def export_top_capture(
    run_dir: Path,
    bundle: TopAcquisitionBundle,
    *,
    profile_dir: Path | None,
    team_catalog_reference: dict[str, Any],
    capture_timestamp_basis: str = "browser_acquisition_time",
) -> dict[str, Path]:
    """Write a complete versioned capture; all files are create-only."""
    raw_html_path = run_dir / "raw" / "source.html"
    raw_html_path.parent.mkdir(parents=True, exist_ok=True)
    with raw_html_path.open("x", encoding="utf-8") as output:
        output.write(bundle.raw_html)
    source_sha256 = hashlib.sha256(bundle.raw_html.encode("utf-8")).hexdigest()
    metadata = {
        "schema_version": 1,
        "capture_id": bundle.capture_id,
        "source": "BDFutbol",
        "url": TOP_URL,
        "final_url": bundle.access.get("final_url"),
        "page_title": bundle.page_title,
        "competition": "Primera Federación",
        "season": "2026-27",
        "group": "II",
        "section": "top",
        "captured_at_utc": bundle.captured_at_utc,
        "capture_timestamp_basis": capture_timestamp_basis,
        "extractor_version": EXTRACTOR_VERSION,
        "browser": bundle.browser,
        "profile_dir": str(profile_dir.expanduser()) if profile_dir is not None else None,
        "access": bundle.access,
        "source_snapshot_sha256": source_sha256,
        "related_team_catalog": team_catalog_reference,
        "category_options": [
            {"value": value, "label": label}
            for value, label in bundle.parsed.category_options
        ],
        "category_source_counts": bundle.parsed.category_source_counts,
        "chart_matchdays": list(bundle.parsed.chart_matchdays),
        "see_all_available_for_goals": bundle.parsed.see_all_available,
        "foreigners_summary": asdict(bundle.parsed.foreigners_summary),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    metadata_path = run_dir / "metadata" / "capture.json"
    _write_json(metadata_path, metadata)

    players_payload = {
        "schema_version": 1,
        "metadata": _dataset_metadata(metadata),
        "records": [asdict(player) for player in bundle.parsed.players],
    }
    players_path = run_dir / "normalized" / "players.json"
    _write_json(players_path, players_payload)

    rankings_payload = {
        "schema_version": 1,
        "metadata": _dataset_metadata(metadata),
        "category_source_counts": bundle.parsed.category_source_counts,
        "records": [asdict(record) for record in bundle.parsed.rankings],
        "coverage_note": (
            "Goles incluye las diez filas HTML y 97 registros DESTACATS_JS.LG; "
            "las otras categorías contienen las filas expuestas por BDFutbol."
        ),
    }
    rankings_path = run_dir / "normalized" / "rankings.json"
    _write_json(rankings_path, rankings_payload)

    progress_payload = {
        "schema_version": 1,
        "metadata": _dataset_metadata(metadata),
        "matchdays": list(bundle.parsed.chart_matchdays),
        "records": [asdict(record) for record in bundle.parsed.progress],
        "warnings": list(bundle.parsed.warnings),
    }
    progress_path = run_dir / "normalized" / "progress.json"
    _write_json(progress_path, progress_payload)

    players_by_id = {player.player_id: player for player in bundle.parsed.players}
    foreigners_payload = {
        "schema_version": 1,
        "metadata": _dataset_metadata(metadata),
        "summary": asdict(bundle.parsed.foreigners_summary),
        "records": [
            {
                **asdict(players_by_id[item.player_id]),
                "statistics": {
                    key: value
                    for key, value in asdict(item).items()
                    if key != "player_id"
                },
            }
            for item in bundle.parsed.foreigners
        ],
    }
    foreigners_path = run_dir / "normalized" / "foreigners.json"
    _write_json(foreigners_path, foreigners_payload)

    validation_path = run_dir / "validation" / "results.json"
    _write_json(validation_path, bundle.validation)
    access_path = run_dir / "raw" / "access.json"
    _write_json(access_path, {
        "capture_id": bundle.capture_id,
        "captured_at_utc": bundle.captured_at_utc,
        "capture_timestamp_basis": capture_timestamp_basis,
        "requested_url": bundle.access.get("requested_url"),
        "final_url": bundle.access.get("final_url"),
        "title": bundle.page_title,
        "access": bundle.access,
        "browser": bundle.browser,
    })
    return {
        "raw_snapshot": raw_html_path,
        "access_diagnostic": access_path,
        "metadata": metadata_path,
        "players": players_path,
        "rankings": rankings_path,
        "progress": progress_path,
        "foreigners": foreigners_path,
        "validation": validation_path,
    }


def _dataset_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: metadata[key]
        for key in (
            "source", "url", "competition", "season", "group", "section",
            "capture_id", "captured_at_utc", "extractor_version",
            "source_snapshot_sha256", "related_team_catalog",
        )
    }
