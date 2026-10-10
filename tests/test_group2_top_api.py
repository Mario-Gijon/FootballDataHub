"""Strict API contract and isolation tests for the independent TOP capture."""

from __future__ import annotations

import json
import hashlib
import shutil
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from football_data_hub_api.config import ApiSettings, PROJECT_ROOT
from football_data_hub_api.dataset import load_dataset
from football_data_hub_api.main import create_app
from football_data_hub_api.top_dataset import TopDatasetLoadError, load_top_dataset

TOP_ROOT = PROJECT_ROOT / "data/exports/bdfutbol/group2_top/20261010T155145.195266Z-c5b031a6"
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


def future_capture_fixture(tmp_path: Path) -> Path:
    """Create a coherent, deliberately synthetic future TOP snapshot."""
    root = tmp_path / "synthetic-future-top"
    shutil.copytree(TOP_ROOT, root)
    capture_id = "synthetic-future-capture"
    captured_at = "2026-10-17T15:00:00+00:00"

    raw_path = root / "raw/source.html"
    raw_html = raw_path.read_bytes() + b"\n<!-- synthetic future fixture; not a BDFutbol capture -->\n"
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
        assert set(foreign_player) == {"player_id", "statistics"}
        assert foreign_player["statistics"]["goals"] == 0
        assert payload["rankings"][0]["matches_played"] is None
        assert response.headers["etag"] == (
            f'"top-v2-{payload["metadata"]["dataset_version"]}"'
        )

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
        assert set(stale_schema.json()["foreigners"][0]) == {"player_id", "statistics"}

        cached = client.get(
            "/api/v1/group2/top/bootstrap",
            headers={"If-None-Match": response.headers["etag"]},
        )
        assert cached.status_code == 304
        assert cached.content == b""


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
