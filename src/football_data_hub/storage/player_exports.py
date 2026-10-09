"""Immutable compact exports for offline BDFutbol player parsing."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from football_data_hub.parsers.player_pages import PLAYER_PARSER_VERSION, PLAYER_SCHEMA_VERSION


def _json_bytes(value: Any) -> bytes:
    raw = (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    return gzip.compress(raw, compresslevel=6, mtime=0)


def _csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    from io import StringIO

    fields = list(dict.fromkeys(key for row in rows for key in row))
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({
            key: value if isinstance(value, (str, int, float)) or value is None
            else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for key, value in row.items()
        })
    return gzip.compress(stream.getvalue().encode("utf-8"), compresslevel=6, mtime=0)


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _wrapper(name: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": PLAYER_SCHEMA_VERSION,
        "parser_version": PLAYER_PARSER_VERSION,
        "resource": name,
        "items": items,
    }


def _coverage_rows(
    acquisition_coverage: list[dict[str, Any]],
    parsed_pages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    parsed = {
        (str(page["player_id"]), str(page["view"])): page
        for page in parsed_pages
    }
    result = []
    for original in acquisition_coverage:
        row = dict(original)
        page = parsed.get((str(row["player_id"]), str(row["view"])))
        if page:
            page_parse_status = page["coverage"].get("parse_status", "PARSED")
            row["parse_status"] = page_parse_status
            row["normalized_fields_status"] = "PARTIAL_NORMALIZATION"
            row["raw_only_fields_status"] = "RAW_FIELDS_PRESERVED"
            row["filters_status"] = "NOT_TESTED_OFFLINE_SNAPSHOT_ONLY"
            row["coverage_status"] = (
                "CAPTURED_AND_PARSED" if page_parse_status == "PARSED"
                else "CAPTURED_WITH_PARTIAL_TABLE_SET"
            )
            row["fields_normalized"] = _normalized_field_names(page)
            row["fields_preserved_raw"] = _raw_field_names(page)
            row["fields_not_found_in_snapshot"] = _missing_field_names(page)
            row["filters_pending"] = [
                control.get("id") or control.get("name")
                for control in page.get("filter_controls", [])
            ]
            row["parsed_source"] = page["source"]
        else:
            row["fields_normalized"] = []
            row["fields_preserved_raw"] = []
            row["fields_not_found_in_snapshot"] = []
            row["filters_pending"] = []
            row["fields_not_investigated"] = [
                "vista no capturada; no se puede clasificar presencia/ausencia de campos"
            ]
        result.append(row)
    return result


def _normalized_field_names(page: dict[str, Any]) -> list[str]:
    view = page["view"]
    if view == "profile":
        profile = page["view_data"]
        names = []
        for key in ("birth_date_iso", "age_as_displayed_years", "height_cm"):
            if profile.get(key) is not None:
                names.append(key)
        for label, key in (
            ("Nombre completo", "full_name_raw"),
            ("Lugar de nacimiento", "birth_place_raw"),
            ("País de nacimiento", "country_of_birth_raw"),
            ("Demarcación", "position_raw"),
        ):
            if profile.get(key):
                names.append(label)
        return names
    if view == "statistics":
        return [
            "numeric_cell_values_only (no semantic expansion of abbreviations)"
        ]
    if view == "matches":
        return ["numeric aggregate cell values only"]
    if view == "rivals":
        return ["source entity IDs parsed from related URLs", "numeric cell values"]
    return []


def _raw_field_names(page: dict[str, Any]) -> list[str]:
    if page["view"] == "profile":
        return sorted({
            key for key, value in page["view_data"].get("personal_fields", {}).items()
            if value is not None
        })
    return sorted({
        str(column.get("header_original") or f"column_{column.get('column_index')}")
        for table in page.get("tables", [])
        for column in table.get("column_headers", [])
        if column.get("column_interpretation_status") == "PENDING_INTERPRETATION"
    })


def _missing_field_names(page: dict[str, Any]) -> list[str]:
    if page["view"] != "profile":
        return []
    return [
        label for label, status in page["view_data"].get("personal_field_status", {}).items()
        if status == "NOT_FOUND_IN_CAPTURED_SNAPSHOT"
    ]


def _rows_by_page(parsed_pages: list[dict[str, Any]], view: str, collection: str) -> list[dict[str, Any]]:
    result = []
    for page in parsed_pages:
        if page["view"] != view:
            continue
        result.extend({"source": page["source"], **row} for row in page["view_data"].get(collection, []))
    return result


def _variant_export_row(page: dict[str, Any]) -> dict[str, Any]:
    parameters = page.get("source", {}).get("filter_parameters", {})
    parameter_key = hashlib.sha256(json.dumps(
        parameters, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()[:12]
    return {
        "player_id": page["player_id"],
        "view": page["view"],
        "snapshot_kind": "FILTERED_VARIANT",
        "variant_key": parameter_key,
        "filter_parameters": parameters,
        "source": page["source"],
        "coverage": page["coverage"],
        "tables": page["tables"],
        "relationships": page["relationships"],
        "view_data": page["view_data"],
    }


def build_player_exports(
    *,
    inventory: dict[str, Any],
    parsed_pages: list[dict[str, Any]],
    parsed_variants: list[dict[str, Any]] | None = None,
    source_audit: dict[str, Any],
    output_root: Path,
) -> Path:
    """Write normalized JSON/CSV gzip resources without copying any raw HTML."""
    coverage = _coverage_rows(inventory["coverage"], parsed_pages)
    filtered_variants = [_variant_export_row(page) for page in (parsed_variants or [])]
    players = inventory["players"]
    memberships = inventory["memberships"]
    profiles = [
        {
            "player_id": page["player_id"],
            "source": page["source"],
            **page["view_data"],
        }
        for page in parsed_pages if page["view"] == "profile"
    ]
    trajectories = []
    for page in parsed_pages:
        if page["view"] != "profile":
            continue
        trajectories.extend({
            "player_id": page["player_id"],
            "source": page["source"],
            **row,
        } for row in page["view_data"].get("career_rows", []))
        for index, row in enumerate(page["view_data"].get("career_totals_raw", [])):
            trajectories.append({
                "player_id": page["player_id"],
                "record_type": "TOTAL_ROW",
                "source": page["source"],
                "source_row_index": row.get("row_index", index),
                "columns": row.get("cells", []),
            })
    statistics = _rows_by_page(parsed_pages, "statistics", "statistics_rows")
    matches = _rows_by_page(parsed_pages, "matches", "match_summary_rows")
    individual_matches = _rows_by_page(parsed_pages, "matches", "individual_match_rows")
    rivals = _rows_by_page(parsed_pages, "rivals", "rival_records")
    relationships = [
        {"source": page["source"], **relation}
        for page in parsed_pages
        for relation in page.get("relationships", [])
    ]

    source_manifest = []
    for page in parsed_pages:
        source_manifest.append({
            "player_id": page["player_id"],
            "view": page["view"],
            **page["source"],
        })
    parsed_view_keys = {
        (str(row["player_id"]), str(row["view"]))
        for row in coverage if row["parse_status"] == "PARSED"
    }
    overview = {
        "season_scope": "2026/27 club-team-season participants; player career pages may cover earlier seasons",
        "player_count": len(players),
        "membership_count": len(memberships),
        "player_view_rows_expected": len(coverage),
        "player_views_captured": sum(row["snapshot_status"] == "CAPTURED_VALID" for row in coverage),
        "player_views_pending": sum(row["snapshot_status"] != "CAPTURED_VALID" for row in coverage),
        "player_views_parsed": sum(row["parse_status"] == "PARSED" for row in coverage),
        "parsed_player_count": len({page["player_id"] for page in parsed_pages}),
        "players_with_all_four_views": sum(
            all((player["player_id"], view) in parsed_view_keys
                for view in ("profile", "statistics", "matches", "rivals"))
            for player in players
        ),
        "match_fixture_rows_parsed": len(individual_matches),
        "match_aggregate_rows_parsed": len(matches),
        "rival_records_parsed": len(rivals),
        "trajectory_rows_parsed": len([item for item in trajectories if item.get("record_type") != "TOTAL_ROW"]),
        "statistics_rows_parsed": len(statistics),
        "source_snapshot_pages_parsed": len(parsed_pages),
        "filtered_variant_snapshots_parsed": len(filtered_variants),
        "filtered_variant_data_rows": sum(
            len(row["view_data"].get(collection, []))
            for row in filtered_variants
            for collection in (
                "statistics_rows", "match_summary_rows", "individual_match_rows", "rival_records"
            )
        ),
        "future_pilot_candidates_prepared": len(inventory.get("player_pilot_candidates", [])),
        "career_completeness_certified": False,
    }
    metadata = {
        "schema_version": PLAYER_SCHEMA_VERSION,
        "parser_version": PLAYER_PARSER_VERSION,
        "season_scope": "2026/27",
        "provider": "BDFutbol",
        "source_player_roster": "snapshot-f36c91119a98390766ff-parser-1.3.0",
        "source_page_snapshots": source_manifest,
        "source_filtered_variants": [
            {
                "player_id": row["player_id"],
                "view": row["view"],
                "filter_parameters": row["filter_parameters"],
                "source": row["source"],
            }
            for row in filtered_variants
        ],
        "source_audit": {
            "competition_extraction_keys": [
                item.get("extraction_key") for item in source_audit.get("hito1b", {}).get("candidates", [])
            ],
            "retained_competition_extraction_key": source_audit.get("hito1b", {}).get("retained_extraction_key"),
        },
        "summary": overview,
    }
    datasets = {
        "players": players,
        "memberships": memberships,
        "profiles": profiles,
        "trajectory": trajectories,
        "statistics": statistics,
        "matches": matches,
        "individual_matches": individual_matches,
        "rivals": rivals,
        "relationships": relationships,
        "coverage": coverage,
        "acquisition_manifest": inventory["acquisition_manifest"],
        "player_pilot_candidates": inventory.get("player_pilot_candidates", []),
        "source_audit": [source_audit],
        "filtered_variants": filtered_variants,
    }
    source_digest = hashlib.sha256(json.dumps(
        {
            "sources": sorted(json.dumps(
                [page["player_id"], page["view"], page["source"]],
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ) for page in parsed_pages),
            "filtered_variants": sorted(json.dumps(
                [row["player_id"], row["view"], row["variant_key"], row["source"]],
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ) for row in filtered_variants),
            "inventory": {
                "players": players,
                "memberships": memberships,
                "coverage": coverage,
                "acquisition_manifest": inventory["acquisition_manifest"],
                "player_pilot_candidates": inventory.get("player_pilot_candidates", []),
            },
            "source_audit": source_audit,
            "parser": PLAYER_PARSER_VERSION,
        },
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()[:20]
    output_dir = output_root / "compact" / f"snapshot-{source_digest}-parser-{PLAYER_PARSER_VERSION}"

    contents: dict[Path, bytes] = {
        Path("dataset_metadata.json.gz"): _json_bytes(metadata),
        Path("summary.json.gz"): _json_bytes(_wrapper("summary", [overview])),
    }
    for name, rows in datasets.items():
        contents[Path(f"{name}.json.gz")] = _json_bytes(_wrapper(name, rows))
        contents[Path(f"{name}.csv.gz")] = _csv_bytes(rows)
    for page in parsed_pages:
        contents[Path("pages") / page["player_id"] / f"{page['view']}.json.gz"] = _json_bytes(page)
    for variant in filtered_variants:
        contents[
            Path("variants") / variant["player_id"] / variant["view"]
            / f"{variant['variant_key']}.json.gz"
        ] = _json_bytes(variant)

    if output_dir.exists():
        for relative, expected in contents.items():
            path = output_dir / relative
            if not path.is_file() or path.read_bytes() != expected:
                raise FileExistsError(f"El export existente difiere y no se sobrescribirá: {output_dir}")
        return output_dir
    for relative, content in contents.items():
        _atomic_write(output_dir / relative, content)
    return output_dir
