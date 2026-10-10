"""Strict API contract and isolation tests for the independent TOP capture."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from football_data_hub_api.config import ApiSettings, PROJECT_ROOT
from football_data_hub_api.main import create_app

TOP_ROOT = PROJECT_ROOT / "data/exports/bdfutbol/group2_top/20261010T155145.195266Z-c5b031a6"
CLASSIFICATION_ROOT = PROJECT_ROOT / "data/exports/bdfutbol/group2_classification"


def settings() -> ApiSettings:
    return ApiSettings(
        matches_path=CLASSIFICATION_ROOT / "derived-res01-20261010T102656Z/normalized/matches.json",
        classification_path=CLASSIFICATION_ROOT / "20261010T102656.252222Z-72f200ad/normalized/classification.json",
        progress_path=CLASSIFICATION_ROOT / "20261010T102656.252222Z-72f200ad/normalized/progress.json",
        capture_metadata_path=CLASSIFICATION_ROOT / "20261010T102656.252222Z-72f200ad/metadata/capture.json",
    )


def test_top_bootstrap_has_verified_counts_nulls_and_etag() -> None:
    with TestClient(create_app(settings())) as client:
        response = client.get("/api/v1/group2/top/bootstrap")
        assert response.status_code == 200
        payload = response.json()
        assert payload["metadata"]["capture_id"] == "20261010T155145.195266Z-c5b031a6"
        assert payload["metadata"]["capture_id"] != "20261010T102656.252222Z-72f200ad"
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
        assert foreign_player["statistics"]["goals"] == 0
        assert payload["rankings"][0]["matches_played"] is None
        assert response.headers["etag"]

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
