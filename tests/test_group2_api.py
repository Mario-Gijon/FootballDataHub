"""Offline contract and startup tests for the standalone Group II API."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from football_data_hub_api.config import ApiSettings
from football_data_hub_api.config import PROJECT_ROOT
from football_data_hub_api.main import create_app

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/exports/bdfutbol/group2_classification"
CAPTURE_DIRECTORY = DATA_ROOT / "20261010T102656.252222Z-72f200ad"
MATCHES_FILE = (
    DATA_ROOT
    / "derived-res01-20261010T102656Z/normalized/matches.json"
)
MATCHES_V1_FILE = DATA_ROOT / "derived-clas01b-20261010T102656Z/normalized/matches.json"


def settings_for(
    matches: Path = MATCHES_FILE,
    classification: Path = CAPTURE_DIRECTORY / "normalized/classification.json",
    progress: Path = CAPTURE_DIRECTORY / "normalized/progress.json",
    metadata: Path = CAPTURE_DIRECTORY / "metadata/capture.json",
) -> ApiSettings:
    return ApiSettings(
        matches_path=matches,
        classification_path=classification,
        progress_path=progress,
        capture_metadata_path=metadata,
    )


def test_settings_support_project_relative_roots_and_absolute_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data_root = tmp_path / "configured-data"
    absolute_matches = tmp_path / "absolute-matches.json"
    monkeypatch.setenv("FDH_DATA_ROOT", str(data_root))
    monkeypatch.setenv("FDH_GROUP2_MATCHES", str(absolute_matches))
    monkeypatch.setenv("FDH_GROUP2_CLASSIFICATION", "capture/standings.json")
    monkeypatch.setenv("FDH_GROUP2_PROGRESS", "capture/progress.json")
    monkeypatch.setenv("FDH_GROUP2_CAPTURE_METADATA", "capture/metadata.json")
    monkeypatch.setenv("FDH_CORS_ORIGINS", "https://dashboard.example")

    configured = ApiSettings.from_env()
    assert configured.matches_path == absolute_matches
    assert configured.classification_path == data_root / "capture/standings.json"
    assert configured.progress_path == data_root / "capture/progress.json"
    assert configured.capture_metadata_path == data_root / "capture/metadata.json"
    assert configured.cors_origins == ("https://dashboard.example",)
    assert not str(configured.matches_path).startswith(str(PROJECT_ROOT / "home"))


def test_default_matches_dataset_is_the_res01_enriched_export(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in (
        "FDH_DATA_ROOT",
        "FDH_GROUP2_MATCHES",
        "FDH_GROUP2_CLASSIFICATION",
        "FDH_GROUP2_PROGRESS",
        "FDH_GROUP2_CAPTURE_METADATA",
    ):
        monkeypatch.delenv(variable, raising=False)
    configured = ApiSettings.from_env()
    assert configured.matches_path == (
        DATA_ROOT / "derived-res01-20261010T102656Z/normalized/matches.json"
    )


@pytest.fixture
def client() -> TestClient:
    with TestClient(create_app(settings_for())) as test_client:
        yield test_client


def test_health_readiness_metadata_and_bootstrap_contract(client: TestClient) -> None:
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "dataset_ready": True}

    readiness = client.get("/ready")
    assert readiness.status_code == 200
    assert readiness.json()["capture_id"] == "20261010T102656.252222Z-72f200ad"

    metadata_response = client.get("/api/v1/group2/metadata")
    assert metadata_response.status_code == 200
    metadata = metadata_response.json()
    assert metadata["competition"] == "Primera Federación"
    assert metadata["season"] == "2026-27"
    assert metadata["group"] == "II"
    assert metadata["team_count"] == 20
    assert metadata["scheduled_matchdays"] == list(range(1, 39))
    assert metadata["last_matchday_with_results"] == 6
    assert metadata["captured_at"] == "2026-10-10T10:26:56.252397Z"
    assert metadata["availability"]["matches"] == 380
    assert metadata["availability"]["played_matches"] == 59
    assert metadata["availability"]["progress_records"] == 120
    assert metadata["progress_context"]["classification_type"] == "general"
    assert metadata["progress_context"]["available_through_matchday"] == 6

    bootstrap_response = client.get("/api/v1/group2/bootstrap")
    assert bootstrap_response.status_code == 200
    assert bootstrap_response.headers["etag"] == f'"{metadata["dataset_version"]}"'
    bootstrap = bootstrap_response.json()
    assert len(bootstrap["teams"]) == 20
    assert len(bootstrap["matches"]) == 380
    assert len(bootstrap["progress"]) == 120
    assert len(bootstrap["published_standings"]["rows"]) == 20
    assert bootstrap["published_standings"]["context"]["matchday"] == 6
    assert bootstrap["published_standings"]["context"]["classification_type"] == "general"
    assert {team["team_id"] for team in bootstrap["teams"]} == {
        row["team_id"] for row in bootstrap["published_standings"]["rows"]
    }
    assert all(match["matchday_date"].startswith("202") for match in bootstrap["matches"])
    assert all(
        "source_fields" not in match and "source_references" not in match
        for match in bootstrap["matches"]
    )
    enriched = next(match for match in bootstrap["matches"] if match["status"] == "played")
    assert enriched["source_match_url"].startswith("https://www.bdfutbol.com/")
    assert enriched["stadium_name"]
    assert enriched["stadium_url"].startswith("https://www.bdfutbol.com/")
    assert enriched["referee_name"]
    assert enriched["referee_url"].startswith("https://www.bdfutbol.com/")


def test_null_values_and_published_table_context_are_preserved(client: TestClient) -> None:
    bootstrap = client.get("/api/v1/group2/bootstrap").json()
    unplayed = next(match for match in bootstrap["matches"] if match["status"] == "unplayed")
    assert unplayed["home_goals"] is None
    assert unplayed["away_goals"] is None
    assert unplayed["home_yellow_cards"] is None
    assert unplayed["unplayed_state"] in {
        "scheduled",
        "result_unavailable_at_capture",
        "unknown",
    }
    assert any(
        row["points"] is None
        or row["position"] is None
        or row["goals_for"] is None
        or row["goals_against"] is None
        for row in bootstrap["progress"]
    )
    assert all(
        match[key] is None
        for match in bootstrap["matches"]
        if match["status"] == "unplayed"
        for key in (
            "source_match_url",
            "stadium_id",
            "stadium_name",
            "stadium_url",
            "referee_id",
            "referee_name",
            "referee_url",
        )
    )
    assert all(
        row["sports_zone"] in {"direct_promotion", "promotion", "stay", "relegation", None}
        for row in bootstrap["published_standings"]["rows"]
    )


def test_bootstrap_supports_conditional_etag(client: TestClient) -> None:
    first = client.get("/api/v1/group2/bootstrap")
    second = client.get(
        "/api/v1/group2/bootstrap", headers={"If-None-Match": first.headers["etag"]}
    )
    assert first.status_code == 200
    assert second.status_code == 304
    assert second.content == b""


def test_openapi_documents_the_public_contract(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    assert "/health" in paths
    assert "/ready" in paths
    assert "/api/v1/group2/metadata" in paths
    assert "/api/v1/group2/bootstrap" in paths
    bootstrap_schema = paths["/api/v1/group2/bootstrap"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert bootstrap_schema["$ref"].endswith("/BootstrapResponse")


def test_requests_serve_the_in_memory_dataset_without_reloading(client: TestClient, monkeypatch) -> None:
    import football_data_hub_api.main as api_main

    def fail_reload(*_args, **_kwargs):
        raise AssertionError("el dataset no debe recargarse durante una petición")

    monkeypatch.setattr(api_main, "load_dataset", fail_reload)
    assert client.get("/api/v1/group2/bootstrap").status_code == 200
    assert client.get("/api/v1/group2/metadata").status_code == 200


def test_mixed_capture_is_not_ready_and_data_routes_return_503(tmp_path: Path) -> None:
    capture_copy = tmp_path / "capture.json"
    shutil.copyfile(CAPTURE_DIRECTORY / "metadata/capture.json", capture_copy)
    capture = json.loads(capture_copy.read_text(encoding="utf-8"))
    capture["capture_id"] = "another-capture"
    capture_copy.write_text(json.dumps(capture), encoding="utf-8")

    with TestClient(create_app(settings_for(metadata=capture_copy))) as invalid_client:
        assert invalid_client.get("/health").json() == {
            "status": "ok",
            "dataset_ready": False,
        }
        assert invalid_client.get("/ready").status_code == 503
        assert invalid_client.get("/api/v1/group2/metadata").status_code == 503
        assert invalid_client.get("/api/v1/group2/bootstrap").status_code == 503


def test_corrupt_json_is_not_served(tmp_path: Path) -> None:
    broken_matches = tmp_path / "matches.json"
    broken_matches.write_text("{not json", encoding="utf-8")

    with TestClient(create_app(settings_for(matches=broken_matches))) as invalid_client:
        assert invalid_client.get("/health").json()["dataset_ready"] is False
        assert invalid_client.get("/api/v1/group2/bootstrap").status_code == 503


def test_matches_v1_remains_compatible_and_missing_enrichment_is_null() -> None:
    source_matches = json.loads(MATCHES_V1_FILE.read_text(encoding="utf-8"))["matches"]
    with TestClient(create_app(settings_for(matches=MATCHES_V1_FILE))) as legacy_client:
        response = legacy_client.get("/api/v1/group2/bootstrap")
    assert response.status_code == 200
    matches = response.json()["matches"]
    assert len(matches) == 380
    optional_fields = (
            "source_match_url",
            "stadium_id",
            "stadium_name",
            "stadium_url",
            "referee_id",
            "referee_name",
            "referee_url",
    )
    for source_match, public_match in zip(source_matches, matches, strict=True):
        assert all(public_match[key] == source_match.get(key) for key in optional_fields)


def test_matches_v2_requires_explicit_enrichment_fields(tmp_path: Path) -> None:
    copied = tmp_path / "matches-v2.json"
    payload = json.loads(MATCHES_FILE.read_text(encoding="utf-8"))
    del payload["matches"][0]["stadium_name"]
    copied.write_text(json.dumps(payload), encoding="utf-8")
    with TestClient(create_app(settings_for(matches=copied))) as invalid_client:
        assert invalid_client.get("/health").json()["dataset_ready"] is False
        assert invalid_client.get("/api/v1/group2/bootstrap").status_code == 503


def test_all_public_ids_resolve_and_records_preserve_nullable_shapes(client: TestClient) -> None:
    data = client.get("/api/v1/group2/bootstrap").json()
    team_ids = {team["team_id"] for team in data["teams"]}
    for match in data["matches"]:
        assert match["home_team_id"] in team_ids
        assert match["away_team_id"] in team_ids
    for record in data["progress"]:
        assert record["team_id"] in team_ids
        assert isinstance(record["matchday"], int)
    for row in data["published_standings"]["rows"]:
        assert row["team_id"] in team_ids
