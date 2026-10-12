"""Source-integrity and HTTP contract tests for the team transfers endpoint."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from fastapi import HTTPException, Request, Response
import pytest
from pydantic import ValidationError

from football_data_hub_api.config import ApiSettings, PROJECT_ROOT
from football_data_hub_api.dataset import load_dataset
from football_data_hub_api.main import create_app
from football_data_hub_api.schemas import TeamTransferRecordResponse, TeamTransfersResponse
from football_data_hub_api.team_roster_dataset import load_team_roster_registry
from football_data_hub_api.team_transfers_dataset import (
    TeamTransfersRegistry,
    load_team_transfers_registry,
)

INDEX_PATH = PROJECT_ROOT / "config/team_profiles_2026-27.json"
CAPTURE_PATHS = {
    49: PROJECT_ROOT / "data/exports/bdfutbol/teams/2026-27/49/20261012T131457.209360Z-602005d8",
    48: PROJECT_ROOT / "data/exports/bdfutbol/teams/2026-27/48/20261012T131518.543469Z-43ff1122",
}


@pytest.fixture(scope="module")
def loaded() -> tuple[TeamTransfersRegistry, object, dict[str, object], dict[str, Path]]:
    settings = ApiSettings.from_env()
    group_settings = {group: settings.for_group(group) for group in ("1", "2")}
    datasets = {group: load_dataset(group_settings[group]) for group in group_settings}
    matches_paths = {group: group_settings[group].matches_path for group in group_settings}
    roster = load_team_roster_registry(settings.team_profiles_index_path, datasets=datasets, matches_paths=matches_paths)
    transfers = load_team_transfers_registry(settings.team_profiles_index_path, roster_registry=roster)
    return transfers, roster, datasets, matches_paths


def invoke_endpoint(
    registry: TeamTransfersRegistry,
    team_id: int,
    season: str = "2026-27",
    if_none_match: str | None = None,
) -> tuple[object, Response]:
    app = create_app(ApiSettings.from_env())
    app.state.team_transfers_registry = registry
    path = f"/api/v1/teams/{team_id}/seasons/{season}/transfers"
    headers = [(b"host", b"testserver")]
    if if_none_match is not None:
        headers.append((b"if-none-match", if_none_match.encode("latin-1")))
    request = Request({
        "type": "http", "method": "GET", "scheme": "http", "path": path,
        "raw_path": path.encode("ascii"), "query_string": b"", "headers": headers,
        "server": ("testserver", 80), "client": ("127.0.0.1", 12345),
        "root_path": "", "app": app,
    })
    route = next(route for route in app.routes if getattr(route, "path", None) == "/api/v1/teams/{team_id}/seasons/{season}/transfers")
    response = Response()
    result = route.endpoint(team_id=team_id, season=season, request=request, response=response)
    return result, result if isinstance(result, Response) else response


def test_real_jaen_and_racing_transfers_are_source_verified(loaded: tuple) -> None:
    registry, roster, _, _ = loaded
    assert registry.index_error is None
    assert registry.profile_errors == {}
    assert set(registry.profiles) == {48, 49}
    assert set(roster.profiles) == {48, 49}
    assert len(registry.profiles[49].incoming) == 14
    assert len(registry.profiles[49].outgoing) == 20
    assert len(registry.profiles[48].incoming) == len(registry.profiles[48].outgoing) == 15
    assert registry.profiles[49].metadata.captured_at.isoformat().startswith("2026-10-11T11:40:34")
    assert registry.profiles[49].metadata.derived_at is not None
    outgoing = next(row for row in registry.profiles[49].outgoing if row.player_id == 22537)
    assert outgoing.player_display_name == "Rabanillo"
    assert outgoing.other_team_name is None
    assert outgoing.age_years == 31
    jaen_in = next(row for row in registry.profiles[49].incoming if row.player_id == 304042)
    assert jaen_in.other_team_url == "https://www.bdfutbol.com/es/t/t2025-26130.html"
    racing_out = next(row for row in registry.profiles[48].outgoing if row.player_id == 23024)
    assert racing_out.other_team_name == "Cultural Leonesa"
    assert racing_out.other_team_id == 84
    for team_id in (48, 49):
        assert all(row.fee is None and row.transfer_date is None for row in registry.profiles[team_id].incoming + registry.profiles[team_id].outgoing)
        assert {item.status for item in registry.profiles[team_id].sections} == {"verified_with_rows"}


def test_transfers_route_etag_unknown_uncaptured_and_wrong_season(loaded: tuple) -> None:
    registry, _, _, _ = loaded
    jaen, response = invoke_endpoint(registry, 49)
    assert isinstance(jaen, TeamTransfersResponse)
    assert response.status_code == 200
    etag = response.headers["etag"]
    assert etag.startswith('"team-transfers-v1-49-2026-27-')
    cached, cached_response = invoke_endpoint(registry, 49, if_none_match=etag)
    assert isinstance(cached, Response)
    assert cached.status_code == cached_response.status_code == 304
    _, stale_response = invoke_endpoint(registry, 49, if_none_match='"team-transfers-v0-49-2026-27-old"')
    assert stale_response.status_code == 200

    uncaptured = next(team_id for team_id in registry.known_teams if team_id not in {48, 49})
    for team_id, season, expected_code in (
        (uncaptured, "2026-27", "transfers_not_captured"),
        (999999, "2026-27", "team_unknown"),
        (49, "2025-26", "season_not_available"),
    ):
        with pytest.raises(HTTPException) as error:
            invoke_endpoint(registry, team_id, season)
        assert error.value.status_code == 404
        assert error.value.detail["code"] == expected_code


def _make_paths_absolute(index: dict) -> None:
    for entry in index["profiles"].values():
        entry["directory"] = str((INDEX_PATH.parent / entry["directory"]).resolve())


def test_transfer_hash_failure_is_isolated_from_other_sections(loaded: tuple, tmp_path: Path) -> None:
    _, roster, _, _ = loaded
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    _make_paths_absolute(index)
    index["profiles"]["49"]["transfers_files_sha256"]["normalized/transfers.json"] = "0" * 64
    index_path = tmp_path / "profiles.json"
    index_path.write_text(json.dumps(index), encoding="utf-8")
    transfers = load_team_transfers_registry(index_path, roster_registry=roster)
    assert 49 in transfers.profile_errors and 49 not in transfers.profiles
    assert 48 in transfers.profiles
    assert 49 in roster.profiles
    with pytest.raises(HTTPException) as error:
        invoke_endpoint(transfers, 49)
    assert error.value.status_code == 503
    assert error.value.detail["code"] == "transfers_invalid"


def test_transfers_are_reparsed_against_the_fixed_original_html(loaded: tuple, tmp_path: Path) -> None:
    _, roster, _, _ = loaded
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    _make_paths_absolute(index)
    selected = tmp_path / CAPTURE_PATHS[49].name
    shutil.copytree(CAPTURE_PATHS[49], selected)
    transfer_path = selected / "normalized/transfers.json"
    transfers_doc = json.loads(transfer_path.read_text(encoding="utf-8"))
    transfers_doc["records"][0]["direction"] = "outgoing"
    transfer_path.write_text(json.dumps(transfers_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    transfer_hash = hashlib.sha256(transfer_path.read_bytes()).hexdigest()
    index["profiles"]["49"]["directory"] = str(selected)
    index["profiles"]["49"]["transfers_files_sha256"]["normalized/transfers.json"] = transfer_hash
    index["profiles"]["49"]["transfers_evidence"]["normalized"]["sha256"] = transfer_hash
    metadata_path = selected / "metadata/capture.json"
    metadata_doc = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata_doc["normalized_snapshots"]["transfers.json"]["sha256"] = transfer_hash
    metadata_path.write_text(json.dumps(metadata_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    index["profiles"]["49"]["transfers_files_sha256"]["metadata/capture.json"] = hashlib.sha256(metadata_path.read_bytes()).hexdigest()
    index_path = tmp_path / "altered-profile.json"
    index_path.write_text(json.dumps(index), encoding="utf-8")
    transfers = load_team_transfers_registry(index_path, roster_registry=roster)
    assert 49 in transfers.profile_errors
    assert "no corresponden al HTML original" in transfers.profile_errors[49]


def test_strict_contract_rejects_direction_and_heading_mismatch(loaded: tuple) -> None:
    row = loaded[0].profiles[49].incoming[0].model_dump()
    row["source_heading"] = "Bajas"
    with pytest.raises(ValidationError):
        TeamTransferRecordResponse.model_validate(row)
