from __future__ import annotations

import json
import socket
from collections import Counter
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from football_data_hub.domain.classification.engine import calculate_standings
from football_data_hub.domain.classification.models import (
    ClassificationFilter,
    MatchResult,
    Team,
)
from football_data_hub.domain.classification.results import (
    build_group2_results_matrix,
    list_group2_results,
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


def test_extracts_stadium_and_referee_only_where_the_source_provides_them(source_data):
    _, _, matches = source_data
    played = [match for match in matches if match.status == "played"]
    unplayed = [match for match in matches if match.status == "unplayed"]
    assert len(played) == 59
    assert all(match.stadium_name and match.stadium_id and match.stadium_url for match in played)
    assert all(match.referee_name and match.referee_id and match.referee_url for match in played)
    assert len({match.stadium_id for match in played}) == 19
    assert len({match.referee_id for match in played}) == 42
    assert all(
        match.stadium_id is match.stadium_name is match.stadium_url is None
        and match.referee_id is match.referee_name is match.referee_url is None
        for match in unplayed
    )
    first = next(match for match in matches if match.match_id == "272516")
    assert (first.stadium_id, first.stadium_name) == ("55", "Nuevo Mirador")
    assert first.stadium_url == "https://www.bdfutbol.com/es/s/55.html"
    assert (first.referee_id, first.referee_name) == ("r601469", "Ramo Andrés")
    assert first.referee_url == "https://www.bdfutbol.com/es/r/r601469.html"


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


def test_matchday_six_result_list_matches_source_rows_by_id(source_data):
    _, teams, matches = source_data
    entries = list_group2_results(teams, matches, matchday=6)
    assert len(entries) == 10
    assert [entry.match.match_id for entry in entries] == [
        "272572", "272566", "272568", "272569", "272567",
        "272570", "272571", "272573", "272574", "272575",
    ]
    expected = {
        "272572": ("Real Madrid Castilla", "Atlético Madrileño", 3, 2),
        "272566": ("Alcorcón", "Juventud de Torremolinos", 5, 0),
        "272568": ("FC Cartagena", "Águilas FC", 4, 1),
        "272569": ("Hércules", "Jaén", 0, 0),
        "272567": ("Algeciras", "Rayo Majadahonda", 1, 0),
        "272570": ("Huesca", "Europa", 3, 1),
        "272571": ("Murcia", "Gimnàstic de Tarragona", 2, 0),
        "272573": ("Sant Andreu", "Antequera", 2, 2),
        "272574": ("Villarreal B", "UD Ibiza", 0, 1),
        "272575": ("Zaragoza", "Teruel", 4, 1),
    }
    observed = {
        entry.match.match_id: (
            entry.home_team.name,
            entry.away_team.name,
            entry.match.home_goals,
            entry.match.away_goals,
        )
        for entry in entries
    }
    assert observed == expected
    assert all(entry.home_team.crest_url for entry in entries)
    assert all(entry.away_team.crest_url for entry in entries)
    all_entries = list_group2_results(teams, matches)
    assert len(all_entries) == 380
    dates = [entry.match.source_match_date for entry in all_entries]
    assert dates == sorted(dates)
    assert all(entry.match.match_id for entry in all_entries)


def test_results_matrix_has_one_cell_per_fixture_and_null_pending_scores(source_data):
    _, teams, matches = source_data
    matrix = build_group2_results_matrix(teams, matches)
    assert len(matrix.rows) == 20
    assert len(matrix.teams) == 20
    assert all(len(row.cells) == 20 for row in matrix.rows)
    cells = [cell for row in matrix.rows for cell in row.cells]
    assert sum(cell.state == "diagonal" for cell in cells) == 20
    fixture_cells = [cell for cell in cells if cell.state == "fixture"]
    assert len(fixture_cells) == 380
    assert sum(cell.match_status == "played" for cell in fixture_cells) == 59
    assert sum(cell.match_status == "unplayed" for cell in fixture_cells) == 321
    assert len({cell.match_id for cell in fixture_cells}) == 380
    assert not any(cell.state == "missing" for cell in cells)
    matrix_by_pair = {
        (cell.row_team_id, cell.column_team_id): cell
        for row in matrix.rows
        for cell in row.cells
    }
    match_by_id = {match.match_id: match for match in matches}
    def cell_for(match_id: str):
        match = match_by_id[match_id]
        return matrix_by_pair[(match.home_team_id, match.away_team_id)]

    assert cell_for("272574").outcome == "home_loss"
    assert cell_for("272573").outcome == "draw"
    assert cell_for("272575").outcome == "home_win"
    pending = cell_for("272576")
    assert pending.match_id == "272576"
    assert pending.match_status == "unplayed"
    assert pending.home_goals is pending.away_goals is pending.outcome is None


def test_results_matrix_rejects_collisions_and_marks_absent_pairs_explicitly():
    teams = (Team(1, "Home"), Team(2, "Away"), Team(3, "Other"))
    match = _match("one", 1, date(2026, 8, 30), 1, 2, 1, 0)
    matrix = build_group2_results_matrix(teams, (match,))
    assert matrix.rows[0].cells[0].state == "diagonal"
    assert matrix.rows[0].cells[1].state == "fixture"
    assert matrix.rows[0].cells[2].state == "missing"
    with pytest.raises(ValueError, match="Fixture local/visitante duplicado"):
        build_group2_results_matrix(teams, (match, replace(match, match_id="duplicate")))


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
    assert payload["schema_version"] == 2
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
    first_loaded = next(match for match in loaded_matches if match.match_id == "272516")
    assert first_loaded.stadium_name == "Nuevo Mirador"
    assert first_loaded.referee_id == "r601469"
    assert result.source_capture_id == CAPTURE_ID
    assert result.source_snapshot == SNAPSHOT_RELATIVE
    assert result.rows[0].team.team_id == 39
