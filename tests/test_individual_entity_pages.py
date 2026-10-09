"""Offline checks using real captured pages and explicitly synthetic edge cases."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from football_data_hub.parsers.individual_entity_pages import (
    EntityPageError,
    load_valid_entity_snapshot,
    parse_entity_metadata_file,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
_REAL_PAGE_URLS = {
    "match": "https://www.bdfutbol.com/es/p/p.php?id=269462",
    "coach": "https://www.bdfutbol.com/es/l/l1835.html",
    "referee": "https://www.bdfutbol.com/es/r/r602267.html",
    "stadium": "https://www.bdfutbol.com/es/s/81.html",
}


def _real_metadata_path(expected_url: str) -> Path:
    for path in (REPO_ROOT / "data/raw/bdfutbol").rglob("metadata.json"):
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if metadata.get("final_url") == expected_url:
            return path
    raise AssertionError(f"No se encontró la captura local requerida: {expected_url}")


def _synthetic_snapshot(
    tmp_path: Path,
    *,
    requested_url: str = _REAL_PAGE_URLS["coach"],
    final_url: str | None = None,
    http_status: int = 200,
    access_status: str = "VALID",
    html: str = (
        "<html><head><title>Entrenador | BDFutbol</title></head>"
        "<body><h1>Entrenador de prueba</h1>"
        "<table class='taula_estil traject'><tr><td>Temp</td></tr></table>"
        "</body></html>"
    ),
) -> Path:
    """Construct synthetic validation input; it is not a claimed BDFutbol sample."""
    snapshot_dir = tmp_path / "synthetic_snapshot"
    snapshot_dir.mkdir(parents=True)
    html_bytes = html.encode("utf-8")
    (snapshot_dir / "rendered.html").write_bytes(html_bytes)
    metadata = {
        "requested_url": requested_url,
        "final_url": final_url or requested_url,
        "http_status": http_status,
        "access_status": access_status,
        "captured_at_utc": "2026-10-09T00:00:00+00:00",
        "rendered_html_bytes": len(html_bytes),
        "rendered_html_sha256": hashlib.sha256(html_bytes).hexdigest(),
    }
    metadata_path = snapshot_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    return metadata_path


def _synthetic_player_row(
    index: int,
    *,
    name: str | None = None,
    player_id: str | None = None,
    markers: str = "",
) -> str:
    """Build a synthetic table row; it is not claimed to match another live page."""
    display = name or f"Fixture Player {index}"
    player_cell = (
        f'<a href="../j/j{player_id}.html">{display}</a>'
        if player_id else display
    )
    return (
        f"<tr><td>{index}</td><td></td><td></td><td>{player_cell}</td>"
        f"<td>{markers}</td><td></td></tr>"
    )


def _synthetic_match_html(
    *,
    home_events: list[str] | None = None,
    away_events: list[str] | None = None,
    home_starters: list[str] | None = None,
    away_starters: list[str] | None = None,
    home_substitutes: list[str] | None = None,
    away_substitutes: list[str] | None = None,
    include_away_substitute_table: bool = True,
    home_coach_markers: str = "",
    include_hidden_sports_table: bool = False,
) -> str:
    """Return an explicitly synthetic match-shaped fixture for parser edge cases."""
    home_starters = home_starters or [
        _synthetic_player_row(index, player_id=str(1000 + index))
        for index in range(1, 12)
    ]
    away_starters = away_starters or [
        _synthetic_player_row(index, player_id=str(2000 + index))
        for index in range(1, 12)
    ]
    home_substitutes = home_substitutes or []
    away_substitutes = away_substitutes or []

    def table(rows: list[str]) -> str:
        return "<table class='taula_estil text-left'><tbody>" + "".join(rows) + "</tbody></table>"

    home_events_html = "".join(home_events or [])
    away_events_html = "".join(away_events or [])
    hidden_table = (
        "<table class='taula_estil d-none'><tr><td>hidden synthetic sports row</td></tr></table>"
        if include_hidden_sports_table else ""
    )
    away_substitute_table = (
        f"<div class='col-6'>{table(away_substitutes)}</div>"
        if include_away_substitute_table else ""
    )
    home_coach = table([
        f'<tr class="entren"><td></td><td></td>'
        f'<td><a href="../l/l100.html">Home Coach</a></td>'
        f'<td><div class="cosa">{home_coach_markers}</div></td></tr>'
    ])
    away_coach = table([
        '<tr class="entren"><td></td><td></td>'
        '<td><a href="../l/l200.html">Away Coach</a></td><td></td></tr>'
    ])
    return (
        "<html><head><title>Home - Away (1 - 0) 02/10/2026 | BDFutbol</title></head><body>"
        "<div class='hero hero-partit'><h1>"
        "<a href='../e/e81.html'>Home</a> 1 <a href='../e/e76.html'>Away</a>"
        "</h1><div class='row text-center mb-0'>"
        f"<div class='col-6'><div class='text-right'>{home_events_html}</div></div>"
        f"<div class='col-6'><div class='text-left'>{away_events_html}</div></div>"
        "</div></div>"
        "<div class='row pt-3 pb-2'><div class='col-md-12 mb-3'></div>"
        f"<div class='col-6'>{table(home_starters)}</div>"
        f"<div class='col-6'>{table(away_starters)}</div>"
        "<div class='col-md-12'><h2>Suplentes</h2></div>"
        f"<div class='col-6'>{table(home_substitutes)}</div>"
        f"{away_substitute_table}"
        "<div class='col-md-12'><h2>Entrenadores</h2></div>"
        f"<div class='col-6'>{home_coach}</div>"
        f"<div class='col-6'>{away_coach}</div>"
        f"{hidden_table}</div></body></html>"
    )


def _synthetic_match_snapshot(tmp_path: Path, html: str | None = None) -> Path:
    return _synthetic_snapshot(
        tmp_path,
        requested_url="https://www.bdfutbol.com/es/p/p.php?id=269462",
        html=html or _synthetic_match_html(),
    )


@pytest.mark.parametrize("entity_type,url", _REAL_PAGE_URLS.items())
def test_real_captured_pages_validate_hash_identity_and_parse(entity_type: str, url: str) -> None:
    metadata_path = _real_metadata_path(url)
    snapshot = load_valid_entity_snapshot(metadata_path, REPO_ROOT)
    record = parse_entity_metadata_file(metadata_path, REPO_ROOT)

    assert snapshot.entity_type == entity_type
    assert record["entity_type"] == entity_type
    assert record["entity_id"] == {
        "match": "269462", "coach": "l1835", "referee": "602267", "stadium": "81",
    }[entity_type]
    assert snapshot.html_sha256 == snapshot.metadata["rendered_html_sha256"]
    assert record["source"]["access_status"] == "VALID"
    assert record["source"]["http_status"] == 200
    assert record["coverage"]["page_status"] == "CAPTURED_VALID"
    assert record["coverage"]["semantic_entity_completeness"] == "NOT_ASSERTED"
    assert record["coverage"]["full_html_retained_at_raw_path"].endswith("rendered.html")


def test_real_match_contract_preserves_title_tables_and_explicit_relationships() -> None:
    record = parse_entity_metadata_file(_real_metadata_path(_REAL_PAGE_URLS["match"]), REPO_ROOT)

    assert record["match_title_fields"] == {
        "home_team_name_raw": "Avilés Industrial",
        "away_team_name_raw": "Lugo",
        "home_goals": 1,
        "away_goals": 2,
        "date_raw": "02/10/2026",
        "date": "2026-10-02",
        "evidence": "BDFUTBOL_MATCH_TITLE_PATTERN",
    }
    assert len(record["tables"]) == 6
    assert record["coverage"]["table_row_count"] == 52
    assert record["coverage"]["table_cell_count"] == 278
    links = {
        (item["target_entity_type"], item["target_entity_id"])
        for item in record["related_entity_links"]
    }
    assert ("club", "81") in links
    assert ("club", "76") in links
    assert ("stadium", "81") in links
    assert ("referee", "602267") in links
    assert record["match_hero_fields_raw"][0]["label_raw"] == "Competición"
    assert len(record["match_hero_events_text_raw"]) == 1


def test_real_match_extracts_supported_participants_coaches_and_events() -> None:
    record = parse_entity_metadata_file(_real_metadata_path(_REAL_PAGE_URLS["match"]), REPO_ROOT)

    assert [(club["entity_id"], club["name_raw"]) for club in record["match_clubs"]] == [
        ("81", "Avilés Industrial"), ("76", "Lugo"),
    ]
    assert [club["source_id_raw"] for club in record["match_clubs"]] == ["e81", "e76"]
    assert len(record["match_participants"]) == 44
    starters = [item for item in record["match_participants"] if item["roster_section"] == "STARTING_LINEUP"]
    substitutes = [item for item in record["match_participants"] if item["roster_section"] == "SUBSTITUTES"]
    assert len(starters) == 22
    assert len(substitutes) == 22
    assert all(item["team"]["entity_id"] in {"81", "76"} for item in starters + substitutes)
    assert all(item["leading_cell_interpretation"] == "RAW_ONLY_NO_VERIFIED_COLUMN_HEADER"
               for item in starters + substitutes)

    goals = [event for event in record["match_events"] if event["event_type"] == "GOAL"]
    assert [(item["score_raw"], item["minute_raw"], item["player_entity_id"]) for item in goals] == [
        ("1-0", "5", "j27562"),
        ("1-1", "68", "j206674"),
        ("1-2", "90+11", "j26448"),
    ]
    assert [item["player_source_id_raw"] for item in goals] == [
        "j27562", "j206674", "j26448",
    ]
    assert [item["team"]["entity_id"] for item in goals] == ["81", "76", "76"]
    assert all(len(item["corroborating_player_table_markers"]) == 1 for item in goals)
    assert record["match_quality"]["goal_event_count"] == 3
    assert record["match_quality"]["published_result_coherence"] == (
        "EVENT_SCORE_SEQUENCE_MATCHES_PUBLISHED_RESULT_COUNT_NOT_COMPLETENESS"
    )
    assert record["match_quality"]["event_list_completeness"] == "UNKNOWN"

    substitution_events = [
        event for event in record["match_events"]
        if event["event_type"] == "SUBSTITUTION_ACTION"
    ]
    assert len(substitution_events) == 20
    assert {item["action"] for item in substitution_events} == {"PLAYER_ENTERED", "PLAYER_LEFT"}
    assert all(item["pairing_status"] == "NOT_INFERRED" for item in substitution_events)
    cards = [event for event in record["match_events"] if event["event_type"] == "CARD"]
    assert len(cards) == 1
    assert (cards[0]["actor_entity_id"], cards[0]["team"]["entity_id"], cards[0]["minute_raw"]) == (
        "l104929", "81", "63",
    )
    assert [(item["coach_entity_id"], item["team"]["entity_id"], item["role"]) for item in record["match_coaches"]] == [
        ("l104929", "81", "COACH"), ("l330", "76", "COACH"),
    ]
    assert [item["coach_source_id_raw"] for item in record["match_coaches"]] == [
        "l104929", "l330",
    ]
    assert record["match_quality"]["capture_ready_state"] == "loading"
    assert record["match_quality"]["capture_inventory_complete"] is False
    assert record["match_quality"]["capture_interaction_coverage"] == "NOT_TESTED"
    assert record["match_quality"]["capture_readiness_status"] == "PRESENT_SNAPSHOT_REPORTED_LOADING"
    assert record["match_quality"]["semantic_entity_completeness"] == "NOT_ASSERTED"
    assert record["match_quality"]["total_source_table_count"] == 63
    assert record["match_quality"]["excluded_presentation_table_count"] == 57
    assert record["match_quality"]["event_ordering"] == (
        "GOALS_THEN_TABLE_ACTIONS_THEN_CARDS_NOT_A_GLOBAL_TIMELINE"
    )
    assert record["excluded_hidden_sports_tables"] == []
    assert record["tables"][0]["rows"][0]["hidden_by_inline_style"] is True
    assert any(
        element["title_raw"] == "Gol"
        for element in record["tables"][0]["rows"][11]["cells"][5]["source_elements_raw"]
    )


def test_real_match_details_crosscheck_historical_club_match_export_offline() -> None:
    import gzip

    record = parse_entity_metadata_file(_real_metadata_path(_REAL_PAGE_URLS["match"]), REPO_ROOT)
    historical_path = (
        REPO_ROOT
        / "data/parsed/bdfutbol/club_team_2026_27/compact/"
        / "snapshot-7ffcbd5f11c8e83fdae4-parser-1.7.0/sports/"
        / "matches_from_embedded_data.json.gz"
    )
    historical = json.loads(gzip.decompress(historical_path.read_bytes()))
    match = next(item for item in historical["items"] if item["match_id"] == "269462")

    assert record["match_title_fields"]["date"] == match["date"] == "2026-10-02"
    assert [club["entity_id"] for club in record["match_clubs"]] == ["81", "76"]
    assert (match["home_club_id"], match["away_club_id"]) == ("e81", "e76")
    assert (
        record["match_title_fields"]["home_goals"],
        record["match_title_fields"]["away_goals"],
    ) == (match["home_goals"], match["away_goals"]) == (1, 2)
    hero_values = {item["label_raw"]: item for item in record["match_hero_fields_raw"]}
    assert hero_values["Competición"]["value_raw"] == "1ª RFEF"
    assert hero_values["Jornada"]["value_raw"] == "Jornada 6"
    assert any(
        item["target_entity_type"] == "referee" and item["target_entity_id"] == "602267"
        for item in record["related_entity_links"]
    )
    assert match["referee_id_raw"] == 602267
    assert any(
        item["target_entity_type"] == "stadium" and item["target_entity_id"] == "81"
        for item in record["related_entity_links"]
    )
    assert match["source_observation_count"] == 2
    assert match["differing_fields_between_club_sources"] == []
    assert "stadium_id" not in match


def test_real_match_resource_exports_keep_provenance_and_detail_counts(tmp_path: Path) -> None:
    import gzip

    from parse_bdfutbol_entity_pages_offline import write_immutable_entity_exports

    record = parse_entity_metadata_file(_real_metadata_path(_REAL_PAGE_URLS["match"]), REPO_ROOT)
    records = {
        "match": [record],
        "coach": [],
        "referee": [],
        "stadium": [],
    }
    output = write_immutable_entity_exports(
        records_by_type=records,
        coverage=[],
        errors=[],
        source_fingerprint="synthetic-match-resource-test",
        output_root=tmp_path,
    )

    expected_counts = {
        "match_participants": 44,
        "match_coaches": 2,
        "match_events": 24,
    }
    for resource, expected_count in expected_counts.items():
        payload = json.loads(gzip.decompress((output / f"{resource}.json.gz").read_bytes()))
        match = payload["matches"][0]
        assert payload["parser_version"] == record["parser_version"] == "0.2.0"
        assert match["match_id"] == "269462"
        assert match["source"]["rendered_html_sha256"] == record["source"]["rendered_html_sha256"]
        assert len(match["items"]) == expected_count

    quality = json.loads(gzip.decompress((output / "match_quality.json.gz").read_bytes()))
    assert quality["matches"][0]["items"]["event_list_completeness"] == "UNKNOWN"


def test_a2_match_export_remains_immutable_and_uses_its_original_contract() -> None:
    import gzip

    old_export_path = (
        REPO_ROOT
        / "data/parsed/bdfutbol/entity_detail_pilots/"
        / "parser-0.1.1-source-4b97a04a5c1b8a6f/match_details.json.gz"
    )
    old_export = json.loads(gzip.decompress(old_export_path.read_bytes()))
    old_match = next(item for item in old_export["entities"] if item["entity_id"] == "269462")

    assert old_export["parser_version"] == "0.1.1"
    assert old_export["schema_version"] == "football_data_hub.match_details_export.v1"
    assert "match_events" not in old_match
    assert "rendered_html_sha256" in old_match["source"]


def test_synthetic_unlinked_player_and_unpaired_team_stay_unresolved(tmp_path: Path) -> None:
    starters = [
        _synthetic_player_row(1, name="No Link", player_id=None),
        *[
            _synthetic_player_row(index, player_id=str(1000 + index))
            for index in range(2, 12)
        ],
    ]
    unpaired_substitute = _synthetic_player_row(
        12,
        name="Bench Without Team",
        player_id="901",
        markers='<div class="cosa"><div class="Entra" title="Entra"></div></div>',
    )
    html = _synthetic_match_html(
        home_starters=starters,
        home_substitutes=[unpaired_substitute],
        include_away_substitute_table=False,
    )
    record = parse_entity_metadata_file(_synthetic_match_snapshot(tmp_path, html), tmp_path)

    unlinked = next(item for item in record["match_participants"] if item["player_name_raw"] == "No Link")
    assert unlinked["player_entity_id"] is None
    assert unlinked["identity_status"] == "PLAYER_LINK_NOT_PRESENT"
    assert unlinked["team"]["entity_id"] == "81"
    unpaired = next(
        item for item in record["match_participants"]
        if item["player_name_raw"] == "Bench Without Team"
    )
    assert unpaired["player_entity_id"] == "j901"
    assert unpaired["team"]["entity_id"] is None
    assert unpaired["team"]["assignment_status"] == "UNVERIFIABLE_FROM_TWO_COLUMN_MATCH_LAYOUT"
    action = next(event for event in record["match_events"] if event["event_type"] == "SUBSTITUTION_ACTION")
    assert action["team"]["entity_id"] is None
    assert action["minute_raw"] is None
    assert action["player_identity_status"] == "LINK_VERIFIED"


def test_synthetic_goal_without_minute_and_added_time_keep_source_values(tmp_path: Path) -> None:
    no_minute = (
        '<div class="text-blanc"><span>1-0</span> '
        '<a href="../j/j300.html">Scorer</a></div>'
    )
    added_time = (
        '<div class="text-blanc"><span>1-0</span> '
        '<a href="../j/j300.html">Scorer</a> 90+11\'</div>'
    )
    no_minute_record = parse_entity_metadata_file(
        _synthetic_match_snapshot(tmp_path / "no-minute", _synthetic_match_html(home_events=[no_minute])),
        tmp_path,
    )
    added_time_record = parse_entity_metadata_file(
        _synthetic_match_snapshot(tmp_path / "added-time", _synthetic_match_html(home_events=[added_time])),
        tmp_path,
    )

    assert no_minute_record["match_events"][0]["minute_raw"] is None
    assert no_minute_record["match_events"][0]["minute_status"] == "NOT_PRESENT"
    assert added_time_record["match_events"][0]["minute_raw"] == "90+11"
    assert "90+11" in added_time_record["match_events"][0]["source_event_text_raw"]


def test_synthetic_duplicate_goal_occurrences_are_preserved_but_not_double_counted(tmp_path: Path) -> None:
    goal = (
        '<div class="text-blanc"><span>1-0</span> '
        '<a href="../j/j300.html">Scorer</a> 15\'</div>'
    )
    record = parse_entity_metadata_file(
        _synthetic_match_snapshot(
            tmp_path,
            _synthetic_match_html(home_events=[goal, goal]),
        ),
        tmp_path,
    )

    goals = [event for event in record["match_events"] if event["event_type"] == "GOAL"]
    assert len(goals) == 1
    assert goals[0]["source_occurrence_count"] == 2
    assert goals[0]["source_occurrence_indexes"] == [0, 1]
    assert len(record["match_event_occurrences_raw"]) == 2


def test_synthetic_simultaneous_substitution_actions_are_not_paired(tmp_path: Path) -> None:
    outgoing = _synthetic_player_row(
        1,
        player_id="401",
        markers='<div class="cosa"><div class="Surt" title="Sale"></div>60</div>',
    )
    incoming = _synthetic_player_row(
        2,
        player_id="402",
        markers='<div class="cosa"><div class="Entra" title="Entra"></div>60</div>',
    )
    record = parse_entity_metadata_file(
        _synthetic_match_snapshot(
            tmp_path,
            _synthetic_match_html(home_substitutes=[incoming], home_starters=[
                outgoing,
                *[
                    _synthetic_player_row(index, player_id=str(410 + index))
                    for index in range(2, 12)
                ],
            ]),
        ),
        tmp_path,
    )
    actions = [
        event for event in record["match_events"]
        if event["event_type"] == "SUBSTITUTION_ACTION" and event["minute_raw"] == "60"
    ]

    assert {event["action"] for event in actions} == {"PLAYER_ENTERED", "PLAYER_LEFT"}
    assert len(actions) == 2
    assert all(event["pairing_status"] == "NOT_INFERRED" for event in actions)


def test_synthetic_hidden_sports_table_and_unknown_events_remain_raw_only(tmp_path: Path) -> None:
    unknown_hero_event = '<div class="text-blanc">Interrupción sin marcador</div>'
    record = parse_entity_metadata_file(
        _synthetic_match_snapshot(
            tmp_path,
            _synthetic_match_html(
                home_events=[unknown_hero_event],
                home_coach_markers='<div class="mystery" title="Unknown event"></div>12',
                include_hidden_sports_table=True,
            ),
        ),
        tmp_path,
    )

    assert record["match_events"] == []
    assert record["unclassified_hero_event_occurrences"][0]["event_text_raw"] == (
        "Interrupción sin marcador"
    )
    assert record["unclassified_source_markers"][0]["title_raw"] == "Unknown event"
    assert record["match_quality"]["hidden_sports_table_count"] == 1
    assert record["excluded_hidden_sports_tables"][0]["interpretation_status"] == (
        "RAW_ONLY_HIDDEN_TABLE_NOT_PROMOTED"
    )
    assert all(
        "hidden synthetic sports row" not in cell["value_raw"]
        for table in record["tables"]
        for row in table["rows"]
        for cell in row["cells"]
    )


def test_real_coach_and_referee_keep_source_trajectory_headers_and_json() -> None:
    coach = parse_entity_metadata_file(_real_metadata_path(_REAL_PAGE_URLS["coach"]), REPO_ROOT)
    referee = parse_entity_metadata_file(_real_metadata_path(_REAL_PAGE_URLS["referee"]), REPO_ROOT)

    coach_trajectory = next(item for item in coach["embedded_json"] if item["variable_name_raw"] == "trajectoria")
    referee_trajectory = next(item for item in referee["embedded_json"] if item["variable_name_raw"] == "trajectoria")
    assert len(coach_trajectory["values_raw"]) == 14
    assert len(referee_trajectory["values_raw"]) == 4
    assert coach["tables"][0]["headers_raw"][:3] == ["Temp", "Equipo", "País"]
    assert referee["tables"][0]["headers_raw"][:3] == ["Temp", "País", ""]
    assert any(cell["value_raw"] == "-" for table in coach["tables"] for row in table["rows"] for cell in row["cells"])
    assert any(cell["hidden_by_source_class"] for table in referee["tables"] for row in table["rows"] for cell in row["cells"])
    assert coach["coverage"]["interpretation_status"] == "PARTIAL_STRUCTURED_WITH_RAW_PRESERVATION"


def test_real_stadium_keeps_sections_chart_values_and_map_literals_raw() -> None:
    record = parse_entity_metadata_file(_real_metadata_path(_REAL_PAGE_URLS["stadium"]), REPO_ROOT)
    data_visit = next(item for item in record["embedded_json"] if item["variable_name_raw"] == "dataVisit")

    assert [section["heading_raw"] for section in record["page_sections"]] == [
        "Equipo Local", "Competiciones", "Top Visitantes", "Equipos Visitantes",
        "Temporadas", "Primer partido oficial", "Nombres", "Ubicación",
    ]
    assert len(data_visit["values_raw"]) == 15
    assert record["map_literals_raw"] == [{
        "center_coordinates_raw": "[43.557,-5.930]",
        "zoom_raw": "15",
        "marker_coordinates_raw": "[43.557,-5.930]",
        "popup_label_raw": "Suárez Puerta",
        "interpretation_status": "SOURCE_LITERALS_ONLY",
    }]


def test_real_snapshot_parse_is_deterministic() -> None:
    path = _real_metadata_path(_REAL_PAGE_URLS["coach"])
    assert parse_entity_metadata_file(path, REPO_ROOT) == parse_entity_metadata_file(path, REPO_ROOT)


def test_synthetic_profile_with_missing_sports_structure_is_rejected(tmp_path: Path) -> None:
    metadata_path = _synthetic_snapshot(
        tmp_path,
        html=(
            "<html><head><title>Entrenador | BDFutbol</title></head>"
            "<body><h1>Entrenador de prueba</h1><p>Contenido sin trayectoria.</p></body></html>"
        ),
    )

    with pytest.raises(EntityPageError, match="estructura deportiva"):
        load_valid_entity_snapshot(metadata_path, tmp_path)


def test_synthetic_wrong_final_identity_is_rejected(tmp_path: Path) -> None:
    metadata_path = _synthetic_snapshot(
        tmp_path,
        final_url="https://www.bdfutbol.com/es/l/l1836.html",
    )

    with pytest.raises(EntityPageError, match="tipo e ID solicitados"):
        load_valid_entity_snapshot(metadata_path, tmp_path)


def test_synthetic_http_403_challenge_is_not_valid_sports_content(tmp_path: Path) -> None:
    metadata_path = _synthetic_snapshot(
        tmp_path,
        http_status=403,
        access_status="BLOCKED",
        html="<html><title>Just a moment</title><body>challenge-platform</body></html>",
    )

    with pytest.raises(EntityPageError, match="estado de acceso no válido"):
        load_valid_entity_snapshot(metadata_path, tmp_path)


def test_synthetic_rendered_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    metadata_path = _synthetic_snapshot(tmp_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["rendered_html_sha256"] = "0" * 64
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(EntityPageError, match="SHA-256"):
        load_valid_entity_snapshot(metadata_path, tmp_path)


def test_versioned_export_reuses_identical_bytes_and_rejects_overwrite(tmp_path: Path) -> None:
    from parse_bdfutbol_entity_pages_offline import write_immutable_entity_exports

    records = {entity_type: [] for entity_type in ("match", "coach", "referee", "stadium")}
    first = write_immutable_entity_exports(
        records_by_type=records,
        coverage=[],
        errors=[],
        source_fingerprint="synthetic-source",
        output_root=tmp_path,
    )
    first_bytes = {path.name: path.read_bytes() for path in first.iterdir() if path.is_file()}
    assert {
        "match_participants.json.gz",
        "match_coaches.json.gz",
        "match_events.json.gz",
        "match_quality.json.gz",
    } <= set(first_bytes)
    second = write_immutable_entity_exports(
        records_by_type=records,
        coverage=[],
        errors=[],
        source_fingerprint="synthetic-source",
        output_root=tmp_path,
    )

    assert second == first
    assert {path.name: path.read_bytes() for path in second.iterdir() if path.is_file()} == first_bytes
    changed = {**records, "match": [{"entity_type": "match", "entity_id": "fixture-only"}]}
    with pytest.raises(FileExistsError, match="contenido distinto"):
        write_immutable_entity_exports(
            records_by_type=changed,
            coverage=[],
            errors=[],
            source_fingerprint="synthetic-source",
            output_root=tmp_path,
        )
