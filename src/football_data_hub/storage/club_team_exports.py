"""Atomic JSON/CSV exports for BDFutbol club and team-season snapshots."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

from football_data_hub.providers.bdfutbol.club_team import PARSER_VERSION
from football_data_hub.parsers.match_status import normalized_match_state
from football_data_hub.parsers.club_team_sports import build_club_team_sports_data


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


def _write_json(path: Path, value: Any, *, compressed: bool = False) -> None:
    content = json.dumps(
        value,
        ensure_ascii=False,
        indent=None if compressed else 2,
        separators=(",", ":") if compressed else None,
        sort_keys=True,
    ) + "\n"
    data = content.encode("utf-8")
    _atomic_write(path, gzip.compress(data, compresslevel=6, mtime=0) if compressed else data)


def _write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fields: tuple[str, ...],
    *,
    compressed: bool = False,
) -> None:
    from io import StringIO

    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    data = output.getvalue().encode("utf-8")
    _atomic_write(path, gzip.compress(data, compresslevel=6, mtime=0) if compressed else data)


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
    compact: bool = False,
    processing_seconds: float | None = None,
    include_table_csv: bool | None = None,
    competition_matches: list[dict[str, Any]] | None = None,
    competition_selection: dict[str, Any] | None = None,
) -> Path:
    """Write lossless JSON/CSV exports; compact mode uses deterministic gzip files."""
    write_started = time.perf_counter()
    include_table_csv = not compact if include_table_csv is None else include_table_csv
    all_pages = [*parsed_pages, *(variant_pages or [])]
    source_key = "|".join(sorted(
        f"{page['url']}:{page.get('source', {}).get('rendered_html_sha256')}"
        for page in all_pages
    ))
    competition_source_key = "|".join(sorted(
        ":".join(str(item.get(field) or "") for field in (
            "_competition_extraction_key", "match_id", "result_status", "date", "home_goals", "away_goals",
            "_captured_at_utc",
        ))
        for item in (competition_matches or [])
    ))
    competition_selection_key = json.dumps(
        competition_selection or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    storage_profile = f"gzip-table-csv-{include_table_csv}" if compact else "legacy"
    key = hashlib.sha256(
        f"{source_key}|competition:{competition_source_key}|selection:{competition_selection_key}|parser:{PARSER_VERSION}|coverage:{coverage.get('schema_version')}|storage:{storage_profile}".encode("utf-8")
    ).hexdigest()[:20]
    base_output = output_root.expanduser().resolve()
    if compact:
        base_output = base_output / "compact"
    output_dir = base_output / f"snapshot-{key}-parser-{PARSER_VERSION}"
    output_dir.mkdir(parents=True, exist_ok=True)

    def output_path(path: Path) -> Path:
        return path.with_name(f"{path.name}.gz") if compact else path

    def write_json(path: Path, value: Any) -> None:
        _write_json(output_path(path), value, compressed=compact)

    def write_csv(path: Path, rows: list[dict[str, Any]], fields: tuple[str, ...]) -> None:
        _write_csv(output_path(path), rows, fields, compressed=compact)

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
        "schema_version": "football_data_hub.bdfutbol.club_team_export.v2",
        "extraction_key": key,
        "parser_version": PARSER_VERSION,
        "provider": "BDFutbol",
        "season_scope": "2026/27",
        "source_snapshots": sources,
        "competition_crosscheck_source": {
            "selection": competition_selection,
            "extraction_keys": sorted({
                str(item["_competition_extraction_key"])
                for item in (competition_matches or []) if item.get("_competition_extraction_key")
            }),
            "snapshot_timestamps_utc": sorted({
                str(item["_captured_at_utc"])
                for item in (competition_matches or []) if item.get("_captured_at_utc")
            }),
            "multiple_extractions_detected": len({
                str(item.get("_competition_extraction_key"))
                for item in (competition_matches or []) if item.get("_competition_extraction_key")
            }) > 1,
            "fixtures_loaded": len(competition_matches or []),
            "played_fixtures_loaded": sum(
                normalized_match_state(item) == "played" for item in (competition_matches or [])
            ),
            "normalized_state_counts": {
                state: sum(normalized_match_state(item) == state for item in (competition_matches or []))
                for state in ("played", "scheduled", "unresolved", "inconsistent")
            },
        } if competition_matches is not None or competition_selection is not None else None,
        "coverage_summary": coverage.get("summary"),
        "storage_format": {
            "compression": "gzip" if compact else "none",
            "lossless": True,
            "json_suffix": ".json.gz" if compact else ".json",
            "csv_suffix": ".csv.gz" if compact else ".csv",
            "table_rows_csv_included": include_table_csv,
            "compatibility_note": "Uncompressed exports remain the default; compact exports use standard gzip readers.",
        },
    }
    write_json(output_dir / "dataset_metadata.json", metadata)
    for page in parsed_pages:
        write_json(output_dir / _page_path(page), page)
    for page in variant_pages or []:
        write_json(output_dir / _variant_path(page), page)
    write_json(output_dir / "resource_catalog.json", {
        "schema_version": "football_data_hub.bdfutbol.club_team.catalog.v1",
        "provider": "BDFutbol",
        "resources": coverage.get("resources", []),
        "interaction_variants": coverage.get("interaction_variants", []),
    })
    write_json(output_dir / "coverage_matrix.json", coverage)
    write_csv(
        output_dir / "coverage_matrix.csv",
        _csv_metrics(coverage),
        (
            "entity_type", "entity_id", "view", "status", "coverage_status", "access_status",
            "evidence_status", "url", "records_observed", "reason", "pending_json", "snapshot_sha256",
        ),
    )
    write_json(output_dir / "interaction_variants.json", {
        **metadata,
        "items": coverage.get("interaction_variants", []),
    })
    write_csv(
        output_dir / "interaction_variants.csv",
        _variant_csv_metrics(coverage),
        (
            "entity_type", "entity_id", "view", "variant_id", "scope", "status", "coverage_status",
            "access_status", "evidence_status", "url", "records_observed", "snapshot_sha256",
            "filter_parameters_json", "validation_json", "pending_json",
        ),
    )

    members = _member_exports(parsed_pages)
    write_json(output_dir / "team_members.json", {**metadata, "items": members})
    write_csv(
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
    write_json(output_dir / "relationships.json", {**metadata, "items": relationships})
    write_csv(
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
    write_json(output_dir / "club_people.json", {**metadata, "items": club_people})
    write_csv(
        output_dir / "club_people.csv",
        club_people,
        (
            "club_id", "registry_view", "person_type", "person_id", "name_raw", "url",
            "source_table_id", "source_row_index", "source_column_index", "source_snapshot_sha256",
        ),
    )

    table_rows_count = sum(
        len(table.get("rows", [])) for page in parsed_pages for table in page.get("tables", [])
    )
    variant_table_rows_count = sum(
        len(table.get("rows", []))
        for page in variant_pages or []
        for table in page.get("tables", [])
    )
    if include_table_csv:
        table_rows = _table_row_exports(parsed_pages)
        variant_table_rows = _table_row_exports(variant_pages or [])
        write_csv(
            output_dir / "table_rows.csv",
            table_rows,
            (
                "entity_type", "entity_id", "view", "variant_id", "url", "table_index", "table_id",
                "section_heading", "row_index", "row_kind", "row_role", "cell_count",
                "column_alignment_json", "cells_json", "source_snapshot_sha256",
            ),
        )
        write_csv(
            output_dir / "variant_table_rows.csv",
            variant_table_rows,
            (
                "entity_type", "entity_id", "view", "variant_id", "url", "table_index", "table_id",
                "section_heading", "row_index", "row_kind", "row_role", "cell_count",
                "column_alignment_json", "cells_json", "source_snapshot_sha256",
            ),
        )
    view_counts = Counter(str(page.get("view")) for page in parsed_pages)
    write_json(output_dir / "export_summary.json", {
        **metadata,
        "parsed_page_count": len(parsed_pages),
        "variant_page_count": len(variant_pages or []),
        "pages_by_view": dict(sorted(view_counts.items())),
        "team_membership_rows": len(members),
        "relationships": len(relationships),
        "club_people_registry_rows": len(club_people),
        "table_rows": table_rows_count,
        "variant_table_rows": variant_table_rows_count,
        "table_rows_csv_included": include_table_csv,
        "processing_seconds": (processing_seconds or 0.0) + (time.perf_counter() - write_started),
    })

    sports = build_club_team_sports_data(all_pages, competition_matches)
    sports_dir = output_dir / "sports"
    sports_metadata = {
        "schema_version": sports["schema_version"],
        "extraction_key": key,
        "parser_version": PARSER_VERSION,
        "season_scope": "2026/27",
        "source_export": output_dir.as_posix(),
    }

    def write_sports_json(name: str, items: Any) -> None:
        write_json(sports_dir / f"{name}.json", {**sports_metadata, "items": items})

    def write_sports_csv(name: str, items: list[dict[str, Any]], fields: tuple[str, ...]) -> None:
        csv_items = [
            {
                **item,
                "columns_json": _json_cell(item.get("columns")),
                "source_values_raw_json": _json_cell(item.get("source_values_raw")),
                "source_field_map_json": _json_cell(item.get("source_field_map")),
                "source_club_ids_json": _json_cell(item.get("source_club_ids")),
                "unmapped_values_raw_json": _json_cell(item.get("unmapped_values_raw")),
                "differing_fields_between_club_sources_json": _json_cell(item.get("differing_fields_between_club_sources")),
                "seasons_observed_json": _json_cell(item.get("seasons_observed")),
                "source_observations_json": _json_cell(item.get("source_observations")),
                "acquisition_context_json": _json_cell(item.get("acquisition_context")),
                "competition_fields_json": _json_cell(item.get("competition_fields")),
                "team_season_identity_evidence_json": _json_cell(item.get("team_season_identity_evidence")),
                "aggregate_expected_json": _json_cell(item.get("aggregate_expected")),
                "outcomes_observed_json": _json_cell(item.get("outcomes_observed")),
                "checks_json": _json_cell(item.get("checks")),
                "fields_json": _json_cell(item.get("fields")),
                "different_fields_json": _json_cell(item.get("different_fields")),
                "headers_original_json": _json_cell(item.get("headers_original")),
                "match_variant_snapshot_timestamps_utc_json": _json_cell(item.get("match_variant_snapshot_timestamps_utc")),
                "competition_match_ids_expected_json": _json_cell(item.get("competition_match_ids_expected")),
                "competition_match_ids_observed_json": _json_cell(item.get("competition_match_ids_observed")),
                "nonempty_cells_by_header_json": _json_cell(item.get("nonempty_cells_by_header")),
                "occurrences_json": _json_cell(item.get("occurrences")),
                "record_json": _json_cell(item.get("record")),
                "explanation": item.get("explanation"),
            }
            for item in items
        ]
        write_csv(sports_dir / f"{name}.csv", csv_items, fields)

    write_sports_json("rosters", sports["rosters"])
    write_sports_csv(
        "rosters", sports["rosters"],
        ("team_season_id", "club_id", "player_id", "player_url", "name_raw", "shirt_number_raw", "position_raw",
         "birth_date_raw", "birth_place_raw", "birth_province_raw", "statistics_present", "appearances_raw",
         "appearances", "zero_appearances", "source_row_index", "url", "snapshot_directory", "snapshot_sha256", "captured_at_utc"),
    )
    write_sports_json("player_statistics", sports["player_statistics"])
    write_sports_csv(
        "player_statistics", sports["player_statistics"],
        ("team_season_id", "player_id", "player_url", "source_row_index", "appearances_raw", "appearances",
         "zero_appearances", "url", "snapshot_directory", "snapshot_sha256", "captured_at_utc", "headers_original", "columns_json"),
    )
    write_sports_json("coaches_current", sports["coaches_current"])
    write_sports_csv(
        "coaches_current", sports["coaches_current"],
        ("team_season_id", "club_id", "coach_id", "coach_url", "name_raw", "birth_date_raw", "birth_place_raw",
         "birth_province_raw", "source_row_index", "url", "snapshot_directory", "snapshot_sha256", "captured_at_utc"),
    )
    write_sports_json("movement_references", sports["movement_references"])
    write_sports_csv(
        "movement_references", sports["movement_references"],
        ("team_season_id", "entity_type", "entity_id", "name_raw", "url", "source_table_id", "source_row_index",
         "occurrences_json", "snapshot_directory", "snapshot_sha256", "captured_at_utc"),
    )
    write_sports_json("matches_played", sports["matches_played"])
    write_sports_csv(
        "matches_played", sports["matches_played"],
        ("match_id", "match_url", "group", "date", "date_raw", "home_team_season_id", "away_team_season_id",
         "home_team_name_raw", "away_team_name_raw", "home_goals", "away_goals", "score_raw", "round_raw",
         "competition_match_present", "source_observation_count", "source_club_ids", "source_team_season_ids",
         "source_snapshot_sha256", "captured_at_utc", "competition_comparison"),
    )
    write_sports_json("match_observations", sports["match_observations"])
    write_sports_json("embedded_match_observations", sports["embedded_match_observations"])
    write_sports_csv(
        "embedded_match_observations",
        sports["embedded_match_observations"],
        (
            "match_id", "match_url", "season_raw", "competition_code_raw", "date_raw", "date",
            "home_team_name_raw", "home_goals_raw", "away_goals_raw", "away_team_name_raw",
            "home_club_id_raw", "away_club_id_raw", "source_club_id", "source_team_season_id",
            "source_club_is_home", "source_club_home_flag_raw", "source_club_result_code_raw",
            "source_club_result_validation", "source_club_result_from_score", "referee_id_raw",
            "round_label_raw", "round_code_raw", "source_club_yellow_cards_raw",
            "source_club_red_cards_raw", "source_record_index", "source_kind", "url",
            "snapshot_directory", "snapshot_sha256", "captured_at_utc", "source_values_raw_json",
            "source_field_map_json", "unmapped_values_raw_json",
        ),
    )
    write_sports_json("matches_from_embedded_data", sports["matches_from_embedded_data"])
    write_sports_csv(
        "matches_from_embedded_data",
        sports["matches_from_embedded_data"],
        (
            "match_id", "match_url", "season_raw", "competition_code_raw", "date_raw", "date",
            "home_team_name_raw", "home_goals_raw", "away_goals_raw", "away_team_name_raw",
            "home_club_id_raw", "away_club_id_raw", "match_season_raw", "group",
            "home_team_season_id", "away_team_season_id", "team_season_identity_status",
            "team_season_identity_evidence_json", "competition_fields_json",
            "source_observation_count", "source_club_ids",
            "source_club_ids_json", "differing_fields_between_club_sources_json", "source_values_raw_json",
            "source_observations_json", "acquisition_context_json",
        ),
    )
    write_sports_json("duplicate_embedded_matches", sports["duplicate_embedded_matches"])
    write_sports_json("embedded_match_coverage_by_club", sports["embedded_match_coverage_by_club"])
    write_sports_csv(
        "embedded_match_coverage_by_club",
        sports["embedded_match_coverage_by_club"],
        (
            "club_id", "team_season_id", "source_parse_status", "source_records_reported",
            "source_observations_parsed", "unique_match_ids", "records_without_match_id",
            "seasons_observed_json", "current_season_1rf_observations", "url", "snapshot_directory",
            "snapshot_sha256", "captured_at_utc",
        ),
    )
    write_json(
        sports_dir / "embedded_match_competition_crosscheck.json",
        {**sports_metadata, **sports["embedded_match_competition_crosscheck"]},
    )
    write_sports_json(
        "embedded_match_filtered_table_card_crosscheck",
        sports["embedded_match_filtered_table_card_crosscheck"],
    )
    write_sports_json("coverage_by_club", sports["coverage_by_club"])
    write_sports_csv(
        "coverage_by_club", sports["coverage_by_club"],
        ("club_id", "team_season_id", "all_match_variant_captured", "matches_played_observed", "matches_unscored_observed",
         "match_rows_observed", "aggregate_expected_json", "aggregate_snapshot_captured_at_utc",
         "match_variant_snapshot_timestamps_utc_json", "outcomes_observed_json", "competition_matches_expected",
         "competition_match_sets_equal", "checks_json", "status"),
    )
    write_sports_json("coverage_by_team", sports["coverage_by_team"])
    write_sports_csv(
        "coverage_by_team", sports["coverage_by_team"],
        ("team_season_id", "roster_players", "statistics_players", "roster_without_statistics", "statistics_without_roster",
         "zero_appearance_players", "all_statistics_columns_preserved"),
    )
    write_sports_json("tracking_variants", sports["tracking_variants"])
    write_sports_json("tracking_player_rows", sports["tracking_player_rows"])
    write_sports_csv(
        "tracking_player_rows", sports["tracking_player_rows"],
        ("team_season_id", "player_id", "player_name_raw", "source_row_index", "columns_json", "url",
         "snapshot_directory", "snapshot_sha256", "captured_at_utc"),
    )
    write_sports_json("duplicate_matches", sports["duplicate_matches"])
    write_sports_json("duplicate_player_memberships", sports["duplicate_player_memberships"])
    write_sports_json("multi_coach_teams", sports["multi_coach_teams"])
    write_sports_json("incidents", sports["incidents"])
    write_sports_csv(
        "incidents", sports["incidents"],
        ("code", "severity", "match_id", "club_id", "team_season_id", "fields", "fields_json", "different_fields_json", "captured_at_utc", "explanation", "checks_json"),
    )
    write_sports_json("summary", sports["summary"])
    return output_dir
