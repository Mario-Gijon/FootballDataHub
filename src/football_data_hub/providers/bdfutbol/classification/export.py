"""Exportación versionada por captura a JSON y snapshot HTML."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .acquisition import AcquisitionBundle, CLASSIFICATION_URL, EXTRACTOR_VERSION
from .models import ClassificationRequest


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"No se puede serializar {type(value).__name__} a JSON")


def create_run_directory(output_root: Path, capture_id: str) -> Path:
    run_dir = output_root.expanduser() / capture_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        json.dump(data, output, ensure_ascii=False, indent=2, default=_json_default)
        output.write("\n")


def write_access_failure(run_dir: Path, assessment: dict[str, Any]) -> Path:
    path = run_dir / "metadata" / "access_failure.json"
    _write_json(path, assessment)
    return path


def export_acquisition(
    run_dir: Path,
    bundle: AcquisitionBundle,
    request: ClassificationRequest,
    *,
    browser: str,
    profile_dir: Path,
) -> dict[str, Path]:
    """Write every artifact under one unique run directory; never overwrite."""
    raw_path = run_dir / "raw" / "source.html"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    with raw_path.open("x", encoding="utf-8") as output:
        output.write(bundle.raw_html)

    metadata = {
        "schema_version": 1,
        "capture_id": bundle.capture_id,
        "source": "BDFutbol",
        "url": CLASSIFICATION_URL,
        "final_url": bundle.access.get("final_url"),
        "page_title": bundle.page_title,
        "competition": "Primera Federación",
        "season": "2026-27",
        "group": "II",
        "captured_at_utc": bundle.captured_at_utc,
        "extractor_version": EXTRACTOR_VERSION,
        "browser": browser,
        "browser_executable": bundle.browser_executable,
        "profile_dir": str(profile_dir.expanduser()),
        "virtual_display": True,
        "access": bundle.access,
        "requested_filters": asdict(request),
        "applied_filters": asdict(bundle.context),
        "played_matchdays_in_source": bundle.parsed.played_matchdays,
    }
    metadata_path = run_dir / "metadata" / "capture.json"
    _write_json(metadata_path, metadata)

    classification = {
        "schema_version": 1,
        "metadata": {
            key: metadata[key]
            for key in (
                "source",
                "url",
                "competition",
                "season",
                "group",
                "capture_id",
                "captured_at_utc",
                "extractor_version",
            )
        },
        "context": asdict(bundle.context),
        "standings": [asdict(row) for row in bundle.parsed.standings],
    }
    classification_path = run_dir / "normalized" / "classification.json"
    _write_json(classification_path, classification)

    progress = {
        "schema_version": 1,
        "metadata": classification["metadata"],
        "series_context": asdict(bundle.parsed.progress_context),
        "table_context_at_capture": asdict(bundle.context),
        "records": [asdict(row) for row in bundle.parsed.progress],
        "warnings": list(bundle.parsed.progress_warnings),
    }
    progress_path = run_dir / "normalized" / "progress.json"
    _write_json(progress_path, progress)

    validation_path = run_dir / "validation" / "results.json"
    _write_json(validation_path, bundle.validation)
    return {
        "raw_snapshot": raw_path,
        "metadata": metadata_path,
        "classification": classification_path,
        "progress": progress_path,
        "validation": validation_path,
    }
