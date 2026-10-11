"""Tests for explicitly published team-roster captures and their API route."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from fastapi import HTTPException, Request, Response
import pytest

from football_data_hub_api.config import ApiSettings, PROJECT_ROOT
from football_data_hub_api.dataset import load_dataset
from football_data_hub_api.main import create_app
from football_data_hub_api.schemas import TeamRosterResponse
from football_data_hub_api.team_roster_dataset import (
    TeamRosterRegistry,
    load_team_roster_registry,
)


INDEX_PATH = PROJECT_ROOT / "config/team_profiles_2026-27.json"
JAEN_CAPTURE = PROJECT_ROOT / (
    "data/exports/bdfutbol/teams/2026-27/49/team01a-group2-49-source-evidence"
)


@pytest.fixture(scope="module")
def registry() -> TeamRosterRegistry:
    configured = ApiSettings.from_env()
    group_settings = {group: configured.for_group(group) for group in ("1", "2")}
    datasets = {
        group: load_dataset(group_settings[group])
        for group in ("1", "2")
    }
    return load_team_roster_registry(
        configured.team_profiles_index_path,
        datasets=datasets,
        matches_paths={group: group_settings[group].matches_path for group in group_settings},
    )


def test_team_profile_index_path_is_configurable_for_external_storage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    absolute_index = tmp_path / "mounted-captures" / "profiles.json"
    monkeypatch.setenv("FDH_TEAM_PROFILES_INDEX", str(absolute_index))
    assert ApiSettings.from_env().team_profiles_index_path == absolute_index

    monkeypatch.setenv("FDH_TEAM_PROFILES_INDEX", "mounted/profiles.json")
    assert ApiSettings.from_env().team_profiles_index_path == PROJECT_ROOT / "mounted/profiles.json"


def invoke_roster_endpoint(
    roster_registry: TeamRosterRegistry,
    team_id: int,
    season: str = "2026-27",
    if_none_match: str | None = None,
) -> tuple[object, Response]:
    app = create_app(ApiSettings.from_env())
    app.state.team_roster_registry = roster_registry
    path = f"/api/v1/teams/{team_id}/seasons/{season}/roster"
    headers = [(b"host", b"testserver")]
    if if_none_match is not None:
        headers.append((b"if-none-match", if_none_match.encode("latin-1")))
    request = Request({
        "type": "http",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": headers,
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
        "root_path": "",
        "app": app,
    })
    route = next(
        route for route in app.routes
        if getattr(route, "path", None) == "/api/v1/teams/{team_id}/seasons/{season}/roster"
    )
    response = Response()
    result = route.endpoint(
        team_id=team_id, season=season, request=request, response=response
    )
    return result, response


def absolute_capture_paths(index: dict) -> None:
    for entry in index["profiles"].values():
        directory = Path(entry["directory"])
        if not directory.is_absolute():
            entry["directory"] = str((INDEX_PATH.parent / directory).resolve())


def test_jaen_and_racing_rosters_are_loaded_from_the_published_captures(
    registry: TeamRosterRegistry,
) -> None:
    assert registry.index_error is None
    assert registry.profile_errors == {}
    assert set(registry.profiles) == {48, 49}

    for team_id, group in ((49, "II"), (48, "I")):
        roster = registry.profiles[team_id]
        assert roster.team.team_id == team_id
        assert roster.metadata.season == "2026-27"
        assert roster.metadata.group == group
        assert roster.metadata.validation_status == "valid"
        assert len(roster.players) == len(roster.memberships) == len(roster.statistics) == 25
        assert len(roster.coaches) == 1
        assert {view.view for view in roster.source_views} == {
            "alignment", "squad", "statistics"
        }
        players = {player.player_id for player in roster.players}
        assert {item.player_id for item in roster.memberships} == players
        assert {item.player_id for item in roster.statistics} == players
        assert all(item.team_id == team_id for item in roster.memberships)
        assert all(item.team_id == team_id for item in roster.statistics)
        tactic = roster.tactical_visualization
        assert tactic is not None
        assert tactic.approximate is True
        assert tactic.source_view == "alignment"
        assert tactic.source_sha256 == next(view.sha256 for view in roster.source_views if view.view == "alignment")
        assert len(tactic.positions) == 11
        starter_ids = {
            player_id
            for group_item in roster.squad_groups
            if group_item.label == "Titulares"
            for player_id in group_item.player_ids
        }
        assert {item.player_id for item in tactic.positions} == starter_ids
        assert all(item.player_id in players for item in tactic.positions)
        assert all(0 <= item.horizontal <= 1 and 0 <= item.vertical <= 1 for item in tactic.positions)

    assert any("Seguimiento" in warning for warning in registry.profiles[49].warnings)


def test_roster_route_distinguishes_available_uncaptured_unknown_and_etag(
    registry: TeamRosterRegistry,
) -> None:
    jaen, response = invoke_roster_endpoint(registry, 49)
    assert isinstance(jaen, TeamRosterResponse)
    assert response.status_code == 200
    assert jaen.metadata.team_id == 49
    assert len(jaen.players) == 25
    etag = response.headers["etag"]
    assert jaen.metadata.contract_version == 2
    assert etag.startswith('"team-roster-v2-49-2026-27-')

    cached, _ = invoke_roster_endpoint(registry, 49, if_none_match=etag)
    assert isinstance(cached, Response)
    assert cached.status_code == 304
    # A validator from an older public contract must not receive a 304.
    _, stale_response = invoke_roster_endpoint(
        registry, 49, if_none_match='"team-roster-v1-49-2026-27-old"'
    )
    assert stale_response.status_code == 200

    known_uncaptured = next(team_id for team_id in registry.known_teams if team_id not in {48, 49})
    with pytest.raises(HTTPException) as missing:
        invoke_roster_endpoint(registry, known_uncaptured)
    assert missing.value.status_code == 404
    assert missing.value.detail["code"] == "profile_not_captured"
    with pytest.raises(HTTPException) as unknown:
        invoke_roster_endpoint(registry, 999999)
    assert unknown.value.status_code == 404
    assert unknown.value.detail["code"] == "team_unknown"
    with pytest.raises(HTTPException) as old_season:
        invoke_roster_endpoint(registry, 49, "2025-26")
    assert old_season.value.status_code == 404
    assert old_season.value.detail["code"] == "season_not_available"


def test_invalid_selected_capture_is_isolated_from_the_other_team(
    tmp_path: Path,
    registry: TeamRosterRegistry,
) -> None:
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    absolute_capture_paths(index)
    index["profiles"]["49"]["files_sha256"]["normalized/players.json"] = "0" * 64
    index_path = tmp_path / "team-profiles.json"
    index_path.write_text(json.dumps(index), encoding="utf-8")

    configured = ApiSettings.from_env()
    group_settings = {group: configured.for_group(group) for group in ("1", "2")}
    datasets = {
        group: load_dataset(group_settings[group])
        for group in ("1", "2")
    }
    isolated = load_team_roster_registry(
        index_path,
        datasets=datasets,
        matches_paths={group: group_settings[group].matches_path for group in group_settings},
    )
    assert 49 in isolated.profile_errors
    assert 49 not in isolated.profiles
    assert 48 in isolated.profiles

    with pytest.raises(HTTPException) as invalid:
        invoke_roster_endpoint(isolated, 49)
    assert invalid.value.status_code == 503
    assert invalid.value.detail["code"] == "profile_invalid"
    racing, racing_response = invoke_roster_endpoint(isolated, 48)
    assert isinstance(racing, TeamRosterResponse)
    assert racing_response.status_code == 200
    assert racing.team.team_id == 48


def test_valid_capture_does_not_require_a_fixed_player_count_or_follow_data(
    tmp_path: Path,
    registry: TeamRosterRegistry,
) -> None:
    selected = tmp_path / JAEN_CAPTURE.name
    shutil.copytree(JAEN_CAPTURE, selected)

    players_path = selected / "normalized/players.json"
    memberships_path = selected / "normalized/memberships.json"
    statistics_path = selected / "normalized/player_statistics.json"
    players = json.loads(players_path.read_text(encoding="utf-8"))
    memberships = json.loads(memberships_path.read_text(encoding="utf-8"))
    statistics = json.loads(statistics_path.read_text(encoding="utf-8"))
    keep_id = players["records"][0]["player_id"]
    players["records"] = [record for record in players["records"] if record["player_id"] == keep_id]
    memberships["records"] = [record for record in memberships["records"] if record["player_id"] == keep_id]
    statistics["records"] = [record for record in statistics["records"] if record["player_id"] == keep_id]
    players_path.write_text(json.dumps(players, ensure_ascii=False), encoding="utf-8")
    memberships_path.write_text(json.dumps(memberships, ensure_ascii=False), encoding="utf-8")
    statistics_path.write_text(json.dumps(statistics, ensure_ascii=False), encoding="utf-8")

    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    absolute_capture_paths(index)
    selected_entry = index["profiles"]["49"]
    selected_entry["directory"] = str(selected)
    for relative in (
        "normalized/players.json",
        "normalized/memberships.json",
        "normalized/player_statistics.json",
    ):
        selected_entry["files_sha256"][relative] = hashlib.sha256(
            (selected / relative).read_bytes()
        ).hexdigest()
    index_path = tmp_path / "team-profiles-one-player.json"
    index_path.write_text(json.dumps(index), encoding="utf-8")

    configured = ApiSettings.from_env()
    group_settings = {group: configured.for_group(group) for group in ("1", "2")}
    datasets = {
        group: load_dataset(group_settings[group])
        for group in ("1", "2")
    }
    variable = load_team_roster_registry(
        index_path,
        datasets=datasets,
        matches_paths={group: group_settings[group].matches_path for group in group_settings},
    )
    assert variable.profile_errors == {}
    assert len(variable.profiles[49].players) == 1
    assert len(variable.profiles[49].memberships) == 1
    assert len(variable.profiles[49].statistics) == 1
    assert len(variable.profiles[49].coaches) == 1
    assert len(registry.profiles[49].players) == 25
