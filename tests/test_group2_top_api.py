"""Strict API contract and isolation tests for the independent TOP capture."""

from __future__ import annotations

import json
import hashlib
import re
import shutil
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from football_data_hub_api.config import ApiSettings, PROJECT_ROOT
from football_data_hub_api.dataset import load_dataset
from football_data_hub_api.main import create_app
from football_data_hub_api.top_dataset import (
    TopDatasetLoadError,
    _validate_foreigners_coverage,
    load_top_dataset,
    project_top_player_links,
)

TOP_ROOT = PROJECT_ROOT / "data/exports/bdfutbol/group2_top/20261010T155145.195266Z-c5b031a6"
GROUP1_TOP_ROOT = PROJECT_ROOT / "data/exports/bdfutbol/group1_top/20261010T202506.237287Z-c92b19fb"
GROUP1_TEAMS_PATH = PROJECT_ROOT / "data/exports/bdfutbol/group1_classification/20261010T202500.293648Z-b770724f/normalized/matches.json"
CLASSIFICATION_ROOT = PROJECT_ROOT / "data/exports/bdfutbol/group2_classification"


def settings() -> ApiSettings:
    return ApiSettings(
        matches_path=CLASSIFICATION_ROOT / "derived-res01-20261010T102656Z/normalized/matches.json",
        classification_path=CLASSIFICATION_ROOT / "20261010T102656.252222Z-72f200ad/normalized/classification.json",
        progress_path=CLASSIFICATION_ROOT / "20261010T102656.252222Z-72f200ad/normalized/progress.json",
        capture_metadata_path=CLASSIFICATION_ROOT / "20261010T102656.252222Z-72f200ad/metadata/capture.json",
    )


def settings_for_top(root: Path) -> ApiSettings:
    configured = settings()
    return replace(
        configured,
        top_players_path=root / "normalized/players.json",
        top_rankings_path=root / "normalized/rankings.json",
        top_progress_path=root / "normalized/progress.json",
        top_foreigners_path=root / "normalized/foreigners.json",
        top_capture_metadata_path=root / "metadata/capture.json",
        top_validation_path=root / "validation/results.json",
        top_source_html_path=root / "raw/source.html",
    )


def settings_for_group1_top(root: Path = GROUP1_TOP_ROOT) -> ApiSettings:
    return replace(
        settings(),
        group="I",
        top_players_path=root / "normalized/players.json",
        top_rankings_path=root / "normalized/rankings.json",
        top_progress_path=root / "normalized/progress.json",
        top_foreigners_path=root / "normalized/foreigners.json",
        top_capture_metadata_path=root / "metadata/capture.json",
        top_validation_path=root / "validation/results.json",
        top_source_html_path=root / "raw/source.html",
        top_team_catalog_path=GROUP1_TEAMS_PATH,
    )


def group1_top_copy(tmp_path: Path) -> Path:
    root = tmp_path / "group1-top-copy"
    shutil.copytree(GROUP1_TOP_ROOT, root)
    return root


def update_top_source(root: Path, source_html: str) -> None:
    source_path = root / "raw/source.html"
    raw = source_html.encode("utf-8")
    source_path.write_bytes(raw)
    capture_path = root / "metadata/capture.json"
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    source_hash = hashlib.sha256(raw).hexdigest()
    capture["source_snapshot_sha256"] = source_hash
    capture_path.write_text(json.dumps(capture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for relative in (
        "normalized/players.json",
        "normalized/rankings.json",
        "normalized/progress.json",
        "normalized/foreigners.json",
    ):
        path = root / relative
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["metadata"]["source_snapshot_sha256"] = source_hash
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def replace_foreign_table_row(source_html: str, player_id: int, replacement: str) -> str:
    table_start = source_html.index('<table class="taula_estil taulestemp sortable" id="tab_estran">')
    table_end = source_html.index("</table>", table_start)
    table = source_html[table_start:table_end]
    pattern = re.compile(
        rf"<tr\b[^>]*>(?:(?!</tr>).)*?href=\"(?:\.\./)?j/j{player_id}\.html\".*?</tr>",
        re.DOTALL,
    )
    updated, count = pattern.subn(lambda _: replacement, table, count=1)
    assert count == 1
    return source_html[:table_start] + updated + source_html[table_end:]


def future_capture_fixture(tmp_path: Path) -> Path:
    """Create a coherent, deliberately synthetic future TOP snapshot."""
    root = tmp_path / "synthetic-future-top"
    shutil.copytree(TOP_ROOT, root)
    capture_id = "synthetic-future-capture"
    captured_at = "2026-10-17T15:00:00+00:00"

    raw_path = root / "raw/source.html"
    raw_html = raw_path.read_bytes().decode("utf-8")
    foreign_table_start = raw_html.index('<table class="taula_estil taulestemp sortable" id="tab_estran">')
    foreign_table_end = raw_html.index("</table>", foreign_table_start)
    player_row = re.search(
        r"<tr\b[^>]*>.*?href=\"(?:\.\./)?j/j(\d+)\.html\".*?</tr>",
        raw_html[foreign_table_start:foreign_table_end],
        re.DOTALL,
    )
    assert player_row is not None
    synthetic_row = player_row.group(0).replace(player_row.group(1), "999999")
    raw_html = (
        raw_html[:foreign_table_end]
        + synthetic_row
        + raw_html[foreign_table_end:]
    )
    raw_html, heading_count = re.subn(
        r"(<h2\b[^>]*>\s*Extranjeros\s*<span\b[^>]*>)\s*(\d+)",
        lambda match: f"{match.group(1)} {int(match.group(2)) + 1}",
        raw_html,
        count=1,
    )
    assert heading_count == 1
    raw_html = raw_html.encode("utf-8") + b"\n<!-- synthetic future fixture; not a BDFutbol capture -->\n"
    raw_path.write_bytes(raw_html)
    source_hash = hashlib.sha256(raw_html).hexdigest()

    def read_json(relative_path: str) -> dict:
        return json.loads((root / relative_path).read_text(encoding="utf-8"))

    def write_json(relative_path: str, value: dict) -> None:
        (root / relative_path).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    capture = read_json("metadata/capture.json")
    players = read_json("normalized/players.json")
    rankings = read_json("normalized/rankings.json")
    progress = read_json("normalized/progress.json")
    foreigners = read_json("normalized/foreigners.json")
    validation = read_json("validation/results.json")

    related_catalog_path = tmp_path / "synthetic-related-team-catalog.json"
    related_catalog = json.loads(
        (CLASSIFICATION_ROOT / "derived-res01-20261010T102656Z/normalized/matches.json").read_text(encoding="utf-8")
    )
    related_catalog["metadata"]["source_capture_id"] = "synthetic-related-team-capture"
    related_catalog["metadata"]["source_captured_at_utc"] = captured_at
    related_catalog_path.write_text(
        json.dumps(related_catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    related_team_reference = {
        "path": str(related_catalog_path),
        "source_capture_id": "synthetic-related-team-capture",
        "source_captured_at_utc": captured_at,
        "sha256": hashlib.sha256(related_catalog_path.read_bytes()).hexdigest(),
    }

    capture["capture_id"] = capture_id
    capture["captured_at_utc"] = captured_at
    capture["source_snapshot_sha256"] = source_hash
    capture["chart_matchdays"] = [1, 2, 3, 4, 5, 6, 7]
    capture["category_source_counts"]["goals"] += 1
    capture["related_team_catalog"] = related_team_reference

    metadata_files = (players, rankings, progress, foreigners)
    for payload in metadata_files:
        payload["metadata"]["capture_id"] = capture_id
        payload["metadata"]["captured_at_utc"] = captured_at
        payload["metadata"]["source_snapshot_sha256"] = source_hash
        payload["metadata"]["related_team_catalog"] = deepcopy(related_team_reference)

    source_player = next(player for player in players["records"] if player["player_id"] == 209974)
    synthetic_player = {
        **source_player,
        "player_id": 999999,
        "display_name": "Jugador Sintético",
        "full_name": "Jugador Sintético de Prueba",
        "profile_url": "https://www.bdfutbol.com/es/j/j999999.html",
        "photo_url": "https://www.bdfutbol.com/i/m/999999.png",
        "nationality_code": "pais-sintetico",
        "nationality": "País Sintético",
        "age_years": 20,
    }
    players["records"].append(synthetic_player)

    new_ranking = {
        **next(item for item in rankings["records"] if item["category"] == "goals"),
        "rank": capture["category_source_counts"]["goals"],
        "player_id": synthetic_player["player_id"],
        "metric_value": 1,
        "graph_selected_by_default": False,
    }
    rankings["records"].append(new_ranking)
    rankings["category_source_counts"]["goals"] += 1
    capture["category_source_counts"]["goals"] = rankings["category_source_counts"]["goals"]

    matchdays = capture["chart_matchdays"]
    for series in progress["records"]:
        series["points"].append({"matchday": 7, "value": series["points"][-1]["value"]})
    progress["records"].append({
        "category": "goals",
        "player_id": synthetic_player["player_id"],
        "metric": "goals",
        "unit": "goals",
        "points": [
            {"matchday": matchday, "value": value}
            for matchday, value in zip(matchdays, [0, 0, 1, 1, 1, 1, 1], strict=True)
        ],
        "graph_selected_by_default": False,
    })
    progress["matchdays"] = matchdays

    foreign_record = {
        **synthetic_player,
        "statistics": {
            "matches_played": 1,
            "minutes_played": 90,
            "goals": 1,
            "yellow_cards": 0,
            "red_cards": 0,
        },
    }
    foreigners["records"].append(foreign_record)
    foreigners["summary"]["source_count"] += 1
    foreigners["summary"]["source_percentage"] = 19.8
    foreigners["summary"]["country_options"].append(["pais-sintetico", "País Sintético"])
    capture["foreigners_summary"] = deepcopy(foreigners["summary"])

    validation["summary"].update({
        "ranking_records": len(rankings["records"]),
        "players": len(players["records"]),
        "progress_series": len(progress["records"]),
        "progress_points": sum(len(series["points"]) for series in progress["records"]),
        "foreign_players": len(foreigners["records"]),
        "foreign_country_options": len(foreigners["summary"]["country_options"]),
        "chart_matchdays": matchdays,
    })
    validation["category_counts"] = deepcopy(rankings["category_source_counts"])
    validation["issues"] = []
    validation["valid"] = True

    for path, payload in (
        ("metadata/capture.json", capture),
        ("normalized/players.json", players),
        ("normalized/rankings.json", rankings),
        ("normalized/progress.json", progress),
        ("normalized/foreigners.json", foreigners),
        ("validation/results.json", validation),
    ):
        write_json(path, payload)
    return root


def test_top_bootstrap_has_verified_counts_nulls_and_etag() -> None:
    with TestClient(create_app(settings())) as client:
        response = client.get("/api/v1/group2/top/bootstrap")
        assert response.status_code == 200
        payload = response.json()
        assert payload["metadata"]["capture_id"] == "20261010T155145.195266Z-c5b031a6"
        assert payload["metadata"]["capture_id"] != "20261010T102656.252222Z-72f200ad"
        assert payload["metadata"]["related_team_capture_id"] == "20261010T102656.252222Z-72f200ad"
        assert payload["metadata"]["active_team_capture_id"] == payload["metadata"]["related_team_capture_id"]
        assert payload["availability"] == {
            "players": 217,
            "ranking_records": 157,
            "progress_series": 137,
            "progress_points": 822,
            "foreign_players": 101,
            "categories": {
                "goals": 107,
                "minutes": 10,
                "yellow_cards": 10,
                "red_cards": 10,
                "youngest": 10,
                "oldest": 10,
            },
            "matchdays": [1, 2, 3, 4, 5, 6],
        }
        assert len(payload["foreigners_summary"]["country_options"]) == 44
        assert payload["foreigners_summary"]["denominator_count"] is None
        foreign_player = payload["foreigners"][0]
        assert set(foreign_player) == {"player_id", "internal_player_id", "statistics"}
        assert foreign_player["internal_player_id"] is None
        assert foreign_player["statistics"]["goals"] == 0
        assert payload["rankings"][0]["matches_played"] is None
        assert response.headers["etag"].startswith('"top-player-inventory-v1-')
        assert payload["foreigners_summary"]["coverage_status"] == "complete"
        assert payload["foreigners_summary"]["available_count"] == 101
        assert payload["foreigners_summary"]["missing_count"] == 0

        stale_schema = client.get(
            "/api/v1/group2/top/bootstrap",
            headers={
                "If-None-Match": f'"{payload["metadata"]["dataset_version"]}"'
            },
        )
        assert stale_schema.status_code == 200
        assert stale_schema.json()["metadata"]["active_team_capture_id"] == payload[
            "metadata"
        ]["active_team_capture_id"]
        assert set(stale_schema.json()["foreigners"][0]) == {"player_id", "internal_player_id", "statistics"}

        cached = client.get(
            "/api/v1/group2/top/bootstrap",
            headers={"If-None-Match": response.headers["etag"]},
        )
        assert cached.status_code == 304
        assert cached.content == b""


def test_top_player_links_require_an_exact_inventory_id() -> None:
    source = load_top_dataset(settings()).bootstrap
    known_id = source.players[0].player_id
    unknown_id = max(player.player_id for player in source.players) + 999_999
    source = source.model_copy(update={
        "players": [
            source.players[0].model_copy(update={"player_id": unknown_id}),
            *source.players[1:],
        ],
        "foreigners": [
            source.foreigners[0].model_copy(update={"player_id": known_id}),
            *source.foreigners[1:],
        ],
    })

    payload, etag = project_top_player_links(source, {known_id})

    assert payload.players[0].player_id == unknown_id
    assert payload.players[0].internal_player_id is None
    assert payload.foreigners[0].internal_player_id == known_id
    assert etag.startswith('"top-player-inventory-v1-')


def test_top_load_failure_does_not_break_classification_or_results(tmp_path: Path) -> None:
    broken = tmp_path / "players.json"
    broken.write_text("not json", encoding="utf-8")
    configured = replace(settings(), top_players_path=broken)
    with TestClient(create_app(configured)) as client:
        assert client.get("/health").json()["dataset_ready"] is True
        assert client.get("/ready").status_code == 200
        assert client.get("/api/v1/group2/bootstrap").status_code == 200
        failure = client.get("/api/v1/group2/top/bootstrap")
        assert failure.status_code == 503
        assert "Destacados" in failure.json()["detail"]


def test_team_catalog_hash_mismatch_is_rejected_without_name_reconciliation(tmp_path: Path) -> None:
    catalog = TOP_ROOT / "metadata/capture.json"
    assert catalog.exists()
    copied = tmp_path / "matches.json"
    shutil.copyfile(
        CLASSIFICATION_ROOT / "derived-res01-20261010T102656Z/normalized/matches.json",
        copied,
    )
    copied.write_bytes(copied.read_bytes() + b"\n")
    configured = replace(settings(), top_team_catalog_path=copied)
    with TestClient(create_app(configured)) as client:
        assert client.get("/api/v1/group2/bootstrap").status_code == 200
        response = client.get("/api/v1/group2/top/bootstrap")
        assert response.status_code == 503
        assert "hash del catálogo" in response.json()["detail"]


def test_unknown_top_category_is_rejected_but_existing_bootstrap_stays_ready(tmp_path: Path) -> None:
    source = json.loads((TOP_ROOT / "normalized/rankings.json").read_text(encoding="utf-8"))
    source["records"][0]["category"] = "assists"
    malformed = tmp_path / "rankings.json"
    malformed.write_text(json.dumps(source), encoding="utf-8")
    configured = replace(settings(), top_rankings_path=malformed)
    with TestClient(create_app(configured)) as client:
        assert client.get("/api/v1/group2/bootstrap").status_code == 200
        assert client.get("/api/v1/group2/top/bootstrap").status_code == 503


def test_top_openapi_contract_is_independent() -> None:
    with TestClient(create_app(settings())) as client:
        paths = client.get("/openapi.json").json()["paths"]
        assert "/api/v1/group2/bootstrap" in paths
        assert "/api/v1/group2/top/bootstrap" in paths
        schema = paths["/api/v1/group2/top/bootstrap"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("/TopBootstrapResponse")


def test_dynamic_future_capture_is_accepted_and_retains_both_team_capture_ids(tmp_path: Path) -> None:
    top_root = future_capture_fixture(tmp_path)
    configured = settings_for_top(top_root)
    active = load_dataset(configured)
    new_active_id = "synthetic-classification-capture"

    top = load_top_dataset(
        configured,
        active_teams=active.bootstrap.teams,
        active_team_capture_id=new_active_id,
    ).bootstrap

    assert top.metadata.capture_id == "synthetic-future-capture"
    assert top.metadata.related_team_capture_id == "synthetic-related-team-capture"
    assert top.metadata.active_team_capture_id == new_active_id
    assert top.availability.players == 218
    assert top.availability.ranking_records == 158
    assert top.availability.progress_series == 138
    assert top.availability.progress_points == 966
    assert top.availability.foreign_players == 102
    assert top.availability.categories["goals"] == 108
    assert top.availability.matchdays == [1, 2, 3, 4, 5, 6, 7]
    assert len(top.foreigners_summary.country_options) == 45


def _foreign_evidence_html(published: int, available: int) -> bytes:
    rows = "".join(
        f'<tr><td><a href="/es/j/j{player_id}.html">Jugador</a></td></tr>'
        for player_id in range(700000, 700000 + available)
    )
    return (
        f"<h2>Extranjeros <span>{published} (12.0%)</span></h2>"
        f'<table id="tab_estran"><tr><th>Jugador</th></tr>{rows}</table>'
    ).encode("utf-8")


@pytest.mark.parametrize(
    ("published", "available", "documented", "valid"),
    [
        (60, 60, False, True),
        (61, 61, False, True),
        (65, 64, True, True),
        (60, 45, False, False),
    ],
)
def test_foreign_coverage_is_count_driven_and_requires_matching_evidence(
    published: int, available: int, documented: bool, valid: bool
) -> None:
    warnings = []
    if documented:
        warnings.append(
            f"#tab_estran expone {available} registros, pero el encabezado publica {published}; "
            "no se ha completado la fila ausente."
        )
    evidence_data = {
        "validation": {
            "valid": True,
            "issues": [],
            "warnings": warnings,
            "summary": {"foreign_players": available},
        }
    }
    summary = {"source_count": published}
    player_ids = set(range(700000, 700000 + available))

    if valid:
        _validate_foreigners_coverage(
            evidence_data, summary, _foreign_evidence_html(published, available), player_ids
        )
    else:
        with pytest.raises(TopDatasetLoadError, match="diferencia de extranjeros"):
            _validate_foreigners_coverage(
                evidence_data, summary, _foreign_evidence_html(published, available), player_ids
            )


def test_group1_current_capture_keeps_the_documented_conflict_and_original_records() -> None:
    bundle = load_top_dataset(settings_for_group1_top())
    top = bundle.bootstrap
    player = next(item for item in top.players if item.player_id == 304291)
    assert player.team_id is None
    assert len(top.affiliation_conflicts) == 1
    assert top.affiliation_conflicts[0].player_id == player.player_id
    assert any(item.player_id == player.player_id for item in top.rankings)
    assert any(item.player_id == player.player_id for item in top.progress)
    assert any(item.player_id == player.player_id for item in top.foreigners)
    assert top.availability.foreign_players == 59
    assert top.foreigners_summary.source_count == 60
    assert top.foreigners_summary.available_count == 59
    assert top.foreigners_summary.missing_count == 1
    assert top.foreigners_summary.coverage_status == "documented_discrepancy"


def test_future_group1_capture_without_old_affiliation_conflict_is_valid(tmp_path: Path) -> None:
    root = group1_top_copy(tmp_path)
    teams_data = json.loads(GROUP1_TEAMS_PATH.read_text(encoding="utf-8"))
    team = next(item for item in teams_data["teams"] if item["team_id"] == 58)
    players = json.loads((root / "normalized/players.json").read_text(encoding="utf-8"))
    foreigners = json.loads((root / "normalized/foreigners.json").read_text(encoding="utf-8"))
    for record in players["records"]:
        if record["player_id"] == 304291:
            record.update(team_id=58, team_name=team["name"], team_url=team["team_url"], crest_url=team["crest_url"])
    for record in foreigners["records"]:
        if record["player_id"] == 304291:
            record.update(team_id=58, team_name=team["name"], team_url=team["team_url"], crest_url=team["crest_url"])
    for relative, payload in (
        ("normalized/players.json", players),
        ("normalized/foreigners.json", foreigners),
    ):
        (root / relative).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    capture = json.loads((root / "metadata/capture.json").read_text(encoding="utf-8"))
    capture["affiliation_conflicts"] = []
    (root / "metadata/capture.json").write_text(json.dumps(capture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    validation_path = root / "validation/results.json"
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    validation["summary"]["affiliation_conflicts"] = 0
    validation["warnings"] = [
        warning for warning in validation["warnings"] if not warning.startswith("Afiliación de equipo ambigua para player_id=")
    ]
    validation_path.write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    source_html = (root / "raw/source.html").read_text(encoding="utf-8")
    row_match = re.search(
        r"<tr\b[^>]*>(?:(?!</tr>).)*?href=\"(?:\.\./)?j/j304291\.html\".*?</tr>",
        source_html,
        re.DOTALL,
    )
    assert row_match is not None
    updated_row = row_match.group(0).replace("13l.png", "58.png")
    source_html = replace_foreign_table_row(source_html, 304291, updated_row)
    update_top_source(root, source_html)

    top = load_top_dataset(settings_for_group1_top(root)).bootstrap
    player = next(item for item in top.players if item.player_id == 304291)
    assert player.team_id == 58
    assert top.affiliation_conflicts == []
    assert not any("304291" in warning for warning in top.warnings)
    assert any(item.player_id == player.player_id for item in top.rankings)
    assert any(item.player_id == player.player_id for item in top.progress)
    assert any(item.player_id == player.player_id for item in top.foreigners)


def test_future_capture_can_document_a_player_without_published_affiliation(tmp_path: Path) -> None:
    root = group1_top_copy(tmp_path)
    capture_path = root / "metadata/capture.json"
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    capture["affiliation_conflicts"] = []
    capture["affiliation_absences"] = [{
        "player_id": 304291,
        "source_records": ["DESTACATS_JS.LG", "table#tab_estran"],
        "reason": "not_published",
    }]
    capture_path.write_text(json.dumps(capture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    validation_path = root / "validation/results.json"
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    validation["summary"]["affiliation_conflicts"] = 0
    validation["summary"]["affiliation_absences"] = 1
    validation["warnings"] = [
        warning for warning in validation["warnings"] if not warning.startswith("Afiliación de equipo ambigua para player_id=")
    ]
    validation["warnings"].append(
        "Afiliación de equipo no publicada para player_id=304291; se conserva como null en el catálogo y la ausencia está respaldada por las fuentes indicadas en affiliation_absences."
    )
    validation_path.write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    source_html = (root / "raw/source.html").read_text(encoding="utf-8")
    script = re.search(r"const\s+DESTACATS_JS\s*=\s*(\{.*?\})\s*;", source_html, re.DOTALL)
    assert script is not None
    source_object = json.loads(script.group(1))
    source_row = next(row for row in source_object["LG"] if row[1] == 304291)
    source_row[5] = ""
    source_html = source_html[:script.start(1)] + json.dumps(source_object, ensure_ascii=False) + source_html[script.end(1):]
    table_start = source_html.index('<table class="taula_estil taulestemp sortable" id="tab_estran">')
    table_end = source_html.index("</table>", table_start)
    foreign_row = re.search(
        r"<tr\b[^>]*>(?:(?!</tr>).)*?href=\"(?:\.\./)?j/j304291\.html\".*?</tr>",
        source_html[table_start:table_end],
        re.DOTALL,
    )
    assert foreign_row is not None
    updated_row = re.sub(r"/eg/", "/clubs-unassigned/", foreign_row.group(0))
    source_html = replace_foreign_table_row(source_html, 304291, updated_row)
    update_top_source(root, source_html)

    top = load_top_dataset(settings_for_group1_top(root)).bootstrap
    assert top.affiliation_conflicts == []
    assert len(top.affiliation_absences) == 1
    assert top.affiliation_absences[0].player_id == 304291
    assert top.affiliation_absences[0].reason == "not_published"
    assert next(player for player in top.players if player.player_id == 304291).team_id is None


def test_future_capture_with_two_source_verified_affiliation_conflicts_is_valid(tmp_path: Path) -> None:
    root = group1_top_copy(tmp_path)
    new_player_id = 999991
    player_path = root / "normalized/players.json"
    players = json.loads(player_path.read_text(encoding="utf-8"))
    source_player = next(item for item in players["records"] if item["player_id"] == 304291)
    synthetic_player = {
        **source_player,
        "player_id": new_player_id,
        "display_name": "Jugador Sintético",
        "full_name": "Jugador Sintético de Prueba",
        "profile_url": f"https://www.bdfutbol.com/es/j/j{new_player_id}.html",
        "photo_url": f"https://www.bdfutbol.com/i/m/{new_player_id}.png",
    }
    players["records"].append(synthetic_player)
    foreigners_path = root / "normalized/foreigners.json"
    foreigners = json.loads(foreigners_path.read_text(encoding="utf-8"))
    original_foreigner = next(item for item in foreigners["records"] if item["player_id"] == 304291)
    foreigners["records"].append({**synthetic_player, "statistics": original_foreigner["statistics"]})
    foreigners["summary"]["source_count"] = 60

    capture_path = root / "metadata/capture.json"
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    second_conflict = deepcopy(capture["affiliation_conflicts"][0])
    second_conflict["player_id"] = new_player_id
    capture["affiliation_conflicts"].append(second_conflict)
    capture["foreigners_summary"] = deepcopy(foreigners["summary"])

    validation_path = root / "validation/results.json"
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    validation["summary"]["players"] = len(players["records"])
    validation["summary"]["foreign_players"] = 60
    validation["summary"]["affiliation_conflicts"] = 2
    validation["warnings"] = [
        warning for warning in validation["warnings"] if not warning.startswith("#tab_estran expone ")
    ]
    validation["warnings"].append(
        "Afiliación de equipo ambigua para player_id=999991; se conserva como null en el catálogo y las fuentes/IDs están en affiliation_conflicts."
    )

    source_path = root / "raw/source.html"
    source_html = source_path.read_text(encoding="utf-8")
    script = re.search(r"const\s+DESTACATS_JS\s*=\s*(\{.*?\})\s*;", source_html, re.DOTALL)
    assert script is not None
    source_object = json.loads(script.group(1))
    source_row = next(row for row in source_object["LG"] if row[1] == 304291)
    second_source_row = list(source_row)
    second_source_row[1] = new_player_id
    source_object["LG"].append(second_source_row)
    source_html = source_html[:script.start(1)] + json.dumps(source_object, ensure_ascii=False) + source_html[script.end(1):]
    table_start = source_html.index('<table class="taula_estil taulestemp sortable" id="tab_estran">')
    table_end = source_html.index("</table>", table_start)
    table = source_html[table_start:table_end]
    foreign_row = re.search(
        r"<tr\b[^>]*>(?:(?!</tr>).)*?href=\"(?:\.\./)?j/j304291\.html\".*?</tr>",
        table,
        re.DOTALL,
    )
    assert foreign_row is not None
    source_html = source_html[:table_end] + foreign_row.group(0).replace("304291", str(new_player_id)) + source_html[table_end:]

    for relative, payload in (
        ("normalized/players.json", players),
        ("normalized/foreigners.json", foreigners),
        ("metadata/capture.json", capture),
        ("validation/results.json", validation),
    ):
        (root / relative).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    update_top_source(root, source_html)

    top = load_top_dataset(settings_for_group1_top(root)).bootstrap
    assert {item.player_id for item in top.affiliation_conflicts} == {304291, new_player_id}
    assert len([item for item in top.players if item.team_id is None]) == 2
    assert any(item.player_id == 304291 for item in top.rankings)
    assert any(item.player_id == 304291 for item in top.progress)
    assert {item.player_id for item in top.foreigners} >= {304291, new_player_id}
    assert top.availability.foreign_players == 60
    assert top.foreigners_summary.source_count == 60


@pytest.mark.parametrize(
    "invalid_case",
    ["unknown_team", "missing_source", "unexplained_null", "duplicate_conflict", "resolved_team", "warning_mismatch", "absence_conflicts_source"],
)
def test_unverified_affiliation_nulls_and_conflicts_are_rejected(
    tmp_path: Path, invalid_case: str
) -> None:
    root = group1_top_copy(tmp_path)
    capture_path = root / "metadata/capture.json"
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    validation_path = root / "validation/results.json"
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    if invalid_case == "unknown_team":
        capture["affiliation_conflicts"][0]["affiliations"][0].update(
            team_id=999999, team_name="Equipo inexistente"
        )
    elif invalid_case == "missing_source":
        capture["affiliation_conflicts"][0]["affiliations"][0]["source_records"] = []
    elif invalid_case == "duplicate_conflict":
        capture["affiliation_conflicts"].append(deepcopy(capture["affiliation_conflicts"][0]))
    elif invalid_case == "resolved_team":
        teams_data = json.loads(GROUP1_TEAMS_PATH.read_text(encoding="utf-8"))
        team = next(item for item in teams_data["teams"] if item["team_id"] == 58)
        for relative in ("normalized/players.json", "normalized/foreigners.json"):
            path = root / relative
            payload = json.loads(path.read_text(encoding="utf-8"))
            for record in payload["records"]:
                if record["player_id"] == 304291:
                    record.update(team_id=58, team_name=team["name"], team_url=team["team_url"], crest_url=team["crest_url"])
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif invalid_case == "warning_mismatch":
        validation["warnings"] = [
            warning for warning in validation["warnings"] if not warning.startswith("Afiliación de equipo ambigua para player_id=")
        ]
        validation["warnings"].append("Afiliación de equipo ambigua para player_id=999999; advertencia no respaldada.")
    elif invalid_case == "absence_conflicts_source":
        capture["affiliation_conflicts"] = []
        capture["affiliation_absences"] = [{
            "player_id": 304291,
            "source_records": ["DESTACATS_JS.LG", "table#tab_estran"],
            "reason": "not_published",
        }]
        validation["summary"]["affiliation_conflicts"] = 0
        validation["summary"]["affiliation_absences"] = 1
        validation["warnings"] = [
            warning for warning in validation["warnings"] if not warning.startswith("Afiliación de equipo ambigua para player_id=")
        ]
        validation["warnings"].append(
            "Afiliación de equipo no publicada para player_id=304291; se conserva como null en el catálogo y la ausencia está respaldada por las fuentes indicadas en affiliation_absences."
        )
    else:
        capture["affiliation_conflicts"] = []
        validation["summary"]["affiliation_conflicts"] = 0
        validation["warnings"] = [
            warning for warning in validation["warnings"] if not warning.startswith("Afiliación de equipo ambigua para player_id=")
        ]
    capture_path.write_text(json.dumps(capture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    validation_path.write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(TopDatasetLoadError):
        load_top_dataset(settings_for_group1_top(root))


def test_incompatible_active_team_identity_is_rejected_by_id(tmp_path: Path) -> None:
    configured = settings()
    active = load_dataset(configured)
    team_to_change = active.bootstrap.teams[0]
    conflicting_teams = [
        team.model_copy(update={"name": "Otro club"}) if team.team_id == team_to_change.team_id else team
        for team in active.bootstrap.teams
    ]

    with pytest.raises(TopDatasetLoadError, match="nombre o URL incompatibles"):
        load_top_dataset(
            configured,
            active_teams=conflicting_teams,
            active_team_capture_id="different-capture-id",
        )


@pytest.mark.parametrize("corruption", ["false_count", "orphan_player", "series_value"])
def test_future_capture_inconsistencies_are_rejected_without_breaking_other_sections(
    tmp_path: Path, corruption: str
) -> None:
    top_root = future_capture_fixture(tmp_path)
    configured = settings_for_top(top_root)

    if corruption == "false_count":
        validation_path = top_root / "validation/results.json"
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
        validation["summary"]["players"] -= 1
        validation_path.write_text(json.dumps(validation), encoding="utf-8")
    elif corruption == "orphan_player":
        players_path = top_root / "normalized/players.json"
        players = json.loads(players_path.read_text(encoding="utf-8"))
        players["records"] = [player for player in players["records"] if player["player_id"] != 999999]
        players_path.write_text(json.dumps(players), encoding="utf-8")
    else:
        progress_path = top_root / "normalized/progress.json"
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        progress["records"][-1]["points"][-1]["value"] = 2
        progress_path.write_text(json.dumps(progress), encoding="utf-8")

    with TestClient(create_app(configured)) as client:
        assert client.get("/api/v1/group2/bootstrap").status_code == 200
        assert client.get("/api/v1/group2/top/bootstrap").status_code == 503
