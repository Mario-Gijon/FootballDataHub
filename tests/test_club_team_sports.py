from __future__ import annotations

import gzip
import json
from pathlib import Path

from football_data_hub.parsers.club_team_sports import build_club_team_sports_data
from football_data_hub.storage.club_team_exports import write_club_team_exports


def _source(captured_at: str = "2026-10-08T12:00:00+00:00") -> dict:
    return {
        "access_status": "VALID",
        "http_status": 200,
        "captured_at_utc": captured_at,
        "rendered_html_sha256": f"sha-{captured_at}",
        "snapshot_directory": f"data/raw/bdfutbol/{captured_at}/snapshot",
    }


def _cells(values: list[str | None]) -> list[dict]:
    return [
        {"column_index": index, "column_span": 1, "text": value or "", "links": []}
        for index, value in enumerate(values)
    ]


def _row(index: int, values: list[str | None], *, kind: str = "data", classes: list[str] | None = None) -> dict:
    return {"row_index": index, "kind": kind, "row_role": "header" if kind == "header" else "data", "classes": classes or [], "cells": _cells(values)}


def _team_identity(team_id: str, club_id: str, name: str) -> dict:
    return {
        "entity_type": "team_season",
        "entity_id": team_id,
        "view": "team_alignment",
        "club_id": club_id,
        "title": name,
        "url": f"https://www.bdfutbol.com/es/t/{team_id}.html",
        "source": _source(),
        "relationships": [{"entity_type": "club", "entity_id": club_id, "name": name}],
        "tables": [],
        "team_data": {},
    }


def _statistics(team_id: str, player_values: list[tuple[str, list[str | None]]], headers: list[str]) -> dict:
    rows = [_row(0, headers, kind="header")]
    player_stats = []
    relations = []
    for row_index, (player_id, values) in enumerate(player_values, start=1):
        rows.append(_row(row_index, values))
        player_stats.append({"team_season_id": team_id, "player_id": player_id, "player_url": f"https://www.bdfutbol.com/es/j/{player_id}.html", "source_row_index": row_index})
        relations.append({"entity_type": "player", "entity_id": player_id, "occurrences": [{"source_table_id": "c3p0", "source_row_index": row_index}]})
    return {
        "entity_type": "team_season",
        "entity_id": team_id,
        "view": "team_statistics",
        "url": f"https://www.bdfutbol.com/es/t/{team_id}.html?t=lista",
        "source": _source(),
        "tables": [{"table_id": "c3p0", "header_cells": headers, "rows": rows}],
        "team_data": {"player_statistics": player_stats},
        "relationships": relations,
    }


def _roster(team_id: str, club_id: str, players: list[str], coach_ids: tuple[str, ...] = ()) -> dict:
    rows = []
    coaches = []
    for index, player_id in enumerate(players, start=1):
        rows.append({
            "team_season_id": team_id,
            "player_id": player_id,
            "player_url": f"https://www.bdfutbol.com/es/j/{player_id}.html",
            "name_raw": f"Jugador {player_id}",
            "shirt_number_raw": str(index),
            "position_raw": "Delantero",
            "birth_date_raw": "01/01/2000",
            "birth_place_raw": "Jaén",
            "birth_province_raw": "Jaén",
            "source_row_index": index,
        })
    for index, coach_id in enumerate(coach_ids, start=1):
        coaches.append({
            "team_season_id": team_id,
            "coach_id": coach_id,
            "coach_url": f"https://www.bdfutbol.com/es/l/{coach_id}.html",
            "name_raw": f"Entrenador {coach_id}",
            "source_row_index": index,
            "raw_cells": _cells(["", "", f"Entrenador {coach_id}", "50", "Ciudad", "Provincia"]),
        })
    return {
        "entity_type": "team_season",
        "entity_id": team_id,
        "view": "team_roster",
        "club_id": club_id,
        "url": f"https://www.bdfutbol.com/es/t/{team_id}.html?t=plantilla",
        "source": _source(),
        "tables": [],
        "team_data": {"roster_rows": rows, "coach_rows": coaches},
        "relationships": [],
    }


def _tracking(team_id: str, headers: list[str], match_id: str = "272516") -> dict:
    rows = [_row(0, headers, kind="header")]
    cells = _cells(["Jugador Uno", *(["90"] * (len(headers) - 1))])
    cells[0]["links"] = [{"url": "https://www.bdfutbol.com/es/j/j100.html"}]
    cells[-1]["links"] = [{"url": f"https://www.bdfutbol.com/es/p/p.php?id={match_id}"}]
    rows.append({"row_index": 1, "kind": "data", "row_role": "data", "cells": cells})
    return {
        "entity_type": "team_season",
        "entity_id": team_id,
        "view": "team_tracking",
        "url": f"https://www.bdfutbol.com/es/t/{team_id}.html?t=seg",
        "source": _source(),
        "tables": [{"table_id": "taula-seguiment", "header_cells": headers, "rows": rows}],
        "team_data": {},
        "relationships": [],
    }


MATCH_HEADERS = ["#", "Fecha", "Temporada", "Competición", "Tipo", "Local", "", "Visitante", "TA", "TR", "GF", "GC"]


def _club_matches(
    club_id: str,
    team_id: str,
    *,
    captured_at: str,
    score: str,
    gf: str,
    gc: str,
    aggregate: tuple[str, str, str, str] = ("1", "1", "0", "0"),
) -> tuple[dict, dict]:
    canonical = {
        "entity_type": "club", "entity_id": club_id, "view": "club_matches",
        "url": f"https://www.bdfutbol.com/es/p/{club_id}.html",
        "source": _source("2026-10-08T11:00:00+00:00"), "relationships": [], "team_data": {},
        "tables": [
            {"table_id": "tpartits", "header_cells": MATCH_HEADERS, "rows": [_row(0, MATCH_HEADERS, kind="header")]},
            {"table_id": "t1", "header_cells": ["Temporada", "PJ", "PG", "PE", "PP"],
             "rows": [_row(0, ["Temporada", "PJ", "PG", "PE", "PP"], kind="header"), _row(1, ["2026-27", *aggregate])]},
        ],
    }
    match_cells = ["1", "01/10/2026", "2026-27", "1rf", "Jornada 1", "Home", score, "Away", "0", "0", gf, gc]
    variant = {
        "entity_type": "club", "entity_id": club_id, "view": "club_matches",
        "url": f"https://www.bdfutbol.com/es/p/{club_id}.html?cat=1rf&temp=2026-27",
        "view_variant": {"variant_id": "cat-1rf__temp-2026-27", "filter_parameters": {"cat": "1rf", "temp": "2026-27"}},
        "source": _source(captured_at), "team_data": {},
        "tables": [
            {"table_id": "tpartits", "header_cells": MATCH_HEADERS,
             "rows": [_row(0, MATCH_HEADERS, kind="header"), _row(1, match_cells)]},
            {"table_id": "t1", "header_cells": ["Temporada", "PJ", "PG", "PE", "PP"],
             "rows": [_row(0, ["Temporada", "PJ", "PG", "PE", "PP"], kind="header"), _row(1, ["2026-27", *aggregate])]},
        ],
        "relationships": [{"entity_type": "match", "entity_id": "272516", "url": "https://www.bdfutbol.com/es/p/p.php?id=272516",
                           "occurrences": [{"source_table_id": "tpartits", "source_row_index": 1}]}],
    }
    return canonical, variant


def _base_pages() -> list[dict]:
    headers = ["#", "", "", "Apodo", "Pos", "PJ", "PT", "PC", "PS", "PX", "C", "Min", "TA", "TR", "G", "Minutos/G", "GP", "GPP", "GE", "PG", "PE", "PP"]
    pages = []
    for team_id, club_id, name in (("t2026-1", "e1", "Home"), ("t2026-2", "e2", "Away")):
        pages.append(_team_identity(team_id, club_id, name))
        pages.append(_roster(team_id, club_id, ["j100", "j101"], ("l10", "l11") if team_id.endswith("2") else ("l10",)))
        pages.append(_statistics(team_id, [("j100", ["9", "", "", "Jugador Uno", "9", "0", "0", "0", "0", "0", "0", "0", "-", "-", "0", "-", "0", "0", "0", "0", "0", "0"]),
                                           ("j101", ["10", "", "", "Jugador Dos", "10", "—", "0", "0", "0", "0", "0", "", "-", "-", "0", "-", "0", "0", "0", "0", "0", "0"])], headers))
        pages.append(_tracking(team_id, ["", "1", "2", "3", "4", "5", "6"] if team_id.endswith("1") else ["", "1", "2", "3", "4", "6"]))
        pages.append({
            "entity_type": "team_season", "entity_id": team_id, "view": "team_transfers",
            "url": f"https://www.bdfutbol.com/es/t/{team_id}.html?t=altas", "source": _source(),
            "tables": [], "team_data": {},
            "relationships": [{"entity_type": "player", "entity_id": "j100", "name": "Jugador Uno",
                                "url": "https://www.bdfutbol.com/es/j/j100.html",
                                "source_table_id": "movements", "source_row_index": 1,
                                "occurrences": [{"source_table_id": "movements", "source_row_index": 1}]}],
        })
    canonical_home, variant_home = _club_matches("e1", "t2026-1", captured_at="2026-10-08T12:00:00+00:00", score="2 0", gf="2", gc="0")
    canonical_away, variant_away = _club_matches("e2", "t2026-2", captured_at="2026-10-08T13:00:00+00:00", score="2 1", gf="1", gc="2", aggregate=("1", "0", "0", "1"))
    pages.extend([canonical_home, canonical_away, variant_home, variant_away])
    return pages


def test_statistics_keep_all_22_positions_and_normalize_only_numeric_shapes() -> None:
    data = build_club_team_sports_data(_base_pages())
    first = next(row for row in data["player_statistics"] if row["team_season_id"] == "t2026-1" and row["player_id"] == "j100")
    assert len(first["columns"]) == 22
    assert [item["column_index"] for item in first["columns"]] == list(range(22))
    assert [item["header_original"] for item in first["columns"]][0:6] == ["#", "", "", "Apodo", "Pos", "PJ"]
    assert first["columns"][5]["normalized_integer"] == 0
    assert first["columns"][5]["raw_value"] == "0"
    assert first["columns"][3]["normalized_integer"] is None
    assert first["columns"][3]["raw_value"] == "Jugador Uno"
    second = next(row for row in data["player_statistics"] if row["team_season_id"] == "t2026-1" and row["player_id"] == "j101")
    assert second["columns"][5]["normalized_integer"] is None
    assert second["columns"][5]["raw_value"] == "—"
    assert second["columns"][11]["value_status"] == "MISSING_OR_PLACEHOLDER"
    assert second["columns"][20]["interpretation_status"] == "PENDING_INTERPRETATION"
    optional = _statistics("t2026-3", [("j300", ["7", "Jugador Tres", "0"])], ["#", "Apodo", "PJ"])
    optional_result = build_club_team_sports_data([optional])["player_statistics"][0]
    assert len(optional_result["columns"]) == 3
    assert optional_result["columns"][-1]["normalized_integer"] == 0


def test_rosters_keep_zero_rows_duplicate_players_and_multiple_coaches() -> None:
    data = build_club_team_sports_data(_base_pages())
    assert len(data["rosters"]) == 4
    assert len([row for row in data["rosters"] if row["player_id"] == "j100"]) == 2
    assert data["duplicate_player_memberships"] == [{"player_id": "j100", "team_season_ids": ["t2026-1", "t2026-2"]},
                                                     {"player_id": "j101", "team_season_ids": ["t2026-1", "t2026-2"]}]
    assert data["multi_coach_teams"] == [{"team_season_id": "t2026-2", "coach_ids": ["l10", "l11"]}]
    assert sum(item["zero_appearance_players"] for item in data["coverage_by_team"]) == 2
    assert all(item["statistics_players"] == item["roster_players"] for item in data["coverage_by_team"])
    assert len(data["movement_references"]) == 2
    assert {item["entity_id"] for item in data["movement_references"]} == {"j100"}
    assert all(item["source_table_id"] == "movements" and item["snapshot_sha256"] for item in data["movement_references"])


def test_matches_from_both_clubs_are_deduplicated_and_timestamp_variance_is_temporal() -> None:
    competition = [{
        "match_id": "272516", "date": "2026-10-01", "home_team_name": "Home", "away_team_name": "Away",
        "home_team_season_id": "t2026-1", "away_team_season_id": "t2026-2", "home_goals": 2, "away_goals": 1,
        "result_status": "played", "fixture_status": "played", "result_raw": "2 1",
        "group": "I", "_captured_at_utc": "2026-10-08T10:00:00+00:00",
    }]
    data = build_club_team_sports_data(_base_pages(), competition)
    assert data["summary"]["unique_played_matches"] == 1
    assert data["summary"]["played_match_observations"] == 2
    match = data["matches_played"][0]
    assert match["source_observation_count"] == 2
    assert match["source_club_ids"] == ["e1", "e2"]
    assert match["home_goals"] == 2 and match["away_goals"] == 1
    assert match["competition_comparison"]["score_match"] is True
    temporal = next(item for item in data["incidents"] if item["code"] == "MATCH_SOURCE_VALUES_DIFFER")
    assert temporal["severity"] == "temporal_review"
    assert set(temporal["captured_at_utc"]) == {"2026-10-08T12:00:00+00:00", "2026-10-08T13:00:00+00:00"}
    assert all(item["status"] == "VALIDATED" for item in data["coverage_by_club"])


def test_tracking_header_variants_are_preserved_without_synthesizing_column_five() -> None:
    data = build_club_team_sports_data(_base_pages(), [{
        "match_id": None, "round": 5, "home_team_season_id": "t2026-2", "away_team_season_id": "t2026-1",
        "home_team_name": "Away", "away_team_name": "Home", "result_status": "scheduled", "result_raw": "—",
        "_captured_at_utc": "2026-10-08T12:00:00+00:00",
    }])
    tracking = {item["team_season_id"]: item for item in data["tracking_variants"]}
    assert tracking["t2026-1"]["header_5_present"] is True
    assert tracking["t2026-2"]["headers_original"] == ["", "1", "2", "3", "4", "6"]
    assert tracking["t2026-2"]["header_5_present"] is False
    row = next(item for item in data["tracking_player_rows"] if item["team_season_id"] == "t2026-2")
    assert [item["header_original"] for item in row["columns"]] == ["", "1", "2", "3", "4", "6"]
    assert row["columns"][-1]["match_id"] == "272516"
    assert any(item["code"] == "TEAM_TRACKING_HEADER_5_ABSENT" for item in data["incidents"])
    incident = next(item for item in data["incidents"] if item["code"] == "TEAM_TRACKING_HEADER_5_ABSENT")
    assert incident["jornada_5_fixture"]["result_status"] == "scheduled"
    assert "aplazado/sin resultado" in incident["explanation"]


def test_incomplete_all_match_variant_is_reported_without_false_aggregate_error() -> None:
    pages = _base_pages()
    pages = [page for page in pages if page.get("url") != "https://www.bdfutbol.com/es/p/e2.html?cat=1rf&temp=2026-27"]
    data = build_club_team_sports_data(pages)
    away = next(item for item in data["coverage_by_club"] if item["club_id"] == "e2")
    assert away["all_match_variant_captured"] is False
    assert away["status"] == "INCOMPLETE"
    assert all(value is None for value in away["checks"].values())
    assert any(item["code"] == "CLUB_MATCH_ALL_VARIANT_MISSING" and item["club_id"] == "e2" for item in data["incidents"])


def test_competition_match_ids_can_confirm_scope_difference_in_season_aggregate() -> None:
    pages = _base_pages()
    for page in pages:
        if page.get("entity_id") == "e1" and page.get("view") == "club_matches":
            aggregate = next(table for table in page["tables"] if table.get("table_id") == "t1")
            row = next(row for row in aggregate["rows"] if row.get("kind") == "data")
            row["cells"][1]["text"] = "2"
            row["cells"][2]["text"] = "2"
    competition = [{
        "match_id": "272516", "date": "2026-10-01", "home_team_name": "Home", "away_team_name": "Away",
        "home_team_season_id": "t2026-1", "away_team_season_id": "t2026-2", "home_goals": 2, "away_goals": 1,
        "result_status": "played", "fixture_status": "played", "result_raw": "2 1",
        "group": "I", "_captured_at_utc": "2026-10-08T10:00:00+00:00",
    }]
    data = build_club_team_sports_data(pages, competition)
    home = next(row for row in data["coverage_by_club"] if row["club_id"] == "e1")
    assert home["competition_match_sets_equal"] is True
    assert home["status"] == "COMPETITION_CROSSCHECKED_SCOPE_DIFFERENCE"
    issue = next(item for item in data["incidents"] if item["code"] == "CLUB_AGGREGATE_SCOPE_DIFFERENCE")
    assert issue["severity"] == "warning"


def test_compact_exports_are_gzip_readable_and_keep_normalized_provenance(tmp_path: Path) -> None:
    all_pages = _base_pages()
    # Synthetic tuples exercise the additive gzip export contract; live raw
    # evidence is checked by the optional snapshot integration test.
    home_tuple = [
        2026, "1rf", "", "01/10/2026", 1, "Home", 2, 1, 272516,
        "Away", 1, 2, 1, 600001, "Jornada 1", "1", 2, 0, "2026-27",
    ]
    away_tuple = [*home_tuple]
    away_tuple[4] = 0
    away_tuple[12] = -1
    away_tuple[16] = 1
    for page in all_pages:
        if page.get("view") != "club_matches" or "?" in page.get("url", ""):
            continue
        source_values = home_tuple if page.get("entity_id") == "e1" else away_tuple
        page["club_data"] = {
            "embedded_match_data": {
                "source_variable": "P",
                "parse_status": "PARSED_19_POSITION_TUPLES",
                "tuple_width": 19,
                "record_count": 1,
                "records": [{"source_record_index": 0, "source_values_raw": source_values}],
            },
        }
    pages = [page for page in all_pages if "?cat=1rf&temp=2026-27" not in page["url"]]
    variants = [page for page in all_pages if "?cat=1rf&temp=2026-27" in page["url"]]
    output = write_club_team_exports(
        parsed_pages=pages,
        variant_pages=variants,
        coverage={"summary": {}, "resources": [], "interaction_variants": []},
        output_root=tmp_path,
        compact=True,
        competition_matches=[],
        competition_selection={
            "selection_status": "SELECTED",
            "selection_mode": "explicit",
            "selected_extraction_key": "hito1b-test",
        },
    )
    with gzip.open(output / "sports/player_statistics.json.gz", "rt", encoding="utf-8") as stream:
        statistics = json.load(stream)
    with gzip.open(output / "sports/matches_played.json.gz", "rt", encoding="utf-8") as stream:
        matches = json.load(stream)
    with gzip.open(output / "sports/tracking_player_rows.json.gz", "rt", encoding="utf-8") as stream:
        tracking = json.load(stream)
    with gzip.open(output / "sports/embedded_match_observations.json.gz", "rt", encoding="utf-8") as stream:
        embedded_observations = json.load(stream)
    with gzip.open(output / "sports/matches_from_embedded_data.json.gz", "rt", encoding="utf-8") as stream:
        embedded_matches = json.load(stream)
    with gzip.open(output / "dataset_metadata.json.gz", "rt", encoding="utf-8") as stream:
        metadata = json.load(stream)
    assert len(statistics["items"]) == 4
    assert len(statistics["items"][0]["columns"]) == 22
    assert statistics["items"][0]["snapshot_sha256"].startswith("sha-")
    assert len(matches["items"]) == 1
    assert len(matches["items"][0]["source_observations"]) == 2
    assert len(tracking["items"]) == 2
    assert len(embedded_observations["items"]) == 2
    assert embedded_observations["items"][0]["source_values_raw"][8] == 272516
    assert embedded_observations["items"][0]["snapshot_sha256"].startswith("sha-")
    assert len(embedded_matches["items"]) == 1
    assert embedded_matches["items"][0]["source_observation_count"] == 2
    assert (output / "sports/player_statistics.csv.gz").is_file()
    assert (output / "sports/embedded_match_observations.csv.gz").is_file()
    assert (output / "sports/matches_from_embedded_data.csv.gz").is_file()
    competition_selection = metadata["competition_crosscheck_source"]
    assert competition_selection["selection"]["selected_extraction_key"] == "hito1b-test"
    assert competition_selection["played_fixtures_loaded"] == 0
    assert competition_selection["normalized_state_counts"] == {
        "played": 0, "scheduled": 0, "unresolved": 0, "inconsistent": 0,
    }


def _embedded_club_page(club_id: str, source_values: list, *, index: int = 0) -> dict:
    return {
        "entity_type": "club",
        "entity_id": club_id,
        "view": "club_matches",
        "url": f"https://www.bdfutbol.com/es/p/{club_id}.html",
        "source": _source(),
        "club_data": {
            "embedded_match_data": {
                "source_variable": "P",
                "parse_status": "PARSED_19_POSITION_TUPLES",
                "tuple_width": 19,
                "record_count": 1,
                "records": [{"source_record_index": index, "source_values_raw": source_values}],
            },
        },
        "tables": [],
        "relationships": [],
    }


def test_embedded_match_observations_deduplicate_ids_and_crosscheck_without_losing_sources() -> None:
    # Synthetic 19-position rows model two club-page observations of one match.
    home_tuple = [
        2026, "1rf", "", "01/10/2026", 1, "Home", 2, 1, 272516,
        "Away", 1, 2, 1, 600001, "Jornada 1", "1", 2, 0, "2026-27",
    ]
    away_tuple = [*home_tuple]
    away_tuple[4] = 0
    away_tuple[12] = -1
    away_tuple[16] = 1
    pages = [
        _team_identity("t2026-1", "e1", "Home"),
        _team_identity("t2026-2", "e2", "Away"),
        _embedded_club_page("e1", home_tuple),
        _embedded_club_page("e2", away_tuple),
    ]
    competition = [{
        "match_id": "272516",
        "date": "2026-10-01",
        "home_team_name": "Home",
        "away_team_name": "Away",
        "home_team_season_id": "t2026-1",
        "away_team_season_id": "t2026-2",
        "home_goals": 2,
        "away_goals": 1,
        "result_raw": "2 1",
        "result_status": "played",
        "fixture_status": "played",
        "season": "2026/27",
    }]

    data = build_club_team_sports_data(pages, competition)

    assert len(data["embedded_match_observations"]) == 2
    assert len(data["matches_from_embedded_data"]) == 1
    assert data["matches_from_embedded_data"][0]["source_observation_count"] == 2
    assert len(data["matches_from_embedded_data"][0]["source_observations"]) == 2
    assert len(data["duplicate_embedded_matches"]) == 1
    assert data["embedded_match_competition_crosscheck"]["match_ids_equal"] is True
    assert data["embedded_match_competition_crosscheck"]["matches_all_fields_equal"] == 1


def test_embedded_match_result_code_disagreement_is_reported_and_raw_is_preserved() -> None:
    # Synthetic anomaly fixture; real raw review separately found three historic
    # source codes that disagree with their score, so scores must not overwrite P.
    source_tuple = [
        2026, "1rf", "", "01/10/2026", 1, "Home", 2, 1, 272516,
        "Away", 1, 2, -1, 600001, "Jornada 1", "1", 2, 0, "2026-27",
    ]
    pages = [
        _team_identity("t2026-1", "e1", "Home"),
        _team_identity("t2026-2", "e2", "Away"),
        _embedded_club_page("e1", source_tuple),
    ]

    data = build_club_team_sports_data(pages)

    observation = data["embedded_match_observations"][0]
    assert observation["source_club_result_code_raw"] == -1
    assert observation["source_club_result_from_score"] == 1
    assert observation["source_club_result_validation"] == "DIFFERS_FROM_SCORE"
    assert any(
        incident["code"] == "EMBEDDED_MATCH_RESULT_CODE_DIFFERS_FROM_SCORE"
        for incident in data["incidents"]
    )
