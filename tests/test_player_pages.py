from __future__ import annotations

import hashlib
import gzip
import json
from pathlib import Path

import pytest

from football_data_hub.parsers.player_pages import (
    PlayerSnapshotError,
    PLAYER_VIEWS,
    build_player_acquisition_inventory,
    build_player_pilot_candidates,
    classify_player_view,
    discover_player_snapshots,
    missing_profile_field_evidence,
    parse_player_html,
    parse_player_snapshot,
    parse_player_snapshot_inventory,
)
from football_data_hub.storage.player_exports import build_player_exports


def _metadata(url: str, html: str) -> dict[str, object]:
    return {
        "requested_url": url,
        "final_url": url,
        "captured_at_utc": "2026-10-08T12:00:00+00:00",
        "access_status": "VALID",
        "http_status": 200,
        "rendered_html_sha256": hashlib.sha256(html.encode()).hexdigest(),
        "page_title": "Synthetic player page",
    }


def _profile_html() -> str:
    return """<!doctype html><html><head><title>Player profile</title></head><body>
    <a href="../j/j123.html">Trayectoria</a>
    <a href="../j/j123.html?p=stats">Estadísticas</a>
    <a href="../p/j123.html">Partidos</a>
    <a href="../p/jr123.html">Rivales</a>
    <div class="hero"><div class="container"><div class="row pb-2">
      <div class="col"><h1>Alias</h1>
        <div class="float-left"><div>Nombre completo</div><div class="font-weight-bold">Player Full Name</div></div>
        <div class="float-left"><div>Fecha de nacimiento</div><div class="font-weight-bold">02/01/2000 (26 años)</div></div>
        <div class="float-left"><div>Lugar de nacimiento</div><div class="font-weight-bold"><a href="../a/place.html">Town</a></div></div>
        <div class="float-left"><div>País de nacimiento</div><div class="font-weight-bold"><a href="../a/country.html">España</a></div></div>
        <div class="float-left"><div>Demarcación</div><div class="font-weight-bold">Defensa</div></div>
        <div class="float-left"><div>Altura</div><div class="font-weight-bold">185 cm</div></div>
      </div>
      <div class="col"><img class="img-enlargable" src="../../i/j/123.jpg" alt=""></div>
    </div></div></div>
    <select id="sel-equip"><option value="-">Todos</option><option value="7">Club A</option></select>
    <div id="traj"><table class="taula_estil traject"><tbody>
      <tr><th>Temp</th><th>Equipo</th><th>País</th><th title="Partidos Jugados">PJ</th><th title="Goles" style="display:none">G</th></tr>
      <tr><td>2024-25</td><td><a href="../t/t2024-257.html">Club A</a></td><td>España</td><td>0</td><td>-</td></tr>
      <tr><td>2024-25</td><td><a href="../t/t2024-258.html">Club B</a></td><td>España</td><td>4</td><td>0</td></tr>
      <tr><td colspan="2">Total</td><td></td><td>4</td><td>0</td></tr>
    </tbody></table></div>
    </body></html>"""


def test_parse_profile_preserves_history_totals_hidden_columns_and_absences() -> None:
    html = _profile_html()
    url = "https://www.bdfutbol.com/es/j/j123.html"
    page = parse_player_html(html, _metadata(url, html), snapshot_directory="raw/player/profile")

    assert page["player_id"] == "j123"
    assert page["view"] == "profile"
    profile = page["view_data"]
    assert profile["full_name_raw"] == "Player Full Name"
    assert profile["birth_date_iso"] == "2000-01-02"
    assert profile["height_cm"] == 185
    assert profile["nationality_raw"] is None
    assert profile["personal_field_status"]["Peso"] == "NOT_FOUND_IN_CAPTURED_SNAPSHOT"
    assert profile["career_completeness"] == "NOT_CERTIFIED_COMPLETE"
    assert [row["season_raw"] for row in profile["career_rows"]] == ["2024-25", "2024-25"]
    assert [row["team_name_raw"] for row in profile["career_rows"]] == ["Club A", "Club B"]
    assert profile["career_rows"][0]["columns"][3]["normalized_integer"] == 0
    assert profile["career_rows"][0]["columns"][4]["value_status"] == "MISSING_OR_PLACEHOLDER"
    assert profile["career_rows"][0]["columns"][4]["hidden_by_inline_style"] is True
    assert len(profile["career_totals_raw"]) == 1
    assert profile["career_totals_raw"][0]["row_role"] == "total"
    assert any("/i/j/123.jpg" in item["url"] for item in profile["photo_references"])
    assert page["coverage"]["parse_status"] == "PARSED"
    assert page["source"]["metadata_sha256_matches"] is True
    assert [tab["label_raw"] for tab in page["view_tabs"]] == [
        "Trayectoria", "Estadísticas", "Partidos", "Rivales",
    ]


def test_profile_semantic_evidence_reuses_parser_field_recognition() -> None:
    assert missing_profile_field_evidence(_profile_html()) == ()
    # Synthetic incomplete page: the labels occur as unrelated page text, but
    # they are not structured personal-field rows accepted by the parser.
    html = """<html><body><p>Nombre completo Demarcación</p>
    <h1>Player</h1><table class="traject"></table></body></html>"""
    assert missing_profile_field_evidence(html) == ("Nombre completo", "Demarcación")
    empty_fields = """<html><body>
    <div class="float-left"><div>Nombre completo</div><div class="font-weight-bold"></div></div>
    <div class="float-left"><div>Demarcación</div><div></div></div>
    </body></html>"""
    assert missing_profile_field_evidence(empty_fields) == ("Nombre completo", "Demarcación")


def test_statistics_keep_zero_null_section_and_reordered_milestone_header() -> None:
    html = """<html><head><title>Stats</title></head><body>
    <table id="table-estadistiques-competicions" class="taula_estil">
      <tr><th>Tipo</th><th>League</th><th>Cup</th></tr>
      <tr><td>Partidos Jugados</td><td>0</td><td>-</td></tr>
      <tr><td>Total</td><td>0</td><td>0</td></tr>
    </table>
    <table id="table-estadistiques-equips" class="taula_estil">
      <tr><th>Tipo</th><th title="Club A">A</th></tr><tr><td>Temporadas</td><td>2</td></tr>
    </table>
    <table class="taula_estil taula-fites-jugador">
      <tr><td>1</td><td>2024-25</td><td>01/01/2025</td><td><a href="../p/p.php?id=90">Fixture</a></td></tr>
      <tr><th>#</th><th>Temporada</th><th>Fecha</th><th>Partido</th></tr>
    </table>
    </body></html>"""
    url = "https://www.bdfutbol.com/es/j/j123.html?p=stats"
    page = parse_player_html(html, _metadata(url, html))
    rows = page["view_data"]["statistics_rows"]
    played = next(row for row in rows if row["metric_label_raw"] == "Partidos Jugados")
    assert played["columns"][1]["normalized_integer"] == 0
    assert played["columns"][2]["raw_value"] == "-"
    assert played["columns"][2]["normalized_integer"] is None
    assert any(row["row_role"] == "total" for row in rows)
    milestone = next(table for table in page["tables"] if table["table_role"] == "milestone_matches")
    assert milestone["rows"][0]["row_role"] == "data"
    assert milestone["rows"][1]["row_role"] == "header"
    assert milestone["rows"][0]["cells"][3]["links"][0]["url"].endswith("id=90")
    assert page["coverage"]["required_table_roles_missing"] == []


def test_matches_view_is_aggregate_only_and_keeps_zero_counts_and_filters() -> None:
    def table(table_id: str, first_header: str) -> str:
        return (
            f'<table id="{table_id}" class="sortable taula_estil">'
            f'<tr><th>{first_header}</th><th>PJ</th></tr>'
            '<tr><td>League</td><td>0</td></tr></table>'
        )
    html = (
        "<html><head><title>Matches</title></head><body>"
        + table("t2", "Competición")
        + table("t1", "Temporada")
        + table("t55", "Equipo")
        + table("t5", "Rival")
        + '<select id="comp"><option value="*">Todas</option><option value="1rf">League</option></select>'
        + "</body></html>"
    )
    url = "https://www.bdfutbol.com/es/p/j123.html"
    page = parse_player_html(html, _metadata(url, html))
    assert len(page["view_data"]["match_summary_rows"]) == 4
    assert page["view_data"]["individual_match_rows"] == []
    assert page["view_data"]["match_detail_coverage"].startswith("AGGREGATE_TABLES_ONLY")
    assert page["coverage"]["match_detail_scope"] == "AGGREGATE_ONLY"
    assert page["filter_controls"][0]["options"][0]["label_raw"] == "Todas"
    assert page["coverage"]["parse_status"] == "PARSED"


def test_individual_match_table_preserves_scored_scheduled_and_non_fixture_rows(tmp_path: Path) -> None:
    columns = (
        ("n", "#", "Número"),
        ("data", "Fecha", "Fecha"),
        ("temp", "Temporada", "Temporada"),
        ("tipus", "Competición", "Tipo"),
        ("jor", "Tipo", "Jornada"),
        ("e1", "Local", "Local"),
        ("res", "", "Marcador"),
        ("e2", "Visitante", "Visitante"),
        ("pt", "PT", "Partidos titular"),
    )
    headers = "".join(
        f'<th data-colid="{colid}" title="{title}">{label}</th>'
        for colid, label, title in columns
    )
    table = f"""<table id="tpartits" class="taula_estil configurable">
      <tr>{headers}</tr>
      <tr><td>1</td><td>30/08/2026</td><td>2026-27</td><td>1ª RFEF</td>
        <td>Jornada 1</td><td>Home FC</td><td><a href="../p/p.php?id=901">2 1</a></td>
        <td>Away FC</td><td class="resp_off">1</td></tr>
      <tr><td>2</td><td>20/09/2026</td><td>2026-27</td><td>1ª RFEF</td>
        <td>Jornada 4</td><td>Home FC</td><td>—</td><td>Away FC</td><td>0</td></tr>
      <tr><td>3</td><td>30/08/2026</td><td>2026-27</td><td>1ª RFEF</td>
        <td>Jornada 1</td><td>Home FC</td><td><a href="../p/p.php?id=902">pendiente</a></td>
        <td>Away FC</td><td>0</td></tr>
      <tr class="total"><td>Total</td><td colspan="8">2</td></tr>
      <tr><td></td><td></td><td></td></tr>
    </table>"""
    summaries = "".join(
        f'<table id="{table_id}" class="taula_estil"><tr><th>Grupo</th><th>PJ</th></tr>'
        "<tr><td>League</td><td>2</td></tr></table>"
        for table_id in ("t2", "t1", "t55", "t5")
    )
    html = f"<html><body>{summaries}{table}</body></html>"
    url = "https://www.bdfutbol.com/es/p/j123.html?temp=2026-27&comp=1rf"
    metadata = _metadata(url, html)
    metadata["captured_at_utc"] = "2026-09-01T12:00:00+00:00"
    page = parse_player_html(html, metadata)

    data = page["view_data"]
    assert [item["match_id"] for item in data["individual_match_rows"]] == ["901", None, "902"]
    played, scheduled, malformed = data["individual_match_rows"]
    assert played["match_url"] == "https://www.bdfutbol.com/es/p/p.php?id=901"
    assert (played["season_raw"], played["competition_raw"], played["round_raw"]) == (
        "2026-27", "1ª RFEF", "Jornada 1",
    )
    assert (played["date"], played["home_team_raw"], played["away_team_raw"]) == (
        "2026-08-30", "Home FC", "Away FC",
    )
    assert played["result_raw"] == "2 1"
    assert (played["home_goals"], played["away_goals"], played["match_state"]) == (2, 1, "played")
    assert played["source_values_raw"][8] == "1"
    assert scheduled["match_state"] == "scheduled"
    assert malformed["match_state"] == "inconsistent"
    assert malformed["result_raw"] == "pendiente"
    assert data["individual_match_row_role_counts"] == {
        "header": 1, "data": 3, "total": 1, "blank": 1, "section": 0,
    }
    assert data["filter_parameters"] == {"temp": "2026-27", "comp": "1rf"}
    assert data["filtered_view"] is True
    assert data["exhaustiveness_status"] == "FILTERED_SNAPSHOT_NOT_EXHAUSTIVE"
    assert page["coverage"]["match_detail_scope"] == "INDIVIDUAL_FIXTURE_ROWS"

    inventory = build_player_acquisition_inventory(
        [{
            "player_id": "j123", "player_url": "https://www.bdfutbol.com/es/j/j123.html",
            "team_season_id": "t2026-271", "club_id": "e1", "name_raw": "Player",
        }],
        {("j123", "matches"): [{
            "usable": True, "snapshot_directory": "raw/j123/matches",
            "snapshot_sha256": page["source"]["rendered_html_sha256"],
        }]},
    )
    export = build_player_exports(
        inventory=inventory,
        parsed_pages=[page],
        source_audit={},
        output_root=tmp_path,
    )
    with gzip.open(export / "individual_matches.json.gz", "rt", encoding="utf-8") as stream:
        exported_matches = json.load(stream)["items"]
    assert [item["match_id"] for item in exported_matches] == ["901", None, "902"]
    assert exported_matches[0]["source"]["rendered_html_sha256"] == page["source"]["rendered_html_sha256"]
    assert exported_matches[0]["source_values_raw"][6] == "2 1"


def test_real_morillas_snapshots_keep_four_views_three_trajectory_rows_and_empty_fixture_table() -> None:
    raw_root = Path(__file__).resolve().parents[1] / "data/raw/bdfutbol"
    pages = parse_player_snapshot_inventory(discover_player_snapshots(raw_root), raw_root)
    morillas = [page for page in pages if page["player_id"] == "j209629"]
    by_view = {page["view"]: page for page in morillas}

    assert set(by_view) == set(PLAYER_VIEWS)
    assert len(by_view["profile"]["view_data"]["career_rows"]) == 3
    assert len(by_view["matches"]["view_data"]["match_summary_rows"]) == 51
    assert by_view["matches"]["view_data"]["individual_match_rows"] == []
    assert by_view["matches"]["view_data"]["match_detail_coverage"] == "AGGREGATE_TABLES_ONLY_HEADER_ONLY_NO_FIXTURES"
    assert len(by_view["statistics"]["view_data"]["statistics_rows"]) == 97
    assert len(by_view["rivals"]["view_data"]["rival_records"]) == 533


def test_rivals_preserve_hierarchical_columns_relations_and_duplicates() -> None:
    html = """<html><head><title>Rivals</title></head><body>
    <table id="t5" class="sortable taula_estil">
      <tr><th colspan="8"></th><th colspan="4">Jugador</th><th colspan="4">Rival</th></tr>
      <tr><th>#</th><th>Nombre</th><th>Pos</th><th>PJ</th><th>PG</th><th>PE</th><th>PP</th><th>P%</th><th>G</th><th>GE</th><th>TA</th><th>TR</th><th>G</th><th>GE</th><th>TA</th><th>TR</th></tr>
      <tr><td>1</td><td><a href="../j/j700.html">Opponent</a></td><td></td><td>0</td><td>0</td><td>0</td><td>0</td><td></td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td></tr>
      <tr><td>1</td><td><a href="../j/j700.html">Opponent</a></td><td></td><td>0</td><td>0</td><td>0</td><td>0</td><td></td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td></tr>
    </table>
    <table id="t6" class="sortable taula_estil"><tr><th>#</th><th>Nombre</th><th>PJ</th></tr>
      <tr><td>1</td><td><a href="../l/l900.html">Coach</a></td><td>0</td></tr></table>
    <table id="t7" class="sortable taula_estil"><tr><th>#</th><th>Nombre</th><th>PJ</th></tr>
      <tr><td>1</td><td><a href="../e/e901.html">Club</a></td><td>0</td></tr></table>
    </body></html>"""
    url = "https://www.bdfutbol.com/es/p/jr123.html"
    page = parse_player_html(html, _metadata(url, html))
    records = page["view_data"]["rival_records"]
    players = [row for row in records if row["rival_kind"] == "player"]
    assert [row["rival_id"] for row in players] == ["j700", "j700"]
    assert players[1]["row_duplicate_of"] == players[0]["source_row_index"]
    table = next(table for table in page["tables"] if table["table_id"] == "t5")
    assert table["column_headers"][8]["group_header_raw"] == "Jugador"
    assert table["column_headers"][12]["group_header_raw"] == "Rival"
    assert {row["related_entity_type"] for row in page["relationships"]} == {"player", "coach", "club"}
    assert page["coverage"]["parse_status"] == "PARSED"


def test_acquisition_inventory_keeps_distinct_team_memberships_and_view_states() -> None:
    memberships = [
        {
            "player_id": "j123", "player_url": "https://www.bdfutbol.com/es/j/j123.html",
            "team_season_id": "t2024-257", "club_id": "e7", "name_raw": "Player A",
            "zero_appearances": True, "position_raw": "1",
        },
        {
            "player_id": "j123", "player_url": "https://www.bdfutbol.com/es/j/j123.html",
            "team_season_id": "t2025-258", "club_id": "e8", "name_raw": "Player A",
            "zero_appearances": False, "position_raw": "1",
        },
        {
            "player_id": "j456", "player_url": "https://www.bdfutbol.com/es/j/j456.html",
            "team_season_id": "t2025-259", "club_id": "e9", "name_raw": "Player B",
            "zero_appearances": False, "position_raw": "5",
        },
    ]
    raw_snapshots = {
        ("j123", "profile"): [{
            "usable": True, "snapshot_directory": "j123/profile", "snapshot_sha256": "sha",
        }]
    }
    inventory = build_player_acquisition_inventory(memberships, raw_snapshots)
    assert len(inventory["players"]) == 2
    player = next(row for row in inventory["players"] if row["player_id"] == "j123")
    assert player["team_season_ids"] == ["t2024-257", "t2025-258"]
    assert player["membership_count"] == 2
    assert player["zero_appearance_membership_count"] == 1
    assert player["views_with_snapshot"] == ["profile"]
    assert player["views_pending"] == [view for view in PLAYER_VIEWS if view != "profile"]
    assert len(inventory["coverage"]) == 8
    assert len(inventory["acquisition_manifest"]) == 8
    profile_entry = next(
        row for row in inventory["acquisition_manifest"]
        if row["player_id"] == "j123" and row["view"] == "profile"
    )
    assert profile_entry["url"] == memberships[0]["player_url"]
    assert profile_entry["url_status"] == "VERIFIED_FROM_ROSTER"
    assert profile_entry["snapshot_status"] == "VALID_SNAPSHOT_EXISTS"
    inferred_view = next(
        row for row in inventory["acquisition_manifest"]
        if row["player_id"] == "j123" and row["view"] == "matches"
    )
    assert inferred_view["url_status"] == "INFERRED_FROM_OBSERVED_ROUTE_PATTERN"
    assert inferred_view["snapshot_status"] == "PENDING_SNAPSHOT"
    assert inferred_view["variants_status"] == "NOT_INVESTIGATED"
    assert {item["player_id"] for item in inventory["player_pilot_candidates"]} == {"j123", "j456"}
    assert all(item["acquisition_status"] == "NOT_ACQUIRED_PLANNED_PILOT" for item in inventory["player_pilot_candidates"])


def test_invalid_or_incomplete_player_snapshot_is_not_usable_or_parsed(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    snapshot = raw_root / "player" / "profile"
    snapshot.mkdir(parents=True)
    html = _profile_html()
    (snapshot / "rendered.html").write_text(html, encoding="utf-8")
    (snapshot / "metadata.json").write_text(json.dumps({
        "requested_url": "https://www.bdfutbol.com/es/j/j123.html",
        "final_url": "https://www.bdfutbol.com/es/j/j123.html",
        "access_status": "VALID",
        "http_status": 200,
    }), encoding="utf-8")
    inventory = discover_player_snapshots(raw_root)
    candidate = inventory[("j123", "profile")][0]
    assert candidate["usable"] is False
    assert candidate["hash_status"] == "MISSING_OR_MISMATCH"
    roster = [{
        "player_id": "j123", "player_url": "https://www.bdfutbol.com/es/j/j123.html",
        "team_season_id": "t1", "club_id": "e1", "zero_appearances": False,
    }]
    entry = build_player_acquisition_inventory(roster, inventory)["acquisition_manifest"][0]
    assert entry["snapshot_status"] == "SNAPSHOT_REQUIRES_REVALIDATION"
    assert entry["acquisition_status"] == "REQUIRES_REVALIDATION"
    with pytest.raises(PlayerSnapshotError, match="Falta rendered_html_sha256"):
        parse_player_snapshot(snapshot)


def test_filtered_snapshot_stays_a_variant_and_leaves_base_view_pending() -> None:
    url = "https://www.bdfutbol.com/es/p/j123.html?temp=2026-27&pgep=pg"
    inventory = build_player_acquisition_inventory(
        [{
            "player_id": "j123", "player_url": "https://www.bdfutbol.com/es/j/j123.html",
            "team_season_id": "t2026-271", "club_id": "e1", "zero_appearances": False,
        }],
        {("j123", "matches"): [{
            "usable": True,
            "url": url,
            "is_base_view_snapshot": False,
            "filter_parameters": {"temp": "2026-27", "pgep": "pg"},
            "snapshot_directory": "raw/j123/matches-filtered",
            "snapshot_sha256": "sha-filtered",
        }]},
    )
    matches = next(
        row for row in inventory["acquisition_manifest"]
        if row["player_id"] == "j123" and row["view"] == "matches"
    )

    assert matches["snapshot_available"] is False
    assert matches["snapshot_status"] == "VALID_FILTERED_VARIANT_EXISTS_BASE_VIEW_PENDING"
    assert matches["view_coverage_status"] == "FILTERED_VARIANT_ONLY"
    assert matches["acquisition_status"] == "PENDING_BASE_VIEW_CAPTURE"
    assert matches["snapshot_count"] == 1
    assert matches["selected_snapshot_directory"] is None


def test_pilot_position_representative_uses_raw_position_as_unique_key() -> None:
    memberships = [
        {"player_id": "j101", "team_season_id": "t2026-1", "position_raw": "4"},
        {"player_id": "j102", "team_season_id": "t2026-2", "position_raw": "4"},
        {"player_id": "j103", "team_season_id": "t2026-3", "position_raw": "1"},
    ]
    players = [
        {"player_id": row["player_id"], "profile_url": f"https://www.bdfutbol.com/es/j/{row['player_id']}.html"}
        for row in memberships
    ]

    candidates = build_player_pilot_candidates(memberships, players, {})
    reasons = {row["player_id"]: row["selection_reasons"] for row in candidates}

    assert reasons["j101"] == ["REPRESENTATIVE_RAW_POSITION_CODE:4"]
    assert reasons["j103"] == ["REPRESENTATIVE_RAW_POSITION_CODE:1"]
    assert "j102" not in reasons


def test_player_view_classification_handles_all_four_urls() -> None:
    assert classify_player_view("https://www.bdfutbol.com/es/j/j123.html") == ("j123", "profile")
    assert classify_player_view("https://www.bdfutbol.com/es/j/j123.html?p=stats") == ("j123", "statistics")
    assert classify_player_view("https://www.bdfutbol.com/es/p/j123.html") == ("j123", "matches")
    assert classify_player_view("https://www.bdfutbol.com/es/p/jr123.html") == ("j123", "rivals")


def test_compact_exports_are_repeatable_and_do_not_embed_raw_html(tmp_path: Path) -> None:
    html = _profile_html()
    url = "https://www.bdfutbol.com/es/j/j123.html"
    page = parse_player_html(html, _metadata(url, html), snapshot_directory="raw/j123/profile")
    memberships = [{
        "player_id": "j123",
        "player_url": url,
        "team_season_id": "t2024-257",
        "club_id": "e7",
        "name_raw": "Alias Player Full Name",
        "zero_appearances": True,
    }]
    inventory = build_player_acquisition_inventory(memberships, {
        ("j123", "profile"): [{
            "usable": True,
            "snapshot_directory": "raw/j123/profile",
            "snapshot_sha256": page["source"]["rendered_html_sha256"],
        }]
    })
    audit = {"hito1b": {"candidates": [], "retained_extraction_key": "candidate"}, "caceres": {}}
    previous_version = tmp_path / "exports/compact/snapshot-previous-parser-0.1.4"
    previous_version.mkdir(parents=True)
    sentinel = previous_version / "preserved.txt"
    sentinel.write_text("previous immutable export", encoding="utf-8")
    first = build_player_exports(
        inventory=inventory,
        parsed_pages=[page],
        source_audit=audit,
        output_root=tmp_path / "exports",
    )
    second = build_player_exports(
        inventory=inventory,
        parsed_pages=[page],
        source_audit=audit,
        output_root=tmp_path / "exports",
    )
    assert first == second
    assert first.name.endswith("parser-0.2.1")
    assert sentinel.read_text(encoding="utf-8") == "previous immutable export"
    profiles = json.load(gzip.open(first / "profiles.json.gz", "rt", encoding="utf-8"))
    assert profiles["items"][0]["player_id"] == "j123"
    assert "<html" not in (first / "pages/j123/profile.json.gz").read_bytes().decode("latin-1")
    assert (first / "acquisition_manifest.csv.gz").is_file()
    coverage = json.load(gzip.open(first / "coverage.json.gz", "rt", encoding="utf-8"))
    assert len(coverage["items"]) == 4
    assert coverage["items"][0]["parse_status"] == "PARSED"
    immutable_file = first / "dataset_metadata.json.gz"
    immutable_file.write_bytes(b"tampered historical export")
    with pytest.raises(FileExistsError, match="no se sobrescribirá"):
        build_player_exports(
            inventory=inventory,
            parsed_pages=[page],
            source_audit=audit,
            output_root=tmp_path / "exports",
        )
