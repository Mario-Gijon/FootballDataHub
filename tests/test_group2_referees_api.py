"""Contract, provenance, and isolation tests for the REF-01 API capture."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from football_data_hub_api.config import ApiSettings, PROJECT_ROOT
from football_data_hub_api.main import create_app
from football_data_hub_api.referee_dataset import (
    RefereeDatasetLoadError,
    load_referee_dataset,
)

REFEREES_ROOT = PROJECT_ROOT / "data/exports/bdfutbol/group2_referees/20261010T171227.617128Z-4cfe71bc"
CLASSIFICATION_ROOT = PROJECT_ROOT / "data/exports/bdfutbol/group2_classification"
GROUP1_CAPTURE_ROOT = PROJECT_ROOT / "data/exports/bdfutbol/group1_classification/20261010T202500.293648Z-b770724f"


def settings() -> ApiSettings:
    return ApiSettings(
        matches_path=CLASSIFICATION_ROOT / "derived-res01-20261010T102656Z/normalized/matches.json",
        classification_path=CLASSIFICATION_ROOT / "20261010T102656.252222Z-72f200ad/normalized/classification.json",
        progress_path=CLASSIFICATION_ROOT / "20261010T102656.252222Z-72f200ad/normalized/progress.json",
        capture_metadata_path=CLASSIFICATION_ROOT / "20261010T102656.252222Z-72f200ad/metadata/capture.json",
        referees_root=REFEREES_ROOT,
    )


def capture_copy(tmp_path: Path) -> Path:
    root = tmp_path / "referees-capture"
    shutil.copytree(REFEREES_ROOT, root)
    return root


def read_json(root: Path, relative: str) -> dict[str, Any]:
    return json.loads((root / relative).read_text(encoding="utf-8"))


def write_json(root: Path, relative: str, value: dict[str, Any]) -> None:
    (root / relative).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def current_group_match_sources() -> dict[str, tuple[Path, Path]]:
    return {
        "I": (
            GROUP1_CAPTURE_ROOT / "normalized/matches.json",
            GROUP1_CAPTURE_ROOT / "validation/referee_reference.json",
        ),
        "II": (
            CLASSIFICATION_ROOT / "derived-res01-20261010T102656Z/normalized/matches.json",
            REFEREES_ROOT / "validation/match_reference.json",
        ),
    }


def future_capture_with_fewer_rows(root: Path) -> None:
    """Adjust an isolated fixture to prove that the loader has no fixed row counts."""
    removed_id = "r600338"  # fixture-only change; a Group I-only referee
    referees = read_json(root, "normalized/referees.json")
    statistics = read_json(root, "normalized/statistics.json")
    options = read_json(root, "normalized/filter_options.json")
    capture = read_json(root, "metadata/capture.json")
    validation = read_json(root, "validation/results.json")

    referees["records"] = [row for row in referees["records"] if row["referee_id"] != removed_id]
    statistics["records"] = [row for row in statistics["records"] if row["referee_id"] != removed_id]
    actual_counts = {
        scope: sum(row["group_scope"] == scope for row in statistics["records"])
        for scope in ("all", "group1", "group2")
    }
    capture["scope_counts"] = actual_counts
    capture["referee_count"] = len(referees["records"])
    capture["statistics_count"] = len(statistics["records"])
    validation["summary"].update({
        "referees": len(referees["records"]),
        "statistics": len(statistics["records"]),
        "scope_counts": actual_counts,
        "unique_ids": len(referees["records"]),
    })
    for payload in (referees, statistics, options):
        payload["metadata"]["scope_counts"] = actual_counts
    options["group_options"] = [
        {**option, "selected": option["scope"] == "all"}
        for option in options["group_options"]
    ]
    for relative, payload in (
        ("normalized/referees.json", referees),
        ("normalized/statistics.json", statistics),
        ("normalized/filter_options.json", options),
        ("metadata/capture.json", capture),
        ("validation/results.json", validation),
    ):
        write_json(root, relative, payload)


@pytest.fixture
def client() -> TestClient:
    with TestClient(create_app(settings())) as test_client:
        yield test_client


def test_referees_bootstrap_has_provenance_unique_catalog_and_three_real_scopes(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/group2/referees/bootstrap")
    assert response.status_code == 200
    payload = response.json()
    assert payload["metadata"]["capture_id"] == "20261010T171227.617128Z-4cfe71bc"
    assert payload["metadata"]["capture_id"] != payload["metadata"]["related_matches_capture_id"]
    assert payload["metadata"]["match_reference_status"] == "consistent"
    assert set(payload["metadata"]["source_snapshot_sha256"]) == {"all", "group1", "group2"}
    assert len(payload["referees"]) == 60
    assert len({row["referee_id"] for row in payload["referees"]}) == 60
    assert len(payload["statistics"]) == 145
    assert payload["availability"]["scope_counts"] == {
        "all": {
            "group_scope": "all", "label": "Todos", "referee_count": 60,
            "matches_officiated": 119, "yellow_cards": 563, "red_cards": 35,
        },
        "group1": {
            "group_scope": "group1", "label": "Grupo I", "referee_count": 43,
            "matches_officiated": 60, "yellow_cards": 273, "red_cards": 20,
        },
        "group2": {
            "group_scope": "group2", "label": "Grupo II", "referee_count": 42,
            "matches_officiated": 59, "yellow_cards": 290, "red_cards": 15,
        },
    }
    assert [season["label"] for season in payload["seasons"]] == ["2026/27"]
    assert {option["group_scope"] for option in payload["groups"]} == {"all", "group1", "group2"}
    referee = next(row for row in payload["referees"] if row["referee_id"] == "r602675")
    assert referee["profile_url"] == "https://www.bdfutbol.com/es/r/r602675.html"
    assert referee["nationality"] is None
    assert referee["birth_date"] is None
    assert any(row["referee_id"] == referee["referee_id"] and row["group_scope"] == "group2" for row in payload["statistics"])
    assert response.headers["etag"] == f'"referees-v1-{payload["metadata"]["dataset_version"]}"'


def test_referees_endpoint_supports_schema_versioned_conditional_etag(client: TestClient) -> None:
    first = client.get("/api/v1/group2/referees/bootstrap")
    stale_schema = client.get(
        "/api/v1/group2/referees/bootstrap",
        headers={"If-None-Match": f'"{first.json()["metadata"]["dataset_version"]}"'},
    )
    assert stale_schema.status_code == 200
    cached = client.get(
        "/api/v1/group2/referees/bootstrap",
        headers={"If-None-Match": first.headers["etag"]},
    )
    assert cached.status_code == 304
    assert cached.content == b""


def test_openapi_documents_referees_bootstrap(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/group2/referees/bootstrap" in paths


def test_referee_capture_and_related_results_paths_are_configurable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "configured-referees"
    matches = tmp_path / "related-matches.json"
    monkeypatch.setenv("FDH_GROUP2_REFEREES_ROOT", str(root))
    monkeypatch.setenv("FDH_GROUP2_REFEREES_MATCHES", str(matches))
    configured = ApiSettings.from_env()
    assert configured.referees_root == root
    assert configured.referees_related_matches_path == matches


def test_future_capture_counts_are_data_driven_not_hard_coded(tmp_path: Path) -> None:
    root = capture_copy(tmp_path)
    future_capture_with_fewer_rows(root)
    bundle = load_referee_dataset(replace(settings(), referees_root=root))
    assert bundle.bootstrap.availability.catalog_referee_count == 59
    assert bundle.bootstrap.availability.statistics_record_count == 143
    assert bundle.bootstrap.availability.scope_counts["all"].referee_count == 59
    assert bundle.bootstrap.availability.scope_counts["group1"].referee_count == 42
    assert bundle.bootstrap.availability.scope_counts["group2"].referee_count == 42


@pytest.mark.parametrize("failure", ["source_hash", "duplicate", "empty_scope", "aggregate"])
def test_invalid_referee_capture_is_rejected(tmp_path: Path, failure: str) -> None:
    root = capture_copy(tmp_path)
    if failure == "source_hash":
        raw = root / "raw/source_all.html"
        raw.write_bytes(raw.read_bytes() + b"\n<!-- altered -->")
    elif failure == "duplicate":
        payload = read_json(root, "normalized/statistics.json")
        payload["records"].append(payload["records"][0])
        write_json(root, "normalized/statistics.json", payload)
    elif failure == "empty_scope":
        payload = read_json(root, "normalized/statistics.json")
        payload["records"] = [row for row in payload["records"] if row["group_scope"] != "group2"]
        write_json(root, "normalized/statistics.json", payload)
    else:
        payload = read_json(root, "normalized/statistics.json")
        row = next(row for row in payload["records"] if row["group_scope"] == "all")
        row["yellow_cards"] += 1
        write_json(root, "normalized/statistics.json", payload)

    with pytest.raises(RefereeDatasetLoadError):
        load_referee_dataset(replace(settings(), referees_root=root))


def test_referee_failure_is_isolated_from_other_api_sections(tmp_path: Path) -> None:
    broken_root = tmp_path / "missing-referees"
    broken_root.mkdir()
    configured = replace(settings(), referees_root=broken_root)
    with TestClient(create_app(configured)) as isolated_client:
        assert isolated_client.get("/api/v1/group2/bootstrap").status_code == 200
        assert isolated_client.get("/api/v1/group2/top/bootstrap").status_code == 200
        response = isolated_client.get("/api/v1/group2/referees/bootstrap")
        assert response.status_code == 503
        assert "Árbitros" in response.json()["detail"]


def test_related_match_metadata_is_stable_when_group_sources_are_reordered() -> None:
    sources = current_group_match_sources()
    regular = load_referee_dataset(settings(), group_match_sources=sources)
    reversed_order = load_referee_dataset(
        settings(), group_match_sources=dict(reversed(list(sources.items())))
    )
    expected_group2 = read_json(REFEREES_ROOT, "metadata/capture.json")["related_match_dataset"]

    for bundle in (regular, reversed_order):
        metadata = bundle.bootstrap.metadata
        assert metadata.related_matches_path == expected_group2["path"]
        assert metadata.related_matches_sha256 == expected_group2["sha256"]
        assert metadata.related_matches_capture_id == expected_group2["source_capture_id"]
        assert metadata.related_matches_captured_at.isoformat() == expected_group2[
            "source_captured_at_utc"
        ]
        assert set(metadata.related_match_datasets) == {"I", "II"}
    assert regular.bootstrap.metadata == reversed_order.bootstrap.metadata
    assert regular.etag == reversed_order.etag
    assert regular.bootstrap.compatibility_warnings == reversed_order.bootstrap.compatibility_warnings


@pytest.mark.parametrize("invalid_group", ["I", "II"])
def test_one_invalid_group_reference_does_not_contaminate_the_other(
    tmp_path: Path, invalid_group: str
) -> None:
    sources = current_group_match_sources()
    _, report_path = sources[invalid_group]
    sources[invalid_group] = (tmp_path / f"missing-{invalid_group}-matches.json", report_path)

    bundle = load_referee_dataset(settings(), group_match_sources=sources)
    expected = "II" if invalid_group == "I" else "I"
    assert set(bundle.bootstrap.metadata.related_match_datasets) == {expected}
    assert set(bundle.group_reference_errors) == {invalid_group}

    # The legacy fields describe the declared historical Group II reference;
    # only the per-group map makes a current verified claim.
    reference = read_json(REFEREES_ROOT, "metadata/capture.json")["related_match_dataset"]
    assert bundle.bootstrap.metadata.related_matches_path == reference["path"]
    assert bundle.bootstrap.metadata.related_matches_sha256 == reference["sha256"]
    assert bundle.bootstrap.metadata.related_matches_capture_id == reference["source_capture_id"]


def test_referee_loader_fails_when_both_group_references_fail(tmp_path: Path) -> None:
    sources = {
        group: (tmp_path / f"missing-{group}.json", report)
        for group, (_, report) in current_group_match_sources().items()
    }
    with pytest.raises(RefereeDatasetLoadError, match="ninguna relación"):
        load_referee_dataset(settings(), group_match_sources=sources)
