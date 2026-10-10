"""Exportación inmutable de capturas de Árbitros."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .acquisition import EXTRACTOR_VERSION, RefereeAcquisitionBundle
from .models import ParsedReferees
from .parser import REFEREES_URL


def create_run_directory(output_root: Path, capture_id: str) -> Path:
    run_dir = output_root.expanduser() / capture_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Tipo no serializable a JSON: {type(value).__name__}")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2, default=_json_default)
        output.write("\n")


def export_referee_capture(
    run_dir: Path,
    bundle: RefereeAcquisitionBundle,
    parsed: ParsedReferees,
    *,
    validation: dict[str, Any],
    match_reference_report: dict[str, Any],
) -> dict[str, Path]:
    """Escribe una captura completa. La creación es exclusiva, nunca sobrescribe."""
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    scope_files: dict[str, Path] = {}
    scope_metadata: dict[str, dict[str, Any]] = {}
    for page in bundle.pages:
        filename = f"source_{page.scope}.html"
        path = raw_dir / filename
        with path.open("x", encoding="utf-8") as output:
            output.write(page.raw_html)
        digest = hashlib.sha256(page.raw_html.encode("utf-8")).hexdigest()
        scope_files[page.scope] = path
        scope_metadata[page.scope] = {
            "scope": page.scope,
            "file": f"raw/{filename}",
            "requested_url": page.requested_url,
            "final_url": page.final_url,
            "http_status": page.http_status,
            "page_title": page.page_title,
            "captured_at_utc": page.captured_at_utc,
            "access": page.access,
            "source_snapshot_sha256": digest,
        }

    match_reference = match_reference_report.get("reference_dataset", {})
    metadata = {
        "schema_version": 1,
        "capture_id": bundle.capture_id,
        "parent_capture_id": bundle.parent_capture_id,
        "source": "BDFutbol",
        "url": REFEREES_URL,
        "final_url": scope_metadata.get("all", {}).get("final_url"),
        "competition": "Primera Federación",
        "season": "2026-27",
        "group": "II",
        "section": "referees",
        "captured_at_utc": bundle.captured_at_utc,
        "capture_timestamp_basis": "each scope timestamp follows HTML serialization; captured_at_utc is the first scope",
        "extractor_version": EXTRACTOR_VERSION,
        "browser": bundle.browser,
        "profile_dir": str(bundle.profile_dir.expanduser()) if bundle.profile_dir else None,
        "scope_captures": scope_metadata,
        "scope_counts": parsed.scope_counts,
        "referee_count": len(parsed.referees),
        "statistics_count": len(parsed.statistics),
        "related_match_dataset": match_reference,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    metadata_path = run_dir / "metadata" / "capture.json"
    _write_json(metadata_path, metadata)

    access_path = raw_dir / "access.json"
    _write_json(access_path, {
        "capture_id": bundle.capture_id,
        "captured_at_utc": bundle.captured_at_utc,
        "browser": bundle.browser,
        "scope_captures": scope_metadata,
    })

    referees_path = run_dir / "normalized" / "referees.json"
    _write_json(referees_path, {
        "schema_version": 1,
        "metadata": _dataset_metadata(metadata),
        "records": [asdict(referee) for referee in parsed.referees],
    })
    statistics_path = run_dir / "normalized" / "statistics.json"
    _write_json(statistics_path, {
        "schema_version": 1,
        "metadata": _dataset_metadata(metadata),
        "records": [asdict(item) for item in parsed.statistics],
    })
    options_path = run_dir / "normalized" / "filter_options.json"
    _write_json(options_path, {
        "schema_version": 1,
        "metadata": _dataset_metadata(metadata),
        "season_options": [asdict(option) for option in parsed.season_options],
        "group_options": [asdict(option) for option in parsed.group_options],
        "supported_season": "2026-27",
    })
    validation_path = run_dir / "validation" / "results.json"
    _write_json(validation_path, validation)
    relation_path = run_dir / "validation" / "match_reference.json"
    _write_json(relation_path, match_reference_report)
    return {
        "raw_all": scope_files["all"],
        "raw_group1": scope_files["group1"],
        "raw_group2": scope_files["group2"],
        "access_diagnostic": access_path,
        "metadata": metadata_path,
        "referees": referees_path,
        "statistics": statistics_path,
        "filter_options": options_path,
        "validation": validation_path,
        "match_reference": relation_path,
    }


def _dataset_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: metadata[key]
        for key in (
            "source", "url", "competition", "season", "group", "section",
            "capture_id", "captured_at_utc", "extractor_version",
            "related_match_dataset", "scope_counts",
        )
    }
