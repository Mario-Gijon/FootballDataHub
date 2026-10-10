"""API integration and provenance checks for the STAT-01 capture."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from football_data_hub_api.config import ApiSettings, PROJECT_ROOT
from football_data_hub_api.main import create_app
from football_data_hub_api.statistics_dataset import (
    StatisticsDatasetLoadError,
    load_statistics_dataset,
)
from football_data_hub_api.dataset import load_dataset

STATISTICS_ROOT = PROJECT_ROOT / "data/exports/bdfutbol/group2_statistics/20261010T182210.859321Z-28543363"
CLASSIFICATION_ROOT = PROJECT_ROOT / "data/exports/bdfutbol/group2_classification"


def settings() -> ApiSettings:
    return ApiSettings(
        matches_path=CLASSIFICATION_ROOT / "derived-res01-20261010T102656Z/normalized/matches.json",
        classification_path=CLASSIFICATION_ROOT / "20261010T102656.252222Z-72f200ad/normalized/classification.json",
        progress_path=CLASSIFICATION_ROOT / "20261010T102656.252222Z-72f200ad/normalized/progress.json",
        capture_metadata_path=CLASSIFICATION_ROOT / "20261010T102656.252222Z-72f200ad/metadata/capture.json",
        statistics_root=STATISTICS_ROOT,
    )


def copied_capture(tmp_path: Path) -> Path:
    root = tmp_path / "statistics-capture"
    shutil.copytree(STATISTICS_ROOT, root)
    return root


def read_json(root: Path, relative: str) -> dict[str, Any]:
    return json.loads((root / relative).read_text(encoding="utf-8"))


def write_json(root: Path, relative: str, value: dict[str, Any]) -> None:
    (root / relative).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def future_capture_with_changed_penalties(root: Path) -> None:
    """Build an isolated future capture whose exclusive totals changed."""
    capture_id = "synthetic-statistics-capture"
    captured_at = "2026-10-17T18:22:10+00:00"
    raw_html = root / "raw/source.html"
    raw_html.write_bytes(raw_html.read_bytes() + b"\n<!-- synthetic fixture -->\n")
    capture = read_json(root, "metadata/capture.json")
    derived = read_json(root, "normalized/derived_statistics.json")
    exclusive = read_json(root, "normalized/exclusive_statistics.json")
    access = read_json(root, "raw/access.json")
    reconciliation = read_json(root, "validation/reconciliation.json")

    source_hash = hashlib.sha256(raw_html.read_bytes()).hexdigest()
    capture.update({
        "capture_id": capture_id,
        "captured_at_utc": captured_at,
        "source_html_sha256": source_hash,
    })
    exclusive.update({"capture_id": capture_id, "captured_at_utc": captured_at})
    exclusive["items"]["penalties"].update({
        "penalties_awarded": 25,
        "penalties_scored": 22,
        "penalties_missed": 3,
    })
    access.update({
        "capture_id": capture_id,
        "captured_at_utc": captured_at,
        "source_snapshot_sha256": source_hash,
    })
    reconciliation.update({
        "statistics_capture_id": capture_id,
        "statistics_captured_at_utc": captured_at,
    })
    reconciliation["exclusive_penalties"]["source"].update({
        "penalties_awarded": 25,
        "penalties_scored": 22,
        "penalties_missed": 3,
    })
    for path, payload in (
        ("metadata/capture.json", capture),
        ("normalized/derived_statistics.json", derived),
        ("normalized/exclusive_statistics.json", exclusive),
        ("raw/access.json", access),
        ("validation/reconciliation.json", reconciliation),
    ):
        write_json(root, path, payload)


@pytest.fixture
def client() -> TestClient:
    with TestClient(create_app(settings())) as test_client:
        yield test_client


def test_statistics_bootstrap_exposes_verified_data_and_capture_provenance(client: TestClient) -> None:
    response = client.get("/api/v1/group2/statistics/bootstrap")
    assert response.status_code == 200
    data = response.json()
    assert data["metadata"]["capture_id"] == "20261010T182210.859321Z-28543363"
    assert data["metadata"]["active_match_capture_id"] == "20261010T102656.252222Z-72f200ad"
    assert data["metadata"]["captured_at"] != data["metadata"]["match_dataset_captured_at"]
    assert data["statistics"]["team_count"] == 20
    assert data["statistics"]["played_matches"] == 59
    assert data["statistics"]["goals"] == 155
    assert data["statistics"]["rounds"][4]["goals"] == 21
    assert data["statistics"]["rounds"][4]["played_matches"] == 9
    assert data["statistics"]["rounds"][6]["goals"] is None
    assert data["penalties"]["penalties_awarded"] == 24
    assert data["penalties"]["penalties_scored"] == 21
    assert data["penalties"]["penalties_missed"] == 3
    assert len(data["records"]["match_records"][1]["matches"]) == 2
    winless = [row for row in data["records"]["streaks"] if row["kind"] == "winless" and row["match_count"] == 6]
    assert {row["team_id"] for row in winless} == {204, 488}
    assert any(item["matchday"] == 5 and item["statistic"] == "goals" and item["published"] == 19 and item["calculated"] == 21 for item in data["reconciliation"]["round_series"])
    assert response.headers["etag"].startswith('"statistics-v1-')


def test_statistics_endpoint_supports_versioned_conditional_etag(client: TestClient) -> None:
    first = client.get("/api/v1/group2/statistics/bootstrap")
    cached = client.get(
        "/api/v1/group2/statistics/bootstrap",
        headers={"If-None-Match": first.headers["etag"]},
    )
    assert cached.status_code == 304
    assert cached.content == b""


def test_statistics_integrity_rejects_tampered_source_snapshot(tmp_path: Path) -> None:
    root = copied_capture(tmp_path)
    raw_html = root / "raw/source.html"
    raw_html.write_bytes(raw_html.read_bytes() + b"<!-- tampered -->")
    configured = replace(settings(), statistics_root=root)
    with pytest.raises(StatisticsDatasetLoadError, match="hash del HTML"):
        load_statistics_dataset(configured, load_dataset(configured))


def test_statistics_rejects_results_capture_with_different_hash(tmp_path: Path) -> None:
    root = copied_capture(tmp_path)
    capture = read_json(root, "metadata/capture.json")
    derived = read_json(root, "normalized/derived_statistics.json")
    capture["match_dataset"]["sha256"] = "0" * 64
    derived["match_dataset"]["sha256"] = "0" * 64
    write_json(root, "metadata/capture.json", capture)
    write_json(root, "normalized/derived_statistics.json", derived)
    configured = replace(settings(), statistics_root=root)
    with pytest.raises(StatisticsDatasetLoadError, match="versión distinta de Resultados"):
        load_statistics_dataset(configured, load_dataset(configured))


def test_statistics_accepts_a_future_capture_with_different_source_totals(tmp_path: Path) -> None:
    root = copied_capture(tmp_path)
    future_capture_with_changed_penalties(root)
    bundle = load_statistics_dataset(replace(settings(), statistics_root=root), load_dataset(settings()))
    assert bundle.bootstrap.metadata.capture_id == "synthetic-statistics-capture"
    assert bundle.bootstrap.penalties.penalties_awarded == 25
    assert bundle.bootstrap.penalties.penalties_scored == 22


def test_statistics_failure_is_isolated_from_other_endpoints(tmp_path: Path) -> None:
    missing_root = tmp_path / "missing-statistics"
    missing_root.mkdir()
    configured = replace(settings(), statistics_root=missing_root)
    with TestClient(create_app(configured)) as isolated_client:
        assert isolated_client.get("/api/v1/group2/bootstrap").status_code == 200
        assert isolated_client.get("/api/v1/group2/top/bootstrap").status_code == 200
        assert isolated_client.get("/api/v1/group2/referees/bootstrap").status_code == 200
        response = isolated_client.get("/api/v1/group2/statistics/bootstrap")
        assert response.status_code == 503
        assert "Estadísticas" in response.json()["detail"]


def test_statistics_endpoint_is_in_openapi(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert "/api/v1/group2/statistics/bootstrap" in response.json()["paths"]
