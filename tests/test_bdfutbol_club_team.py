from __future__ import annotations

import hashlib
import json
import gzip
from pathlib import Path

import pytest
import scrape_bdfutbol_club_team as club_team_cli

from football_data_hub.collectors.bdfutbol_club_team import (
    InvalidClubTeamSnapshot,
    _new_snapshot_run_root,
    _snapshot_for_reuse,
    _club_urls,
    discover_latest_snapshots,
    load_club_team_snapshot,
)
from football_data_hub.collectors.bdfutbol_competition import InvalidCompetitionExport
from football_data_hub.parsers.club_team_coverage import build_club_team_coverage
from football_data_hub.providers.bdfutbol.club_team import (
    InvalidClubTeamPage,
    classify_club_team_url,
    parse_club_team_html,
)
from football_data_hub.storage.club_team_exports import write_club_team_exports
from scrape_bdfutbol_club_team import parse_args


TEAM_ID = "t2026-2749"
CLUB_ID = "e49"
BASE = f"https://www.bdfutbol.com/es/t/{TEAM_ID}.html"


def team_html(
    *,
    roster_rows: str = "",
    statistics_rows: str = "",
    include_roster: bool = True,
    team_season_id: str = TEAM_ID,
    club_id: str = CLUB_ID,
    statistics_table: str | None = None,
) -> str:
    roster_table = (
        '<table id="c3p1"><tr><th>#</th><th>Apodo y Nombre</th><th>Fecha</th>'
        f"<th>Pos</th><th class='optional'>Min</th></tr>{roster_rows}</table>"
        if include_roster
        else ""
    )
    stats_table = statistics_table or (
        '<table id="c3p0"><tr><th>Apodo</th><th>PJ</th><th>Min</th></tr>'
        f"{statistics_rows}"
        '<tr class="font-weight-bold total"><td colspan="1"></td><td>4</td><td>180</td></tr>'
        "</table>"
    )
    return f"""<!doctype html><html><head><title>Real Jaén | BDFutbol</title></head><body>
      <div id="body">
        <div id="superheader"><table id="global"><tr><td>Menú 1ª RFEF</td></tr></table></div>
        <div class="hero"><h1>Plantilla 2026-27</h1>
          <a href="/es/e/{club_id}.html">Real Jaén</a>
          <a href="/es/t/{team_season_id}.html">Equipo temporada</a>
        </div>
        <main><h2>Plantilla</h2>
          {roster_table}
          <table id="taulaentrenadors"><tr><th>Apodo y Nombre</th></tr>
            <tr><td><a href="/es/l/l77.html">Entrenador</a></td></tr></table>
          {stats_table}
        </main>
      </div></body></html>"""


def member_row(player_id: str, name: str, *, hidden_value: str = "120") -> str:
    return (
        f'<tr><td>9</td><td><a href="/es/j/{player_id}.html">{name}</a></td>'
        f'<td>01/01/2000</td><td>Delantero</td>'
        f'<td class="optional" style="display:none">{hidden_value}</td></tr>'
    )


def stats_row(player_id: str, name: str, appearances: str) -> str:
    return f'<tr><td><a href="/es/j/{player_id}.html">{name}</a></td><td>{appearances}</td><td>0</td></tr>'


def parsed_team_pages(*, player_ids: tuple[str, ...] = ("j101",), stats_ids: tuple[str, ...] | None = None) -> list[dict]:
    stats_ids = stats_ids if stats_ids is not None else player_ids
    roster = parse_club_team_html(
        team_html(roster_rows="".join(member_row(item, f"Jugador {item}") for item in player_ids)),
        f"{BASE}?t=plantilla",
        source_metadata={"access_status": "VALID", "http_status": 200},
    )
    statistics = parse_club_team_html(
        team_html(
            include_roster=False,
            statistics_rows="".join(stats_row(item, f"Jugador {item}", "0") for item in stats_ids),
        ),
        f"{BASE}?t=lista",
        source_metadata={"access_status": "VALID", "http_status": 200},
    )
    return [roster, statistics]


def write_snapshot(directory: Path, url: str, html: str, captured_at: str = "2026-10-08T12:00:00Z") -> None:
    directory.mkdir(parents=True)
    content = html.encode("utf-8")
    (directory / "rendered.html").write_bytes(content)
    (directory / "metadata.json").write_text(
        json.dumps({
            "requested_url": url,
            "final_url": url,
            "http_status": 200,
            "access_status": "VALID",
            "captured_at_utc": captured_at,
            "rendered_html_sha256": hashlib.sha256(content).hexdigest(),
            "rendered_html_bytes": len(content),
        }),
        encoding="utf-8",
    )


@pytest.mark.parametrize(("url", "view", "entity_type", "entity_id"), [
    (BASE, "team_alignment", "team_season", TEAM_ID),
    (f"{BASE}?t=plantilla", "team_roster", "team_season", TEAM_ID),
    (f"{BASE}?t=lista", "team_statistics", "team_season", TEAM_ID),
    (f"{BASE}?t=seg", "team_tracking", "team_season", TEAM_ID),
    (f"{BASE}?t=altas", "team_transfers", "team_season", TEAM_ID),
    (f"{BASE}?tab=partits", "team_matches", "team_season", TEAM_ID),
    ("https://www.bdfutbol.com/es/e/e49.html", "club_profile", "club", CLUB_ID),
    ("https://www.bdfutbol.com/es/e/e49.html?p=stats", "club_statistics", "club", CLUB_ID),
    ("https://www.bdfutbol.com/es/e/egols49.html", "club_players", "club", CLUB_ID),
    ("https://www.bdfutbol.com/es/e/eentr49.html", "club_coaches", "club", CLUB_ID),
    ("https://www.bdfutbol.com/es/p/e49.html", "club_matches", "club", CLUB_ID),
    ("https://www.bdfutbol.com/es/p/er49.html", "club_rivals", "club", CLUB_ID),
])
def test_all_discovered_url_families_keep_permanent_and_season_ids(
    url: str, view: str, entity_type: str, entity_id: str,
) -> None:
    assert classify_club_team_url(url) == {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "view": view,
    }


def test_foreign_and_unrecognized_pages_are_out_of_scope() -> None:
    assert classify_club_team_url("http://www.bdfutbol.com/es/e/e49.html") is None
    assert classify_club_team_url("https://example.org/es/e/e49.html") is None
    assert classify_club_team_url("https://www.bdfutbol.com/es/t/t2026-2749.html?t=unknown") is None
    assert classify_club_team_url("https://www.bdfutbol.com/es/j/j101.html") is None


def test_club_url_builder_uses_permanent_club_number() -> None:
    assert _club_urls("e72") == {
        "club_profile": "https://www.bdfutbol.com/es/e/e72.html",
        "club_statistics": "https://www.bdfutbol.com/es/e/e72.html?p=stats",
        "club_players": "https://www.bdfutbol.com/es/e/egols72.html",
        "club_coaches": "https://www.bdfutbol.com/es/e/eentr72.html",
        "club_matches": "https://www.bdfutbol.com/es/p/e72.html",
        "club_rivals": "https://www.bdfutbol.com/es/p/er72.html",
    }


def test_team_roster_preserves_hidden_cells_zero_stats_and_entity_relations() -> None:
    html = team_html(
        roster_rows=member_row("j101", "Delantero Uno", hidden_value="137"),
        statistics_rows=stats_row("j101", "Delantero Uno", "0"),
    )
    page = parse_club_team_html(html, f"{BASE}?t=plantilla")

    assert page["entity_id"] == TEAM_ID
    assert page["club_id"] == CLUB_ID
    assert page["team_data"]["roster_rows"][0]["player_id"] == "j101"
    assert page["team_data"]["roster_rows"][0]["zero_appearances"] is True
    assert page["team_data"]["roster_rows"][0]["statistics_present"] is True
    hidden_cell = page["team_data"]["roster_rows"][0]["raw_cells"][-1]
    assert hidden_cell["text"] == "137"
    assert hidden_cell["classes"] == ["optional"]
    assert hidden_cell["style"] == "display:none"
    assert {("player", "j101"), ("coach", "l77"), ("club", CLUB_ID)} <= {
        (item["entity_type"], item["entity_id"]) for item in page["relationships"]
    }
    assert not any(table.get("table_id") == "global" for table in page["tables"])


def test_other_team_season_and_permanent_club_ids_remain_distinct() -> None:
    team_id = "t2026-2772"
    club_id = "e72"
    page = parse_club_team_html(
        team_html(
            roster_rows=member_row("j505", "Jugador de Bilbao"),
            team_season_id=team_id,
            club_id=club_id,
        ),
        f"https://www.bdfutbol.com/es/t/{team_id}.html?t=plantilla",
    )

    assert page["entity_id"] == team_id
    assert page["club_id"] == club_id
    assert page["team_data"]["roster_rows"][0]["team_season_id"] == team_id


def test_statistics_view_keeps_zero_appearances_and_original_cells() -> None:
    page = parse_club_team_html(
        team_html(include_roster=False, statistics_rows=stats_row("j202", "Sin minutos", "0")),
        f"{BASE}?t=lista",
    )
    record = page["team_data"]["player_statistics"][0]

    assert record["player_id"] == "j202"
    assert record["appearances"] == 0
    assert record["zero_appearances"] is True
    assert [cell["text"] for cell in record["raw_cells"]] == ["Sin minutos", "0", "0"]
    total = page["team_data"]["statistics_totals"][0]
    assert total["values_by_column"] == [
        {"column_index": 0, "header": "Apodo", "value": None},
        {"column_index": 1, "header": "PJ", "value": "4"},
        {"column_index": 2, "header": "Min", "value": "180"},
    ]
    assert page["team_data"]["statistics_unparsed_rows"] == []


def test_statistics_total_row_maps_source_colspans_to_all_22_headers() -> None:
    headers = (
        "#", "", "", "Apodo", "Pos", "PJ", "PT", "PC", "PS", "PX", "C", "Min",
        "TA", "TR", "G", "Minutos/G", "GP", "GPP", "GE", "PG", "PE", "PP",
    )
    header_html = "".join(f"<th>{value}</th>" for value in headers)
    player_cells = ["1", "", "", "", "1", "0", "0", "0", "0", "0", "0", "90"] + ["0"] * 10
    player_cells[3] = '<a href="/es/j/j606.html">Jugador seis</a>'
    player_html = "<tr>" + "".join(f"<td>{value}</td>" for value in player_cells) + "</tr>"
    total_html = (
        '<tr class="font-weight-bold total"><td colspan="11"></td><td></td>'
        "<td>15</td><td>2</td><td>8</td><td></td><td>0</td><td>0</td><td>5</td>"
        "<td colspan=\"3\"></td></tr>"
    )
    stats_table = f'<table id="c3p0"><tr>{header_html}</tr>{player_html}{total_html}</table>'
    page = parse_club_team_html(
        team_html(include_roster=False, statistics_table=stats_table),
        f"{BASE}?t=lista",
    )
    values = {item["header"]: item["value"] for item in page["team_data"]["statistics_totals"][0]["values_by_column"]}

    assert page["team_data"]["player_statistics"][0]["player_id"] == "j606"
    assert values["TA"] == "15"
    assert values["TR"] == "2"
    assert values["G"] == "8"
    assert values["GE"] == "5"
    assert page["team_data"]["statistics_unparsed_rows"] == []
    stats_table = next(table for table in page["tables"] if table["table_id"] == "c3p0")
    total_row = next(row for row in stats_table["rows"] if row["row_role"] == "total")
    assert total_row["column_alignment"]["status"] == "MATCH"
    assert total_row["column_alignment"]["represented_column_count"] == 22
    assert [row["row_role"] for row in stats_table["rows"]] == ["header", "data", "total"]


def test_header_positions_and_omitted_coach_columns_are_preserved() -> None:
    headers = [f"Campo {index}" for index in range(25)]
    headers[4] = ""
    html = (
        "<html><body><div id='body'><div class='hero'><h1>Entrenadores</h1></div><main>"
        "<table id='llista'><tr>"
        + "".join(f"<th>{value}</th>" for value in headers)
        + "</tr><tr>"
        + "".join(f"<td>valor {index}</td>" for index in range(23))
        + "</tr></table></main></div></body></html>"
    )
    url = "https://www.bdfutbol.com/es/e/eentr49.html"
    page = parse_club_team_html(html, url)
    table = page["tables"][0]
    data_row = next(row for row in table["rows"] if row["row_role"] == "data")
    coverage = build_club_team_coverage([page])
    catalog_table = next(
        item for item in coverage["resources"][0]["field_inventory"]["tables"]
        if item["table_id"] == "llista"
    )

    assert len(table["header_cells"]) == 25
    assert table["header_cells"][4] == ""
    assert catalog_table["headers"] == headers
    assert data_row["column_alignment"] == {
        "expected_column_count": 25,
        "represented_column_count": 23,
        "missing_trailing_column_indexes": [23, 24],
        "overflow_column_count": 0,
        "status": "TRAILING_COLUMNS_OMITTED",
    }


def test_missing_statistics_are_not_fabricated_and_roster_is_retained() -> None:
    page = parse_club_team_html(
        team_html(roster_rows=member_row("j303", "Sin fila estadística"), statistics_rows=""),
        f"{BASE}?t=plantilla",
    )
    member = page["team_data"]["roster_rows"][0]

    assert member["player_id"] == "j303"
    assert member["statistics_present"] is False
    assert member["appearances"] is None
    assert member["zero_appearances"] is None


def test_duplicate_player_ids_are_reported_without_dropping_rows() -> None:
    page = parse_club_team_html(
        team_html(roster_rows=member_row("j404", "Uno") + member_row("j404", "Uno duplicado")),
        f"{BASE}?t=plantilla",
    )

    assert len(page["team_data"]["roster_rows"]) == 2
    assert any("duplicados" in diagnostic for diagnostic in page["diagnostics"])


def test_relationship_identity_retains_each_source_row_occurrence() -> None:
    page = parse_club_team_html(
        team_html(roster_rows=member_row("j404", "Jugador cuatro") + member_row("j404", "Jugador cuatro")),
        f"{BASE}?t=plantilla",
    )
    relationship = next(
        item for item in page["relationships"]
        if item["entity_type"] == "player" and item["entity_id"] == "j404"
    )

    assert len(relationship["occurrences"]) == 2
    assert len({item["source_row_index"] for item in relationship["occurrences"]}) == 2


def test_html_with_no_expected_roster_table_does_not_create_members() -> None:
    page = parse_club_team_html(
        team_html(include_roster=False, statistics_rows=""),
        f"{BASE}?t=plantilla",
        source_metadata={"access_status": "VALID", "http_status": 200},
    )
    coverage = build_club_team_coverage([page], team_season_ids=[TEAM_ID])
    roster_state = next(item for item in coverage["views"] if item["view"] == "team_roster")

    assert page["team_data"]["roster_rows"] == []
    assert roster_state["status"] == "PARSED"
    assert roster_state["coverage_status"] == "INCOMPLETE"
    assert coverage["summary"]["views_complete"] == 0


def test_valid_access_and_successful_parse_do_not_validate_unreconciled_views() -> None:
    page = parse_club_team_html(
        team_html(),
        f"{BASE}?t=seg",
        source_metadata={"access_status": "VALID", "http_status": 200},
    )
    coverage = build_club_team_coverage([page], team_season_ids=[TEAM_ID])
    tracking = next(item for item in coverage["views"] if item["view"] == "team_tracking")

    assert tracking["access_status"] == "VALID"
    assert tracking["status"] == "PARSED"
    assert tracking["coverage_status"] == "INCOMPLETE"


@pytest.mark.parametrize(
    ("snapshot_directory", "expected_evidence"),
    [
        ("data/raw/bdfutbol/20261008T145616.342283Z/t2026-2749/team_roster", "VERIFIED"),
        ("data/raw/bdfutbol/luna_audit/20261008T121250.991672Z/roster", "ARTIFACT_ONLY"),
    ],
)
def test_coverage_evidence_status_distinguishes_captures_from_old_artifacts(
    snapshot_directory: str, expected_evidence: str,
) -> None:
    page = parse_club_team_html(
        team_html(roster_rows=member_row("j101", "Jugador j101")),
        f"{BASE}?t=plantilla",
        source_metadata={
            "access_status": "VALID",
            "http_status": 200,
            "snapshot_directory": snapshot_directory,
        },
    )
    page["source"]["snapshot_directory"] = snapshot_directory
    coverage = build_club_team_coverage([page], team_season_ids=[TEAM_ID])
    roster = next(item for item in coverage["views"] if item["view"] == "team_roster")

    assert roster["evidence_status"] == expected_evidence


def test_complete_roster_and_stats_pair_does_not_mark_whole_entity_complete() -> None:
    pages = parsed_team_pages()
    coverage = build_club_team_coverage(pages, team_season_ids=[TEAM_ID])
    checks = coverage["team_membership_checks"][TEAM_ID]
    roster = next(item for item in coverage["views"] if item["view"] == "team_roster")
    statistics = next(item for item in coverage["views"] if item["view"] == "team_statistics")

    assert checks["roster_rows"] == checks["statistics_rows"] == 1
    assert checks["roster_ids_without_statistics"] == []
    assert checks["statistics_ids_without_roster"] == []
    assert roster["coverage_status"] == statistics["coverage_status"] == "COMPLETE"
    assert "Apodo y Nombre" in roster["structured_source_headers"]
    assert "Min" in roster["raw_only_headers"]
    assert "player_id" in roster["interpreted_record_fields"]
    assert coverage["entity_coverage"][0]["status"] == "INCOMPLETE"
    assert coverage["summary"]["views_complete"] == 2


def test_unmatched_stats_and_duplicates_leave_view_coverage_incomplete() -> None:
    pages = parsed_team_pages(player_ids=("j101", "j102"), stats_ids=("j101", "j101"))
    coverage = build_club_team_coverage(pages, team_season_ids=[TEAM_ID])
    checks = coverage["team_membership_checks"][TEAM_ID]
    roster = next(item for item in coverage["views"] if item["view"] == "team_roster")
    statistics = next(item for item in coverage["views"] if item["view"] == "team_statistics")

    assert checks["roster_ids_without_statistics"] == ["j102"]
    assert checks["statistics_duplicate_player_ids"] == ["j101"]
    assert roster["coverage_status"] == statistics["coverage_status"] == "INCOMPLETE"


def test_invalid_empty_html_raises_a_page_error() -> None:
    with pytest.raises(InvalidClubTeamPage, match="vacío"):
        parse_club_team_html("  ", f"{BASE}?t=plantilla")


def test_snapshot_integrity_is_checked_before_offline_use(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "raw" / "one"
    write_snapshot(snapshot_dir, f"{BASE}?t=plantilla", team_html())

    snapshot = load_club_team_snapshot(snapshot_dir)
    assert snapshot.page["view"] == "team_roster"
    assert snapshot.metadata["access_status"] == "VALID"

    (snapshot_dir / "rendered.html").write_text("changed", encoding="utf-8")
    with pytest.raises(InvalidClubTeamSnapshot, match="SHA-256"):
        load_club_team_snapshot(snapshot_dir)


def test_snapshot_discovery_scopes_by_team_and_resolves_club_ids(tmp_path: Path) -> None:
    write_snapshot(tmp_path / "raw" / "alignment", BASE, team_html())
    write_snapshot(tmp_path / "raw" / "team", f"{BASE}?t=plantilla", team_html())
    club_url = "https://www.bdfutbol.com/es/e/e49.html"
    write_snapshot(
        tmp_path / "raw" / "club",
        club_url,
        "<html><body><div id='body'><div class='hero'><h1>Real Jaén</h1></div></div></body></html>",
    )
    other_url = "https://www.bdfutbol.com/es/t/t2026-2772.html?t=plantilla"
    write_snapshot(tmp_path / "raw" / "other", other_url, team_html())

    snapshots = discover_latest_snapshots(tmp_path / "raw", team_season_ids={TEAM_ID})

    assert [(item.page["entity_type"], item.page["entity_id"], item.page["view"]) for item in snapshots] == [
        ("club", CLUB_ID, "club_profile"),
        ("team_season", TEAM_ID, "team_alignment"),
        ("team_season", TEAM_ID, "team_roster"),
    ]


def test_club_page_preserves_historical_rows_and_profile_links() -> None:
    url = "https://www.bdfutbol.com/es/e/e49.html"
    html = """<html><head><title>Real Jaén | BDFutbol</title></head><body><div id="body">
      <div class="hero"><h1>Real Jaén</h1><a href="/es/e/e49.html">Real Jaén</a></div>
      <main><h2>Trayectoria</h2><table id="trayectoria">
        <tr><th>Temporada</th><th>Liga</th><th>Pos</th></tr>
        <tr><td>2026-27</td><td>1ª RFEF Grupo II</td><td>1</td></tr>
      </table></main></div></body></html>"""
    page = parse_club_team_html(html, url)

    assert (page["entity_type"], page["entity_id"], page["view"]) == ("club", CLUB_ID, "club_profile")
    assert page["tables"][0]["data_row_count"] == 1
    assert [cell["text"] for cell in page["tables"][0]["rows"][-1]["cells"]] == [
        "2026-27", "1ª RFEF Grupo II", "1",
    ]


def _filtered_match_pages() -> tuple[dict, dict]:
    canonical_html = """<html><body><div id="body"><div class="hero"><h1>Partidos Jaén</h1></div>
      <main><h2>Temporadas</h2><table id="t1"><tr><th>Temporada</th><th>PJ</th><th>PG</th><th>PE</th><th>PP</th></tr>
        <tr><td>2026-27</td><td>6</td><td>3</td><td>2</td><td>1</td></tr></table></main></div></body></html>"""
    outcomes = (("pg", "0", "3"), ("pg", "0", "1"), ("pg", "1", "2"),
        ("pe", "1", "1"), ("pe", "0", "0"), ("pp", "2", "0"))
    def row(index: int, outcome: str, against: str, scored: str) -> str:
        return (
            f'<tr><td><a href="/es/p/p.php?id={1000 + index}">{index}</a></td>'
            f'<td>0{index}/09/2026</td><td>2026-27</td><td>1rf</td><td>Jornada {index}</td>'
            f'<td>Local</td><td>{against} {scored}</td><td>Visitante</td><td>0</td><td>0</td>'
            f'<td>{scored}</td><td>{against}</td></tr>'
        )
    all_rows = "".join(row(index, *item) for index, item in enumerate(outcomes, start=1))
    all_html = f"""<html><body><div id="body"><div class="hero"><h1>Partidos Jaén</h1></div>
      <main><h2>Partidos</h2><table id="tpartits">
        <tr><th>#</th><th>Fecha</th><th>Temporada</th><th>Competición</th><th>Tipo</th>
          <th>Local</th><th></th><th>Visitante</th><th>TA</th><th>TR</th><th>GF</th><th>GC</th></tr>
        {all_rows}<tr class="filatotal"><td colspan="12">Total 6 partidos</td></tr>
      </table></main></div></body></html>"""
    canonical = parse_club_team_html(
        canonical_html,
        "https://www.bdfutbol.com/es/p/e49.html",
        source_metadata={"access_status": "VALID", "http_status": 200, "rendered_html_sha256": "base-hash"},
    )
    filters = {"cat": "1rf", "temp": "2026-27", "pgep": "pg"}
    wins = "".join(row(index, *item) for index, item in enumerate(outcomes[:3], start=1))
    variant_html = all_html.replace(all_rows, wins).replace("Total 6 partidos", "Total 3 victorias")
    variant = parse_club_team_html(
        variant_html,
        "https://www.bdfutbol.com/es/p/e49.html?cat=1rf&temp=2026-27&pgep=pg",
        source_metadata={
            "access_status": "VALID",
            "http_status": 200,
            "rendered_html_sha256": "variant-hash",
            "snapshot_directory": "data/raw/bdfutbol/hito_1d_a2_interactions/variant",
        },
    )
    variant["view_variant"] = {
        "variant_id": "cat-1rf__pgep-pg__temp-2026-27",
        "filter_parameters": filters,
        "scope": "cat=1rf; pgep=pg; temp=2026-27",
    }
    return canonical, variant


def _match_variant_for_filter(
    outcome_filter: str | None,
    source_results: tuple[tuple[str, str, str], ...] | None = None,
) -> dict:
    canonical, _ = _filtered_match_pages()
    all_outcomes = source_results or (("pg", "0", "3"), ("pg", "0", "1"), ("pg", "1", "2"),
        ("pe", "1", "1"), ("pe", "0", "0"), ("pp", "2", "0"))
    selected = [item for item in all_outcomes if outcome_filter is None or item[0] == outcome_filter]
    def row(index: int, against: str, scored: str) -> str:
        return (
            f'<tr><td><a href="/es/p/p.php?id={1000 + index}">{index}</a></td>'
            f'<td>0{index}/09/2026</td><td>2026-27</td><td>1rf</td><td>Jornada {index}</td>'
            f'<td>Local</td><td>{against} {scored}</td><td>Visitante</td><td>0</td><td>0</td>'
            f'<td>{scored}</td><td>{against}</td></tr>'
        )
    outcome_positions = {item: index for index, item in enumerate(all_outcomes, start=1)}
    rows = "".join(row(outcome_positions[item], item[1], item[2]) for item in selected)
    html = f"""<html><body><div id="body"><div class="hero"><h1>Partidos Jaén</h1></div>
      <main><table id="tpartits"><tr><th>#</th><th>Fecha</th><th>Temporada</th><th>Competición</th>
      <th>Tipo</th><th>Local</th><th></th><th>Visitante</th><th>TA</th><th>TR</th><th>GF</th><th>GC</th></tr>
      {rows}<tr class="filatotal"><td colspan="12">Total</td></tr></table></main></div></body></html>"""
    filters = {"cat": "1rf", "temp": "2026-27"}
    query = "cat=1rf&temp=2026-27"
    if outcome_filter:
        filters["pgep"] = outcome_filter
        query += f"&pgep={outcome_filter}"
    page = parse_club_team_html(
        html,
        f"https://www.bdfutbol.com/es/p/e49.html?{query}",
        source_metadata={"access_status": "VALID", "http_status": 200, "rendered_html_sha256": f"filter-{outcome_filter or 'all'}"},
    )
    page["view_variant"] = {"variant_id": f"result-{outcome_filter or 'all'}", "filter_parameters": filters}
    return page


def test_filtered_club_matches_variant_is_validated_only_in_its_scope() -> None:
    canonical, variant = _filtered_match_pages()
    coverage = build_club_team_coverage([canonical], variant_pages=[variant])
    match_variant = coverage["interaction_variants"][0]

    assert match_variant["status"] == "VALIDATED"
    assert match_variant["coverage_status"] == "COMPLETE"
    assert match_variant["records_observed"] == 3
    assert match_variant["validation"]["aggregate_expected"] == 3
    assert match_variant["validation"]["total_rows"] == 1
    canonical_state = next(item for item in coverage["views"] if item["view"] == "club_matches")
    assert canonical_state["status"] == "PARSED"
    assert canonical_state["coverage_status"] == "INCOMPLETE"
    assert coverage["entity_coverage"][0]["status"] == "INCOMPLETE"
    assert coverage["summary"]["interaction_variants_complete"] == 1
    result_scope = coverage["match_result_coverage"][0]
    assert result_scope["status"] == "INCOMPLETE"
    assert result_scope["aggregate_counts"]["pg"] == 3
    assert result_scope["missing_result_views"] == ["all", "pe", "pp"]


def test_all_current_result_filters_reconcile_against_aggregates_and_unique_ids() -> None:
    canonical, _ = _filtered_match_pages()
    variants = [_match_variant_for_filter(value) for value in (None, "pg", "pe", "pp")]
    coverage = build_club_team_coverage([canonical], variant_pages=variants)

    assert [item["coverage_status"] for item in coverage["interaction_variants"]] == [
        "COMPLETE", "COMPLETE", "COMPLETE", "COMPLETE",
    ]
    for item in coverage["interaction_variants"]:
        assert item["validation"]["validated"] is True
    result_scope = coverage["match_result_coverage"][0]
    assert result_scope["status"] == "COMPLETE"
    assert result_scope["aggregate_counts"] == {"pg": 3, "pe": 2, "pp": 1, "all": 6}
    assert result_scope["outcome_union_equals_all_view"] is True
    assert result_scope["all_result_match_ids"] == ["1001", "1002", "1003", "1004", "1005", "1006"]
    assert result_scope["duplicate_ids_across_outcomes"] == []
    base_match_view = next(
        item for item in coverage["views"] if item["entity_type"] == "club" and item["view"] == "club_matches"
    )
    assert all("resultado" not in pending.lower() for pending in base_match_view["pending"])
    # Match-filter completeness is scoped; the club entity remains incomplete because
    # its other base views and historical interactions were not all supplied here.
    assert coverage["entity_coverage"][0]["status"] == "INCOMPLETE"


def test_all_results_variant_alone_closes_primary_scope_against_pj_pg_pe_pp() -> None:
    canonical, _ = _filtered_match_pages()
    all_results = _match_variant_for_filter(None)
    coverage = build_club_team_coverage([canonical], variant_pages=[all_results])

    result_scope = coverage["match_result_coverage"][0]
    assert result_scope["status"] == "COMPLETE"
    assert result_scope["required_result_views"] == ["all"]
    assert result_scope["missing_required_result_views"] == []
    assert result_scope["optional_outcome_filter_views_pending"] == ["pe", "pg", "pp"]
    assert result_scope["all_view_outcomes_match_aggregates"] is True
    assert result_scope["aggregate_counts"] == {"pg": 3, "pe": 2, "pp": 1, "all": 6}
    assert result_scope["outcome_union_equals_all_view"] is True


def test_zero_match_result_filter_validates_against_zero_aggregate() -> None:
    source_results = (("pg", "0", "3"), ("pg", "0", "1"), ("pg", "1", "2"),
        ("pg", "0", "2"), ("pg", "1", "3"), ("pe", "1", "1"))
    canonical_html = """<html><body><div id="body"><div class="hero"><h1>Partidos Lugo</h1></div>
      <main><table id="t1"><tr><th>Temporada</th><th>PJ</th><th>PG</th><th>PE</th><th>PP</th></tr>
      <tr><td>2026-27</td><td>6</td><td>5</td><td>1</td><td>0</td></tr></table></main></div></body></html>"""
    canonical = parse_club_team_html(
        canonical_html,
        "https://www.bdfutbol.com/es/p/e76.html",
        source_metadata={"access_status": "VALID", "http_status": 200},
    )
    empty_losses = _match_variant_for_filter("pp", source_results)
    empty_losses["entity_id"] = "e76"
    empty_losses["url"] = "https://www.bdfutbol.com/es/p/e76.html?cat=1rf&temp=2026-27&pgep=pp"
    coverage = build_club_team_coverage([canonical], variant_pages=[empty_losses])

    validation = coverage["interaction_variants"][0]["validation"]
    assert validation["aggregate_expected"] == 0
    assert validation["played_match_rows"] == 0
    assert validation["validated"] is True


def test_competition_crosscheck_loader_rejects_partial_exports_instead_of_ranking_labels(tmp_path: Path) -> None:
    poorer = tmp_path / "snapshot-newer"
    richer = tmp_path / "snapshot-richer"
    poorer.mkdir()
    richer.mkdir()
    for directory, extraction_key, result_status in (
        (poorer, "newer-empty", "scheduled"),
        (richer, "older-played", "played"),
    ):
        (directory / "dataset_metadata.json").write_text(
            json.dumps({"extraction_key": extraction_key}), encoding="utf-8",
        )
        for group, suffix in (("I", "i"), ("II", "ii")):
            (directory / f"matches_group_{suffix}.json").write_text(json.dumps({
                "source_snapshots": {group: {"captured_at_utc": f"2026-10-08T1{0 if result_status == 'played' else 2}:00:00+00:00"}},
                "items": [{
                    "match_id": f"{group}-1", "result_status": result_status,
                    "date": "2026-10-01", "home_goals": 1 if result_status == "played" else None,
                    "away_goals": 0 if result_status == "played" else None,
                }],
            }), encoding="utf-8")

    assert club_team_cli._load_competition_matches(tmp_path) is None
    with pytest.raises(InvalidCompetitionExport, match="older-played"):
        club_team_cli._load_competition_matches(tmp_path, extraction_key="older-played")


def test_entity_capture_state_changes_when_all_base_snapshots_are_present() -> None:
    from football_data_hub.providers.bdfutbol.club_team import expected_views_for_club, expected_views_for_team

    html = """<html><body><div id="body"><div class="hero"><h1>Real Jaén</h1>
      <a href="/es/e/e49.html">Real Jaén</a></div><main><h2>Datos</h2>
      <table id="sample"><tr><th>Campo</th></tr><tr><td>valor</td></tr></table>
      </main></div></body></html>"""
    team_urls = {
        "team_alignment": BASE,
        "team_roster": f"{BASE}?t=plantilla",
        "team_statistics": f"{BASE}?t=lista",
        "team_tracking": f"{BASE}?t=seg",
        "team_transfers": f"{BASE}?t=altas",
        "team_matches": f"{BASE}?tab=partits",
    }
    club_urls = {
        "club_profile": "https://www.bdfutbol.com/es/e/e49.html",
        "club_statistics": "https://www.bdfutbol.com/es/e/e49.html?p=stats",
        "club_players": "https://www.bdfutbol.com/es/e/egols49.html",
        "club_coaches": "https://www.bdfutbol.com/es/e/eentr49.html",
        "club_matches": "https://www.bdfutbol.com/es/p/e49.html",
        "club_rivals": "https://www.bdfutbol.com/es/p/er49.html",
    }
    pages = [
        parse_club_team_html(
            html,
            url,
            source_metadata={"access_status": "VALID", "http_status": 200, "rendered_html_sha256": view},
        )
        for view, url in {**team_urls, **club_urls}.items()
    ]
    partial = build_club_team_coverage(pages[:2], team_season_ids=[TEAM_ID])
    captured = build_club_team_coverage(pages, team_season_ids=[TEAM_ID])
    team_state = next(item for item in captured["entity_coverage"] if item["entity_type"] == "team_season")

    assert partial["entity_coverage"][0]["status"] == "INCOMPLETE"
    assert team_state["base_capture_status"] == "COMPLETE"
    assert team_state["status"] == "BASE_CAPTURED"
    assert team_state["interpretation_status"] == "PARTIAL_RAW_PRESERVED"
    assert team_state["views_captured"] == len(expected_views_for_team())
    assert len(expected_views_for_club()) == 6
    assert team_state["pending_interactions"]


def test_two_new_participants_with_different_roster_shapes_use_same_parser() -> None:
    team_specs = (
        ("t2026-27149", "e149", ("j201", "j202"), False),
        ("t2026-2740", "e40", ("j301", "j302", "j303"), True),
    )
    pages = []
    for team_id, club_id, player_ids, wider_roster in team_specs:
        base = f"https://www.bdfutbol.com/es/t/{team_id}.html"
        roster_rows = "".join(member_row(player_id, f"Jugador {player_id}") for player_id in player_ids)
        roster_html = team_html(
            roster_rows=roster_rows,
            team_season_id=team_id,
            club_id=club_id,
        )
        if wider_roster:
            roster_html = roster_html.replace(
                "<th class='optional'>Min</th>",
                "<th class='optional'>Min</th><th>Dato adicional</th>",
            ).replace("</td></tr>", "</td><td>valor raw</td></tr>")
        stats_html = team_html(
            include_roster=False,
            statistics_rows="".join(stats_row(player_id, f"Jugador {player_id}", "0") for player_id in player_ids),
            team_season_id=team_id,
            club_id=club_id,
        )
        pages.extend([
            parse_club_team_html(
                roster_html,
                f"{base}?t=plantilla",
                source_metadata={"access_status": "VALID", "http_status": 200},
            ),
            parse_club_team_html(
                stats_html,
                f"{base}?t=lista",
                source_metadata={"access_status": "VALID", "http_status": 200},
            ),
        ])

    coverage = build_club_team_coverage(pages, team_season_ids=[item[0] for item in team_specs])

    for team_id, _, player_ids, _ in team_specs:
        check = coverage["team_membership_checks"][team_id]
        assert check["roster_rows"] == len(player_ids)
        assert check["statistics_rows"] == len(player_ids)
        assert check["roster_ids_without_statistics"] == []
        assert check["statistics_ids_without_roster"] == []
    assert coverage["team_membership_checks"]["t2026-27149"]["roster_rows"] != coverage[
        "team_membership_checks"
    ]["t2026-2740"]["roster_rows"]


def test_full_width_section_row_is_preserved_without_false_table_overflow() -> None:
    html = """<html><body><div id="body"><div class="hero"><h1>Plantilla 2026-27</h1>
      <a href="/es/e/e49.html">Real Jaén</a></div><main><table id="taulaplantilla">
      <tr><th>Apodo</th><th>Pos</th></tr>
      <tr><td><a href="/es/j/j101.html">Jugador</a></td><td>Delantero</td></tr>
      <tr><td colspan="50">Suplentes</td></tr></table></main></div></body></html>"""
    page = parse_club_team_html(
        html,
        BASE,
        source_metadata={"access_status": "VALID", "http_status": 200},
    )
    coverage = build_club_team_coverage([page], team_season_ids=[TEAM_ID])
    alignment = next(item for item in coverage["views"] if item["view"] == "team_alignment")

    assert alignment["status"] == "VALIDATED"
    assert alignment["table_integrity_status"] == "VALIDATED"
    assert alignment["table_integrity"]["taulaplantilla"]["section_spanning_row_indexes"] == [2]
    assert alignment["table_integrity"]["taulaplantilla"]["row_indexes_with_overflow"] == []


def test_export_writes_json_csv_and_relationships_without_network(tmp_path: Path) -> None:
    pages = parsed_team_pages()
    coverage = build_club_team_coverage(pages, team_season_ids=[TEAM_ID])
    output = write_club_team_exports(parsed_pages=pages, coverage=coverage, output_root=tmp_path)

    assert (output / "pages/team_season/t2026-2749/team_roster.json").is_file()
    assert (output / "team_members.json").is_file()
    assert (output / "team_members.csv").is_file()
    assert (output / "relationships.csv").is_file()
    export_summary = json.loads((output / "export_summary.json").read_text(encoding="utf-8"))
    members = json.loads((output / "team_members.json").read_text(encoding="utf-8"))

    assert export_summary["team_membership_rows"] == 1
    assert members["items"][0]["player_id"] == "j101"
    assert members["items"][0]["zero_appearances"] is True


def test_compact_export_is_gzip_lossless_and_keeps_legacy_export_untouched(tmp_path: Path) -> None:
    pages = parsed_team_pages()
    coverage = build_club_team_coverage(pages, team_season_ids=[TEAM_ID])
    legacy = write_club_team_exports(parsed_pages=pages, coverage=coverage, output_root=tmp_path)
    compact = write_club_team_exports(
        parsed_pages=pages,
        coverage=coverage,
        output_root=tmp_path,
        compact=True,
        processing_seconds=1.25,
    )
    compact_with_tables = write_club_team_exports(
        parsed_pages=pages,
        coverage=coverage,
        output_root=tmp_path,
        compact=True,
        include_table_csv=True,
    )

    assert legacy.parent == tmp_path.resolve()
    assert compact.parent == (tmp_path / "compact").resolve()
    original = json.loads((legacy / "pages/team_season/t2026-2749/team_roster.json").read_text(encoding="utf-8"))
    with gzip.open(compact / "pages/team_season/t2026-2749/team_roster.json.gz", "rt", encoding="utf-8") as stream:
        restored = json.load(stream)
    assert restored == original
    assert not (compact / "table_rows.csv.gz").exists()
    with gzip.open(compact_with_tables / "table_rows.csv.gz", "rt", encoding="utf-8") as stream:
        csv_header = stream.readline()
    assert "cells_json" in csv_header
    assert (legacy / "pages/team_season/t2026-2749/team_roster.json").is_file()
    with gzip.open(compact / "dataset_metadata.json.gz", "rt", encoding="utf-8") as stream:
        metadata = json.load(stream)
    assert metadata["storage_format"]["compression"] == "gzip"
    assert metadata["storage_format"]["table_rows_csv_included"] is False
    with gzip.open(compact_with_tables / "dataset_metadata.json.gz", "rt", encoding="utf-8") as stream:
        metadata_with_csv = json.load(stream)
    assert metadata_with_csv["storage_format"]["table_rows_csv_included"] is True
    with gzip.open(compact / "export_summary.json.gz", "rt", encoding="utf-8") as stream:
        summary = json.load(stream)
    assert summary["processing_seconds"] >= 1.25


def test_new_raw_run_root_never_reuses_an_existing_path(tmp_path: Path, monkeypatch) -> None:
    from football_data_hub.collectors import bdfutbol_club_team as collector

    monkeypatch.setattr(collector, "timestamp_utc", lambda: "20261008T120000Z")
    old = tmp_path / "raw" / "20261008T120000Z"
    old.mkdir(parents=True)
    sentinel = old / "existing.raw"
    sentinel.write_text("preserve", encoding="utf-8")

    created = _new_snapshot_run_root(tmp_path / "raw")

    assert created.name == "20261008T120000Z-01"
    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_latest_snapshot_selection_is_reusable_without_refresh(tmp_path: Path) -> None:
    url = f"{BASE}?t=plantilla"
    older = tmp_path / "raw" / "older"
    newer = tmp_path / "raw" / "newer"
    write_snapshot(older, url, team_html(), "2026-10-08T12:00:00Z")
    write_snapshot(newer, url, team_html(), "2026-10-08T13:00:00Z")

    snapshots = discover_latest_snapshots(tmp_path / "raw", team_season_ids={TEAM_ID})

    assert [item.directory for item in snapshots] == [newer.resolve()]


@pytest.mark.parametrize("latest_failure", ["bad_sha", "incomplete_marker"])
def test_latest_invalid_snapshot_falls_back_to_previous_valid_copy(
    tmp_path: Path, latest_failure: str,
) -> None:
    url = f"{BASE}?t=plantilla"
    older = tmp_path / "raw" / "older"
    newer = tmp_path / "raw" / "newer"
    write_snapshot(older, url, team_html(), "2026-10-08T12:00:00Z")
    write_snapshot(newer, url, team_html(), "2026-10-08T13:00:00Z")
    if latest_failure == "bad_sha":
        (newer / "rendered.html").write_text("changed after capture", encoding="utf-8")
    else:
        (newer / "INCOMPLETE").write_text("capture stopped", encoding="utf-8")

    snapshots = discover_latest_snapshots(tmp_path / "raw", team_season_ids={TEAM_ID})

    assert [item.directory for item in snapshots] == [older.resolve()]
    assert snapshots[0].sha256 == hashlib.sha256((older / "rendered.html").read_bytes()).hexdigest()


def test_refresh_skips_a_reusable_snapshot_without_mutating_it(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "raw" / "prior"
    url = f"{BASE}?t=plantilla"
    write_snapshot(snapshot_dir, url, team_html())
    existing = load_club_team_snapshot(snapshot_dir)
    cache = {url: existing}

    reused = _snapshot_for_reuse(cache, url, reuse_existing=True)
    refreshed = _snapshot_for_reuse(cache, url, reuse_existing=False)

    assert reused is not None and reused.capture_disposition == "REUSED"
    assert refreshed is None
    assert existing.capture_disposition == "CAPTURED"
    assert (snapshot_dir / "rendered.html").is_file()


def test_cli_distinguishes_reuse_refresh_and_offline_modes() -> None:
    reusable = parse_args(["live", "--team-id", TEAM_ID])
    refresh = parse_args(["live", "--team-id", TEAM_ID, "--refresh"])
    offline = parse_args(["offline", "--team-id", TEAM_ID])

    assert reusable.mode == "live" and reusable.refresh is False
    assert refresh.mode == "live" and refresh.refresh is True
    assert offline.mode == "offline"


def test_offline_cli_returns_nonzero_when_a_base_view_is_missing(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    team_views = (
        "team_alignment", "team_roster", "team_statistics", "team_tracking",
        "team_transfers", "team_matches",
    )
    club_views = (
        "club_profile", "club_statistics", "club_players", "club_coaches",
        "club_matches", "club_rivals",
    )
    view_rows = []
    for entity_type, entity_id, names in (
        ("team_season", TEAM_ID, team_views),
        ("club", CLUB_ID, club_views),
    ):
        for view in names:
            missing = entity_type == "club" and view == "club_rivals"
            view_rows.append({
                "entity_type": entity_type,
                "entity_id": entity_id,
                "view": view,
                "status": "DISCOVERED" if missing else "PARSED",
                "access_status": None if missing else "VALID",
                "table_integrity_status": "NOT_CAPTURED" if missing else "VALIDATED",
                "table_integrity": {} if missing else {"main": {"raw_cell_values_preserved": True}},
            })
    coverage = {
        "summary": {
            "views_expected": 12,
            "views_captured": 11,
            "views_validated": 10,
            "unique_team_player_ids": 1,
            "unique_team_coach_ids": 1,
        },
        "entity_coverage": [
            {
                "entity_type": "team_season", "entity_id": TEAM_ID, "club_id": CLUB_ID,
                "views_expected": 6, "views_captured": 6, "views_access_valid": 6,
                "base_capture_status": "COMPLETE",
            },
            {
                "entity_type": "club", "entity_id": CLUB_ID, "club_id": None,
                "views_expected": 6, "views_captured": 5, "views_access_valid": 5,
                "base_capture_status": "PARTIAL",
            },
        ],
        "views": view_rows,
    }
    parsed_pages = [{
        "entity_type": "team_season", "entity_id": TEAM_ID, "view": "team_alignment",
        "relationships": [{"entity_type": "club", "entity_id": CLUB_ID}],
    }]
    monkeypatch.setattr(
        club_team_cli,
        "_process_snapshots",
        lambda **_: (tmp_path, coverage, parsed_pages, []),
    )

    exit_code = club_team_cli.run(
        parse_args(["offline", "--team-id", TEAM_ID, "--output-root", str(tmp_path)])
    )

    captured = capsys.readouterr()
    assert exit_code == 5
    assert "CAPTURA BASE INCOMPLETA" in captured.err
    assert "club e49/club_rivals" in captured.err
    assert "Estado de captura base: BASE_CAPTURED" not in captured.out


def test_raw_integrity_validation_count_is_separate_from_parser_state() -> None:
    coverage = {
        "views": [
            {
                "access_status": "VALID",
                "table_integrity_status": "VALIDATED",
                "table_integrity": {"main": {"raw_cell_values_preserved": True}},
                "status": "PARSED",
            },
            {
                "access_status": "VALID",
                "table_integrity_status": "VALIDATED",
                "table_integrity": {"main": {"raw_cell_values_preserved": False}},
                "status": "PARSED",
            },
            {
                "access_status": "VALID",
                "table_integrity_status": "NOT_CAPTURED",
                "table_integrity": {},
                "status": "DISCOVERED",
            },
        ]
    }

    assert club_team_cli._base_raw_integrity_validated_count(coverage) == 1


def test_export_keeps_filtered_variant_separate_with_source_provenance(tmp_path: Path) -> None:
    team_pages = parsed_team_pages()
    canonical, variant = _filtered_match_pages()
    pages = [*team_pages, canonical]
    coverage = build_club_team_coverage(pages, team_season_ids=[TEAM_ID], variant_pages=[variant])
    output = write_club_team_exports(
        parsed_pages=pages,
        variant_pages=[variant],
        coverage=coverage,
        output_root=tmp_path,
    )

    assert (output / "pages/club/e49/club_matches.json").is_file()
    assert (output / "variants/club/e49/club_matches/cat-1rf__pgep-pg__temp-2026-27.json").is_file()
    assert (output / "interaction_variants.csv").is_file()
    assert (output / "variant_table_rows.csv").is_file()
    summary = json.loads((output / "export_summary.json").read_text(encoding="utf-8"))
    variant_export = json.loads((output / "interaction_variants.json").read_text(encoding="utf-8"))
    relationships = json.loads((output / "relationships.json").read_text(encoding="utf-8"))

    assert summary["parsed_page_count"] == 3
    assert summary["variant_page_count"] == 1
    assert summary["variant_table_rows"] > 0
    assert variant_export["items"][0]["coverage_status"] == "COMPLETE"
    assert any(item["source_variant_id"] == variant["view_variant"]["variant_id"] for item in relationships["items"])
