from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from football_data_hub.providers.bdfutbol.players.capture_store import PlayerCaptureStore
from football_data_hub.providers.bdfutbol.players.export import build_player_capture_export
from football_data_hub.providers.bdfutbol.players.models import (
    PlayerMatchesPage,
    PlayerRivalsPage,
    PlayerStatisticsPage,
    PlayerTrajectoryPage,
)
from football_data_hub.providers.bdfutbol.players.parsers import (
    PlayerCaptureParseError,
    parse_player_html,
    parse_snapshot,
)


def _table(identifier: str, header: str = "Métrica", value: str = "Dato") -> str:
    return (
        f'<table id="{identifier}" class="taula_estil"><thead><tr>'
        f"<th>{header}</th><th>2026-27</th></tr></thead><tbody>"
        f"<tr><td>{value}</td><td>0</td></tr></tbody></table>"
    )


def _fixture(view: str, player_id: int = 12345) -> tuple[str, str]:
    title = "Test Player, Test Full Name | BDFutbol"
    identity = (
        f"<title>{title}</title><h1>Test Player</h1>"
        f'<a href="/es/j/j{player_id}.html">Perfil</a>'
    )
    if view == "profile":
        body = (
            '<table class="taula_estil traject"><thead><tr><th>Temp</th>'
            "<th>Equipo</th><th>País</th><th>Div</th><th>Edad</th><th>PJ</th>"
            "</tr></thead><tbody><tr><td>2026-27</td>"
            '<td><a href="/es/t/t2026-271.html">Test FC</a></td>'
            "<td>España</td><td>1ªRf</td><td>20</td><td>0</td></tr>"
            "<tr><td>Total</td><td></td><td></td><td></td><td></td><td>0</td></tr>"
            "</tbody></table>"
        )
        url = f"https://www.bdfutbol.com/es/j/j{player_id}.html"
    elif view == "statistics":
        body = _table("table-estadistiques-competicions") + _table("table-estadistiques-equips")
        url = f"https://www.bdfutbol.com/es/j/j{player_id}.html?p=stats"
    elif view == "matches":
        body = "".join(_table(identifier) for identifier in ("t2", "t1", "t55", "t5"))
        body += (
            '<table id="tpartits" class="taula_estil"><thead><tr>'
            "<th>Fecha</th><th>Local</th><th>Resultado</th><th>Visitante</th>"
            "</tr></thead><tbody></tbody></table>"
        )
        url = f"https://www.bdfutbol.com/es/p/j{player_id}.html"
    elif view == "rivals":
        body = "".join(_table(identifier) for identifier in ("t5", "t6", "t7"))
        url = f"https://www.bdfutbol.com/es/p/jr{player_id}.html"
    else:
        raise AssertionError(view)
    if view == "rivals":
        identity += f'<a href="/es/p/jr{player_id}.html">Rivales</a>'
    return f"<html><head>{identity}</head><body>{body}</body></html>", url


def _metadata(view: str, player_id: int, html: str, url: str) -> dict[str, object]:
    return {
        "player_id": player_id,
        "view": view,
        "access_status": "VALID",
        "http_status": 200,
        "requested_url": url,
        "final_url": url,
        "page_title": "Test Player, Test Full Name | BDFutbol",
        "captured_at_utc": "2026-10-14T10:00:00Z",
        "html_sha256": hashlib.sha256(html.encode()).hexdigest(),
        "filter_parameters": {},
        "is_base_view_snapshot": True,
    }


@pytest.mark.parametrize(
    ("view", "model_type"),
    [
        ("profile", PlayerTrajectoryPage),
        ("statistics", PlayerStatisticsPage),
        ("matches", PlayerMatchesPage),
        ("rivals", PlayerRivalsPage),
    ],
)
def test_each_player_view_has_a_separate_typed_contract(view: str, model_type: type) -> None:
    html, url = _fixture(view)
    page = parse_player_html(
        html,
        _metadata(view, 12345, html, url),
        expected_player_id=12345,
        expected_names=("Test Player", "Test Full Name"),
    )
    assert isinstance(page, model_type)
    assert page.player_id == 12345
    assert page.source_player_key == "j12345"
    assert page.view == view


def test_match_summaries_are_not_counted_as_individual_fixtures() -> None:
    html, url = _fixture("matches")
    page = parse_player_html(
        html,
        _metadata("matches", 12345, html, url),
        expected_player_id=12345,
        expected_names=("Test Player",),
    )
    assert isinstance(page, PlayerMatchesPage)
    assert len(page.summary_rows) == 4
    assert page.individual_matches == []
    assert page.detail_coverage == "AGGREGATE_TABLES_ONLY_HEADER_ONLY_NO_FIXTURES"


def test_source_column_headers_are_attached_to_statistics_cells() -> None:
    html, url = _fixture("statistics")
    page = parse_player_html(html, _metadata("statistics", 12345, html, url), expected_player_id=12345, expected_names=("Test Player",))

    row = page.statistics_rows[0]
    assert row["columns"][0]["header_original"] == "Métrica"
    assert row["columns"][1]["header_original"] == "2026-27"
    assert row["columns"][1]["column_index"] == 1


def test_milestone_table_keeps_its_real_preceding_heading() -> None:
    html, url = _fixture("statistics")
    milestone = (
        '<div class="milestones"><h4 class="pl-3">Participaciones</h4>'
        '<table class="taula_estil taula_estil-compacte stats taula-fites-jugador">'
        "<thead><tr><th>#</th><th>Temporada</th><th>Fecha</th><th>Partido</th></tr></thead>"
        "<tbody><tr><td>1</td><td>2025-26</td><td>10/10/2025</td><td>Real Jaén - Rival</td></tr></tbody>"
        "</table></div>"
    )
    html = html.replace("</body>", milestone + "</body>")

    page = parse_player_html(
        html, _metadata("statistics", 12345, html, url),
        expected_player_id=12345, expected_names=("Test Player",),
    )

    milestone_table = next(table for table in page.tables if table["table_role"] == "milestone_matches")
    assert milestone_table["caption_raw"] == "Participaciones"
    milestone_row = next(row for row in page.statistics_rows if row["table_role"] == "milestone_matches")
    assert milestone_row["table_caption_raw"] == "Participaciones"


def test_rival_table_preserves_group_headers_for_player_and_opponent_metrics() -> None:
    player_columns = "".join(
        f"<th>{label}</th>" for label in ("#", "Nombre", "POS", "PJ")
    )
    opponent_columns = "".join(
        f"<th title='{title}'>{short}</th>"
        for short, title in (("PJ", "Partidos"), ("G", "Goles"), ("TA", "Tarjetas amarillas"), ("TR", "Tarjetas rojas"))
    )
    row = "<td>1</td><td><a href='/es/j/j987.html'>Rival</a></td><td>Defensa</td><td>2</td><td>2</td><td>1</td><td>0</td><td>1</td>"
    html = (
        "<html><head><title>Test Player | BDFutbol</title></head><body><h1>Test Player</h1>"
        "<table id='t5'><thead><tr><th colspan='4'>JUGADOR</th><th colspan='4'>RIVAL</th></tr>"
        f"<tr>{player_columns}{opponent_columns}</tr></thead><tbody><tr>{row}</tr></tbody></table>"
        + _table("t6") + _table("t7") + "</body></html>"
    )
    url = "https://www.bdfutbol.com/es/p/jr12345.html"
    page = parse_player_html(html, _metadata("rivals", 12345, html, url), expected_player_id=12345, expected_names=("Test Player",))

    columns = page.rival_records[0]["columns"]
    assert columns[3]["header_original"] == "PJ"
    assert columns[3]["group_header_raw"] == "JUGADOR"
    assert columns[4]["header_title_raw"] == "Partidos"
    assert columns[4]["group_header_raw"] == "RIVAL"


def test_profile_career_rows_keep_verified_achievement_and_competition_markers() -> None:
    headers = ["Temp", "Equipo", "País", "", "Div", "Edad"] + ["PJ"] * 20
    headers[3] = "__achievement__"
    headers[25] = "__competitions__"
    head_cells = []
    for index, value in enumerate(headers):
        if index == 3:
            head_cells.append("<th class='colTrofeu'></th>")
        elif index == 25:
            head_cells.append("<th class='colComps'></th>")
        else:
            head_cells.append(f"<th>{value}</th>")
    values = ["2025-26", "Real Jaén", "España", "", "1ªRf", "25"] + ["0"] * 20
    cells = []
    for index, value in enumerate(values):
        if index == 1:
            cells.append("<td><a href='/es/t/t2026-271g2.html'>Real Jaén</a></td>")
        elif index == 3:
            cells.append("<td class='colTrofeu'><img src='/up.png' title='Ascenso'></td>")
        elif index == 25:
            cells.append("<td class='colComps'><span class='punt_comp' title='Copa del Rey'>Copa</span></td>")
        else:
            cells.append(f"<td>{value}</td>")
    html = (
        "<html><head><title>Test Player | BDFutbol</title></head><body><h1>Test Player</h1>"
        f"<table class='taula_estil traject'><thead><tr>{''.join(head_cells)}</tr></thead>"
        f"<tbody><tr>{''.join(cells)}</tr></tbody></table></body></html>"
    )
    url = "https://www.bdfutbol.com/es/j/j12345.html"
    page = parse_player_html(html, _metadata("profile", 12345, html, url), expected_player_id=12345, expected_names=("Test Player",))

    career = page.profile["career_rows"][0]
    assert career["team_achievements_raw"] == ["Ascenso"]
    assert career["competition_participations_raw"] == ["Copa del Rey"]
    assert "colTrofeu" in career["columns"][3]["classes_raw"]


def test_window_p_match_values_are_labeled_from_captured_fixture_headers() -> None:
    html, url = _fixture("matches")
    headers = [
        ("#", "Número", "n"), ("Fecha", "Fecha", "data"), ("Temporada", "Temporada", "temp"),
        ("Competición", "Tipo", "tipus"), ("Tipo", "Jornada", "jor"), ("Local", "Local", "e1"),
        ("", "Marcador", "res"), ("Visitante", "Visitante", "e2"),
        ("PT", "Partidos titular", "pt"), ("PC", "Partidos completos", "pc"),
        ("PS", "Partidos suplente", "ps"), ("PX", "Partidos sustituido", "px"),
        ("PI", "Partidos incompletos", "pinc"), ("C", "Convocado (sin jugar)", "pv"),
        ("Min", "Minutos", "mins"), ("TA", "Tarjetas amarillas 1", "tg1"),
        ("TR", "Tarjetas rojas", "tv"), ("G", "Goles", "gols"), ("GE", "Goles encajados", "genc"),
    ]
    table = "<table id='tpartits'><thead><tr>" + "".join(
        f"<th title='{title}' data-colid='{colid}'>{label}</th>" for label, title, colid in headers
    ) + "</tr></thead><tbody></tbody></table>"
    start = html.index("<table id=\"tpartits\"")
    end = html.index("</table>", start) + len("</table>")
    html = html[:start] + table + html[end:]
    values = [2026, "1rf", "", "10/10/2026", 1, "Jaén", 3, 3, 272582, 1, 1, 0, 90, 0, 0, 0, 0, "", "Villarreal B", 49, 123, 0, 0, 0, "Jornada 6", "6", "2026-27"]
    html = html.replace("</body>", f"<script>window.P={json.dumps([values])};</script></body>")
    metadata = _metadata("matches", 12345, html, url)
    page = parse_player_html(html, metadata, expected_player_id=12345, expected_names=("Test Player",))

    stats = page.individual_matches[0]["match_statistics"]
    by_label = {item["label_raw"]: item for item in stats}
    assert by_label["Partidos titular"]["normalized_integer"] == 1
    assert by_label["Minutos"]["normalized_integer"] == 90
    assert by_label["Tarjetas amarillas 1"]["normalized_integer"] == 0
    assert by_label["Goles"]["raw_value"] == ""


def test_redirect_or_wrong_player_identity_is_rejected() -> None:
    html, url = _fixture("profile")
    metadata = _metadata("profile", 12345, html, url)
    redirected = {**metadata, "final_url": "https://www.bdfutbol.com/es/j/j54321.html"}
    with pytest.raises(PlayerCaptureParseError, match="URL final"):
        parse_player_html(html, redirected, expected_player_id=12345, expected_names=("Test Player",))
    with pytest.raises(PlayerCaptureParseError, match="identidad"):
        parse_player_html(html, metadata, expected_player_id=12345, expected_names=("Other Player",))


def test_http_denial_and_hash_mismatch_are_not_parseable() -> None:
    html, url = _fixture("profile")
    metadata = _metadata("profile", 12345, html, url)
    with pytest.raises(PlayerCaptureParseError, match="HTTP 200"):
        parse_player_html(html, {**metadata, "http_status": 403}, expected_player_id=12345, expected_names=("Test Player",))
    with pytest.raises(PlayerCaptureParseError, match="hash"):
        parse_player_html(html, {**metadata, "html_sha256": "0" * 64}, expected_player_id=12345, expected_names=("Test Player",))


def test_saved_capture_recovers_offline_and_parser_failure_keeps_raw(tmp_path: Path) -> None:
    html, url = _fixture("profile")
    store = PlayerCaptureStore(tmp_path, capture_id="parser-recovery")
    metadata = store.save_snapshot(
        player_id=12345,
        view="profile",
        requested_url=url,
        final_url=url,
        http_status=200,
        page_title="Test Player, Test Full Name | BDFutbol",
        html=html,
        browser={"backend": "seleniumbase-pure-cdp", "uses_xvfb": True},
    )
    record = store.manifest["snapshots"][0]
    page = parse_snapshot(store.run_dir, record, expected_player_id=12345, expected_names=("Test Player",))
    assert isinstance(page, PlayerTrajectoryPage)
    assert page.profile["career_rows_observed"] == 1
    with pytest.raises(PlayerCaptureParseError):
        parse_snapshot(store.run_dir, record, expected_player_id=12345, expected_names=("Wrong Name",))
    assert (store.run_dir / metadata["raw_path"]).is_file()
    assert json.loads((store.run_dir / "manifest.json").read_text())["snapshots"][0]["html_sha256"] == metadata["html_sha256"]


def test_export_is_versioned_round_trippable_and_partial_failures_keep_raw(tmp_path: Path) -> None:
    capture_root = tmp_path / "capture-root"
    store = PlayerCaptureStore(capture_root, capture_id="export-run")
    valid_html, url = _fixture("profile")
    bad_html = valid_html.replace("Test Player", "Different Player").replace(
        "Test Full Name", "Different Full Name"
    )
    store.save_snapshot(
        player_id=12345,
        view="profile",
        requested_url=url,
        final_url=url,
        http_status=200,
        page_title="Test Player",
        html=valid_html,
        browser={"backend": "seleniumbase-pure-cdp"},
    )
    store.save_snapshot(
        player_id=12345,
        view="profile",
        requested_url=url,
        final_url=url,
        http_status=200,
        page_title="Different Player",
        html=bad_html,
        browser={"backend": "seleniumbase-pure-cdp"},
    )
    store.mark_complete()
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"records": [{
        "player_id": 12345,
        "display_name": "Test Player",
        "full_name": "Test Full Name",
    }]}), encoding="utf-8")

    result = build_player_capture_export(
        capture_dir=store.run_dir,
        inventory_path=inventory,
        derivation_id="derivation-test",
    )
    assert result["status"] == "partial"
    assert result["parsed_count"] == 1
    assert result["error_count"] == 1
    base = store.run_dir / "normalized/derivations/derivation-test"
    report = json.loads((base / "validation/results.json").read_text(encoding="utf-8"))
    assert report["snapshots"][0]["normalized_path"]
    source = json.loads((store.run_dir / "manifest.json").read_text(encoding="utf-8"))["inventory_source"]
    assert source["sha256"] == hashlib.sha256(inventory.read_bytes()).hexdigest()
    assert source["season"] == "2026-27"
    assert json.loads((store.run_dir / "manifest.json").read_text(encoding="utf-8")).get("review_notes") is None
    normalized_path = base / report["snapshots"][0]["normalized_path"]
    assert json.loads(normalized_path.read_text(encoding="utf-8"))["player_id"] == 12345
    assert all((store.run_dir / item["raw_path"]).is_file() for item in store.manifest["snapshots"])
