from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from football_data_hub.dev_explorer.data import (
    EXPECTED_PLAYER_EXPORT_SCHEMA,
    PLAYER_EXPORT_ARRAYS,
    DatasetValidationError,
    discover_player_exports,
    filter_player_matches,
    latest_valid_player_export,
    load_player_export,
    player_match_counts,
    player_search_label,
)


def _write_synthetic_player_export(
    root: Path,
    name: str,
    *,
    captured_at: str,
    parser_version: str = "0.2.3",
    schema_version: str = EXPECTED_PLAYER_EXPORT_SCHEMA,
    include_all_arrays: bool = True,
) -> Path:
    path = root / name
    path.mkdir(parents=True)
    metadata = {
        "provider": "BDFutbol",
        "parser_version": parser_version,
        "schema_version": schema_version,
        "season_scope": "2026/27",
        "source_page_snapshots": [
            {"captured_at_utc": captured_at, "access_status": "VALID"}
        ],
    }
    players = [
        {
            "player_id": "j-full",
            "name_raw_values": ["Test Full Name"],
            "views_with_snapshot": ["profile", "statistics", "matches", "rivals"],
            "views_pending": [],
            "views_required": ["profile", "statistics", "matches", "rivals"],
            "team_memberships": [{"team_name": "Club A", "team_season_id": "t-a"}],
        },
        {
            "player_id": "j-partial",
            "name_raw_values": ["Test Partial Name"],
            "views_with_snapshot": ["profile"],
            "views_pending": ["statistics", "matches", "rivals"],
            "views_required": ["profile", "statistics", "matches", "rivals"],
            "team_memberships": [{"team_name": "Club B", "team_season_id": "t-b"}],
        },
        {
            "player_id": "j-roster",
            "name_raw_values": ["Test Roster Name"],
            "views_with_snapshot": [],
            "views_pending": ["profile", "statistics", "matches", "rivals"],
            "views_required": ["profile", "statistics", "matches", "rivals"],
            "team_memberships": [],
        },
    ]
    row = {
        "source_row_index": 0,
        "columns": [
            {"header_original": "Temp", "raw_value": "2026-27", "value_status": "RAW_ONLY"},
            {"header_original": "Equipo", "raw_value": "Club A", "value_status": "RAW_ONLY"},
            {"header_original": "PJ", "raw_value": "0", "value_status": "INTEGER_NORMALIZED", "hidden_by_inline_style": True},
        ],
    }
    profiles = [
        {
            "player_id": "j-full",
            "display_name_raw": "Full",
            "full_name_raw": "Test Full Name",
            "career_completeness": "NOT_CERTIFIED_COMPLETE",
            "career_rows": [row],
            "personal_fields": {"Nacionalidad": None, "Peso": {"raw_value": "70 kg"}},
            "personal_field_status": {"Nacionalidad": "NOT_FOUND_IN_CAPTURED_SNAPSHOT", "Peso": "RAW_ONLY"},
            "photo_references": [{"url": "https://example.invalid/test.jpg", "downloaded": False}],
        },
        {
            "player_id": "j-partial",
            "display_name_raw": "Partial",
            "full_name_raw": "Test Partial Name",
            "career_completeness": "NOT_CERTIFIED_COMPLETE",
            "career_rows": [],
            "personal_fields": {"Nacionalidad": None},
            "personal_field_status": {"Nacionalidad": "NOT_FOUND_IN_CAPTURED_SNAPSHOT"},
            "photo_references": [],
        },
    ]
    appeared = {
        "player_id": "j-full",
        "match_id": "m-1",
        "season_raw": "2026-27",
        "competition_raw": "1rf",
        "player_team_raw": "Club A",
        "player_appearance_status": "APPEARED_PER_SOURCE_FLAGS",
        "player_match_metrics_raw": {"min": 90},
    }
    duplicate_no_appearance = {
        **appeared,
        "player_appearance_status": "NO_APPEARANCE_PER_SOURCE_FLAGS",
        "source_record_index": 1,
    }
    second_match = {
        **appeared,
        "match_id": "m-2",
        "competition_raw": "copa",
        "source_record_index": 2,
    }
    coverage = []
    for player_id, captured in (("j-full", {"profile", "statistics", "matches", "rivals"}),
                                ("j-partial", {"profile"}), ("j-roster", set())):
        for view in ("profile", "statistics", "matches", "rivals"):
            valid = view in captured
            coverage.append({
                "player_id": player_id,
                "view": view,
                "coverage_status": "CAPTURED_AND_PARSED" if valid else "PENDING_CAPTURE",
                "snapshot_status": "VALID_SNAPSHOT" if valid else "PENDING_CAPTURE",
                "parse_status": "PARSED" if valid else "NOT_AVAILABLE",
                "fields_normalized": [],
                "fields_preserved_raw": [],
                "fields_not_found_in_snapshot": [],
            })
    items_by_resource: dict[str, list[dict[str, Any]]] = {
        "players": players,
        "profiles": profiles,
        "trajectory": [{"player_id": "j-full", **row}],
        "statistics": [{"player_id": "j-full", "table_role": "statistics_by_competition", "columns": row["columns"]}],
        "matches": [{"player_id": "j-full", "summary_dimension": "match_summary_by_season", "dimension_value_raw": "2026-27", "columns": row["columns"]}],
        "individual_matches": [appeared, duplicate_no_appearance, second_match],
        "rivals": [{"player_id": "j-full", "rival_kind": "player", "rival_id": "j-opponent", "rival_name_raw": "Opponent", "columns": row["columns"]}],
        "coverage": coverage,
        "acquisition_manifest": [],
        "memberships": [],
        "relationships": [],
        "filtered_variants": [],
        "player_pilot_candidates": [],
        "summary": [{"player_count": 3, "parsed_player_count": 2, "players_with_all_four_views": 1, "player_views_captured": 5, "match_fixture_rows_parsed": 3}],
    }
    (path / "dataset_metadata.json.gz").write_bytes(gzip.compress(json.dumps(metadata).encode("utf-8")))
    for resource in PLAYER_EXPORT_ARRAYS:
        if not include_all_arrays and resource == "rivals":
            continue
        document = {
            "schema_version": schema_version,
            "resource": resource,
            "parser_version": parser_version,
            "items": items_by_resource[resource],
        }
        (path / f"{resource}.json.gz").write_bytes(gzip.compress(json.dumps(document).encode("utf-8")))
    return path


def test_synthetic_gzip_exports_discover_latest_valid_and_keep_older_choices(tmp_path: Path) -> None:
    older = _write_synthetic_player_export(
        tmp_path, "older-version", captured_at="2026-10-08T10:00:00+00:00", parser_version="0.2.2"
    )
    latest = _write_synthetic_player_export(
        tmp_path, "latest-export", captured_at="2026-10-09T10:00:00+00:00", parser_version="0.2.3"
    )
    _write_synthetic_player_export(
        tmp_path, "incomplete-export", captured_at="2026-10-10T10:00:00+00:00", include_all_arrays=False
    )

    candidates = discover_player_exports(tmp_path)
    selected = latest_valid_player_export(candidates)

    assert selected is not None and selected.path == latest
    assert any(candidate.path == older and candidate.valid for candidate in candidates)
    assert any(candidate.path.name == "incomplete-export" and not candidate.valid for candidate in candidates)


def test_synthetic_player_export_distinguishes_full_partial_and_roster_only_players(tmp_path: Path) -> None:
    path = _write_synthetic_player_export(tmp_path, "player-export", captured_at="2026-10-09T10:00:00+00:00")
    dataset = load_player_export(path)

    assert len(dataset.players) == 3
    assert dataset.profile("j-full") is not None
    assert dataset.profile("j-partial") is not None
    assert dataset.profile("j-roster") is None
    assert dataset.coverage_for("j-full", "rivals")["coverage_status"] == "CAPTURED_AND_PARSED"
    assert dataset.coverage_for("j-partial", "statistics")["snapshot_status"] == "PENDING_CAPTURE"
    assert dataset.coverage_for("j-roster", "profile")["parse_status"] == "NOT_AVAILABLE"
    assert player_search_label(dataset.player("j-roster")) == "Test Roster Name · j-roster"
    profile = dataset.profile("j-full")
    assert profile["personal_field_status"]["Nacionalidad"] == "NOT_FOUND_IN_CAPTURED_SNAPSHOT"
    assert profile["personal_fields"]["Peso"]["raw_value"] == "70 kg"


def test_synthetic_match_counts_preserve_duplicate_rows_and_separate_appearance_flags() -> None:
    records = [
        {"match_id": "m-1", "player_appearance_status": "APPEARED_PER_SOURCE_FLAGS"},
        {"match_id": "m-1", "player_appearance_status": "NO_APPEARANCE_PER_SOURCE_FLAGS"},
        {"match_id": "m-2", "player_appearance_status": "NO_APPEARANCE_PER_SOURCE_FLAGS"},
        {"match_id": None, "player_appearance_status": None},
    ]

    counts = player_match_counts(records)

    assert counts["source_records"] == 4
    assert counts["unique_match_ids"] == 2
    assert counts["unique_match_ids_with_appearance_flag"] == 1
    assert counts["unique_match_ids_with_non_appearance_flag"] == 2
    assert counts["appearance_flag_records"] == 1
    assert counts["non_appearance_flag_records"] == 2
    assert counts["duplicate_match_ids"] == {"m-1": 2}
    assert counts["duplicate_source_rows"] == 1
    assert counts["records_without_match_id"] == 1


def test_synthetic_player_match_filters_are_local_and_keep_duplicates() -> None:
    records = [
        {"match_id": "m-1", "season_raw": "2026-27", "player_team_raw": "Club A", "competition_raw": "1rf"},
        {"match_id": "m-1", "season_raw": "2026-27", "player_team_raw": "Club A", "competition_raw": "1rf"},
        {"match_id": "m-2", "season_raw": "2025-26", "player_team_raw": "Club B", "competition_raw": "copa"},
    ]

    selected = filter_player_matches(records, season="2026-27", team="Club A", competition="1rf")

    assert len(selected) == 2
    assert [row["match_id"] for row in selected] == ["m-1", "m-1"]


def test_incompatible_synthetic_schema_is_rejected(tmp_path: Path) -> None:
    path = _write_synthetic_player_export(
        tmp_path,
        "old-schema",
        captured_at="2026-10-09T10:00:00+00:00",
        schema_version="football_data_hub.bdfutbol.player_pages.v2",
    )

    try:
        load_player_export(path)
    except DatasetValidationError as exc:
        assert "schema_version no compatible" in str(exc)
    else:
        raise AssertionError("El esquema anterior no debe cargarse como export v3")
