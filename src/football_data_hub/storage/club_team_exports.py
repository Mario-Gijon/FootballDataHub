"""Atomic JSON/CSV exports for BDFutbol club and team-season snapshots."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from football_data_hub.providers.bdfutbol.club_team import PARSER_VERSION


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_json(path: Path, value: Any) -> None:
    content = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _atomic_write(path, content.encode("utf-8"))


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: tuple[str, ...]) -> None:
    from io import StringIO

    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    _atomic_write(path, output.getvalue().encode("utf-8"))


def _json_cell(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _relative_source(page: dict[str, Any]) -> str | None:
    return page.get("source", {}).get("snapshot_directory")


def _member_exports(parsed_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stats_by_team: dict[str, dict[str, dict[str, Any]]] = {}
    for page in parsed_pages:
        if page.get("entity_type") == "team_season" and page.get("view") == "team_statistics":
            stats_by_team[str(page["entity_id"])] = {
                str(row["player_id"]): row
                for row in page.get("team_data", {}).get("player_statistics", [])
            }
    result = []
    for page in parsed_pages:
        if page.get("entity_type") != "team_season" or page.get("view") != "team_roster":
            continue
        for row in page.get("team_data", {}).get("roster_rows", []):
            stat = stats_by_team.get(str(page["entity_id"]), {}).get(str(row["player_id"]))
            result.append({
                **row,
                "statistics_present": stat is not None,
                "appearances": stat.get("appearances") if stat else None,
                "zero_appearances": stat.get("zero_appearances") if stat else None,
                "statistics_cells": stat.get("raw_cells") if stat else None,
                "team_name": page.get("title"),
                "club_id": page.get("club_id"),
                "roster_snapshot_sha256": page.get("source", {}).get("rendered_html_sha256"),
                "statistics_snapshot_sha256": next((
                    candidate.get("source", {}).get("rendered_html_sha256")
                    for candidate in parsed_pages
                    if candidate.get("entity_type") == "team_season"
                    and candidate.get("entity_id") == page.get("entity_id")
                    and candidate.get("view") == "team_statistics"
                ), None),
            })
    return result


def _relationship_exports(parsed_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found = []
    for page in parsed_pages:
        for item in page.get("relationships", []):
            found.append({
                "source_entity_type": page.get("entity_type"),
                "source_entity_id": page.get("entity_id"),
                "source_view": page.get("view"),
                "source_variant_id": page.get("view_variant", {}).get("variant_id"),
                "source_url": page.get("url"),
                **item,
                "source_snapshot_sha256": page.get("source", {}).get("rendered_html_sha256"),
            })
    return found


def _table_row_exports(parsed_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for page in parsed_pages:
        for table in page.get("tables", []):
            for row in table.get("rows", []):
                rows.append({
                    "entity_type": page.get("entity_type"),
                    "entity_id": page.get("entity_id"),
                    "view": page.get("view"),
                    "variant_id": page.get("view_variant", {}).get("variant_id"),
                    "url": page.get("url"),
                    "table_index": table.get("table_index"),
                    "table_id": table.get("table_id"),
                    "section_heading": table.get("section_heading"),
                    "row_index": row.get("row_index"),
                    "row_kind": row.get("kind"),
                    "row_role": row.get("row_role"),
                    "cell_count": len(row.get("cells", [])),
                    "column_alignment_json": _json_cell(row.get("column_alignment")),
                    "cells_json": _json_cell(row.get("cells", [])),
                    "source_snapshot_sha256": page.get("source", {}).get("rendered_html_sha256"),
                })
    return rows


def _club_people(parsed_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for page in parsed_pages:
        if page.get("entity_type") != "club" or page.get("view") not in {"club_players", "club_coaches"}:
            continue
        for item in page.get("relationships", []):
            if item.get("entity_type") not in {"player", "coach"}:
                continue
            for occurrence in item.get("occurrences", [item]):
                rows.append({
                    "club_id": page.get("entity_id"),
                    "registry_view": page.get("view"),
                    "person_type": item.get("entity_type"),
                    "person_id": item.get("entity_id"),
                    "name_raw": item.get("name"),
                    "url": item.get("url"),
                    "source_table_id": occurrence.get("source_table_id", item.get("source_table_id")),
                    "source_row_index": occurrence.get("source_row_index", item.get("source_row_index")),
                    "source_column_index": occurrence.get("source_column_index", item.get("source_column_index")),
                    "source_snapshot_sha256": page.get("source", {}).get("rendered_html_sha256"),
                })
    return rows


def _page_path(page: dict[str, Any]) -> Path:
    entity_type = str(page["entity_type"])
    entity_id = str(page["entity_id"])
    view = str(page["view"])
    if not all(character.isalnum() or character in "_-" for character in entity_id + view):
        raise ValueError("ID o vista contiene caracteres no seguros para la ruta")
    return Path("pages") / entity_type / entity_id / f"{view}.json"


def _variant_path(page: dict[str, Any]) -> Path:
    entity_type = str(page["entity_type"])
    entity_id = str(page["entity_id"])
    view = str(page["view"])
    variant_id = str(page.get("view_variant", {}).get("variant_id", ""))
    if not variant_id or not all(character.isalnum() or character in "_-" for character in variant_id):
        raise ValueError("ID de variante vacío o contiene caracteres no seguros para la ruta")
    return Path("variants") / entity_type / entity_id / view / f"{variant_id}.json"


def _csv_metrics(coverage: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in coverage.get("views", []):
        rows.append({
            "entity_type": item.get("entity_type"),
            "entity_id": item.get("entity_id"),
            "view": item.get("view"),
            "status": item.get("status"),
            "coverage_status": item.get("coverage_status"),
            "access_status": item.get("access_status"),
            "evidence_status": item.get("evidence_status"),
            "url": item.get("url"),
            "records_observed": item.get("records_observed"),
            "reason": item.get("reason"),
            "pending_json": _json_cell(item.get("pending", [])),
            "snapshot_sha256": item.get("snapshot_sha256"),
        })
    return rows


def _variant_csv_metrics(coverage: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "entity_type": item.get("entity_type"),
            "entity_id": item.get("entity_id"),
            "view": item.get("view"),
            "variant_id": item.get("variant_id"),
            "scope": item.get("scope"),
            "status": item.get("status"),
            "coverage_status": item.get("coverage_status"),
            "access_status": item.get("access_status"),
            "evidence_status": item.get("evidence_status"),
            "url": item.get("url"),
            "records_observed": item.get("records_observed"),
            "snapshot_sha256": item.get("snapshot_sha256"),
            "filter_parameters_json": _json_cell(item.get("filter_parameters", {})),
            "validation_json": _json_cell(item.get("validation")),
            "pending_json": _json_cell(item.get("pending", [])),
        }
        for item in coverage.get("interaction_variants", [])
    ]


def write_club_team_exports(
    *,
    parsed_pages: list[dict[str, Any]],
    variant_pages: list[dict[str, Any]] | None = None,
    coverage: dict[str, Any],
    output_root: Path,
) -> Path:
    """Write page-level JSON plus relation, roster and lossless table-row CSVs."""
    all_pages = [*parsed_pages, *(variant_pages or [])]
    source_key = "|".join(sorted(
        f"{page['url']}:{page.get('source', {}).get('rendered_html_sha256')}"
        for page in all_pages
    ))
    key = hashlib.sha256(f"{source_key}|parser:{PARSER_VERSION}".encode("utf-8")).hexdigest()[:20]
    output_dir = output_root.expanduser().resolve() / f"snapshot-{key}-parser-{PARSER_VERSION}"
    output_dir.mkdir(parents=True, exist_ok=True)

    sources = [
        {
            "entity_type": page.get("entity_type"),
            "entity_id": page.get("entity_id"),
            "view": page.get("view"),
            "variant_id": page.get("view_variant", {}).get("variant_id"),
            "filter_parameters": page.get("view_variant", {}).get("filter_parameters"),
            "url": page.get("url"),
            "access_status": page.get("source", {}).get("access_status"),
            "http_status": page.get("source", {}).get("http_status"),
            "captured_at_utc": page.get("source", {}).get("captured_at_utc"),
            "sha256": page.get("source", {}).get("rendered_html_sha256"),
            "snapshot_directory": _relative_source(page),
        }
        for page in all_pages
    ]
    metadata = {
        "schema_version": "football_data_hub.bdfutbol.club_team_export.v1",
        "extraction_key": key,
        "parser_version": PARSER_VERSION,
        "provider": "BDFutbol",
        "season_scope": "2026/27",
        "source_snapshots": sources,
        "coverage_summary": coverage.get("summary"),
    }
    _write_json(output_dir / "dataset_metadata.json", metadata)
    for page in parsed_pages:
        _write_json(output_dir / _page_path(page), page)
    for page in variant_pages or []:
        _write_json(output_dir / _variant_path(page), page)
    _write_json(output_dir / "resource_catalog.json", {
        "schema_version": "football_data_hub.bdfutbol.club_team.catalog.v1",
        "provider": "BDFutbol",
        "resources": coverage.get("resources", []),
        "interaction_variants": coverage.get("interaction_variants", []),
    })
    _write_json(output_dir / "coverage_matrix.json", coverage)
    _write_csv(
        output_dir / "coverage_matrix.csv",
        _csv_metrics(coverage),
        (
            "entity_type", "entity_id", "view", "status", "coverage_status", "access_status",
            "evidence_status", "url", "records_observed", "reason", "pending_json", "snapshot_sha256",
        ),
    )
    _write_json(output_dir / "interaction_variants.json", {
        **metadata,
        "items": coverage.get("interaction_variants", []),
    })
    _write_csv(
        output_dir / "interaction_variants.csv",
        _variant_csv_metrics(coverage),
        (
            "entity_type", "entity_id", "view", "variant_id", "scope", "status", "coverage_status",
            "access_status", "evidence_status", "url", "records_observed", "snapshot_sha256",
            "filter_parameters_json", "validation_json", "pending_json",
        ),
    )

    members = _member_exports(parsed_pages)
    _write_json(output_dir / "team_members.json", {**metadata, "items": members})
    _write_csv(
        output_dir / "team_members.csv",
        [
            {
                **item,
                "raw_cells_json": _json_cell(item.get("raw_cells")),
                "statistics_cells_json": _json_cell(item.get("statistics_cells")),
            }
            for item in members
        ],
        (
            "team_season_id", "club_id", "player_id", "player_url", "name_raw", "shirt_number_raw",
            "birth_date_raw", "birth_place_raw", "birth_province_raw", "position_raw", "statistics_present",
            "appearances", "zero_appearances", "source_row_index", "roster_snapshot_sha256",
            "statistics_snapshot_sha256", "raw_cells_json", "statistics_cells_json",
        ),
    )

    relationships = _relationship_exports(all_pages)
    _write_json(output_dir / "relationships.json", {**metadata, "items": relationships})
    _write_csv(
        output_dir / "relationships.csv",
        [{**item, "occurrences": _json_cell(item.get("occurrences", []))} for item in relationships],
        (
            "source_entity_type", "source_entity_id", "source_view", "source_variant_id", "source_url",
            "entity_type", "entity_id",
            "name", "url", "source_table_id", "source_table_index", "source_row_index",
            "source_column_index", "source_root_index", "occurrences", "source_snapshot_sha256",
        ),
    )

    club_people = _club_people(parsed_pages)
    _write_json(output_dir / "club_people.json", {**metadata, "items": club_people})
    _write_csv(
        output_dir / "club_people.csv",
        club_people,
        (
            "club_id", "registry_view", "person_type", "person_id", "name_raw", "url",
            "source_table_id", "source_row_index", "source_column_index", "source_snapshot_sha256",
        ),
    )

    table_rows = _table_row_exports(parsed_pages)
    variant_table_rows = _table_row_exports(variant_pages or [])
    _write_csv(
        output_dir / "table_rows.csv",
        table_rows,
        (
            "entity_type", "entity_id", "view", "variant_id", "url", "table_index", "table_id",
            "section_heading", "row_index", "row_kind", "row_role", "cell_count",
            "column_alignment_json", "cells_json", "source_snapshot_sha256",
        ),
    )
    _write_csv(
        output_dir / "variant_table_rows.csv",
        variant_table_rows,
        (
            "entity_type", "entity_id", "view", "variant_id", "url", "table_index", "table_id",
            "section_heading", "row_index", "row_kind", "row_role", "cell_count",
            "column_alignment_json", "cells_json", "source_snapshot_sha256",
        ),
    )
    view_counts = Counter(str(page.get("view")) for page in parsed_pages)
    _write_json(output_dir / "export_summary.json", {
        **metadata,
        "parsed_page_count": len(parsed_pages),
        "variant_page_count": len(variant_pages or []),
        "pages_by_view": dict(sorted(view_counts.items())),
        "team_membership_rows": len(members),
        "relationships": len(relationships),
        "club_people_registry_rows": len(club_people),
        "table_rows": len(table_rows),
        "variant_table_rows": len(variant_table_rows),
    })
    return output_dir
