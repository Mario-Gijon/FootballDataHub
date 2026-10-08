from __future__ import annotations

import json
from pathlib import Path

from football_data_hub.bdfutbol.player import (
    parse_aggregate_matrix,
    parse_player_career,
    parse_player_full_run,
    parse_player_identity,
    parse_player_match_appearances,
)

PROFILE_HTML = """
<html><head><title>Morillas, Jaime Morillas Giménez - Futbolista | BDFutbol</title></head><body>
<h1>Morillas</h1>
<div><span>Nombre completo</span><span>Jaime Morillas Giménez</span></div>
<div><span>Fecha de nacimiento</span><span>10/08/2004 (22 años)</span></div>
<div><span>Lugar de nacimiento</span><span>Sa Pobla ( Islas Baleares )</span></div>
<div><span>Demarcación</span><span>Portero</span></div>
<div><span>Altura</span><span>185 cm</span></div>
<table class="taula_estil traject">
<tr><th>Temp</th><th>Equipo</th><th>País</th><th></th><th>Div</th><th>Edad</th><th>PJ</th><th>PT</th><th>PC</th><th>PS</th><th>PX</th><th>PI</th><th>C</th><th>TC</th><th>PG</th><th>PE</th><th>PP</th><th>Min</th><th>TA</th><th>TR</th><th>G</th><th>GP</th><th>GPP</th><th>GE</th><th>NR</th><th></th></tr>
<tr>
<td data-temporada="2026-27" data-temporadaid="0" data-idclub="49" data-idjug="0">2026-27</td>
<td data-codi="49">Jaén</td><td></td><td></td><td>1ªRf</td><td>22</td><td>6</td><td>6</td><td>6</td><td>0</td><td>0</td><td>0</td><td>0</td><td>6</td><td>3</td><td>2</td><td>1</td><td>540</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>5</td><td>1</td><td></td>
</tr>
</table></body></html>
"""

STATS_HTML = """
<html><body>
<table id="table-estadistiques-competicions">
<tr><th>Tipo</th><th>2ªB</th><th>1ªRf</th><th>COP</th></tr>
<tr><td>Temporadas</td><td>2</td><td>1</td><td>1</td></tr>
<tr><td>Partidos Jugados</td><td><a href="/es/p/j209629.html?cat=2aB&pj=1">23</a></td><td>6</td><td>1</td></tr>
</table>
<table id="table-estadistiques-equips">
<tr><th>Tipo</th><th title="Atlético Baleares">ATL</th><th title="Jaén">JAÉ</th></tr>
<tr><td>Temporadas</td><td>1</td><td>2</td></tr>
<tr><td>Partidos Jugados</td><td>18</td><td>16</td></tr>
</table>
</body></html>
"""

MATCHES_HTML = """
<html><body><table id="tpartits">
<tr><th>#</th><th>Fecha</th><th>Temporada</th><th>Competición</th><th>Tipo</th><th>Local</th><th></th><th>Visitante</th><th>PT</th><th>PC</th><th>PS</th><th>PX</th><th>PI</th><th>C</th><th>Min</th><th>TA</th><th>TR</th><th>G</th><th>GE</th></tr>
<tr><td><a href="/es/p/p.php?id=272523">1</a></td><td>30/08/2026</td><td>2026-27</td><td>1rf</td><td>1</td><td>Europa</td><td>0 3</td><td>Jaén</td><td></td><td></td><td></td><td></td><td></td><td></td><td>90</td><td></td><td></td><td></td><td></td></tr>
<tr><td></td><td>Total 1</td><td></td><td></td><td></td><td></td><td></td><td>1</td><td>1</td><td></td><td></td><td></td><td></td><td>90</td><td></td><td></td><td></td><td>0</td></tr>
</table></body></html>
"""


def test_identity():
    x = parse_player_identity(PROFILE_HTML, player_id=209629, source_url="x")
    assert (x.display_name, x.full_name, x.birth_date, x.age_displayed) == ("Morillas", "Jaime Morillas Giménez", "10/08/2004", 22)
    assert (x.birth_place, x.birth_region, x.position, x.height_cm) == ("Sa Pobla", "Islas Baleares", "Portero", 185)


def test_career():
    row = parse_player_career(PROFILE_HTML, provenance="bdfutbol", source_url="x")[0]
    assert row.season == "2026-27"
    assert row.team_name == "Jaén"
    assert row.team_provider_id == 49
    assert row.appearances == 6
    assert row.starts == 6
    assert row.complete_matches == 6
    assert row.minutes == 540
    assert row.goals_conceded == 5
    assert row.squad_number == 1


def test_manager_ids():
    html = PROFILE_HTML.replace('data-temporadaid="0" data-idclub="49" data-idjug="0"', 'data-temporadaid="5742" data-idclub="270" data-idjug="161923"').replace('data-codi="49"', 'data-codi="270"')
    row = parse_player_career(html, provenance="bdfutbol_manager", source_url="x")[0]
    assert row.team_provider_id == 270
    assert row.provider_season_id == 5742
    assert row.provider_player_alias_id == 161923


def test_competition_matrix():
    m = parse_aggregate_matrix(STATS_HTML, table_id="table-estadistiques-competicions", scope="competition", provenance="bdfutbol", source_url="https://www.bdfutbol.com/")
    assert m is not None
    assert m.headers == ("Tipo", "2ªB", "1ªRf", "COP")
    assert m.rows[0].metric == "Temporadas"
    assert m.rows[1].values == ("23", "6", "1")
    assert "cat=2aB" in m.rows[1].raw_links[0][0]


def test_team_matrix_titles():
    m = parse_aggregate_matrix(STATS_HTML, table_id="table-estadistiques-equips", scope="team", provenance="bdfutbol", source_url="x")
    assert m is not None
    assert m.header_titles == (None, "Atlético Baleares", "Jaén")


def test_match_row():
    row = parse_player_match_appearances(MATCHES_HTML, provenance="bdfutbol", source_url="x")[0]
    assert row.match_provider_id == 272523
    assert row.match_provider_key == "bdfutbol:match:272523"
    assert row.provider_season_id is None
    assert row.date == "30/08/2026"
    assert row.home_team == "Europa"
    assert row.away_team == "Jaén"
    assert row.score_text == "0 3"
    assert (row.home_goals, row.away_goals, row.minutes) == (0, 3, 90)


def test_blank_status_cells_not_invented():
    row = parse_player_match_appearances(MATCHES_HTML, provenance="bdfutbol", source_url="x")[0]
    assert row.started_raw is None
    assert row.complete_raw is None
    assert "PT" in row.raw_cells and "PC" in row.raw_cells


def test_total_row_ignored():
    assert len(parse_player_match_appearances(MATCHES_HTML, provenance="bdfutbol", source_url="x")) == 1


def _write_resource(run: Path, name: str, html: str, provenance="bdfutbol"):
    attempt = run / name / "attempt_01"
    attempt.mkdir(parents=True)
    (attempt / "page.html").write_text(html, encoding="utf-8")
    (attempt / "metadata.json").write_text(json.dumps({"status": "VALID", "provenance": provenance, "final_url": "https://www.bdfutbol.com/"}), encoding="utf-8")


def test_full_run(tmp_path: Path):
    run = tmp_path / "run"
    _write_resource(run, "player_profile", PROFILE_HTML)
    _write_resource(run, "player_profile_manager", PROFILE_HTML, "bdfutbol_manager")
    _write_resource(run, "player_stats", STATS_HTML)
    _write_resource(run, "player_matches_season_2026-27", MATCHES_HTML)
    _write_resource(run, "player_matches_season_2025-26", MATCHES_HTML)
    snap = parse_player_full_run(run, player_id=209629)
    assert snap.identity.full_name == "Jaime Morillas Giménez"
    assert len(snap.canonical_career) == 1
    assert len(snap.manager_career) == 1
    assert len(snap.match_appearances) == 1
    assert snap.warnings == ()



def test_match_row_with_real_relative_bdfutbol_href() -> None:
    html = MATCHES_HTML.replace(
        '/es/p/p.php?id=272523',
        'p.php?id=272523',
    )

    rows = parse_player_match_appearances(
        html,
        provenance="bdfutbol",
        source_url=(
            "https://www.bdfutbol.com/es/p/"
            "j209629.html?temp=2026-27"
        ),
    )

    assert len(rows) == 1
    assert rows[0].match_provider_id == 272523
    assert rows[0].date == "30/08/2026"


def test_relative_match_href_is_resolved_from_manager_page() -> None:
    html = MATCHES_HTML.replace(
        '/es/p/p.php?id=272523',
        'p.php?id=272523',
    )

    rows = parse_player_match_appearances(
        html,
        provenance="bdfutbol_manager",
        source_url=(
            "https://www.bdfutbol.com/es/p/"
            "j209629.html?temp=2023-24&manager=1"
        ),
    )

    assert len(rows) == 1
    assert rows[0].match_provider_id == 272523
    assert rows[0].provenance == "bdfutbol_manager"


def test_unrelated_relative_id_link_is_not_a_match() -> None:
    html = MATCHES_HTML.replace(
        '/es/p/p.php?id=272523',
        '../j/j272523.html?id=272523',
    )

    rows = parse_player_match_appearances(
        html,
        provenance="bdfutbol",
        source_url=(
            "https://www.bdfutbol.com/es/p/"
            "j209629.html?temp=2026-27"
        ),
    )

    assert rows == ()



MANAGER_MATCHES_HTML = """
<html><body>
<table id="tpartits">
  <tr>
    <th>#</th><th>Fecha</th><th>Temporada</th><th>Competición</th>
    <th>Tipo</th><th>Local</th><th></th><th>Visitante</th>
    <th>PT</th><th>PC</th><th>PS</th><th>PX</th><th>PI</th><th>C</th>
    <th>Min</th><th>TA</th><th>TR</th><th>G</th><th>GE</th>
  </tr>
  <tr>
    <td><a href="/es/p/partido.html?id=5742&l=Cornellà&v=Constancia&d=03/09/2022">1</a></td>
    <td><a href="/es/p/partido.html?id=5742&l=Cornellà&v=Constancia&d=03/09/2022">03/09/2022</a></td>
    <td>2022-23</td><td>Juv</td><td>Jornada 1</td>
    <td>Cornellà</td><td>5 0</td><td>Constancia</td>
    <td></td><td></td><td></td><td></td><td></td><td></td>
    <td>54</td><td>'54</td><td></td><td></td><td>5</td>
  </tr>
  <tr>
    <td><a href="/es/p/partido.html?id=5742&l=Constancia&v=Ebro&d=02/10/2022">2</a></td>
    <td><a href="/es/p/partido.html?id=5742&l=Constancia&v=Ebro&d=02/10/2022">02/10/2022</a></td>
    <td>2022-23</td><td>Juv</td><td>Jornada 2</td>
    <td>Constancia</td><td>1 1</td><td>Ebro</td>
    <td></td><td></td><td></td><td></td><td></td><td></td>
    <td>90</td><td></td><td></td><td></td><td>1</td>
  </tr>
</table>
</body></html>
"""


def test_manager_matches_use_composite_provider_key_not_season_as_match_id() -> None:
    rows = parse_player_match_appearances(
        MANAGER_MATCHES_HTML,
        provenance="bdfutbol_manager",
        source_url=(
            "https://www.bdfutbol.com/es/p/"
            "j209629.html?temp=2022-23&manager=1"
        ),
    )

    assert len(rows) == 2
    assert rows[0].match_provider_id is None
    assert rows[0].provider_season_id == 5742
    assert rows[1].provider_season_id == 5742
    assert rows[0].match_provider_key != rows[1].match_provider_key
    assert "d=03%2F09%2F2022" in rows[0].match_provider_key


def test_manager_card_event_minute_is_preserved_raw() -> None:
    row = parse_player_match_appearances(
        MANAGER_MATCHES_HTML,
        provenance="bdfutbol_manager",
        source_url="https://www.bdfutbol.com/es/p/j209629.html?manager=1",
    )[0]

    assert row.yellow_cards_raw == "'54"
    assert row.red_cards_raw is None
    assert row.goals_raw is None


def test_full_run_keeps_two_manager_matches_with_same_provider_season_id(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    _write_resource(
        run,
        "player_profile",
        PROFILE_HTML,
    )
    _write_resource(
        run,
        "player_stats",
        STATS_HTML,
    )
    _write_resource(
        run,
        "player_matches_season_2022-23",
        MANAGER_MATCHES_HTML,
        "bdfutbol_manager",
    )

    snapshot = parse_player_full_run(run, player_id=209629)

    assert len(snapshot.match_appearances) == 2
    assert {
        item.provider_season_id
        for item in snapshot.match_appearances
    } == {5742}
    assert len({
        item.match_provider_key
        for item in snapshot.match_appearances
    }) == 2
    assert snapshot.warnings == ()


def test_canonical_and_manager_match_keys_have_separate_identity_spaces() -> None:
    canonical = parse_player_match_appearances(
        MATCHES_HTML,
        provenance="bdfutbol",
        source_url="https://www.bdfutbol.com/es/p/j209629.html?temp=2026-27",
    )[0]
    manager = parse_player_match_appearances(
        MANAGER_MATCHES_HTML,
        provenance="bdfutbol_manager",
        source_url="https://www.bdfutbol.com/es/p/j209629.html?temp=2022-23&manager=1",
    )[0]

    assert canonical.match_provider_key.startswith("bdfutbol:match:")
    assert manager.match_provider_key.startswith(
        "bdfutbol_manager:/es/p/partido.html?"
    )
