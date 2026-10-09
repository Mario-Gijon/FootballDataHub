#!/usr/bin/env python3
"""Validate and parse locally captured match/person/stadium detail pages."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from football_data_hub.audits.entity_inventory import identify_entity_url
from football_data_hub.parsers.individual_entity_pages import (
    ENTITY_PAGE_PARSER_VERSION,
    ENTITY_PAGE_TYPES,
    EntityPageError,
    parse_entity_metadata_file,
)


def _read_metadata(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _candidate_metadata_paths(raw_root: Path) -> list[Path]:
    candidates = []
    for path in sorted(raw_root.rglob("metadata.json")):
        metadata = _read_metadata(path)
        if metadata is None:
            continue
        identities = [
            identify_entity_url(str(metadata.get(key) or ""))
            for key in ("requested_url", "final_url")
        ]
        if any(item and item.get("entity_type") in ENTITY_PAGE_TYPES for item in identities):
            candidates.append(path)
    return candidates


def _source_fingerprint(metadata_paths: list[Path], repo_root: Path) -> str:
    signatures = []
    for metadata_path in metadata_paths:
        metadata_bytes = metadata_path.read_bytes()
        html_path = metadata_path.parent / "rendered.html"
        html_digest = (
            hashlib.sha256(html_path.read_bytes()).hexdigest()
            if html_path.is_file() else None
        )
        try:
            relative_path = metadata_path.resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            relative_path = metadata_path.as_posix()
        signatures.append({
            "metadata_path": relative_path,
            "metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
            "rendered_html_sha256": html_digest,
        })
    payload = json.dumps(signatures, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _json_bytes(value: Any, *, compressed: bool) -> bytes:
    text = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":") if compressed else None,
        indent=None if compressed else 2,
    ) + "\n"
    raw = text.encode("utf-8")
    return gzip.compress(raw, compresslevel=6, mtime=0) if compressed else raw


def _build_output_files(
    records_by_type: dict[str, list[dict[str, Any]]],
    coverage: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    source_fingerprint: str,
) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for entity_type in ENTITY_PAGE_TYPES:
        records = sorted(
            records_by_type[entity_type],
            key=lambda item: (
                item["entity_id"],
                item.get("source", {}).get("captured_at_utc") or "",
                item.get("source", {}).get("snapshot_directory") or "",
            ),
        )
        files[f"{entity_type}_details.json.gz"] = _json_bytes({
            "schema_version": (
                f"football_data_hub.{entity_type}_details_export.v2"
                if entity_type == "match"
                else f"football_data_hub.{entity_type}_details_export.v3"
            ),
            "parser_version": ENTITY_PAGE_PARSER_VERSION,
            "entity_type": entity_type,
            "source_fingerprint": source_fingerprint,
            "entities": records,
        }, compressed=True)
    match_resources = {
        "match_participants": "match_participants",
        "match_coaches": "match_coaches",
        "match_events": "match_events",
        "match_quality": "match_quality",
    }
    for resource_name, record_field in match_resources.items():
        files[f"{resource_name}.json.gz"] = _json_bytes({
            "schema_version": f"football_data_hub.{resource_name}_export.v1",
            "parser_version": ENTITY_PAGE_PARSER_VERSION,
            "source_fingerprint": source_fingerprint,
            "matches": [
                {
                    "match_id": record["entity_id"],
                    "url": record.get("url"),
                    "source": record.get("source", {}),
                    "items": record.get(record_field, {}) if resource_name == "match_quality"
                    else record.get(record_field, []),
                }
                for record in sorted(
                    records_by_type["match"], key=lambda item: item["entity_id"],
                )
            ],
        }, compressed=True)
    semantic_resources = {
        "coach_career": ("coach", "coach_career"),
        "coach_honours": ("coach", "coach_honours"),
        "referee_career": ("referee", "referee_career"),
        "stadium_history": ("stadium", "stadium_history"),
        "stadium_visitors": ("stadium", "stadium_visitors"),
        "stadium_competitions": ("stadium", "stadium_competitions"),
        "stadium_relationships": ("stadium", "stadium_relationships"),
        "stadium_location": ("stadium", "stadium_location"),
    }
    for resource_name, (entity_type, record_field) in semantic_resources.items():
        entities = []
        for record in sorted(
            records_by_type[entity_type],
            key=lambda item: (
                item["entity_id"],
                item.get("source", {}).get("captured_at_utc") or "",
                item.get("source", {}).get("snapshot_directory") or "",
            ),
        ):
            if record_field not in record:
                continue
            entities.append({
                "entity_type": entity_type,
                "entity_id": record["entity_id"],
                "url": record.get("url"),
                "source": record.get("source", {}),
                "coverage": record.get("coverage", {}),
                "resource": record[record_field],
            })
        files[f"{resource_name}.json.gz"] = _json_bytes({
            "schema_version": f"football_data_hub.{resource_name}_export.v1",
            "parser_version": ENTITY_PAGE_PARSER_VERSION,
            "source_fingerprint": source_fingerprint,
            "entities": entities,
        }, compressed=True)
    files["coverage.json.gz"] = _json_bytes({
        "schema_version": "football_data_hub.individual_entity_coverage.v3",
        "parser_version": ENTITY_PAGE_PARSER_VERSION,
        "source_fingerprint": source_fingerprint,
        "snapshots": sorted(coverage, key=lambda item: (
            item["entity_type"], item["entity_id"], item["snapshot_directory"],
        )),
    }, compressed=True)
    files["errors.json.gz"] = _json_bytes({
        "schema_version": "football_data_hub.individual_entity_errors.v2",
        "parser_version": ENTITY_PAGE_PARSER_VERSION,
        "source_fingerprint": source_fingerprint,
        "errors": sorted(errors, key=lambda item: item["metadata_path"]),
    }, compressed=True)
    files["summary.json"] = _json_bytes({
        "schema_version": "football_data_hub.individual_entity_export_summary.v2",
        "parser_version": ENTITY_PAGE_PARSER_VERSION,
        "source_fingerprint": source_fingerprint,
        "valid_snapshot_count": sum(len(items) for items in records_by_type.values()),
        "valid_snapshots_by_type": {
            entity_type: len(records_by_type[entity_type]) for entity_type in ENTITY_PAGE_TYPES
        },
        "rejected_snapshot_count": len(errors),
        "files": sorted(files),
    }, compressed=False)
    return files


def write_immutable_entity_exports(
    *,
    records_by_type: dict[str, list[dict[str, Any]]],
    coverage: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    source_fingerprint: str,
    output_root: Path,
) -> Path:
    """Write a content-versioned directory; an existing version is never overwritten."""
    files = _build_output_files(records_by_type, coverage, errors, source_fingerprint)
    target = output_root / f"parser-{ENTITY_PAGE_PARSER_VERSION}-source-{source_fingerprint}"
    if target.exists():
        existing_names = {path.name for path in target.iterdir() if path.is_file()}
        if existing_names != set(files) or any(
            (target / name).read_bytes() != data for name, data in files.items()
        ):
            raise FileExistsError(f"El export versionado ya existe con contenido distinto: {target}")
        return target

    output_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".entity-pages-", dir=output_root))
    try:
        for name, data in files.items():
            (temporary / name).write_bytes(data)
        try:
            os.rename(temporary, target)
        except FileExistsError:
            if not target.exists() or any(
                not (target / name).is_file() or (target / name).read_bytes() != data
                for name, data in files.items()
            ):
                raise
            if {path.name for path in target.iterdir() if path.is_file()} != set(files):
                raise FileExistsError(f"El export versionado ya existe con contenido distinto: {target}")
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return target


def run_offline_pipeline(*, repo_root: Path, raw_root: Path, output_root: Path) -> tuple[Path, dict[str, Any]]:
    metadata_paths = _candidate_metadata_paths(raw_root)
    source_fingerprint = _source_fingerprint(metadata_paths, repo_root)
    records_by_type = {entity_type: [] for entity_type in ENTITY_PAGE_TYPES}
    coverage: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for metadata_path in metadata_paths:
        try:
            record = parse_entity_metadata_file(metadata_path, repo_root)
        except (EntityPageError, OSError, ValueError) as exc:
            metadata = _read_metadata(metadata_path) or {}
            identified = (
                identify_entity_url(str(metadata.get("final_url") or ""))
                or identify_entity_url(str(metadata.get("requested_url") or ""))
                or {}
            )
            errors.append({
                "entity_type": identified.get("entity_type"),
                "entity_id": identified.get("entity_id"),
                "metadata_path": metadata_path.resolve().relative_to(repo_root.resolve()).as_posix()
                if metadata_path.resolve().is_relative_to(repo_root.resolve()) else metadata_path.as_posix(),
                "status": "REJECTED_NOT_EXPORTED",
                "reason": str(exc),
            })
            continue
        entity_type = record["entity_type"]
        records_by_type[entity_type].append(record)
        coverage.append({
            "entity_type": entity_type,
            "entity_id": record["entity_id"],
            "status": "CAPTURED_VALID",
            "semantic_entity_completeness": "NOT_ASSERTED",
            "access_status": record["source"]["access_status"],
            "http_status": record["source"]["http_status"],
            "url": record["url"],
            "captured_at_utc": record["source"]["captured_at_utc"],
            "snapshot_directory": record["source"]["snapshot_directory"],
            "rendered_html_sha256": record["source"]["rendered_html_sha256"],
            "table_count": record["coverage"]["table_count"],
            "table_row_count": record["coverage"]["table_row_count"],
            "table_cell_count": record["coverage"]["table_cell_count"],
            "related_link_count": record["coverage"]["related_link_count"],
            "image_reference_count": record["coverage"]["image_reference_count"],
            "embedded_json_dataset_count": record["coverage"]["embedded_json_dataset_count"],
            "interpretation_status": record["coverage"]["interpretation_status"],
        })
        if entity_type == "match":
            coverage[-1].update({
                "participant_count": record["coverage"]["participant_count"],
                "coach_count": record["coverage"]["coach_count"],
                "event_count": record["coverage"]["event_count"],
                "event_occurrence_count": record["coverage"]["event_occurrence_count"],
                "event_list_completeness": record["coverage"]["event_list_completeness"],
                "capture_ready_state": record["match_quality"]["capture_ready_state"],
                "published_result_coherence": record["match_quality"][
                    "published_result_coherence"
                ],
            })
        elif entity_type in {"coach", "referee"}:
            career = record[f"{entity_type}_career"]
            coverage[-1].update({
                "career_row_count": len(career["items"]),
                "career_html_js_aligned_row_count": career[
                    "html_js_aligned_row_count"
                ],
                "career_html_js_alignment_status": career[
                    "html_js_alignment_status"
                ],
                "competition_aggregate_count": len(career["competition_aggregates"]),
                "career_completeness": "NOT_ASSERTED",
            })
            if entity_type == "coach":
                coverage[-1]["honour_row_count"] = len(record["coach_honours"])
            else:
                coverage[-1]["individual_appointment_count"] = 0
        elif entity_type == "stadium":
            coverage[-1].update({
                "historical_name_count": record["coverage"]["historical_name_count"],
                "stadium_season_count": record["coverage"]["season_count"],
                "stadium_competition_count": record["coverage"]["competition_count"],
                "stadium_local_club_count": record["coverage"]["local_club_count"],
                "stadium_visitor_count": record["coverage"]["visitor_count"],
                "stadium_chart_item_count": record["coverage"]["chart_item_count"],
                "stadium_explicit_relationship_count": record["coverage"][
                    "explicit_relationship_count"
                ],
                "location_status": record["coverage"]["location_status"],
            })

    output = write_immutable_entity_exports(
        records_by_type=records_by_type,
        coverage=coverage,
        errors=errors,
        source_fingerprint=source_fingerprint,
        output_root=output_root,
    )
    counts = Counter({entity_type: len(records) for entity_type, records in records_by_type.items()})
    return output, {
        "candidate_snapshot_count": len(metadata_paths),
        "valid_snapshots_by_type": dict(counts),
        "rejected_snapshot_count": len(errors),
        "output_directory": output.as_posix(),
        "source_fingerprint": source_fingerprint,
    }


def _resolve(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else root / path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", help="Raíz del repositorio")
    parser.add_argument("--raw-root", default="data/raw/bdfutbol", help="Capturas raw locales")
    parser.add_argument(
        "--output-root",
        default="data/parsed/bdfutbol/entity_detail_pilots",
        help="Directorio base para exports inmutables versionados",
    )
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).expanduser().resolve()
    raw_root = _resolve(repo_root, args.raw_root)
    output_root = _resolve(repo_root, args.output_root)
    output, summary = run_offline_pipeline(
        repo_root=repo_root,
        raw_root=raw_root,
        output_root=output_root,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"Export: {output}")
    return 1 if summary["rejected_snapshot_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
