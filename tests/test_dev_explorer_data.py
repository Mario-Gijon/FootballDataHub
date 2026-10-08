from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from football_data_hub.dev_explorer.data import (
    EXPECTED_EXPORT_SCHEMA,
    DatasetValidationError,
    diagnostic_rows,
    discover_datasets,
    filter_matches,
    fixture_status,
    flatten_record,
    group_quality,
    has_result,
    latest_valid_dataset,
    load_dataset,
    null_counts,
    score_label,
    search_records,
    team_records,
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
