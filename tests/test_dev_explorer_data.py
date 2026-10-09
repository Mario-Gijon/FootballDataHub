from __future__ import annotations

import gzip
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from football_data_hub.dev_explorer.data import (
    EXPECTED_EXPORT_SCHEMA,
    EXPECTED_CLUB_EXPORT_SCHEMA,
    EXPECTED_CLUB_SPORTS_SCHEMA,
    DatasetValidationError,
    club_selection_status,
    competition_conflict_evidence,
    discover_club_exports,
    diagnostic_rows,
    discover_datasets,
    filter_matches,
    fixture_status,
    flatten_record,
    group_quality,
    has_result,
    latest_valid_dataset,
    latest_valid_club_export,
    load_club_export,
    load_dataset,
    null_counts,
    recent_results,
    score_label,
    search_records,
    search_clubs,
    filter_club_matches,
    match_observation_comparison,
    team_records,
    upcoming_matches,
    verified_participant_groups,
)


def _match(
    *,
    match_id: str | None,
    group: str = "I",
    round_number: int = 1,
    date: str | None = "2026-10-02",
    home_id: str | None = "team-a",
    away_id: str | None = "team-b",
    home: str = "Local FC",
    away: str = "Visitante FC",
    status: str = "scheduled",
    fixture: str | None = None,
    home_goals: int | None = None,
    away_goals: int | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "match_id": match_id,
        "group": group,
        "round": round_number,
        "date": date,
        "home_team_season_id": home_id,
        "away_team_season_id": away_id,
        "home_team_name": home,
        "away_team_name": away,
        "result_status": status,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "stadium_name": "Estadio Central",
    }
    if fixture is not None:
        item["fixture_status"] = fixture
    return item


def _write_dataset(
    root: Path,
    name: str,
    *,
    captured_at: str = "2026-10-08T12:00:00+00:00",
    matches_i: list[dict[str, Any]] | None = None,
    omit: str | None = None,
    corrupt: str | None = None,
) -> Path:
    path = root / name
    path.mkdir(parents=True)
    snapshots = {
        group: {
            "captured_at_utc": captured_at,
            "access_status": "VALID",
            "http_status": 200,
            "requested_url": f"https://example.test/{group}",
            "final_url": f"https://example.test/{group}",
            "snapshot_sha256": f"sha-{group}",
        }
        for group in ("I", "II")
    }
    documents = {
        "dataset_metadata.json": {
            "schema_version": EXPECTED_EXPORT_SCHEMA,
            "parser_version": "1.0.0",
            "extraction_key": name,
            "season": "2026/27",
            "source_snapshots": snapshots,
        },
        "competition_groups.json": {"items": [{"group": "I"}, {"group": "II"}]},
        "participants.json": {
            "items": [
                {"team_season_id": "team-a", "team_name": "Local FC", "group": "I"},
                {"team_season_id": "team-b", "team_name": "Visitante FC", "group": "I"},
            ]
        },
        "standings_group_i.json": {
            "items": [
                {"team_season_id": "team-a", "team_name": "Local FC", "position": 1, "stats": {"points": 3}},
                {"team_season_id": "team-b", "team_name": "Visitante FC", "position": 2, "stats": {"points": 0}},
            ]
        },
        "standings_group_ii.json": {"items": []},
        "matches_group_i.json": {"items": matches_i if matches_i is not None else [_match(match_id="m-1")]},
        "matches_group_ii.json": {"items": []},
        "quality_coverage.json": {
            "groups": [
                {
                    "group": "I",
                    "expected": {"teams": 2, "rounds": 1, "matches": 1},
                    "observed": {"fixture_team_references_unresolved": 0},
                    "fixture_coverage_complete": True,
                    "coverage_checks": {"expected_match_count": True},
                    "parser_diagnostics": [],
                },
                {
                    "group": "II",
                    "expected": {"teams": 2, "rounds": 1, "matches": 1},
                    "observed": {},
                    "fixture_coverage_complete": False,
                    "coverage_checks": {"expected_match_count": False},
                    "parser_diagnostics": [],
                },
            ]
        },
    }
    for filename, document in documents.items():
        if filename == omit:
            continue
        content = "{" if filename == corrupt else json.dumps(document)
        (path / filename).write_text(content, encoding="utf-8")
    return path


def _write_club_export(
    root: Path,
    name: str,
    *,
    parser_version: str = "1.7.0",
    captured_at: str = "2026-10-08T18:00:00+00:00",
    matches: list[dict[str, Any]] | None = None,
    observations: list[dict[str, Any]] | None = None,
    include_profile: bool = True,
    corrupt_resource: str | None = None,
) -> Path:
    path = root / name
    path.mkdir(parents=True)
    matches = matches if matches is not None else [{
        "match_id": "m-1",
        "date": "2026-08-29",
        "date_raw": "29/08/2026",
        "season_raw": "2026-27",
        "competition_code_raw": "1rf",
        "round_label_raw": "Jornada 1",
        "home_club_id": "e1",
        "away_club_id": "e2",
        "home_team_name_raw": "Real Jaén",
        "away_team_name_raw": "Rival CF",
        "home_goals": 2,
        "away_goals": 1,
        "referee_id_raw": 600001,
        "team_season_identity_status": "NOT_ESTABLISHED",
        "source_observation_count": 2,
        "differing_fields_between_club_sources": [],
    }]
    observations = observations if observations is not None else [
        {
            "match_id": "m-1", "source_club_id": "e1", "source_team_season_id": "t2026-1",
            "captured_at_utc": captured_at, "snapshot_sha256": "sha-e1", "url": "https://example.test/e1",
            "source_record_index": 1, "season_raw": "2026-27", "competition_code_raw": "1rf",
            "date": "2026-08-29", "home_club_id": "e1", "home_team_name_raw": "Real Jaén",
            "home_goals": 2, "away_club_id": "e2", "away_team_name_raw": "Rival CF",
            "away_goals": 1, "round_code_raw": "1", "round_label_raw": "Jornada 1",
            "referee_id_raw": 600001, "source_values_raw": [2026, "1rf", "29/08/2026"],
            "source_field_map": {"0": "season_start_year_raw", "1": "competition_code_raw", "2": "date_raw"},
        },
        {
            "match_id": "m-1", "source_club_id": "e2", "source_team_season_id": "t2026-2",
            "captured_at_utc": captured_at, "snapshot_sha256": "sha-e2", "url": "https://example.test/e2",
            "source_record_index": 7, "season_raw": "2026-27", "competition_code_raw": "1rf",
            "date": "2026-08-29", "home_club_id": "e1", "home_team_name_raw": "Real Jaén",
            "home_goals": 2, "away_club_id": "e2", "away_team_name_raw": "Rival CF",
            "away_goals": 1, "round_code_raw": "1", "round_label_raw": "Jornada 1",
            "referee_id_raw": 600001, "source_values_raw": [2026, "1rf", "29/08/2026"],
            "source_field_map": {"0": "season_start_year_raw", "1": "competition_code_raw", "2": "date_raw"},
        },
    ]
    clubs = [{
        "club_id": "e1", "team_season_id": "t2026-1", "unique_match_ids": 1,
        "source_records_reported": 3, "source_observations_parsed": 3,
        "seasons_observed": ["2025-26", "2026-27"], "source_parse_status": "PARSED_19_POSITION_TUPLES",
        "captured_at_utc": captured_at, "snapshot_sha256": "sha-club", "url": "https://example.test/e1",
    }]
    selection = {
        "selection_status": "AMBIGUOUS_VALID_SOURCES",
        "selection_reason": "Conflicto entre candidatas",
        "candidate_conflicts": [{
            "left_extraction_key": "comp-old", "right_extraction_key": "comp-new",
            "conflicts": [{"fixture_identity": ["fixture", "II", "2026/27", "team-home", "team-away"], "fields": ["normalized_match_state"]}],
        }],
    }
    metadata = {
        "provider": "BDFutbol", "schema_version": EXPECTED_CLUB_EXPORT_SCHEMA,
        "parser_version": parser_version, "extraction_key": name, "season_scope": "2026/27",
        "source_snapshots": [{"captured_at_utc": captured_at}],
        "competition_crosscheck_source": {"selection": selection},
    }
    summary = {
        "embedded_unique_match_ids": len(matches),
        "embedded_match_observations": len(observations),
        "embedded_duplicate_observations": len(observations) - len(matches),
        "embedded_historical_seasons_observed": 2,
    }
    crosscheck = {
        "schema_version": EXPECTED_CLUB_SPORTS_SCHEMA, "parser_version": parser_version,
        "extraction_key": name, "status": "NOT_RUN_NO_SELECTED_COMPETITION_SOURCE",
        "matches_compared": 0, "competition_export_played_matches": None,
        "competition_match_ids_missing_from_embedded": None,
        "embedded_match_ids_absent_from_competition": None,
    }
    resources: dict[str, Any] = {
        "matches_from_embedded_data": matches,
        "embedded_match_observations": observations,
        "embedded_match_coverage_by_club": clubs,
        "rosters": [{"club_id": "e1", "team_season_id": "t2026-1", "player_id": "j1", "name_raw": "Jugadora Raw", "position_raw": "1"}],
        "coaches_current": [{"club_id": "e1", "team_season_id": "t2026-1", "coach_id": "l1", "name_raw": "Entrenador Raw"}],
        "coverage_by_club": [{"club_id": "e1", "team_season_id": "t2026-1", "status": "VALIDATED", "aggregate_expected": {"PJ": 1, "PG": 1}}],
        "summary": summary,
        "embedded_match_competition_crosscheck": crosscheck,
        "embedded_match_filtered_table_card_crosscheck": {"comparison_count": 0, "comparisons": []},
    }
    metadata_path = path / "dataset_metadata.json.gz"
    metadata_path.write_bytes(gzip.compress(json.dumps(metadata).encode("utf-8"), mtime=0))
    for resource, items in resources.items():
        document = {
            "schema_version": EXPECTED_CLUB_SPORTS_SCHEMA,
            "parser_version": parser_version,
            "extraction_key": name,
            "items": items,
        }
        if resource == "embedded_match_competition_crosscheck":
            document = items
        destination = path / "sports" / f"{resource}.json.gz"
        destination.parent.mkdir(parents=True, exist_ok=True)
        raw = b"not gzip" if resource == corrupt_resource else gzip.compress(json.dumps(document).encode("utf-8"), mtime=0)
        destination.write_bytes(raw)
    if include_profile:
        profile = {"entity_type": "club", "entity_id": "e1", "title": "Real Jaén | BDFutbol", "hero_text": "Nombre completo Real Jaén"}
        profile_path = path / "pages" / "club" / "e1" / "club_profile.json.gz"
        profile_path.parent.mkdir(parents=True)
        profile_path.write_bytes(gzip.compress(json.dumps(profile).encode("utf-8"), mtime=0))
    return path


def test_discovery_selects_latest_valid_dataset_from_metadata(tmp_path: Path) -> None:
    older = _write_dataset(tmp_path, "arbitrary-old-name", captured_at="2026-10-07T12:00:00+00:00")
    newer = _write_dataset(tmp_path, "another-hash", captured_at="2026-10-08T12:00:00+00:00")
    _write_dataset(tmp_path, "missing-json", omit="matches_group_ii.json")
    _write_dataset(tmp_path, "corrupt-json", corrupt="participants.json")

    candidates = discover_datasets(tmp_path)
    selected = latest_valid_dataset(candidates)

    assert selected is not None
    assert selected.path == newer
    assert selected.path != older
    assert selected.valid
    assert any(candidate.path.name == "missing-json" and not candidate.valid for candidate in candidates)
    assert any(candidate.path.name == "corrupt-json" and not candidate.valid for candidate in candidates)


def test_invalid_or_absent_dataset_root_is_handled(tmp_path: Path) -> None:
    assert discover_datasets(tmp_path / "absent") == []
    invalid = _write_dataset(tmp_path, "broken", omit="standings_group_i.json")
    with pytest.raises(DatasetValidationError, match="Falta standings_group_i.json"):
        load_dataset(invalid)
    malformed = _write_dataset(tmp_path, "malformed-quality")
    (malformed / "quality_coverage.json").write_text('{"groups": [null]}', encoding="utf-8")
    with pytest.raises(DatasetValidationError, match="todos los grupos deben ser objetos"):
        load_dataset(malformed)


def test_fixture_states_and_score_support_current_and_legacy_exports(tmp_path: Path) -> None:
    current = load_dataset(_write_dataset(tmp_path, "current"))
    old = load_dataset(
        _write_dataset(
            tmp_path,
            "old",
            matches_i=[
                _match(match_id=None, date="2026-10-09", status="scheduled"),
                _match(match_id=None, date="2026-10-07", status="scheduled"),
                _match(match_id=None, date=None, status="not_available"),
                _match(match_id="m-played", status="available", fixture="played", home_goals=2, away_goals=1),
            ],
        )
    )

    assert fixture_status(_match(match_id="m", status="available", fixture="played"), current) == "played"
    assert fixture_status(_match(match_id=None, date="2026-10-09"), old) == "scheduled"
    assert fixture_status(_match(match_id=None, date="2026-10-07"), old) == "unresolved"
    assert fixture_status(_match(match_id=None, date=None), old) == "unconfirmed"
    assert fixture_status(_match(match_id=None, status="mystery"), old) == "unknown"
    played = old.matches["I"][-1]
    assert has_result(played)
    assert score_label(played) == "2–1"
    assert score_label(old.matches["I"][0]) == "—"


def test_team_joins_and_calendar_filters_use_ids_and_selected_dimensions(tmp_path: Path) -> None:
    matches = [
        _match(match_id="m-1", round_number=1, home_id="team-a", away_id="team-b", status="available", fixture="played", home_goals=1, away_goals=0),
        _match(match_id="m-2", round_number=2, date="2026-10-09", home_id="team-b", away_id="team-a", status="scheduled", home="Visitante FC", away="Local FC"),
        _match(match_id="m-3", group="II", round_number=2, home_id="other-a", away_id="other-b", home="Otro", away="Club"),
    ]
    dataset = load_dataset(_write_dataset(tmp_path, "joins", matches_i=matches[:2]))
    dataset.matches["II"] = [matches[2]]

    joined = team_records(dataset, "team-a")
    assert joined is not None
    assert joined["standing"]["position"] == 1
    assert {match["match_id"] for match in joined["matches"]} == {"m-1", "m-2"}
    filtered = filter_matches(
        dataset,
        group="I",
        round_number=2,
        team_season_id="team-a",
        statuses={"scheduled"},
        search="estadio central",
    )
    assert [match["match_id"] for match in filtered] == ["m-2"]
    assert filtered[0]["_display_fixture_status"] == "scheduled"
    assert filter_matches(dataset, group="I", team_season_id="not-present") == []


def test_dashboard_match_lists_sort_real_statuses_and_limit_results(tmp_path: Path) -> None:
    matches = [
        _match(
            match_id="older-result",
            date="2026-09-01",
            status="available",
            fixture="played",
            home_goals=1,
            away_goals=0,
        ),
        _match(
            match_id="newer-result",
            date="2026-09-04",
            round_number=2,
            status="available",
            fixture="played",
            home_goals=2,
            away_goals=1,
        ),
        _match(match_id=None, date="2026-10-11", round_number=3, fixture="scheduled"),
        _match(match_id=None, date="2026-10-09", round_number=4, fixture="scheduled"),
        _match(match_id=None, date="2026-10-07", round_number=5, fixture="unresolved"),
    ]
    dataset = load_dataset(_write_dataset(tmp_path, "dashboard", matches_i=matches))

    assert [match["match_id"] for match in recent_results(dataset, group="I", limit=1)] == [
        "newer-result"
    ]
    assert [match["date"] for match in upcoming_matches(dataset, group="I", limit=2)] == [
        "2026-10-09",
        "2026-10-11",
    ]


def test_quality_reports_structural_coverage_results_and_integrity_separately(tmp_path: Path) -> None:
    duplicates = [
        _match(match_id="same", status="available", fixture="played", home_goals=0, away_goals=0),
        _match(match_id="same", status="scheduled", round_number=2),
        _match(match_id=None, round_number=3, home_id=None),
    ]
    dataset = load_dataset(_write_dataset(tmp_path, "quality", matches_i=duplicates))
    report = group_quality(dataset, "I")

    assert report["matches"] == 3
    assert report["expected_matches"] == 1
    assert report["results_available"] == 1
    assert report["results_missing"] == 2
    assert len(report["missing_match_ids"]) == 1
    assert report["duplicate_match_ids"] == {"same": 2}
    assert len(report["missing_team_relations"]) == 1
    kinds = {row["kind"] for row in diagnostic_rows(dataset)}
    assert {"duplicate_match_id", "team_relation_unresolved", "coverage_check_failed"} <= kinds
    assert report["structural_complete"] is True


def test_json_explorer_helpers_flatten_search_and_count_nulls() -> None:
    records = [
        {"team": {"name": "Club Águila", "id": "a"}, "tags": ["red", None], "note": None},
        {"team": {"name": "Club Norte", "id": "b"}, "tags": [], "note": "ok"},
    ]

    assert flatten_record(records[0])["team.name"] == "Club Águila"
    assert search_records(records, "team.name", "aguila") == [records[0]]
    assert search_records(records, query="norte") == [records[1]]
    assert null_counts(records) == {"tags": 1, "note": 1}


def test_club_export_validation_and_latest_compatible_version(tmp_path: Path) -> None:
    older = _write_club_export(tmp_path, "snapshot-old-parser-1.6.0", parser_version="1.6.0", captured_at="2026-10-07T18:00:00+00:00")
    newest = _write_club_export(tmp_path, "snapshot-new-parser-1.7.0", captured_at="2026-10-08T18:00:00+00:00")
    broken = _write_club_export(tmp_path, "snapshot-broken-parser-1.8.0", parser_version="1.8.0", corrupt_resource="rosters")

    candidates = discover_club_exports(tmp_path)
    selected = latest_valid_club_export(candidates)

    assert selected is not None and selected.path == newest
    assert selected.path != older
    assert selected.selection_status == "AMBIGUOUS_VALID_SOURCES"
    assert any(item.path == broken and not item.valid for item in candidates)
    with pytest.raises(DatasetValidationError, match="No se pudo leer rosters.json.gz"):
        load_club_export(broken)


def test_club_search_and_history_filters_keep_club_identity_and_raw_dimensions(tmp_path: Path) -> None:
    records = [
        {
            "match_id": "new", "date": "2026-08-29", "season_raw": "2026-27", "competition_code_raw": "1rf",
            "home_club_id": "e1", "away_club_id": "e2", "home_team_name_raw": "Real Jaén", "away_team_name_raw": "Rival CF",
        },
        {
            "match_id": "old", "date": "2025-11-05", "season_raw": "2025-26", "competition_code_raw": "COP",
            "home_club_id": "e3", "away_club_id": "e1", "home_team_name_raw": "Otro Club", "away_team_name_raw": "Real Jaén",
        },
        {
            "match_id": "invalid-date", "date": "not-a-date", "season_raw": "2026-27", "competition_code_raw": "1rf",
            "home_club_id": "e1", "away_club_id": "e4", "home_team_name_raw": "Real Jaén", "away_team_name_raw": "Norte CF",
        },
    ]
    path = _write_club_export(tmp_path, "clubs", matches=records, observations=[])
    dataset = load_club_export(path, team_groups={"t2026-1": {"group": "II", "team_name": "Real Jaén"}})

    assert [club["club_id"] for club in search_clubs(dataset.clubs, "jaen")] == ["e1"]
    assert [club["club_id"] for club in search_clubs(dataset.clubs, "Real Jaén")] == ["e1"]
    filtered = filter_club_matches(
        dataset.matches_for_club("e1"),
        club_id="e1",
        season="2026-27",
        competition="1rf",
        rival="rival",
        venue="local",
        date_from=date(2026, 8, 1),
        date_to=date(2026, 9, 1),
    )
    assert [match["match_id"] for match in filtered] == ["new"]
    assert filter_club_matches(dataset.matches_for_club("e1"), club_id="e1", rival="e2")[0]["match_id"] == "new"
    assert dataset.clubs[0]["team_season_id"] == "t2026-1"
    assert dataset.clubs[0]["group"] == "II"


def test_club_match_detail_keeps_two_or_one_sources_without_historical_team_identity(tmp_path: Path) -> None:
    path = _write_club_export(tmp_path, "two-sources")
    dataset = load_club_export(path)
    observations = dataset.observations_for_match("m-1")
    comparison = match_observation_comparison(observations)

    assert len(observations) == 2
    assert {row["source_club_id"] for row in observations} == {"e1", "e2"}
    assert comparison["matching_fields"]
    assert comparison["differing_fields"] == []
    assert dataset.matches[0]["team_season_identity_status"] == "NOT_ESTABLISHED"
    assert dataset.matches[0].get("home_team_season_id") is None

    one_source = _write_club_export(tmp_path, "one-source", observations=observations[:1])
    one_source_dataset = load_club_export(one_source)
    single_comparison = match_observation_comparison(one_source_dataset.observations_for_match("m-1"))
    assert single_comparison == {"source_count": 1, "matching_fields": [], "differing_fields": []}


def test_ambiguous_club_competition_selection_is_not_reported_as_missing(tmp_path: Path) -> None:
    dataset = load_club_export(_write_club_export(tmp_path, "ambiguous"))
    status = club_selection_status(dataset)

    assert status["selection_status"] == "AMBIGUOUS_VALID_SOURCES"
    assert status["crosscheck_status"] == "NOT_RUN_NO_SELECTED_COMPETITION_SOURCE"
    assert status["crosscheck_expected"] is None
    assert status["crosscheck_missing_from_embedded"] is None
    assert status["crosscheck_absent_from_competition"] is None
    assert status["historical_unique_matches"] == 1
    assert status["historical_source_observations"] == 2


def test_partial_club_export_keeps_available_history_without_inventing_profile_or_roster(tmp_path: Path) -> None:
    path = _write_club_export(tmp_path, "partial", include_profile=False)
    dataset = load_club_export(path)

    assert len(dataset.clubs) == 1
    assert dataset.clubs[0]["profile"] == {}
    assert dataset.clubs[0]["profile_error"] is None
    assert dataset.matches_for_club("e1")
    assert dataset.arrays["rosters"][0]["position_raw"] == "1"


def test_verified_current_group_mapping_requires_consensus_across_exports(tmp_path: Path) -> None:
    first = load_dataset(_write_dataset(tmp_path, "group-map-a"))
    second = load_dataset(_write_dataset(tmp_path, "group-map-b"))
    groups = verified_participant_groups([first, second])
    assert groups["team-a"] == {"group": "I", "team_name": "Local FC"}

    second.participants[0]["group"] = "II"
    second.participants[0]["team_name"] = "Otro nombre"
    disputed = verified_participant_groups([first, second])
    assert "team-a" not in disputed
    assert "team-b" in disputed


def test_ambiguous_competition_fixture_evidence_comes_from_both_local_exports(tmp_path: Path) -> None:
    left_matches = [_match(
        match_id=None, group="II", home_id="team-home", away_id="team-away",
        home="FC Cartagena", away="Murcia", date="2026-09-27", round_number=5,
        status="scheduled", fixture="scheduled",
    )]
    right_matches = [_match(
        match_id=None, group="II", home_id="team-home", away_id="team-away",
        home="FC Cartagena", away="Murcia", date="2026-09-27", round_number=5,
        status="not_available", fixture="unresolved",
    )]
    left = load_dataset(_write_dataset(tmp_path, "comp-old", matches_i=[]))
    right = load_dataset(_write_dataset(tmp_path, "comp-new", matches_i=[]))
    left.matches["II"] = left_matches
    right.matches["II"] = right_matches
    left.metadata["extraction_key"] = "comp-old"
    right.metadata["extraction_key"] = "comp-new"
    conflict = {
        "left_extraction_key": "comp-old", "right_extraction_key": "comp-new",
        "conflicts": [{"fixture_identity": ["fixture", "II", "2026/27", "team-home", "team-away"]}],
    }

    evidence = competition_conflict_evidence([left, right], conflict)

    assert {row["extraction_key"]: row["status_in_export"] for row in evidence} == {
        "comp-old": "scheduled",
        "comp-new": "unresolved",
    }
    assert {row["home_team_name"] for row in evidence} == {"FC Cartagena"}


def test_current_local_club_export_exposes_real_jaen_and_both_conflict_sources() -> None:
    repository = Path(__file__).parents[1]
    club_root = repository / "data/parsed/bdfutbol/club_team_2026_27/compact"
    competition_root = repository / "data/parsed/bdfutbol/primera_federacion_2026_27"
    candidate = latest_valid_club_export(discover_club_exports(club_root))
    if candidate is None:
        pytest.skip("No está disponible el export local 1.7.0 de clubes")
    competition_datasets = [
        load_dataset(item.path)
        for item in discover_datasets(competition_root)
        if item.valid
    ]
    dataset = load_club_export(candidate.path, team_groups=verified_participant_groups(competition_datasets))
    real_jaen = [item for item in search_clubs(dataset.clubs, "Real Jaén") if item["club_id"] == "e49"]

    assert real_jaen
    assert real_jaen[0]["team_season_id"] == "t2026-2749"
    assert real_jaen[0]["group"] == "II"
    assert len(dataset.matches) == 47_449
    assert len(dataset.observations) == 52_904
    status = club_selection_status(dataset)
    assert status["selection_status"] == "AMBIGUOUS_VALID_SOURCES"
    evidence = competition_conflict_evidence(competition_datasets, status["candidate_conflicts"][0])
    assert {row["status_in_export"] for row in evidence} == {"scheduled", "unresolved"}
