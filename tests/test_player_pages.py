from __future__ import annotations

import hashlib
import gzip
import json
from pathlib import Path

from football_data_hub.parsers.player_pages import (
    PLAYER_VIEWS,
    build_player_acquisition_inventory,
    classify_player_view,
    parse_player_html,
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
            "zero_appearances": True,
        },
        {
            "player_id": "j123", "player_url": "https://www.bdfutbol.com/es/j/j123.html",
            "team_season_id": "t2025-258", "club_id": "e8", "name_raw": "Player A",
            "zero_appearances": False,
        },
        {
            "player_id": "j456", "player_url": "https://www.bdfutbol.com/es/j/j456.html",
            "team_season_id": "t2025-259", "club_id": "e9", "name_raw": "Player B",
            "zero_appearances": False,
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
    profiles = json.load(gzip.open(first / "profiles.json.gz", "rt", encoding="utf-8"))
    assert profiles["items"][0]["player_id"] == "j123"
    assert "<html" not in (first / "pages/j123/profile.json.gz").read_bytes().decode("latin-1")
    assert (first / "acquisition_manifest.csv.gz").is_file()
    coverage = json.load(gzip.open(first / "coverage.json.gz", "rt", encoding="utf-8"))
    assert len(coverage["items"]) == 4
    assert coverage["items"][0]["parse_status"] == "PARSED"
