from __future__ import annotations

import pytest

from football_data_hub.bdfutbol.team_season import (
    TeamSeasonParseError,
    parse_team_season,
)


HTML = """
<!doctype html>
<html>
<head>
  <link rel="canonical" href="/es/t/t2026-2749.html">
</head>
<body>
  <h1><a href="/es/e/e49.html">Jaén</a> 2026-27</h1>

  <!-- Real BDFutbol can emit a relative competition href. -->
  <a href="t2026-271rf2.html">1ª RFEF</a>
  <p>Partidos: 6 (50% ganados)</p>

  <h2>Entrenador</h2>
  <table>
    <tr>
      <th></th><th></th><th>Apodo y Nombre</th><th>Edad</th>
      <th>Jornadas</th><th>Partidos</th><th>TA</th><th>TR</th>
    </tr>
    <tr>
      <td></td><td></td>
      <td>
        <a href="/es/l/l1835.html">
          Manolo Herrero
          <span class="responsive-full-name">Manuel Herrero Galaso</span>
        </a>
      </td>
      <td>56</td><td>1-6</td><td>6</td><td>-</td><td>-</td>
    </tr>
  </table>

  <h2>Titulares</h2>

  <!-- Model the real responsive layout conservatively: both sections may be
       present in one physical table, with a section boundary inside it. -->
  <table>
    <tr>
      <th>#</th><th></th><th></th><th>Apodo y Nombre</th><th>Pos</th>
      <th>Edad</th><th>PJ</th><th>PT</th><th>PC</th><th>PS</th>
      <th>C</th><th>Min</th><th>TA</th><th>TR</th><th>G</th>
    </tr>
    <tr>
      <td>1</td><td></td><td></td>
      <td>
        <a href="/es/j/j209629.html">
          Morillas
          <span class="responsive-full-name">Jaime Morillas</span>
        </a>
      </td>
      <td><img title="Portero"></td>
      <td>22</td><td>6</td><td>6</td><td>6</td><td>0</td>
      <td>0</td><td>540</td><td>0</td><td>0</td><td>-5</td>
    </tr>
    <tr>
      <td>3</td><td></td><td></td>
      <td><a href="/es/j/j300003.html">Serrano</a></td>
      <td>Defensa</td>
      <td>21</td><td>6</td><td>6</td><td>6</td><td>0</td>
      <td>0</td><td>540</td><td>1</td><td>0</td><td>1</td>
    </tr>

    <tr><th colspan="15">Suplentes</th></tr>

    <tr>
      <th>#</th><th></th><th></th><th>Apodo y Nombre</th><th>Pos</th>
      <th>Edad</th><th>PJ</th><th>PT</th><th>PC</th><th>PS</th>
      <th>C</th><th>Min</th><th>TA</th><th>TR</th><th>G</th>
    </tr>
    <tr>
      <td>13</td><td></td><td></td>
      <td>
        <a href="/es/j/j300013.html">
          Salvi⬤⬤
          <span class="responsive-full-name">Salvador Montañez</span>
        </a>
      </td>
      <td></td>
      <td>26</td><td>0</td><td>0</td><td>0</td><td>0</td>
      <td>6</td><td>0</td><td>0</td><td>0</td><td>0</td>
    </tr>
  </table>
</body>
</html>
"""


def test_parses_team_season_context() -> None:
    snapshot = parse_team_season(
        HTML,
        "https://www.bdfutbol.com/es/t/t2026-2749.html",
        expected_team_id=49,
    )

    assert snapshot.context.team.provider_id == 49
    assert snapshot.context.team_name == "Jaén"
    assert snapshot.context.season == "2026-27"
    assert snapshot.context.competition_code == "1rf"
    assert snapshot.context.competition_name == "1ª RFEF"
    assert snapshot.context.group == 2
    assert snapshot.context.matches_played == 6
    assert snapshot.context.win_percentage == 50.0


def test_parses_coach_and_uses_visible_name_only() -> None:
    snapshot = parse_team_season(
        HTML,
        "https://www.bdfutbol.com/es/t/t2026-2749.html",
    )

    assert len(snapshot.coaches) == 1
    coach = snapshot.coaches[0]
    assert coach.coach.key == ("bdfutbol", "coach", 1835)
    assert coach.coach_name == "Manolo Herrero"
    assert coach.age == 56
    assert coach.rounds == "1-6"
    assert coach.matches == 6
    assert coach.yellow_cards is None


def test_parses_combined_table_into_starters_and_substitutes() -> None:
    snapshot = parse_team_season(
        HTML,
        "https://www.bdfutbol.com/es/t/t2026-2749.html",
        min_squad_members=3,
    )

    assert len(snapshot.squad) == 3
    morillas, serrano, salvi = snapshot.squad

    assert morillas.player.key == ("bdfutbol", "player", 209629)
    assert morillas.player_name == "Morillas"
    assert morillas.squad_number == 1
    assert morillas.squad_section == "starter"
    assert morillas.position == "Portero"
    assert morillas.appearances == 6
    assert morillas.minutes == 540
    assert morillas.goals == -5

    assert serrano.squad_section == "starter"
    assert serrano.position == "Defensa"

    assert salvi.player_name == "Salvi"
    assert salvi.squad_section == "substitute"
    assert salvi.unused_callups == 6


def test_no_false_section_warnings_after_realistic_split() -> None:
    snapshot = parse_team_season(
        HTML,
        "https://www.bdfutbol.com/es/t/t2026-2749.html",
    )

    assert "starters_not_found" not in snapshot.warnings
    assert "substitutes_not_found" not in snapshot.warnings
    assert "competition_not_found" not in snapshot.warnings


def test_expected_team_id_is_checked() -> None:
    with pytest.raises(TeamSeasonParseError, match="team_id=178"):
        parse_team_season(
            HTML,
            "https://www.bdfutbol.com/es/t/t2026-2749.html",
            expected_team_id=178,
        )


def test_minimum_squad_size_is_checked() -> None:
    with pytest.raises(TeamSeasonParseError, match="al menos 4"):
        parse_team_season(
            HTML,
            "https://www.bdfutbol.com/es/t/t2026-2749.html",
            min_squad_members=4,
        )


def test_wrong_resource_is_not_silently_accepted() -> None:
    with pytest.raises(TeamSeasonParseError, match="temporada/team_id"):
        parse_team_season(
            "<html><body><h1>BDFutbol</h1></body></html>",
            "https://www.bdfutbol.com/es/index.html",
        )
