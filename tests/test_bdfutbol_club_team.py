from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from football_data_hub.collectors.bdfutbol_club_team import (
    InvalidClubTeamSnapshot,
    _club_urls,
    discover_latest_snapshots,
    load_club_team_snapshot,
)
from football_data_hub.parsers.club_team_coverage import build_club_team_coverage
from football_data_hub.providers.bdfutbol.club_team import (
    InvalidClubTeamPage,
    classify_club_team_url,
    parse_club_team_html,
)
from football_data_hub.storage.club_team_exports import write_club_team_exports


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
      <main><h2>Temporadas</h2><table id="t1"><tr><th>Temporada</th><th>PJ</th><th>PG</th></tr>
        <tr><td>2026-27</td><td>6</td><td>3</td></tr></table></main></div></body></html>"""
    variant_html = """<html><body><div id="body"><div class="hero"><h1>Partidos Jaén</h1></div>
      <main><h2>Partidos</h2><table id="tpartits">
        <tr><th>Temporada</th><th>Competición</th><th>Fecha</th><th>Local</th><th>Visitante</th><th>Resultado</th></tr>
        <tr><td>2026-27</td><td>1rf</td><td>30/08/2026</td><td>Europa</td><td>Jaén</td><td>0-3</td></tr>
        <tr><td>2026-27</td><td>1rf</td><td>12/09/2026</td><td><a href="/es/e/e76.html">Teruel</a></td><td>Jaén</td><td>0-1</td></tr>
        <tr><td>2026-27</td><td>1rf</td><td>19/09/2026</td><td>Jaén</td><td>UD Ibiza</td><td>4-2</td></tr>
        <tr class="filatotal"><td colspan="6">Total 3 victorias</td></tr>
      </table></main></div></body></html>"""
    canonical = parse_club_team_html(
        canonical_html,
        "https://www.bdfutbol.com/es/p/e49.html",
        source_metadata={"access_status": "VALID", "http_status": 200, "rendered_html_sha256": "base-hash"},
    )
    filters = {"cat": "1rf", "temp": "2026-27", "pgep": "pg"}
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


def test_filtered_club_matches_variant_is_validated_only_in_its_scope() -> None:
    canonical, variant = _filtered_match_pages()
    coverage = build_club_team_coverage([canonical], variant_pages=[variant])
    match_variant = coverage["interaction_variants"][0]

    assert match_variant["status"] == "VALIDATED"
    assert match_variant["coverage_status"] == "COMPLETE"
    assert match_variant["records_observed"] == 3
    assert match_variant["validation"]["aggregate_wins"] == 3
    assert match_variant["validation"]["total_rows"] == 1
    canonical_state = next(item for item in coverage["views"] if item["view"] == "club_matches")
    assert canonical_state["status"] == "PARSED"
    assert canonical_state["coverage_status"] == "INCOMPLETE"
    assert coverage["entity_coverage"][0]["status"] == "INCOMPLETE"
    assert coverage["summary"]["interaction_variants_complete"] == 1


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
