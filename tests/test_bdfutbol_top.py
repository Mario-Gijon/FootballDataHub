from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from football_data_hub.providers.bdfutbol.top.acquisition import TopAcquisitionBundle
from football_data_hub.providers.bdfutbol.top.export import create_run_directory, export_top_capture
from football_data_hub.providers.bdfutbol.top.cli import main as top_cli_main
from football_data_hub.providers.bdfutbol.top.parser import TopParseError, parse_top_page
from football_data_hub.providers.bdfutbol.top.validation import validate_top_data

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "data/exports/bdfutbol/group2_top/20261010T155145.195266Z-c5b031a6"
TEAM_DATASET = ROOT / (
    "data/exports/bdfutbol/group2_classification/derived-res01-20261010T102656Z/normalized/matches.json"
)


@pytest.fixture(scope="module")
def top_data():
    source = (CAPTURE / "raw/source.html").read_text(encoding="utf-8")
    teams = json.loads(TEAM_DATASET.read_text(encoding="utf-8"))["teams"]
    return parse_top_page(source, team_catalog=teams)


def test_six_categories_and_source_exposed_ranking_coverage(top_data):
    assert dict(top_data.category_options) == {
        "1": "Goles",
        "2": "Minutos",
        "3": "Tarjetas amarillas",
        "4": "Tarjetas rojas",
        "8": "Más joven",
        "9": "Más veterano",
    }
    assert top_data.category_source_counts == {
        "goals": 107,
        "minutes": 10,
        "yellow_cards": 10,
        "red_cards": 10,
        "youngest": 10,
        "oldest": 10,
    }
    assert len(top_data.rankings) == 157
    assert top_data.see_all_available is True


def test_player_ids_team_links_and_typed_semantic_fields(top_data):
    assert len(top_data.players) == 217
    assert len({player.player_id for player in top_data.players}) == 217
    team_ids = {team["team_id"] for team in json.loads(TEAM_DATASET.read_text())["teams"]}
    assert {player.team_id for player in top_data.players} <= team_ids
    assert len({player.team_id for player in top_data.players}) == 20
    assert all(player.player_id > 0 for player in top_data.players)
    assert all("/es/j/j" in player.profile_url for player in top_data.players)
    assert all(player.team_id is not None and player.crest_url for player in top_data.players)
    assert all(isinstance(record.metric_value, int) for record in top_data.rankings)
    goal = next(record for record in top_data.rankings if record.category == "goals")
    assert goal.matches_played is None
    assert goal.metric == "goals" and goal.unit == "goals"
    youngest = next(record for record in top_data.rankings if record.category == "youngest")
    assert isinstance(youngest.metric_value, int)
    assert isinstance(youngest.matches_played, int)
    assert youngest.metric == "age_years" and youngest.unit == "years"


def test_progress_series_are_numeric_cumulative_and_match_rank_totals(top_data):
    assert top_data.chart_matchdays == (1, 2, 3, 4, 5, 6)
    assert len(top_data.progress) == 137
    assert sum(len(series.points) for series in top_data.progress) == 822
    ranking_by_key = {
        (record.category, record.player_id): record.metric_value
        for record in top_data.rankings
    }
    for series in top_data.progress:
        assert tuple(point.matchday for point in series.points) == top_data.chart_matchdays
        values = [point.value for point in series.points]
        assert all(value is None or isinstance(value, int) for value in values)
        assert [value for value in values if value is not None] == sorted(
            value for value in values if value is not None
        )
        assert values[-1] == ranking_by_key[(series.category, series.player_id)]
    for category in ("goals", "minutes", "yellow_cards", "red_cards"):
        selected = [
            series for series in top_data.progress
            if series.category == category and series.graph_selected_by_default
        ]
        assert len(selected) == 3


def test_foreigners_are_complete_and_zero_is_not_missing(top_data):
    assert len(top_data.foreigners) == 101
    assert len({record.player_id for record in top_data.foreigners}) == 101
    assert top_data.foreigners_summary.source_count == 101
    assert top_data.foreigners_summary.source_percentage == 19.65
    assert top_data.foreigners_summary.denominator_count is None
    assert top_data.foreigners_summary.implied_denominator_count == 514
    assert len(top_data.foreigners_summary.country_options) == 44
    player = next(player for player in top_data.players if player.player_id == 401472)
    assert player.display_name == "Gazzaniga"
    assert player.full_name == "Gianfranco Gazzaniga Farías"
    stats = next(record for record in top_data.foreigners if record.player_id == 401472)
    assert stats.matches_played == 6
    assert stats.minutes_played == 540
    assert stats.goals == stats.yellow_cards == stats.red_cards == 0
    assert next(player for player in top_data.players if player.player_id == 23496).full_name is None


def test_validation_rejects_a_series_that_disagrees_with_ranking(top_data):
    series = top_data.progress[0]
    broken_point = replace(series.points[-1], value=(series.points[-1].value or 0) + 1)
    broken_series = replace(series, points=(*series.points[:-1], broken_point))
    broken = replace(top_data, progress=(broken_series, *top_data.progress[1:]))
    result = validate_top_data(broken)
    assert result["valid"] is False
    assert "progress_total_mismatch" in {issue["code"] for issue in result["issues"]}


def test_invalid_page_is_rejected_without_invented_rows():
    teams = json.loads(TEAM_DATASET.read_text(encoding="utf-8"))["teams"]
    with pytest.raises(TopParseError):
        parse_top_page("<html><body>sin datos</body></html>", team_catalog=teams)


def test_versioned_json_export_can_be_read_back(top_data, tmp_path):
    raw_html = (CAPTURE / "raw/source.html").read_text(encoding="utf-8")
    validation = validate_top_data(top_data)
    bundle = TopAcquisitionBundle(
        capture_id="test-capture",
        captured_at_utc="2026-10-10T15:37:14.510238+00:00",
        raw_html=raw_html,
        page_title="Clasificación 1ª RFEF Grupo II 2026-27 | BDFutbol",
        access={"status": "VALID", "http_status": 200},
        browser={"backend": "offline-fixture"},
        parsed=top_data,
        validation=validation,
    )
    run_dir = create_run_directory(tmp_path, bundle.capture_id)
    paths = export_top_capture(
        run_dir,
        bundle,
        profile_dir=None,
        team_catalog_reference={"source_capture_id": "fixture"},
        capture_timestamp_basis="test fixture",
    )
    assert paths["raw_snapshot"].read_text(encoding="utf-8") == raw_html
    players = json.loads(paths["players"].read_text(encoding="utf-8"))
    rankings = json.loads(paths["rankings"].read_text(encoding="utf-8"))
    progress = json.loads(paths["progress"].read_text(encoding="utf-8"))
    foreigners = json.loads(paths["foreigners"].read_text(encoding="utf-8"))
    metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
    assert len(players["records"]) == 217
    assert len(rankings["records"]) == 157
    assert len(progress["records"]) == 137
    assert len(foreigners["records"]) == 101
    assert metadata["related_team_catalog"]["source_capture_id"] == "fixture"
    with pytest.raises(FileExistsError):
        create_run_directory(tmp_path, bundle.capture_id)


def test_saved_capture_can_be_re_normalized_offline(tmp_path):
    output = tmp_path / "offline-output"
    result = top_cli_main([
        "--team-catalog", str(TEAM_DATASET),
        "--snapshot", str(CAPTURE / "raw/source.html"),
        "--access-report", str(CAPTURE / "metadata/capture.json"),
        "--output-root", str(output),
    ])
    assert result == 0
    run_dir = next(output.iterdir())
    metadata = json.loads((run_dir / "metadata/capture.json").read_text())
    assert metadata["captured_at_utc"] == "2026-10-10T15:51:49.776520+00:00"
    assert metadata["capture_timestamp_basis"] == "browser acquisition time"
    assert json.loads((run_dir / "validation/results.json").read_text())["valid"] is True
