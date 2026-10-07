from football_data_hub.bdfutbol.competition import parse_competition


HTML = """
<!doctype html>
<html>
<head>
<link rel="canonical" href="https://www.bdfutbol.com/es/t/t2026-271rf1.html">
</head>
<body>
<table id="classification">
<tr>
  <th></th><th></th><th></th><th></th>
  <th>Pts.</th><th>PJ</th><th>PG</th><th>PE</th><th>PP</th>
  <th>GF</th><th>GC</th><th>TA</th><th>TR</th>
</tr>
<tr>
  <td></td><td>1</td><td></td>
  <td><a href="../t/t2026-27178.html">UD Logroñés</a></td>
  <td>16</td><td>6</td><td>5</td><td>1</td><td>0</td><td>15</td><td>7</td><td>15</td><td>2</td>
</tr>
<tr>
  <td></td><td>2</td><td></td>
  <td><a href="../t/t2026-2758.html">Pontevedra</a></td>
  <td>8</td><td>6</td><td>2</td><td>2</td><td>2</td><td>8</td><td>8</td><td>13</td><td>3</td>
</tr>
</table>
<script>
SE=[]; SP=[];
SE[0]="0|UD Logroñés";
SE[1]="1|Pontevedra";
SP[1]=[];SP[1].push({"d":"28/08/2026","a1":"0","a2":"1","g1":"2","g2":"1","id":"269408","r":"1","tg1":"5","tg2":"3","tv1":"0","tv2":"1"});
SP[38]=[];SP[38].push({"d":"23/05/2027","a1":"1","a2":"0","g1":"-1","g2":"-1","id":"269778","r":"0","tg1":"0","tg2":"0","tv1":"0","tv2":"0"});
</script>
<table>
<tr data-jornada="1"><th>Fecha</th><th>Local</th><th></th><th>Visitante</th><th>Estadio</th><th>Árbitro</th></tr>
<tr data-jornada="1">
  <td><a href="../p/p.php?id=269408">28/08/2026</a></td>
  <td><a href="../p/p.php?id=269408">UD Logroñés</a></td>
  <td>2 1</td>
  <td><a href="../p/p.php?id=269408">Pontevedra</a></td>
  <td><a href="../s/22.html">Las Gaunas</a></td>
  <td><a href="../r/r601270.html">Ramo Andrés</a></td>
</tr>
<tr data-jornada="38"><th>Fecha</th><th>Local</th><th></th><th>Visitante</th><th>Estadio</th><th>Árbitro</th></tr>
<tr data-jornada="38">
  <td>23/05/2027</td><td>Pontevedra</td><td>—</td><td>UD Logroñés</td><td></td><td></td>
</tr>
</table>
</body>
</html>
"""


def test_parses_context_standings_and_played_fixture() -> None:
    snapshot = parse_competition(
        HTML,
        "https://www.bdfutbol.com/es/t/t2026-271rf1.html",
        expected_team_count=2,
        expected_fixture_count=2,
    )

    assert snapshot.context.competition_code == "1rf"
    assert snapshot.context.season == "2026-27"
    assert snapshot.context.group == 1

    assert snapshot.standings[0].team.provider_id == 178
    assert snapshot.standings[0].team_name == "UD Logroñés"
    assert snapshot.standings[0].points == 16

    match = snapshot.fixtures[0]
    assert match.match.provider_id == 269408
    assert match.played is True
    assert (match.home_goals, match.away_goals) == (2, 1)
    assert match.home_team.provider_id == 178
    assert match.away_team.provider_id == 58
    assert match.stadium.provider_id == 22
    assert match.referee.provider_id == 601270
    assert match.home_yellow_cards == 5
    assert match.away_red_cards == 1


def test_future_fixture_keeps_match_id_but_not_placeholder_stats() -> None:
    snapshot = parse_competition(
        HTML,
        "https://www.bdfutbol.com/es/t/t2026-271rf1.html",
    )

    match = snapshot.fixtures[1]
    assert match.match.provider_id == 269778
    assert match.played is False
    assert match.home_goals is None
    assert match.away_goals is None
    assert match.home_yellow_cards is None
    assert match.home_red_cards is None
    assert match.stadium is None
    assert match.referee is None


def test_identity_includes_entity_type() -> None:
    snapshot = parse_competition(
        HTML,
        "https://www.bdfutbol.com/es/t/t2026-271rf1.html",
    )
    assert snapshot.fixtures[0].match.key == ("bdfutbol", "match", 269408)
    assert snapshot.standings[0].team.key == ("bdfutbol", "team", 178)
