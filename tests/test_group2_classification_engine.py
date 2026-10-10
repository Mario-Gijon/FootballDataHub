from __future__ import annotations

import json
import socket
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from football_data_hub.domain.classification.engine import calculate_standings
from football_data_hub.domain.classification.models import (
    ClassificationFilter,
    MatchResult,
    Team,
)
from football_data_hub.domain.classification.validation import validate_match_set
from football_data_hub.providers.bdfutbol.classification.match_io import (
    export_match_dataset,
    load_match_dataset,
    make_match_dataset,
)
from football_data_hub.providers.bdfutbol.classification.matches import (
    MatchParseError,
    extract_matches,
)
from football_data_hub.providers.bdfutbol.classification.parser import (
    parse_classification_page,
)
from compare_group2_classification import (
    compare_published_standings,
    compare_reference,
)

ROOT = Path(__file__).parents[1]
SOURCE_SNAPSHOT = (
    ROOT
    / "data/exports/bdfutbol/group2_classification/"
    / "20261010T102656.252222Z-72f200ad/raw/source.html"
)
URL = "https://www.bdfutbol.com/es/t/t2026-271rf2.html"
CAPTURE_ID = "20261010T102656.252222Z-72f200ad"
SNAPSHOT_RELATIVE = (
    "data/exports/bdfutbol/group2_classification/"
    f"{CAPTURE_ID}/raw/source.html"
)


@pytest.fixture(scope="module")
def source_html() -> str:
    return SOURCE_SNAPSHOT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def source_data(source_html: str):
    parsed = parse_classification_page(source_html, base_url=URL)
    teams, matches = extract_matches(
        source_html, parsed, base_url=URL, captured_at=date(2026, 10, 10)
    )
    return parsed, teams, matches


def _match(
    match_id: str,
    matchday: int,
    match_date: date,
    home: int,
    away: int,
    home_goals: int | None,
    away_goals: int | None,
    *,
    yellow_home: int | None = 0,
    yellow_away: int | None = 0,
    red_home: int | None = 0,
    red_away: int | None = 0,
    postponed: bool | None = False,
) -> MatchResult:
    status = "unplayed" if home_goals is None and away_goals is None else "played"
    return MatchResult(
        match_id=match_id,
        matchday=matchday,
        matchday_date=match_date,
        source_match_date=match_date,
        home_team_id=home,
        away_team_id=away,
        home_goals=home_goals,
        away_goals=away_goals,
        home_yellow_cards=None if status == "unplayed" else yellow_home,
        away_yellow_cards=None if status == "unplayed" else yellow_away,
        home_red_cards=None if status == "unplayed" else red_home,
        away_red_cards=None if status == "unplayed" else red_away,
        status=status,
        unplayed_state="unknown" if status == "unplayed" else None,
        postponed_by_source_rule=postponed,
        source_references=(f"fixture:{match_id}",),
    )


def test_extracts_all_matchdays_with_stable_ids_and_source_references(source_data):
    _, teams, matches = source_data
    assert len(teams) == 20
    assert len(matches) == 380
    assert len({match.match_id for match in matches}) == 380
    assert Counter(match.matchday for match in matches) == {round_number: 10 for round_number in range(1, 39)}
    assert Counter(match.status for match in matches) == {"played": 59, "unplayed": 321}
    assert Counter(match.unplayed_state for match in matches if match.status == "unplayed") == {
        "scheduled": 320,
        "result_unavailable_at_capture": 1,
    }
    assert all(match.match_id and len(match.source_references) == 2 for match in matches)
    assert all(match.home_team_id != match.away_team_id for match in matches)


def test_unplayed_matches_keep_null_scores_and_cards(source_data):
    _, _, matches = source_data
    unplayed = next(match for match in matches if match.status == "unplayed")
    assert unplayed.home_goals is None
    assert unplayed.away_goals is None
    assert unplayed.home_yellow_cards is None
    assert unplayed.away_yellow_cards is None
    assert unplayed.home_red_cards is None
    assert unplayed.away_red_cards is None
    assert unplayed.source_fields["g1"] == "-1"
    assert unplayed.source_fields["g2"] == "-1"


def test_cross_checks_sp_against_resultats_and_rejects_conflicting_rows(source_html):
    parsed = parse_classification_page(source_html, base_url=URL)
    _, matches = extract_matches(
        source_html, parsed, base_url=URL, captured_at=date(2026, 10, 10)
    )
    assert sum(match.status == "played" and match.source_match_url is not None for match in matches) == 59
    changed = source_html.replace('"id":"272516"', '"id":"272517"', 1)
    with pytest.raises(MatchParseError, match="duplicados"):
        extract_matches(changed, parsed, base_url=URL)
    changed_score = source_html.replace('"g1":"1","g2":"3"', '"g1":"2","g2":"3"', 1)
    with pytest.raises(MatchParseError, match="Marcador distinto"):
        extract_matches(changed_score, parsed, base_url=URL)


def test_match_set_invariants_for_full_snapshot(source_data):
    _, teams, matches = source_data
    report = validate_match_set(
        teams,
        matches,
        expected_teams=20,
        expected_rounds=38,
        fixtures_per_round=10,
    )
    assert report["valid"]
    assert report["counts"]["played"] == 59
    assert report["counts"]["unplayed"] == 321
    assert report["counts"]["postponed_by_source_rule"] == 0
    assert report["totals"]["goals_for_across_matches"] == report["totals"]["goals_against_across_matches"]
    assert all(check["status"] == "pass" for check in report["checks"])


def test_nine_live_bdfutbol_javascript_scenarios_match_by_team_id(source_data):
    _, teams, matches = source_data
    derived = ROOT / "data/exports/bdfutbol/group2_classification/derived-clas01b-20261010T102656Z"
    metadata, _, _ = load_match_dataset(derived / "normalized/matches.json")
    reference = json.loads(
        (derived / "validation/bdfutbol_js_reference.json").read_text(encoding="utf-8")
    )
    report = compare_reference(teams, matches, metadata, reference)
    assert report["scenario_count"] == 9
    assert report["correct_scenarios"] == 9
    assert report["pending_scenarios"] == 0
    assert sum(item["fields_compared"] for item in report["scenarios"]) == 1800
    assert all(item["teams_compared"] == 20 for item in report["scenarios"])
    assert all(item["fields_identical"] == 200 for item in report["scenarios"])

    published = json.loads(
        (derived.parent / CAPTURE_ID / "normalized/classification.json").read_text(
            encoding="utf-8"
        )
    )
    official_report = compare_published_standings(teams, matches, metadata, published)
    assert official_report["status"] == "correct"
    assert official_report["teams_compared"] == 20
    assert official_report["fields_identical"] == 200


def test_general_local_visitor_and_matchday_cap(source_data):
    _, teams, matches = source_data
    general = calculate_standings(teams, matches, ClassificationFilter(matchday_cap=6))
    local = calculate_standings(
        teams,
        matches,
        ClassificationFilter(classification_type="local", matchday_cap=6),
    )
    visitor = calculate_standings(
        teams,
        matches,
        ClassificationFilter(classification_type="visitor", matchday_cap=6),
    )
    assert len(general.rows) == len(local.rows) == len(visitor.rows) == 20
    assert general.matches_counted == local.matches_counted == visitor.matches_counted == 59
    assert general.rows[0].team.team_id == 39
    assert general.rows[0].points == 15
    assert general.rows[0].matches_played == 6
    assert sum(row.matches_played for row in general.rows) == 2 * general.matches_counted
    assert sum(row.goals_for for row in general.rows) == sum(
        row.goals_against for row in general.rows
    )
    assert all(
        row.matches_played == row.wins + row.draws + row.losses
        and row.points == 3 * row.wins + row.draws
        for row in general.rows
    )
    assert local.classification_type == "local"
    assert visitor.classification_type == "visitor"
    assert local.rows[0].team.team_id == 40
    assert visitor.rows[0].team.team_id == 94
    assert calculate_standings(
        teams, matches, ClassificationFilter(matchday_cap=5)
    ).matches_counted == 49


def test_date_and_round_ranges_are_inclusive_and_combine_with_cap():
    teams = (Team(1, "Home"), Team(2, "Away"))
    matches = (
        _match("a", 1, date(2026, 8, 29), 1, 2, 2, 0),
        _match("b", 2, date(2026, 9, 5), 2, 1, 1, 0),
        _match("c", 3, date(2026, 9, 12), 1, 2, 1, 1),
    )
    dates = calculate_standings(
        teams,
        matches,
        ClassificationFilter(
            matchday_cap=3,
            range_type="dates",
            date_start=date(2026, 8, 29),
            date_end=date(2026, 9, 5),
        ),
    )
    rounds = calculate_standings(
        teams,
        matches,
        ClassificationFilter(
            matchday_cap=2, range_type="rounds", round_start=1, round_end=3
        ),
    )
    assert dates.matches_counted == 2
    assert rounds.selected_matchday == 2
    assert rounds.matches_counted == 2
    assert dates.rows[0].points == rounds.rows[0].points


def test_unplayed_and_postponed_are_filtered_without_inventing_stats():
    teams = (Team(1, "Home"), Team(2, "Away"))
    played = _match("played", 1, date(2026, 8, 29), 1, 2, 1, 0)
    unplayed = _match("unplayed", 2, date(2026, 9, 7), 2, 1, None, None)
    postponed = _match(
        "postponed-rule", 3, date(2026, 9, 12), 1, 2, 2, 1, postponed=True
    )
    include = calculate_standings(
        teams,
        (played, unplayed, postponed),
        ClassificationFilter(matchday_cap=3),
    )
    exclude = calculate_standings(
        teams,
        (played, unplayed, postponed),
        ClassificationFilter(matchday_cap=3, include_postponed=False),
    )
    assert include.matches_counted == 2
    assert include.unplayed_matches_skipped == 1
    assert exclude.matches_counted == 1
    assert {row.matches_played for row in exclude.rows} == {1}


def test_tie_breaks_points_goal_difference_goals_and_discipline():
    names = ("Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel")
    teams = tuple(Team(index + 1, name) for index, name in enumerate(names))
    matchday = date(2026, 8, 30)
    matches = (
        _match("a", 1, matchday, 1, 2, 3, 2),
        _match("b", 1, matchday, 3, 4, 2, 1),
        _match("c", 1, matchday, 5, 6, 1, 0, yellow_home=8),
        _match("d", 1, matchday, 7, 8, 1, 0, yellow_home=2),
    )
    table = calculate_standings(teams, matches, ClassificationFilter(matchday_cap=1))
    assert [row.team.team_id for row in table.rows[:4]] == [1, 3, 7, 5]


def test_missing_disciplinary_data_stays_null_and_does_not_invent_a_tie_break():
    teams = (Team(2, "Home B"), Team(4, "Home D"), Team(1, "Away A"), Team(3, "Away C"))
    matchday = date(2026, 8, 30)
    matches = (
        _match("b", 1, matchday, 2, 1, 1, 0, yellow_home=None),
        _match("d", 1, matchday, 4, 3, 1, 0, yellow_home=0),
    )
    table = calculate_standings(teams, matches, ClassificationFilter(matchday_cap=1))
    assert [row.team.team_id for row in table.rows[:2]] == [2, 4]
    assert table.rows[0].yellow_cards is None
    assert table.rows[0].disciplinary_score is None
    assert any("Faltan tarjetas" in warning for warning in table.warnings)


def test_duplicate_match_ids_rejected_and_zero_match_teams_retained():
    teams = (Team(1, "Home"), Team(2, "Away"), Team(3, "Idle"))
    match = _match("same", 1, date(2026, 8, 30), 1, 2, 0, 0)
    with pytest.raises(ValueError, match="match_id duplicados"):
        calculate_standings(teams, (match, match))
    table = calculate_standings(teams, (match,), ClassificationFilter(matchday_cap=1))
    idle = next(row for row in table.rows if row.team.team_id == 3)
    assert len(table.rows) == 3
    assert idle.matches_played == idle.points == idle.goals_for == idle.goals_against == 0


def test_matches_json_export_load_and_offline_calculation(tmp_path, source_data, monkeypatch):
    _, teams, matches = source_data
    metadata = {
        "source_capture_id": CAPTURE_ID,
        "source_snapshot": SNAPSHOT_RELATIVE,
        "source": "BDFutbol",
    }
    payload = make_match_dataset(teams=teams, matches=matches, metadata=metadata)
    path = export_match_dataset(tmp_path / "normalized" / "matches.json", payload)
    loaded_metadata, loaded_teams, loaded_matches = load_match_dataset(path)

    def no_network(*_args, **_kwargs):
        raise AssertionError("El motor de dominio intentó usar la red")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    result = calculate_standings(
        loaded_teams,
        loaded_matches,
        ClassificationFilter(matchday_cap=6),
        source_capture_id=loaded_metadata["source_capture_id"],
        source_snapshot=loaded_metadata["source_snapshot"],
    )
    assert json.loads(path.read_text(encoding="utf-8"))["counts"]["played"] == 59
    assert result.source_capture_id == CAPTURE_ID
    assert result.source_snapshot == SNAPSHOT_RELATIVE
    assert result.rows[0].team.team_id == 39
