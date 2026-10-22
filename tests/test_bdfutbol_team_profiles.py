from __future__ import annotations

import hashlib
import gzip
from collections import Counter
import json
from pathlib import Path
from urllib.parse import urlsplit
import pytest
from bs4 import BeautifulSoup

from football_data_hub.core.browser_session import BrowserInfo, PageVisit
from football_data_hub.providers.bdfutbol.context import get_competition_context
from football_data_hub.providers.bdfutbol.teams import acquisition as team_acquisition
from football_data_hub.providers.bdfutbol.teams import cli as team_acquisition_cli
from football_data_hub.providers.bdfutbol.teams.acquisition import (
    DEFAULT_VIEWS,
    StaleMatchCatalogError,
    TeamAcquisitionBundle,
    TeamAcquisitionStopped,
)
from football_data_hub.providers.bdfutbol.teams.catalog import load_team_catalog
from football_data_hub.providers.bdfutbol.teams.capture_store import inspect_team_capture
from football_data_hub.providers.bdfutbol.teams.batch_cli import (
    _is_inside_repository,
    _team_plan,
    main as team_batch_main,
    parse_args as parse_team_batch_args,
)
from football_data_hub.providers.bdfutbol.teams.batch import inspect_team_captures
from football_data_hub.providers.bdfutbol.teams.export import export_team_capture
from football_data_hub.providers.bdfutbol.teams.evidence_store import (
    TeamEvidenceCheckpoint,
    read_pending_evidence,
)
from football_data_hub.providers.bdfutbol.teams.parser import (
    TeamProfileParseError,
    _parse_match_ids_by_competition,
    parse_team_profile_pages,
    resolve_team_view_urls,
)
from football_data_hub.providers.bdfutbol.teams.validation import (
    validate_team_catalogs,
    validate_team_profile,
)

ROOT = Path(__file__).resolve().parents[1]
GROUP_CATALOGS = {
    1: ROOT / "data/exports/bdfutbol/group1_classification/20261010T202500.293648Z-b770724f/normalized/matches.json",
    2: ROOT / "data/exports/bdfutbol/group2_classification/derived-res01-20261010T102656Z/normalized/matches.json",
}
PROFILE_RUNS = {
    1: ROOT / "data/exports/bdfutbol/teams/2026-27/48/20261011T123240.190812Z-8f307d1c",
    2: ROOT / "data/exports/bdfutbol/teams/2026-27/49/team01a-group2-49-source-evidence",
}


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_pilot(group: int, team_id: int):
    context = get_competition_context(group=group)
    team_payload = _read_json(GROUP_CATALOGS[group])
    record = next(item for item in team_payload["teams"] if item["team_id"] == team_id)
    run = PROFILE_RUNS[group]
    capture = _read_json(run / "metadata/capture.json")
    views = {}
    for view in capture["requested_views"]:
        evidence = capture.get("source_snapshots", {}).get(view, {})
        path = run / evidence.get("path", f"raw/{view}.html")
        raw = path.read_bytes()
        if evidence.get("compression") == "gzip" or path.suffix == ".gz":
            raw = gzip.decompress(raw)
        views[view] = raw.decode("utf-8")
    follow_state_html = {}
    for state, evidence in capture.get("follow_states", {}).items():
        path = run / evidence["path"]
        raw = path.read_bytes()
        if evidence.get("compression") == "gzip" or path.suffix == ".gz":
            raw = gzip.decompress(raw)
        follow_state_html[state] = raw.decode("utf-8")
    parsed = parse_team_profile_pages(
        views,
        team_catalog_record=record,
        competition_context=context,
        follow_state_html=follow_state_html,
    )
    validation = validate_team_profile(
        parsed,
        catalog_record=record,
        group_team_catalog=team_payload["teams"],
        known_matches=team_payload["matches"],
        requested_views=tuple(capture["requested_views"]),
    )
    return context, team_payload, record, run, capture, views, parsed, validation


@pytest.fixture(scope="module")
def jaen():
    return _load_pilot(2, 49)


@pytest.fixture(scope="module")
def racing():
    return _load_pilot(1, 48)


def test_catalogs_contain_40_distinct_source_team_ids():
    catalogs = {}
    for group, path in GROUP_CATALOGS.items():
        context = get_competition_context(group=group)
        teams, _, reference = load_team_catalog(path, competition=context)
        catalogs[group] = (teams, reference)
        assert len(teams) == 20
        assert len({item["team_id"] for item in teams}) == 20
    result = validate_team_catalogs(catalogs, season="2026-27")
    assert result["valid"] is True
    assert result["summary"]["teams_total"] == 40
    assert result["summary"]["unique_team_ids"] == 40
    assert result["team_ids_by_group"]["II"] == [17, 18, 39, 40, 49, 55, 61, 67, 79, 89, 94, 107, 119, 140, 176, 204, 227, 414, 482, 488]


def test_view_links_are_resolved_from_real_team_page(jaen):
    _, _, record, _, _, views, *_ = jaen
    urls = resolve_team_view_urls(views["alignment"], record["team_url"])
    assert urls["alignment"] == record["team_url"]
    assert urls["squad"].endswith("?t=plantilla")
    assert urls["statistics"].endswith("?t=lista")
    assert urls["follow"].endswith("?t=seg")
    assert urls["transfers"].endswith("?t=altas")
    assert urls["matches"].endswith("?tab=partits")


def test_jaen_normalizes_team_coach_squad_stats_and_references(jaen):
    context, payload, record, run, capture, _, parsed, validation = jaen
    assert parsed.identity.team_id == 49
    assert parsed.identity.name == record["name"]
    assert parsed.identity.team_url == record["team_url"]
    assert parsed.season.group == "II"
    assert parsed.season.season == "2026-27"
    assert len(parsed.season.coaches) == 1
    assert parsed.season.coaches[0].coach_id == 1835
    assert len(parsed.players) == len(parsed.memberships) == 25
    assert len(parsed.player_statistics) == 25
    assert len(parsed.player_match_minutes) == 150
    assert any(item.value is None and item.raw_value == "" for item in parsed.player_match_minutes)
    assert any(item.value == 0 and item.raw_value == "0" for item in parsed.player_match_minutes)
    assert Counter(item.direction for item in parsed.transfers) == {"incoming": 14, "outgoing": 20}
    assert {item.direction: item.row_count for item in parsed.transfer_sections} == {"incoming": 14, "outgoing": 20}
    assert {item.direction: item.status for item in parsed.transfer_sections} == {
        "incoming": "verified_with_rows", "outgoing": "verified_with_rows"
    }
    assert {item.direction: item.source_heading for item in parsed.transfer_sections} == {
        "incoming": "Altas", "outgoing": "Bajas"
    }
    assert next(item for item in parsed.transfers if item.player_id == 304042).source_heading == "Altas"
    assert next(item for item in parsed.transfers if item.player_id == 22537).source_heading == "Bajas"
    assert all(item.transfer_date is None and item.fee is None for item in parsed.transfers)
    assert all(item.player_id > 0 and item.player_display_name and item.player_profile_url for item in parsed.transfers)
    assert len(parsed.group_team_ids_from_profile) == 20
    assert len(parsed.team_match_ids_from_profile) == 6
    assert set(parsed.team_match_ids_from_profile) <= {str(item["match_id"]) for item in payload["matches"]}
    assert validation["valid"] is True
    assert capture["access_by_view"]["alignment"]["status"] == "VALID"
    assert capture["source_snapshots"]["alignment"]["http_status"] == 200
    assert (run / "raw/alignment.html").is_file()


def test_roster_groups_and_nulls_are_preserved(jaen):
    *_, parsed, _ = jaen
    group_counts = {label: sum(item.squad_group_label == label for item in parsed.memberships) for label in ("Titulares", "Suplentes")}
    assert group_counts == {"Titulares": 11, "Suplentes": 14}
    assert any(item.value is None and item.raw_value == "" for item in parsed.player_match_minutes)
    salvi = next(item for item in parsed.player_statistics if item.player_id == 19269)
    assert salvi.matches_played == 0
    assert salvi.minutes_played == 0
    assert salvi.goals == 0


def test_group1_pilot_uses_same_parser_and_catalog_identity(racing):
    context, payload, record, _, capture, _, parsed, validation = racing
    assert record["team_id"] == 48
    assert parsed.identity.name == "Racing de Ferrol"
    assert parsed.identity.team_url == "https://www.bdfutbol.com/es/t/t2026-2748.html"
    assert parsed.season.group == "I"
    assert len(parsed.players) == len(parsed.player_statistics) == 25
    assert len(parsed.season.coaches) == 1
    assert parsed.season.coaches[0].coach_id == 400293
    assert len(parsed.player_match_minutes) == 150
    assert len(parsed.player_match_metrics) == 17
    assert parsed.follow_states_captured == ("go", "p", "t", "tot")
    assert set(capture["requested_views"]) == {"alignment", "squad", "statistics", "follow", "transfers", "matches"}
    assert Counter(item.direction for item in parsed.transfers) == {"incoming": 15, "outgoing": 15}
    assert {item.direction: item.row_count for item in parsed.transfer_sections} == {"incoming": 15, "outgoing": 15}
    assert next(item for item in parsed.transfers if item.player_id == 15141).source_heading == "Altas"
    assert next(item for item in parsed.transfers if item.player_id == 23024).source_heading == "Bajas"
    assert all(item.transfer_date is None and item.fee is None for item in parsed.transfers)
    assert validation["valid"] is True
    assert len(parsed.group_team_ids_from_profile) == len(payload["teams"]) == 20


def test_racing_follow_states_normalize_verified_goals_and_yellow_cards(racing):
    _, payload, _, run, capture, views, parsed, validation = racing
    assert parsed.follow_states_captured == ("go", "p", "t", "tot")
    counts = Counter(item.metric for item in parsed.player_match_metrics)
    assert counts == {"yellow_cards": 10, "goals": 7}
    assert all(item.source_state == ("t" if item.metric == "yellow_cards" else "go") for item in parsed.player_match_metrics)
    assert all(item.value > 0 for item in parsed.player_match_metrics)
    assert len({(item.player_id, item.match_id, item.metric) for item in parsed.player_match_metrics}) == 17
    stat_totals = {
        "yellow_cards": sum(item.yellow_cards or 0 for item in parsed.player_statistics),
        "goals": sum(item.goals or 0 for item in parsed.player_statistics),
    }
    metric_totals = Counter()
    for item in parsed.player_match_metrics:
        metric_totals[item.metric] += item.value
        assert item.match_id in {str(match["match_id"]) for match in payload["matches"]}
    assert dict(metric_totals) == stat_totals == {"yellow_cards": 10, "goals": 7}
    assert validation["valid"] is True
    follow_scripts = " ".join(
        script.get_text()
        for script in BeautifulSoup(views["follow"], "html.parser").select("script")
    )
    assert "var JSEGJ=" in follow_scripts
    assert "JSEGC['lig']" in follow_scripts
    assert "JSEGG['lig']" in follow_scripts
    assert "JSEGID=JSON.parse(" in follow_scripts
    assert "json_data = JSON.parse(" in follow_scripts
    assert all(match_id in follow_scripts for match_id in ("269411", "269426", "269432", "269442", "269453", "269460"))
    metadata = _read_json(run / "metadata/capture.json")
    state_diagnostics = metadata["follow_states"]
    assert {state: item["selected_value"] for state, item in state_diagnostics.items()} == {
        "p": "p", "t": "t", "go": "go", "tot": "tot"
    }
    assert len({item["url"] for item in state_diagnostics.values()}) == 1
    assert all(item["table_rows"] == 26 for item in state_diagnostics.values())
    assert not any(
        (urlsplit(resource).hostname or "").endswith("bdfutbol.com")
        for item in state_diagnostics.values()
        for resource in item["resource_urls_added_since_previous_state"]
    )
    assert all(item.raw_value == "tg1" for item in parsed.player_match_metrics if item.metric == "yellow_cards")


def test_follow_empty_is_not_zero_and_unverified_states_are_not_fabricated(jaen):
    *_, parsed, _ = jaen
    assert parsed.player_match_metrics == ()
    assert parsed.follow_states_captured == ()
    assert any(item.value is None and item.raw_value == "" for item in parsed.player_match_minutes)


def test_player_and_match_relationships_use_ids_not_names(jaen):
    _, payload, _, _, _, _, parsed, _ = jaen
    player_ids = {item.player_id for item in parsed.players}
    assert len(player_ids) == len(parsed.players)
    matches = {str(item["match_id"]) for item in payload["matches"]}
    assert set(parsed.team_match_ids_from_profile) <= matches
    top_path = ROOT / "data/exports/bdfutbol/group2_top/20261010T155145.195266Z-c5b031a6/normalized/players.json"
    top = _read_json(top_path)
    top_ids = {item["player_id"] for item in top["records"]}
    assert player_ids.intersection(top_ids)
    assert player_ids - top_ids  # Destacados is a partial list, not a roster authority.


def test_team_match_references_are_partitioned_by_source_competition():
    html = """
    <table id="taula-resultats-plantilla">
      <tr class="COM COM_LIG"><td>10/10/2026</td><td>Liga</td><td>Jornada 7</td>
        <td><a href="../p/p.php?id=900001">Local</a></td></tr>
      <tr class="COM COM_FED"><td>12/10/2026</td><td>Copa Federación</td><td>Ronda</td>
        <td><a href="../p/p.php?id=900002">Local</a></td></tr>
    </table>
    """
    all_ids, league_ids, other_ids = _parse_match_ids_by_competition(
        BeautifulSoup(html, "html.parser")
    )

    assert all_ids == ("900001", "900002")
    assert league_ids == ("900001",)
    assert other_ids == ("900002",)


def test_team_match_reference_without_competition_is_rejected():
    html = """
    <table id="taula-resultats-plantilla">
      <tr><td>10/10/2026</td><td></td><td>Jornada 7</td>
        <td><a href="../p/p.php?id=900001">Local</a></td></tr>
    </table>
    """
    with pytest.raises(TeamProfileParseError, match="competición de origen"):
        _parse_match_ids_by_competition(BeautifulSoup(html, "html.parser"))


def test_validation_joins_only_league_references_to_group_catalog(jaen):
    from dataclasses import replace

    context, payload, record, _, capture, _, parsed, _ = jaen
    league_ids = parsed.team_league_match_ids_from_profile
    other_id = "other-competition-id"
    scoped = replace(
        parsed,
        team_match_ids_from_profile=(*parsed.team_match_ids_from_profile, other_id),
        team_league_match_ids_from_profile=league_ids,
        team_other_competition_match_ids_from_profile=(other_id,),
    )
    known_matches = payload["matches"]
    report = validate_team_profile(
        scoped,
        catalog_record=record,
        group_team_catalog=payload["teams"],
        known_matches=known_matches,
        requested_views=tuple(capture["requested_views"]),
    )

    assert report["valid"] is True
    assert report["cross_references"]["league_match_references"] == len(league_ids)
    assert report["cross_references"]["other_competition_match_ids"] == ["other-competition-id"]
    assert "unknown_profile_match" not in {item["code"] for item in report["issues"]}


def test_snapshot_metadata_and_sha256_are_reproducible(jaen, racing):
    for pilot in (jaen, racing):
        _, _, _, run, capture, _, _, _ = pilot
        metadata = _read_json(run / "metadata/capture.json")
        access = _read_json(run / "raw/access.json")
        assert metadata["team_id"] in {48, 49}
        assert metadata["group"] in {"I", "II"}
        assert set(metadata["requested_views"]) == set(metadata["source_snapshots"])
        assert access["views"] == metadata["access_by_view"]
        for view, evidence in metadata["source_snapshots"].items():
            html = (run / evidence["path"]).read_bytes()
            if evidence.get("compression") == "gzip":
                html = gzip.decompress(html)
            assert hashlib.sha256(html).hexdigest() == evidence["sha256"]
            assert evidence["access_status"] == "VALID"
        assert capture["extractor_version"]


def test_export_json_can_be_read_back_and_capture_is_create_only(racing, tmp_path):
    context, _, record, run, capture, views, parsed, validation = racing
    source_access = _read_json(run / "raw/access.json")
    bundle = TeamAcquisitionBundle(
        capture_id="test-team-profile-export",
        captured_at_utc=capture["captured_at_utc"],
        requested_views=tuple(capture["requested_views"]),
        raw_views=views,
        view_urls=capture["view_urls"],
        access_by_view=capture["access_by_view"],
        page_titles={view: row["title"] for view, row in capture["source_snapshots"].items()},
        browser=capture["browser"],
        team_catalog_reference=capture["related_team_catalog"],
        parsed=parsed,
        validation=validation,
        competition=context,
    )
    paths = export_team_capture(
        tmp_path,
        bundle,
        profile_dir=None,
        capture_timestamp_basis="offline source evidence",
    )
    payload = _read_json(paths["players"])
    assert payload["metadata"]["team_id"] == 48
    assert len(payload["records"]) == 25
    assert _read_json(paths["team_season"])["record"]["group"] == "I"
    assert _read_json(paths["raw_access"])["views"] == source_access["views"]
    assert paths["run_directory"].is_dir()
    players_before = paths["players"].read_bytes()
    with pytest.raises(FileExistsError):
        export_team_capture(
            tmp_path,
            bundle,
            profile_dir=None,
            capture_timestamp_basis="offline source evidence",
        )
    assert paths["players"].read_bytes() == players_before


def test_offline_cli_reparses_compressed_real_snapshots_without_browser(racing, monkeypatch, tmp_path, capsys):
    _, _, record, run, _, _, _, _ = racing

    def unexpected_network(*_args, **_kwargs):
        raise AssertionError("El modo offline no debe iniciar el navegador")

    monkeypatch.setattr(team_acquisition_cli, "acquire_team_profile", unexpected_network)
    result = team_acquisition_cli.main([
        "--group", "1",
        "--team-id", str(record["team_id"]),
        "--snapshot-dir", str(run),
        "--derived-capture",
        "--output-root", str(tmp_path / "exports"),
    ])
    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["acquired_views"] == ["squad", "follow", "transfers", "matches"]
    assert output["reused_views"] == ["alignment", "statistics"]
    exported = Path(output["files"]["run_directory"])
    metrics = _read_json(exported / "normalized/player_match_metrics.json")
    assert Counter(item["metric"] for item in metrics["records"]) == {"yellow_cards": 10, "goals": 7}
    assert "20261011T123240.190812Z-8f307d1c" in metrics["metadata"]["reused_source_capture_ids"]
    assert all(item["compression"] == "gzip" for item in _read_json(exported / "metadata/capture.json")["source_snapshots"].values())


def test_parser_rejects_wrong_catalog_identity_and_invalid_html(jaen):
    context, _, record, _, _, views, *_ = jaen
    wrong_record = {**record, "team_url": "https://www.bdfutbol.com/es/t/t2026-2748.html"}
    with pytest.raises(TeamProfileParseError, match="no coincide"):
        parse_team_profile_pages(views, team_catalog_record=wrong_record, competition_context=context)
    with pytest.raises(TeamProfileParseError, match="no contiene"):
        parse_team_profile_pages(
            {"alignment": "<html><title>challenge</title><body>Just a moment</body></html>"},
            team_catalog_record=record,
            competition_context=context,
        )


def test_transfer_section_distinguishes_verified_empty_from_unparseable(jaen):
    context, _, record, _, _, views, _, _ = jaen
    soup = BeautifulSoup(views["transfers"], "html.parser")
    root = soup.select_one("#pestaltesbaixes")
    assert root is not None
    table = root.select_one("table")
    assert table is not None
    after_bajas_heading = False
    after_destination_header = False
    for row in list(table.select("tr")):
        if row.select_one("h2") and row.select_one("h2").get_text(" ", strip=True) == "Bajas":
            after_bajas_heading = True
            continue
        if after_bajas_heading and "Equipo destino" in row.get_text(" ", strip=True):
            after_destination_header = True
            continue
        if after_destination_header and row.select_one('a[href*="/j/j"]'):
            row.decompose()
    empty_views = {**views, "transfers": str(soup)}
    parsed = parse_team_profile_pages(
        empty_views,
        team_catalog_record=record,
        competition_context=context,
    )
    assert Counter(item.direction for item in parsed.transfers) == {"incoming": 14}
    assert {item.direction: item.status for item in parsed.transfer_sections} == {
        "incoming": "verified_with_rows", "outgoing": "verified_empty"
    }
    assert {item.direction: item.row_count for item in parsed.transfer_sections} == {"incoming": 14, "outgoing": 0}
    broken = BeautifulSoup(views["transfers"], "html.parser")
    broken.select_one("#pestaltesbaixes table").decompose()
    with pytest.raises(TeamProfileParseError, match="Encabezados de Traspasos inesperados"):
        parse_team_profile_pages(
            {**views, "transfers": str(broken)},
            team_catalog_record=record,
            competition_context=context,
        )


def test_same_player_can_have_source_records_in_both_directions(jaen):
    context, _, record, _, _, views, _, _ = jaen
    soup = BeautifulSoup(views["transfers"], "html.parser")
    table = soup.select_one("#pestaltesbaixes table")
    assert table is not None
    incoming_row = next(
        row for row in table.select("tr")
        if row.select_one('a[href*="/j/j304042.html"]')
    )
    clone = BeautifulSoup(str(incoming_row), "html.parser").select_one("tr")
    assert clone is not None
    table.append(clone)
    parsed = parse_team_profile_pages(
        {**views, "transfers": str(soup)},
        team_catalog_record=record,
        competition_context=context,
    )
    copies = [item for item in parsed.transfers if item.player_id == 304042]
    assert {item.direction for item in copies} == {"incoming", "outgoing"}


def test_transfer_parser_rejects_unrecognized_section_table(jaen):
    context, _, record, _, _, views, _, _ = jaen
    soup = BeautifulSoup(views["transfers"], "html.parser")
    table = soup.select_one("#pestaltesbaixes table")
    assert table is not None
    destination_header = next(row for row in table.select("tr") if "Equipo destino" in row.get_text(" ", strip=True))
    destination_header.decompose()
    with pytest.raises(TeamProfileParseError, match="antes de la cabecera de Bajas"):
        parse_team_profile_pages(
            {**views, "transfers": str(soup)},
            team_catalog_record=record,
            competition_context=context,
        )


def test_optional_coach_and_jersey_fields_do_not_invalidate_a_roster(jaen):
    context, _, record, _, _, views, _, _ = jaen
    modified: dict[str, str] = {}
    for view, html in views.items():
        soup = BeautifulSoup(html, "html.parser")
        coach_table = soup.select_one("#taulaentrenadors")
        if coach_table:
            coach_table.decompose()
        if view in {"alignment", "squad"}:
            table = soup.select_one("#taulaplantilla" if view == "alignment" else "#c3p1")
            if table:
                selector = 'th[data-colid="dor"]' if view == "alignment" else 'th[title="Dorsal"]'
                header = table.select_one(selector)
                if header:
                    index = len(header.find_previous_siblings(["th", "td"]))
                    for row in table.select("tr"):
                        cells = row.select("th, td")
                        if index < len(cells):
                            cells[index].decompose()
        modified[view] = str(soup)
    parsed = parse_team_profile_pages(
        modified,
        team_catalog_record=record,
        competition_context=context,
    )
    assert parsed.season.coaches == ()
    assert all(item.jersey_number is None for item in parsed.memberships)
    assert len(parsed.players) == 25


def test_year_only_birth_date_is_preserved_as_null_with_warning(jaen):
    context, _, record, _, _, views, _, _ = jaen
    soup = BeautifulSoup(views["squad"], "html.parser")
    table = soup.select_one("#c3p1")
    assert table is not None
    headers = table.select_one("tr")
    assert headers is not None
    cells = headers.select("th, td")
    birth_index = next(
        index
        for index, cell in enumerate(cells)
        if cell.get("title") == "Fecha de nacimiento"
    )
    player_row = next(
        row
        for row in table.select("tr")[1:]
        if row.select_one('a[href*="/j/j"]')
    )
    player_link = player_row.select_one('a[href*="/j/j"]')
    assert player_link is not None
    player_id = int(player_link["href"].rsplit("j", 1)[-1].removesuffix(".html"))
    player_cells = player_row.select("th, td")
    player_cells[birth_index].clear()
    player_cells[birth_index].string = "2008"
    modified_views = {**views, "squad": str(soup)}

    parsed = parse_team_profile_pages(
        modified_views,
        team_catalog_record=record,
        competition_context=context,
    )

    player = next(item for item in parsed.players if item.player_id == player_id)
    assert player.birth_date is None
    assert any(
        f"player_id={player_id}" in warning and "'2008'" in warning and "null" in warning
        for warning in parsed.warnings
    )

    player_cells[birth_index].string = "not-a-date"
    with pytest.raises(TeamProfileParseError, match="Fecha no interpretable"):
        parse_team_profile_pages(
            {**views, "squad": str(soup)},
            team_catalog_record=record,
            competition_context=context,
        )


class _FakeDocument:
    def __init__(self, url: str, html: str, status: int = 200):
        self.url = url
        self._html = html
        self.response_status = status
        self._soup = BeautifulSoup(html, "html.parser")

    def title(self):
        return self._soup.title.get_text(" ", strip=True) if self._soup.title else ""

    def html(self):
        return self._html

    def text(self, selector: str):
        item = self._soup.select_one(selector)
        return item.get_text(" ", strip=True) if item else ""

    def exists(self, selector: str):
        return self._soup.select_one(selector) is not None

    def wait(self, milliseconds: int):
        return None

    def select(self, selector: str, value: str):
        control = self._soup.select_one(selector)
        option = control.select_one(f'option[value="{value}"]') if control else None
        if option is None:
            raise ValueError(f"No option {value} for {selector}")
        for item in control.select("option"):
            item.attrs.pop("selected", None)
        option["selected"] = "selected"
        self._html = str(self._soup)

    def value(self, selector: str):
        control = self._soup.select_one(selector)
        if control is None:
            return None
        option = control.select_one("option[selected]") or control.select_one("option")
        return str(option.get("value")) if option else None

    def count(self, selector: str):
        return len(self._soup.select(selector))

    def evaluate(self, _script: str):
        return []

    def close(self):
        return None


class _FakeSession:
    def __init__(self, pages: dict[str, tuple[str, int]]):
        self.pages = pages
        self.opened_urls: list[str] = []
        self.info = BrowserInfo(
            backend="seleniumbase-pure-cdp",
            browser_name="Chromium",
            browser_executable="/usr/bin/chromium",
            browser_version="fixture",
            automation_version="fixture",
            display=":99",
            uses_xvfb=True,
            xvfb_external=True,
        )

    def open_page(self, url: str):
        self.opened_urls.append(url)
        html, status = self.pages[url]
        document = _FakeDocument(url, html, status)
        return PageVisit(document=document, requested_url=url, initial_response_status=status)


class _FakeSessionManager:
    def __init__(self, session: _FakeSession):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *_args):
        return None


def test_acquisition_orchestration_uses_pure_cdp_access_contract(jaen, monkeypatch, tmp_path):
    context, payload, record, _, _, views, _, _ = jaen
    urls = resolve_team_view_urls(views["alignment"], record["team_url"])
    pages = {urls[view]: (html, 200) for view, html in views.items()}
    fake_session = _FakeSession(pages)
    monkeypatch.setattr(
        team_acquisition,
        "BrowserSessionManager",
        lambda *_args, **_kwargs: _FakeSessionManager(fake_session),
    )
    access_class = team_acquisition.BDFutbolAccess

    class RecordingAccess(access_class):
        def open(self, url, **kwargs):
            assert kwargs["max_wait_seconds"] == 8
            return super().open(url, **kwargs)

    monkeypatch.setattr(team_acquisition, "BDFutbolAccess", RecordingAccess)
    result = team_acquisition.acquire_team_profile(
        team_catalog_record=record,
        team_catalog_reference={"path": "fixture", "sha256": "fixture"},
        group_team_catalog=payload["teams"],
        known_matches=payload["matches"],
        competition=context,
        profile_dir=tmp_path / "profile",
        requested_views=("alignment", "statistics"),
    )
    assert fake_session.opened_urls == [urls["alignment"], urls["statistics"]]
    assert result.parsed.identity.team_id == 49
    assert result.validation["valid"] is True
    assert result.browser["backend"] == "seleniumbase-pure-cdp"


def test_incremental_acquisition_reuses_validated_alignment_and_statistics(racing, monkeypatch, tmp_path):
    context, payload, record, _, _, views, _, _ = racing
    seed = team_acquisition_cli._reuse_capture_seed(
        ROOT / "data/exports/bdfutbol/teams/2026-27/48/team01a-group1-48-source-evidence",
        team_catalog_record=record,
        competition=context,
        team_catalog_reference=load_team_catalog(
            GROUP_CATALOGS[1], competition=context
        )[2],
        group_team_catalog=payload["teams"],
        known_matches=payload["matches"],
    )
    assert set(seed["raw_views"]) == {"alignment", "statistics"}
    seed_urls = resolve_team_view_urls(seed["raw_views"]["alignment"], record["team_url"])
    pages = {
        seed_urls[view]: (views[view], 200)
        for view in ("squad", "matches")
    }
    fake_session = _FakeSession(pages)
    monkeypatch.setattr(
        team_acquisition,
        "BrowserSessionManager",
        lambda *_args, **_kwargs: _FakeSessionManager(fake_session),
    )
    result = team_acquisition.acquire_team_profile(
        team_catalog_record=record,
        team_catalog_reference={"path": "fixture", "sha256": "fixture"},
        group_team_catalog=payload["teams"],
        known_matches=payload["matches"],
        competition=context,
        profile_dir=tmp_path / "profile",
        requested_views=("squad", "matches"),
        seed_raw_views=seed["raw_views"],
        seed_access_by_view=seed["access_by_view"],
        seed_view_urls=seed["view_urls"],
        seed_page_titles=seed["page_titles"],
        seed_browser=seed["browser"],
        seed_capture_id=seed["capture_id"],
    )
    assert fake_session.opened_urls == [seed_urls["squad"], seed_urls["matches"]]
    assert result.acquired_views == ("squad", "matches")
    assert result.seed_capture_ids == ("team01a-group1-48-source-evidence",)
    assert set(result.raw_views) == {"alignment", "squad", "statistics", "matches"}


def test_refreshing_a_view_preserves_follow_metrics_and_provenance(racing, monkeypatch, tmp_path):
    context, payload, record, run, capture, views, _, _ = racing
    teams, known_matches, reference = load_team_catalog(
        GROUP_CATALOGS[1], competition=context
    )
    seed = team_acquisition_cli._reuse_capture_seed(
        run,
        team_catalog_record=record,
        competition=context,
        team_catalog_reference=reference,
        group_team_catalog=teams,
        known_matches=known_matches,
    )
    assert set(seed["follow_state_html"]) == {"p", "t", "go", "tot"}
    follow_metrics_before = _read_json(run / "normalized/player_match_metrics.json")
    source_state_metadata = capture["follow_states"]
    urls = resolve_team_view_urls(views["alignment"], record["team_url"])
    fake_session = _FakeSession({urls["matches"]: (views["matches"], 200)})
    monkeypatch.setattr(
        team_acquisition,
        "BrowserSessionManager",
        lambda *_args, **_kwargs: _FakeSessionManager(fake_session),
    )

    bundle = team_acquisition.acquire_team_profile(
        team_catalog_record=record,
        team_catalog_reference=reference,
        group_team_catalog=teams,
        known_matches=known_matches,
        competition=context,
        profile_dir=tmp_path / "profile",
        requested_views=("matches",),
        seed_raw_views=seed["raw_views"],
        seed_access_by_view=seed["access_by_view"],
        seed_view_urls=seed["view_urls"],
        seed_page_titles=seed["page_titles"],
        seed_browser=seed["browser"],
        seed_capture_id=seed["capture_id"],
        seed_follow_state_html=seed["follow_state_html"],
        seed_follow_state_diagnostics=seed["follow_state_diagnostics"],
        seed_capture_ids=seed["seed_capture_ids"],
        require_follow_states=True,
    )

    assert fake_session.opened_urls == [urls["matches"]]
    paths = export_team_capture(
        tmp_path / "exports",
        bundle,
        profile_dir=tmp_path / "profile",
        capture_timestamp_basis="simulated view refresh; reused follow states retain source timestamps",
    )
    exported_metrics = _read_json(paths["player_match_metrics"])
    exported_metadata = _read_json(paths["metadata"])
    assert exported_metrics["records"] == follow_metrics_before["records"]
    assert exported_metrics["captured_states"] == follow_metrics_before["captured_states"]
    assert len(exported_metrics["records"]) == len(follow_metrics_before["records"])
    for state, previous in source_state_metadata.items():
        current = exported_metadata["follow_states"][state]
        assert current["source_capture_id"] == previous.get("source_capture_id", capture["capture_id"])
        assert current["sha256"] == previous["sha256"]
    assert capture["capture_id"] in exported_metadata["reused_source_capture_ids"]


def test_global_refresh_reacquires_all_follow_states_in_one_follow_page_visit(monkeypatch, tmp_path):
    context = get_competition_context(group=2)
    record = {"team_id": 49, "name": "Real Jaén", "team_url": "https://www.bdfutbol.com/es/t/t2026-271rf2.html"}
    reference = {"group": "II", "season": context.season, "sha256": "fixture"}
    teams = [record]
    follow_url = "https://www.bdfutbol.com/es/t/t2026-271rf2.html?t=seg"
    html = """<!doctype html><html><head><title>Real Jaén 2026-27</title></head>
    <body><h1>Real Jaén 2026-27</h1><select id="vista_jornades">
    <option value="p" selected>Partidos</option><option value="t">Tarjetas</option>
    <option value="go">Goles</option><option value="tot">Todo</option></select>
    <table id="taula-seguiment"><tr><td>Real Jaén</td></tr></table></body></html>"""
    follow_html = {state: html for state in ("p", "t", "go", "tot")}
    seed = {
        "raw_views": {"alignment": "<html>Real Jaén</html>", "follow": html},
        "access_by_view": {},
        "view_urls": {"alignment": record["team_url"], "follow": follow_url},
        "page_titles": {"follow": "Real Jaén 2026-27"},
        "browser": {},
        "capture_id": "seed-capture",
        "follow_state_html": follow_html,
        "follow_state_diagnostics": {
            state: {"selected_value": state, "url": follow_url, "reused": True}
            for state in follow_html
        },
        "seed_capture_ids": ("seed-capture",),
    }
    session = _FakeSession({follow_url: (html, 200)})
    monkeypatch.setattr(
        team_acquisition,
        "BrowserSessionManager",
        lambda *_args, **_kwargs: _FakeSessionManager(session),
    )
    monkeypatch.setattr(
        team_acquisition, "resolve_team_view_urls",
        lambda *_args, **_kwargs: {"follow": follow_url},
    )
    monkeypatch.setattr(team_acquisition, "parse_team_profile_pages", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(team_acquisition, "validate_team_profile", lambda *_args, **_kwargs: {"valid": True})

    bundle = team_acquisition.acquire_team_profile(
        team_catalog_record=record,
        team_catalog_reference=reference,
        group_team_catalog=teams,
        known_matches=[],
        competition=context,
        profile_dir=tmp_path / "profile",
        requested_views=("follow",),
        seed_raw_views=seed["raw_views"],
        seed_access_by_view=seed["access_by_view"],
        seed_view_urls=seed["view_urls"],
        seed_page_titles=seed["page_titles"],
        seed_browser=seed["browser"],
        seed_capture_id=seed["capture_id"],
        seed_follow_state_html=seed["follow_state_html"],
        seed_follow_state_diagnostics=seed["follow_state_diagnostics"],
        seed_capture_ids=seed["seed_capture_ids"],
        refresh_follow_states=True,
        require_follow_states=True,
    )

    assert session.opened_urls == [follow_url]
    assert set(bundle.follow_state_html) == {"p", "t", "go", "tot"}
    assert all(bundle.follow_state_diagnostics[state].get("reused") is not True for state in ("p", "t", "go", "tot"))
    assert bundle.validation["valid"] is True


def test_cli_derives_jaen_follow_states_offline_without_opening_browser(capsys, monkeypatch, tmp_path):
    source = PROFILE_RUNS[2]
    source_metadata_path = source / "metadata/capture.json"
    source_sha = hashlib.sha256(source_metadata_path.read_bytes()).hexdigest()

    def unexpected_browser(*_args, **_kwargs):
        raise AssertionError("La derivación offline no debe abrir un navegador")

    monkeypatch.setattr(team_acquisition, "BrowserSessionManager", unexpected_browser)
    result = team_acquisition_cli.main([
        "--season", "2026-27",
        "--group", "2",
        "--team-id", "49",
        "--view", "follow",
        "--reuse-capture", str(source),
        "--derive-follow-states-offline",
        "--output-root", str(tmp_path / "teams"),
    ])
    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["team_id"] == 49
    assert output["acquired_views"] == []
    assert set(output["follow_states"]) == {"go", "p", "t", "tot"}

    derived_dir = Path(output["files"]["run_directory"])
    derived_metadata = _read_json(derived_dir / "metadata/capture.json")
    assert derived_metadata["capture_id"] != "team01a-group2-49-source-evidence"
    assert derived_metadata["captured_at_utc"] == _read_json(source_metadata_path)["captured_at_utc"]
    assert derived_metadata["reused_source_capture_ids"] == ["team01a-group2-49-source-evidence"]
    assert derived_metadata["capture_timestamp_basis"].startswith("offline derivation")
    assert derived_metadata["follow_states"]["p"]["status"] == "VALID"
    for state in ("t", "go", "tot"):
        evidence = derived_metadata["follow_states"][state]
        assert evidence["status"] == "DERIVED_OFFLINE"
        assert evidence["origin"] == "derived_offline"
        assert evidence["source_capture_id"] == "team01a-group2-49-source-evidence"
        assert evidence["source_snapshot_sha256"] == derived_metadata["source_snapshots"]["follow"]["sha256"]
        assert evidence["derived_at_utc"]
    assert hashlib.sha256(source_metadata_path.read_bytes()).hexdigest() == source_sha

    context = get_competition_context(group=2)
    teams, known_matches, reference = load_team_catalog(GROUP_CATALOGS[2], competition=context)
    team = next(item for item in teams if int(item["team_id"]) == 49)
    inspection = inspect_team_capture(
        derived_dir,
        team_catalog_record=team,
        competition=context,
        team_catalog_reference=reference,
        group_team_catalog=teams,
        known_matches=known_matches,
    )
    assert inspection.classification == "complete"
    assert inspection.valid_follow_states == ("p", "t", "go", "tot")
    assert inspection.normalized_valid is True


def test_acquisition_stops_on_challenge_without_retry(jaen, monkeypatch, tmp_path):
    context, payload, record, _, _, _, _, _ = jaen
    challenge = '<html><head><title>Just a moment...</title></head><body>Checking your browser</body></html>'
    fake_session = _FakeSession({record["team_url"]: (challenge, 403)})
    monkeypatch.setattr(
        team_acquisition,
        "BrowserSessionManager",
        lambda *_args, **_kwargs: _FakeSessionManager(fake_session),
    )
    with pytest.raises(TeamAcquisitionStopped) as stopped:
        team_acquisition.acquire_team_profile(
            team_catalog_record=record,
            team_catalog_reference={"path": "fixture", "sha256": "fixture"},
            group_team_catalog=payload["teams"],
            known_matches=payload["matches"],
            competition=context,
            profile_dir=tmp_path / "profile",
            requested_views=("alignment", "statistics"),
        )
    assert str(stopped.value.assessment.status) == "CHALLENGE_REQUIRED"
    assert fake_session.opened_urls == [record["team_url"]]


def test_acquisition_preserves_invalid_html_in_checkpoint(jaen, monkeypatch, tmp_path):
    from football_data_hub.providers.bdfutbol.access import (
        AccessAssessment, AccessStatus, BDFutbolVisit,
    )

    context, payload, record, _, _, _, _, _ = jaen
    html = f"<html><head><title>{record['name']} 2026-27</title></head><body>{record['name']} 2026-27</body></html>"
    fake_session = _FakeSession({record["team_url"]: (html, 200)})
    monkeypatch.setattr(
        team_acquisition, "BrowserSessionManager",
        lambda *_args, **_kwargs: _FakeSessionManager(fake_session),
    )

    class FakeAccess:
        def __init__(self, session):
            self.session = session

        def open(self, url, **_kwargs):
            visit = self.session.open_page(url)
            return BDFutbolVisit(
                AccessAssessment(
                    AccessStatus.INVALID_CONTENT, url, url, 200,
                    f"{record['name']} 2026-27", reason="Falta estructura",
                ),
                visit,
            )

    monkeypatch.setattr(team_acquisition, "BDFutbolAccess", FakeAccess)
    checkpoint = TeamEvidenceCheckpoint(
        tmp_path / "captures", season=context.season, group=context.group_roman,
        team_record=record, catalog_reference={"path": "fixture", "sha256": "fixture"},
        requested_views=("alignment",),
    )
    with pytest.raises(TeamAcquisitionStopped):
        team_acquisition.acquire_team_profile(
            team_catalog_record=record,
            team_catalog_reference={"path": "fixture", "sha256": "fixture"},
            group_team_catalog=payload["teams"], known_matches=payload["matches"],
            competition=context, profile_dir=tmp_path / "profile",
            requested_views=("alignment",), evidence_checkpoint=checkpoint,
        )
    manifest = _read_json(checkpoint.manifest_path)
    assert fake_session.opened_urls == [record["team_url"]]
    assert manifest["source_snapshots"] == {}
    rejected = manifest["rejected_snapshots"]["alignment"]
    assert gzip.decompress((checkpoint.path / rejected["path"]).read_bytes()).decode() == html
    assert rejected["sha256"] == hashlib.sha256(html.encode()).hexdigest()


def _checkpoint_from_complete_jaen(root: Path, *, capture_id: str = "diag-jaen-1"):
    context = get_competition_context(group=2)
    payload = _read_json(GROUP_CATALOGS[2])
    record = next(item for item in payload["teams"] if int(item["team_id"]) == 49)
    reference = load_team_catalog(GROUP_CATALOGS[2], competition=context)[2]
    source = ROOT / "data/exports/bdfutbol/teams/2026-27/49/20261012T131457.209360Z-602005d8"
    source_metadata = _read_json(source / "metadata/capture.json")
    checkpoint = TeamEvidenceCheckpoint(
        root,
        season=context.season,
        group=context.group_roman,
        team_record=record,
        catalog_reference=reference,
        requested_views=DEFAULT_VIEWS,
        capture_id=capture_id,
    )
    views: dict[str, str] = {}
    for view, evidence in source_metadata["source_snapshots"].items():
        raw = (source / evidence["path"]).read_bytes()
        html = gzip.decompress(raw).decode("utf-8")
        views[view] = html
        access = dict(source_metadata["access_by_view"][view])
        access.setdefault("captured_at_utc", evidence.get("captured_at_utc"))
        checkpoint.record_view(
            view,
            html,
            requested_url=access["requested_url"],
            final_url=access["final_url"],
            title=evidence.get("title") or access.get("page_title", ""),
            access=access,
        )
    follow_state_html: dict[str, str] = {}
    for state, evidence in source_metadata["follow_states"].items():
        html = gzip.decompress((source / evidence["path"]).read_bytes()).decode("utf-8")
        follow_state_html[state] = html
        checkpoint.record_follow_state(state, html, {
            "selected_value": state,
            "captured_at_utc": evidence.get("captured_at_utc"),
            "url": evidence.get("url"),
        })
    return checkpoint, context, payload, record, reference, views, follow_state_html


def test_rejected_html_is_preserved_but_never_promoted_to_valid_view(tmp_path):
    checkpoint, context, _, record, _, _, _ = _checkpoint_from_complete_jaen(
        tmp_path / "captures"
    )
    html = "<html><body>Respuesta incompleta</body></html>"
    access = {
        "status": "INVALID_CONTENT",
        "http_status": 200,
        "requested_url": record["team_url"],
        "final_url": record["team_url"],
        "page_title": "Respuesta incompleta",
    }
    checkpoint.record_rejected_view("squad", html, access=access)
    manifest = _read_json(checkpoint.manifest_path)
    rejected = manifest["rejected_snapshots"]["squad"]
    assert gzip.decompress((checkpoint.path / rejected["path"]).read_bytes()).decode() == html
    assert rejected["sha256"] == hashlib.sha256(html.encode()).hexdigest()
    assert manifest["source_snapshots"]["squad"]["access_status"] == "VALID"
    with pytest.raises(ValueError):
        checkpoint.record_rejected_view("squad", "new response", access=access)
    assert gzip.decompress((checkpoint.path / rejected["path"]).read_bytes()).decode() == html
    with pytest.raises(ValueError):
        checkpoint.record_rejected_view("statistics", html, access={**access, "status": "VALID"})
    pending = read_pending_evidence(
        checkpoint.path, season=context.season, group=context.group_roman,
        team_record=record,
    )
    assert pending.seed["raw_views"]["squad"] != html


def test_valid_html_is_durable_before_parse_and_recovers_offline(tmp_path):
    checkpoint, context, payload, record, _, _, _ = _checkpoint_from_complete_jaen(tmp_path / "captures")
    checkpoint.record_failure(kind="parse_failed", message="simulated parser regression")
    manifest = _read_json(checkpoint.manifest_path)
    assert manifest["status"] == "parse_failed"
    assert set(manifest["source_snapshots"]) == set(DEFAULT_VIEWS)
    assert (checkpoint.path / "raw/squad.html.gz").is_file()

    pending = read_pending_evidence(
        checkpoint.path,
        season=context.season,
        group=context.group_roman,
        team_record=record,
    )
    assert set(pending.valid_views) == set(DEFAULT_VIEWS)
    assert set(pending.valid_follow_states) == {"p", "t", "go", "tot"}
    parsed = parse_team_profile_pages(
        pending.seed["raw_views"],
        team_catalog_record=record,
        competition_context=context,
        follow_state_html=pending.seed["follow_state_html"],
    )
    validation = validate_team_profile(
        parsed,
        catalog_record=record,
        group_team_catalog=payload["teams"],
        known_matches=payload["matches"],
        requested_views=DEFAULT_VIEWS,
    )
    assert validation["valid"] is True


def test_pending_checkpoint_trusts_captured_follow_value_when_html_attribute_is_stale(tmp_path):
    checkpoint, context, payload, record, _, _, follow_states = _checkpoint_from_complete_jaen(
        tmp_path / "captures",
        capture_id="diag-follow-live-value",
    )
    for state, html in follow_states.items():
        soup = BeautifulSoup(html, "html.parser")
        select = soup.select_one("#vista_jornades")
        assert select is not None
        for option in select.select("option"):
            option.attrs.pop("selected", None)
        # Browser DOM serialization can retain the initial markup selection,
        # while the separately recorded live `selected_value` is authoritative.
        initial_option = select.select_one('option[value="p"]')
        assert initial_option is not None
        initial_option["selected"] = "selected"
        checkpoint.record_follow_state(state, str(soup), {"selected_value": state})

    pending = read_pending_evidence(
        checkpoint.path,
        season=context.season,
        group=context.group_roman,
        team_record=record,
    )
    assert set(pending.valid_follow_states) == {"p", "t", "go", "tot"}
    assert not any("Estado Seguimiento" in warning for warning in pending.warnings)

    parsed = parse_team_profile_pages(
        pending.seed["raw_views"],
        team_catalog_record=record,
        competition_context=context,
        follow_state_html=pending.seed["follow_state_html"],
    )
    validation = validate_team_profile(
        parsed,
        catalog_record=record,
        group_team_catalog=payload["teams"],
        known_matches=payload["matches"],
        requested_views=DEFAULT_VIEWS,
    )
    assert validation["valid"] is True


def test_acquisition_checkpoints_valid_html_before_parser_exception(jaen, monkeypatch, tmp_path):
    context, payload, record, _, _, views, _, _ = jaen
    soup = BeautifulSoup(views["squad"], "html.parser")
    table = soup.select_one("#c3p1")
    assert table is not None
    header_cells = table.select("tr")[0].select("th, td")
    birth_index = next(index for index, cell in enumerate(header_cells) if cell.get("title") == "Fecha de nacimiento")
    player_row = next(row for row in table.select("tr")[1:] if row.select_one('a[href*="/j/j"]'))
    birth_cell = player_row.select("th, td")[birth_index]
    birth_cell.string = "not-a-date"
    malformed_squad = str(soup)
    urls = resolve_team_view_urls(views["alignment"], record["team_url"])
    session = _FakeSession({
        urls["alignment"]: (views["alignment"], 200),
        urls["squad"]: (malformed_squad, 200),
    })
    monkeypatch.setattr(
        team_acquisition,
        "BrowserSessionManager",
        lambda *_args, **_kwargs: _FakeSessionManager(session),
    )
    reference = load_team_catalog(GROUP_CATALOGS[2], competition=context)[2]
    checkpoint = TeamEvidenceCheckpoint(
        tmp_path / "captures",
        season=context.season,
        group=context.group_roman,
        team_record=record,
        catalog_reference=reference,
        requested_views=("alignment", "squad"),
        capture_id="parser-failure-jaen",
    )
    with pytest.raises(TeamProfileParseError, match="Fecha no interpretable"):
        team_acquisition.acquire_team_profile(
            team_catalog_record=record,
            team_catalog_reference=reference,
            group_team_catalog=payload["teams"],
            known_matches=payload["matches"],
            competition=context,
            profile_dir=tmp_path / "profile",
            requested_views=("alignment", "squad"),
            evidence_checkpoint=checkpoint,
        )
    checkpoint.record_failure(kind="parse_failed", message="Fecha no interpretable")
    pending = read_pending_evidence(
        checkpoint.path,
        season=context.season,
        group=context.group_roman,
        team_record=record,
    )
    assert session.opened_urls == [urls["alignment"], urls["squad"]]
    assert set(pending.valid_views) == {"alignment", "squad"}
    assert pending.manifest["status"] == "parse_failed"
    assert not (checkpoint.path / "normalized").exists()


def test_pending_recovery_rejects_hash_missing_identity_and_denial(tmp_path):
    checkpoint, context, _, record, _, _, _ = _checkpoint_from_complete_jaen(tmp_path / "tampered")
    (checkpoint.path / "raw/squad.html.gz").write_bytes(b"tampered gzip")
    (checkpoint.path / "raw/statistics.html.gz").unlink()
    pending = read_pending_evidence(
        checkpoint.path,
        season=context.season,
        group=context.group_roman,
        team_record=record,
    )
    assert "squad" not in pending.valid_views
    assert "statistics" not in pending.valid_views
    assert any("squad" in warning for warning in pending.warnings)
    assert any("statistics" in warning for warning in pending.warnings)
    with pytest.raises(ValueError, match="identidad, grupo, temporada o procedencia"):
        read_pending_evidence(
            checkpoint.path,
            season=context.season,
            group="I",
            team_record=record,
        )

    denied = TeamEvidenceCheckpoint(
        tmp_path / "denied",
        season=context.season,
        group=context.group_roman,
        team_record=record,
        catalog_reference={},
        requested_views=DEFAULT_VIEWS,
        capture_id="denied-jaen",
    )
    with pytest.raises(ValueError, match="VALID y HTTP 200"):
        denied.record_view(
            "alignment",
            "<html>Just a moment</html>",
            requested_url=record["team_url"],
            final_url=record["team_url"],
            title="Just a moment",
            access={"status": "CHALLENGE_REQUIRED", "http_status": 403},
        )
    denied.record_failure(kind="access_denied", message="HTTP 403")
    assert denied.manifest["source_snapshots"] == {}
    with pytest.raises(ValueError, match="no es reutilizable"):
        read_pending_evidence(
            denied.path,
            season=context.season,
            group=context.group_roman,
            team_record=record,
        )


def test_diagnostic_checkpoints_are_not_returned_as_published_captures(tmp_path):
    checkpoint, context, payload, record, reference, _, _ = _checkpoint_from_complete_jaen(
        tmp_path / "exports", capture_id="diagnostic-only"
    )
    captures = inspect_team_captures(
        tmp_path / "exports",
        season=context.season,
        team_catalog_record=record,
        competition=context,
        team_catalog_reference=reference,
        group_team_catalog=payload["teams"],
        known_matches=payload["matches"],
        required_views=DEFAULT_VIEWS,
    )
    assert captures == ()
    assert checkpoint.path.exists()


def test_pending_resume_requests_only_the_page_without_valid_evidence(monkeypatch, tmp_path):
    checkpoint, context, payload, record, reference, views, _ = _checkpoint_from_complete_jaen(
        tmp_path / "resume", capture_id="resume-jaen"
    )
    (checkpoint.path / "raw/squad.html.gz").unlink()
    pending = read_pending_evidence(
        checkpoint.path,
        season=context.season,
        group=context.group_roman,
        team_record=record,
    )
    urls = resolve_team_view_urls(views["alignment"], record["team_url"])
    session = _FakeSession({urls["squad"]: (views["squad"], 200)})
    monkeypatch.setattr(
        team_acquisition,
        "BrowserSessionManager",
        lambda *_args, **_kwargs: _FakeSessionManager(session),
    )
    resumed_checkpoint = TeamEvidenceCheckpoint(
        tmp_path / "resume",
        season=context.season,
        group=context.group_roman,
        team_record=record,
        catalog_reference=reference,
        requested_views=DEFAULT_VIEWS,
        capture_id=pending.capture_id,
        resume_path=pending.path,
    )
    bundle = team_acquisition.acquire_team_profile(
        team_catalog_record=record,
        team_catalog_reference=reference,
        group_team_catalog=payload["teams"],
        known_matches=payload["matches"],
        competition=context,
        profile_dir=tmp_path / "profile",
        requested_views=("squad",),
        seed_raw_views=pending.seed["raw_views"],
        seed_access_by_view=pending.seed["access_by_view"],
        seed_view_urls=pending.seed["view_urls"],
        seed_page_titles=pending.seed["page_titles"],
        seed_browser=pending.seed["browser"],
        seed_capture_id=pending.capture_id,
        seed_follow_state_html=pending.seed["follow_state_html"],
        seed_follow_state_diagnostics=pending.seed["follow_state_diagnostics"],
        seed_capture_ids=(pending.capture_id,),
        capture_id=pending.capture_id,
        require_follow_states=True,
        evidence_checkpoint=resumed_checkpoint,
    )
    assert session.opened_urls == [urls["squad"]]
    assert bundle.acquired_views == ("squad",)
    assert bundle.validation["valid"] is True


def test_dry_run_plan_counts_only_missing_pages_in_pending_evidence(tmp_path, monkeypatch):
    checkpoint, context, _, record, reference, _, _ = _checkpoint_from_complete_jaen(tmp_path / "plan")
    (checkpoint.path / "raw/squad.html.gz").unlink()
    pending = read_pending_evidence(
        checkpoint.path,
        season=context.season,
        group=context.group_roman,
        team_record=record,
    )
    plan = _team_plan(
        record=record,
        group=2,
        views=DEFAULT_VIEWS,
        assessment=None,
        catalog_reference=reference,
        pending_evidence=pending,
    )
    assert plan["action"] == "resume_pending"
    assert plan["planned_page_visits"] == ["squad"]
    assert plan["planned_navigation_count"] == 1


def test_batch_defaults_are_slow_and_storage_is_configurable(monkeypatch, tmp_path):
    monkeypatch.setenv("FDH_TEAM_CAPTURE_ROOT", str(tmp_path / "persistent" / "captures"))
    args = parse_team_batch_args([])
    assert args.pause_seconds >= 5
    assert args.output_root == tmp_path / "persistent" / "captures"
    assert _is_inside_repository(ROOT / "data/exports/bdfutbol/teams") is True
    assert _is_inside_repository(tmp_path / "captures") is False
    with pytest.raises(ValueError, match="requiere almacenamiento externo"):
        team_batch_main([
            "--groups", "both",
            "--team-id", "76",
            "--output-root", str(ROOT / "data/exports/bdfutbol/teams"),
        ])


def test_unknown_match_ids_raise_stale_catalog_error_offline(jaen):
    context, payload, record, _, _, views, parsed, _ = jaen
    referenced_id = parsed.team_match_ids_from_profile[0]
    incomplete_catalog = [item for item in payload["matches"] if str(item["match_id"]) != referenced_id]
    with pytest.raises(StaleMatchCatalogError, match="no cubre las referencias"):
        team_acquisition.acquire_team_profile(
            team_catalog_record=record,
            team_catalog_reference={"path": "fixture", "sha256": "fixture"},
            group_team_catalog=payload["teams"],
            known_matches=incomplete_catalog,
            competition=context,
            profile_dir=Path("unused-profile"),
            requested_views=(),
            seed_raw_views=views,
            require_follow_states=False,
        )
