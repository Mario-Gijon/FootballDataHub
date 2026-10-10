from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from football_data_hub.domain.statistics.engine import calculate_competition_statistics
from football_data_hub.domain.classification.models import MatchResult, Team
from football_data_hub.domain.statistics.models import CompetitionContext
from football_data_hub.providers.bdfutbol.classification.match_io import load_match_dataset
from football_data_hub.providers.bdfutbol.statistics.parser import (
    StatisticsParseError,
    parse_statistics_page,
    validate_statistics_page_html,
)
from scrape_bdfutbol_group2_statistics import main

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "data/exports/bdfutbol/group2_statistics/20261010T182210.859321Z-28543363"
MATCHES_PATH = ROOT / (
    "data/exports/bdfutbol/group2_classification/derived-res01-20261010T102656Z/"
    "normalized/matches.json"
)


@pytest.fixture(scope="module")
def source_data():
    metadata, teams, matches = load_match_dataset(MATCHES_PATH)
    html = (CAPTURE / "raw/source.html").read_text(encoding="utf-8")
    chart = json.loads((CAPTURE / "raw/chart_data_provider.json").read_text(encoding="utf-8"))
    parsed = parse_statistics_page(html, chart)
    return metadata, teams, matches, html, chart, parsed


def test_source_parser_reads_semantic_summary_penalties_and_chart(source_data):
    _, _, _, html, chart, parsed = source_data
    assert validate_statistics_page_html(html) == ()
    assert parsed.source_summary.teams == 20
    assert parsed.source_summary.matches == 59
    assert parsed.source_summary.goals == 155
    assert parsed.exclusive_penalties.penalties_awarded == 24
    assert parsed.exclusive_penalties.penalties_scored == 21
    assert parsed.exclusive_penalties.penalties_missed == 3
    assert parsed.chart.library == "amCharts 3.15.2"
    assert parsed.chart.points[4].goals == 19
    assert parsed.chart.points[6].goals is None
    assert len(parsed.chart.points) == 38
    assert chart["chart"]["data_provider"][4]["VG"] == 19


def test_parser_rejects_challenge_and_unknown_chart_fields(source_data):
    _, _, _, _, chart, _ = source_data
    assert validate_statistics_page_html("<html><title>Just a moment...</title></html>")
    with pytest.raises(StatisticsParseError):
        parse_statistics_page("<html>Access denied</html>", chart)
    bad_chart = json.loads(json.dumps(chart))
    bad_chart["chart"]["graph_fields"][0]["value_field"] = "unknown"
    with pytest.raises(StatisticsParseError):
        parse_statistics_page(
            (CAPTURE / "raw/source.html").read_text(encoding="utf-8"), bad_chart
        )


def test_engine_matches_competition_summary_and_keeps_future_rounds_null(source_data):
    _, teams, matches, _, _, _ = source_data
    report = calculate_competition_statistics(
        teams, matches, CompetitionContext("Primera Federación", "2026-27", "II")
    )
    stats = report.statistics
    assert (stats.team_count, stats.scheduled_matches, stats.played_matches) == (20, 380, 59)
    assert (stats.home_wins, stats.away_wins, stats.draws, stats.goals) == (28, 16, 15, 155)
    assert stats.yellow_cards == 290
    assert stats.red_cards == 15
    assert stats.goals_per_match == pytest.approx(155 / 59)
    assert stats.rounds[4].coverage == "partial"
    assert (stats.rounds[4].played_matches, stats.rounds[4].goals) == (9, 21)
    assert stats.rounds[6].coverage == "not_started"
    assert (stats.rounds[6].goals, stats.rounds[6].yellow_cards, stats.rounds[6].red_cards) == (
        None,
        None,
        None,
    )


def test_engine_card_coverage_unknowns_and_input_order_are_preserved(source_data):
    _, teams, matches, _, _, _ = source_data
    first_played = next(index for index, match in enumerate(matches) if match.status == "played")
    partial = list(matches)
    partial[first_played] = replace(partial[first_played], home_yellow_cards=None)
    report = calculate_competition_statistics(
        teams, partial, CompetitionContext("Primera Federación", "2026-27", "II")
    )
    assert report.statistics.yellow_cards is None
    assert report.statistics.yellow_card_coverage.matches_with_value == 58
    reversed_report = calculate_competition_statistics(
        teams, tuple(reversed(matches)), CompetitionContext("Primera Federación", "2026-27", "II")
    )
    assert reversed_report == calculate_competition_statistics(
        teams, matches, CompetitionContext("Primera Federación", "2026-27", "II")
    )


def test_records_keep_calculated_ties_and_streak_composition(source_data):
    _, teams, matches, _, _, _ = source_data
    report = calculate_competition_statistics(
        teams, matches, CompetitionContext("Primera Federación", "2026-27", "II")
    )
    away = next(item for item in report.records.match_records if item.kind == "largest_away_win")
    assert {item.match_id for item in away.matches} == {"272523", "272540"}
    winless = [item for item in report.records.streaks if item.kind == "winless" and item.match_count == 6]
    assert len(winless) == 2
    assert {item.team_id for item in winless} == {204, 488}


def test_engine_rejects_duplicate_match_ids_and_unknown_teams(source_data):
    _, teams, matches, _, _, _ = source_data
    context = CompetitionContext("Primera Federación", "2026-27", "II")
    with pytest.raises(ValueError, match="match_id duplicado"):
        calculate_competition_statistics(teams, (*matches, matches[0]), context)
    with pytest.raises(ValueError, match="equipo desconocido"):
        calculate_competition_statistics(
            teams,
            (replace(matches[0], home_team_id=999999),),
            context,
        )


def test_streak_policy_skips_an_unplayed_postponed_fixture_without_fabricating_result():
    teams = (Team(1, "Local"), Team(2, "Visitante"))

    def fixture(
        match_id: str,
        matchday: int,
        status: str,
        home_goals: int | None,
        away_goals: int | None,
        *,
        postponed: bool = False,
    ) -> MatchResult:
        return MatchResult(
            match_id=match_id,
            matchday=matchday,
            matchday_date=date(2026, 8, 1 + matchday),
            source_match_date=date(2026, 8, 1 + matchday),
            home_team_id=1,
            away_team_id=2,
            home_goals=home_goals,
            away_goals=away_goals,
            home_yellow_cards=0 if status == "played" else None,
            away_yellow_cards=0 if status == "played" else None,
            home_red_cards=0 if status == "played" else None,
            away_red_cards=0 if status == "played" else None,
            status=status,  # type: ignore[arg-type]
            unplayed_state="scheduled" if status == "unplayed" else None,
            postponed_by_source_rule=postponed,
        )

    matches = (
        fixture("1", 1, "played", 1, 0),
        fixture("2", 2, "unplayed", None, None, postponed=True),
        fixture("3", 3, "played", 2, 0),
    )
    report = calculate_competition_statistics(
        teams, matches, CompetitionContext("Prueba", "2026-27", "II")
    )
    wins = [item for item in report.records.streaks if item.kind == "winning"]
    assert len(wins) == 1
    assert wins[0].match_count == 2
    assert wins[0].match_ids == ("1", "3")
    assert report.statistics.played_matches == 2
    assert report.statistics.unplayed_matches == 1


def test_reconciliation_reports_numeric_ties_and_jornada_five_discrepancy(source_data):
    reconciliation = json.loads(
        (CAPTURE / "validation/reconciliation.json").read_text(encoding="utf-8")
    )
    assert reconciliation["match_data_alignment"]["status"] == "identical"
    assert reconciliation["match_data_alignment"]["matched_id_count"] == 380
    assert reconciliation["summary"]["metric_differences"] == 0
    red_metric = next(item for item in reconciliation["metrics"] if item["statistic"] == "red_cards_vs_expulsions")
    assert red_metric["status"] == "numeric_match_semantics_unverified"
    away = next(item for item in reconciliation["published_match_records"] if item["kind"] == "largest_away_win")
    assert away["status"] == "published_value_matches_calculated_tie"
    winless = next(item for item in reconciliation["published_streaks"] if item["kind"] == "winless")
    assert winless["status"] == "source_team_among_calculated_ties"
    goal_discrepancy = next(
        item
        for item in reconciliation["round_series"]
        if item["matchday"] == 5 and item["statistic"] == "goals"
    )
    assert (goal_discrepancy["calculated"], goal_discrepancy["published"]) == (21, 19)
    assert reconciliation["temporal_comparison_status"] == "same_match_records_verified"


def test_offline_cli_exports_readable_capture_without_network(tmp_path: Path, source_data):
    del source_data
    output_root = tmp_path / "statistics"
    result = main(
        [
            "--matches",
            str(MATCHES_PATH),
            "--output-root",
            str(output_root),
            "--snapshot",
            str(CAPTURE / "raw/source.html"),
            "--chart-snapshot",
            str(CAPTURE / "raw/chart_data_provider.json"),
            "--access-report",
            str(CAPTURE / "raw/access.json"),
        ]
    )
    assert result == 0
    export = output_root / "20261010T182210.859321Z-28543363"
    derived = json.loads((export / "normalized/derived_statistics.json").read_text())
    exclusive = json.loads((export / "normalized/exclusive_statistics.json").read_text())
    assert derived["statistics"]["played_matches"] == 59
    assert exclusive["items"]["penalties"]["penalties_awarded"] == 24
    assert not (export / "normalized/matches.json").exists()
    with pytest.raises(FileExistsError):
        main(
            [
                "--matches",
                str(MATCHES_PATH),
                "--output-root",
                str(output_root),
                "--snapshot",
                str(CAPTURE / "raw/source.html"),
                "--chart-snapshot",
                str(CAPTURE / "raw/chart_data_provider.json"),
                "--access-report",
                str(CAPTURE / "raw/access.json"),
            ]
        )
