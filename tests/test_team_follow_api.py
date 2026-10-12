"""Tests for the explicit, offline player-by-match follow endpoint."""

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
from football_data_hub_api.schemas import TeamFollowResponse
from football_data_hub_api.team_follow_dataset import (
    TeamFollowRegistry,
    load_team_follow_registry,
)
from football_data_hub_api.team_roster_dataset import load_team_roster_registry


INDEX_PATH = PROJECT_ROOT / "config/team_profiles_2026-27.json"
RACING_CAPTURE = PROJECT_ROOT / "data/exports/bdfutbol/teams/2026-27/48/20261011T123240.190812Z-8f307d1c"
JAEN_CAPTURE = PROJECT_ROOT / "data/exports/bdfutbol/teams/2026-27/49/20261012T120720.895650Z-8c75b830"


@pytest.fixture(scope="module")
def loaded() -> tuple[TeamFollowRegistry, object, dict[str, object], dict[str, Path]]:
    settings = ApiSettings.from_env()
    group_settings = {group: settings.for_group(group) for group in ("1", "2")}
    datasets = {group: load_dataset(group_settings[group]) for group in group_settings}
    matches_paths = {group: group_settings[group].matches_path for group in group_settings}
    roster = load_team_roster_registry(settings.team_profiles_index_path, datasets=datasets, matches_paths=matches_paths)
    follow = load_team_follow_registry(
        settings.team_profiles_index_path,
        datasets=datasets,
        matches_paths=matches_paths,
        roster_registry=roster,
    )
    return follow, roster, datasets, matches_paths


def invoke_follow_endpoint(
    registry: TeamFollowRegistry,
    team_id: int,
    season: str = "2026-27",
    if_none_match: str | None = None,
) -> tuple[object, Response]:
    app = create_app(ApiSettings.from_env())
    app.state.team_follow_registry = registry
    path = f"/api/v1/teams/{team_id}/seasons/{season}/follow"
    headers = [(b"host", b"testserver")]
    if if_none_match is not None:
        headers.append((b"if-none-match", if_none_match.encode("latin-1")))
    request = Request({
        "type": "http", "method": "GET", "scheme": "http", "path": path,
        "raw_path": path.encode("ascii"), "query_string": b"", "headers": headers,
        "server": ("testserver", 80), "client": ("127.0.0.1", 12345),
        "root_path": "", "app": app,
    })
    route = next(route for route in app.routes if getattr(route, "path", None) == "/api/v1/teams/{team_id}/seasons/{season}/follow")
    response = Response()
    result = route.endpoint(team_id=team_id, season=season, request=request, response=response)
    return result, result if isinstance(result, Response) else response


def absolute_capture_paths(index: dict) -> None:
    for entry in index["profiles"].values():
        directory = Path(entry["directory"])
        if not directory.is_absolute():
            entry["directory"] = str((INDEX_PATH.parent / directory).resolve())


def test_racing_and_jaen_publish_their_real_follow_coverage(loaded: tuple) -> None:
    follow_registry, _, _, _ = loaded
    assert follow_registry.index_error is None
    assert follow_registry.profile_errors == {}
    racing = follow_registry.profiles[48]
    assert racing.metadata.group == "I"
    assert len(racing.players) == 25
    assert racing.matchdays == [1, 2, 3, 4, 5, 6]
    assert len(racing.matches) == 6
    assert len(racing.minutes) == 150
    assert sum(metric.value for metric in racing.metrics if metric.metric == "yellow_cards") == 10
    assert sum(metric.value for metric in racing.metrics if metric.metric == "goals") == 7
    assert not any(metric.metric == "red_cards" for metric in racing.metrics)
    assert {item.state for item in racing.coverage if item.available} == {"p", "t", "go", "tot"}
    assert racing.metadata.derived_states == []

    jaen = follow_registry.profiles[49]
    assert jaen.metadata.group == "II"
    assert len(jaen.players) == 25
    assert jaen.matchdays == [1, 2, 3, 4, 5, 6]
    assert len(jaen.minutes) == 150
    assert len(jaen.metrics) == 22
    assert sum(metric.value for metric in jaen.metrics if metric.metric == "yellow_cards") == 15
    assert sum(metric.value for metric in jaen.metrics if metric.metric == "red_cards") == 2
    assert sum(metric.value for metric in jaen.metrics if metric.metric == "goals") == 8
    assert {item.state for item in jaen.coverage if item.available} == {"p", "t", "go", "tot"}
    assert jaen.metadata.contract_version == 2
    assert jaen.metadata.derived_states == ["go", "t", "tot"]
    assert jaen.metadata.derived_at is not None
    assert jaen.metadata.captured_at < jaen.metadata.derived_at
    assert any(player.photo_url for player in jaen.players)
    assert not any("no incluye eventos" in warning for warning in jaen.warnings)

    statistics = json.loads((JAEN_CAPTURE / "normalized/player_statistics.json").read_text(encoding="utf-8"))["records"]
    for record in statistics:
        for metric in ("yellow_cards", "red_cards", "goals"):
            actual = sum(item.value for item in jaen.metrics if item.player_id == record["player_id"] and item.metric == metric)
            assert actual == record[metric]


def test_match_player_relations_and_published_zero_null_values_are_preserved(loaded: tuple) -> None:
    follow_registry, _, _, _ = loaded
    for team_id in (48, 49):
        profile = follow_registry.profiles[team_id]
        players = {item.player_id for item in profile.players}
        matches = {item.match_id: item for item in profile.matches}
        assert all(item.player_id in players for item in profile.minutes)
        assert all(item.match_id in matches and matches[item.match_id].matchday == item.matchday for item in profile.minutes)
        assert any(item.minutes_played == 0 for item in profile.minutes)
        assert any(item.minutes_played is None for item in profile.minutes)
        coverage = next(item for item in profile.coverage if item.state == "p")
        assert coverage.value_total is None  # unknown cells make a full sum incomplete
        assert all(item.home_team_id == team_id or item.away_team_id == team_id for item in profile.matches)
    racing = follow_registry.profiles[48]
    metrics = {(item.player_id, item.match_id, item.metric) for item in racing.metrics}
    assert len(metrics) == len(racing.metrics)
    assert all(item.value > 0 for item in racing.metrics)


def test_follow_route_etag_unknown_uncaptured_and_wrong_season(loaded: tuple) -> None:
    registry, _, _, _ = loaded
    jaen, response = invoke_follow_endpoint(registry, 49)
    assert isinstance(jaen, TeamFollowResponse)
    assert response.status_code == 200
    assert jaen.metadata.contract_version == 2
    etag = response.headers["etag"]
    assert etag.startswith('"team-follow-v2-49-2026-27-')
    not_modified, cached_response = invoke_follow_endpoint(registry, 49, if_none_match=etag)
    assert isinstance(not_modified, Response)
    assert not_modified.status_code == 304
    assert cached_response.status_code == 304
    _, stale = invoke_follow_endpoint(registry, 49, if_none_match='"team-follow-v0-49-2026-27-old"')
    assert stale.status_code == 200

    uncaptured_id = next(team_id for team_id in registry.known_teams if team_id not in {48, 49})
    for team_id, season, expected_code in (
        (uncaptured_id, "2026-27", "follow_not_captured"),
        (999999, "2026-27", "team_unknown"),
        (49, "2025-26", "season_not_available"),
    ):
        with pytest.raises(HTTPException) as error:
            invoke_follow_endpoint(registry, team_id, season)
        assert error.value.status_code == 404
        assert error.value.detail["code"] == expected_code


def test_follow_hash_failure_is_isolated_and_does_not_break_roster(
    tmp_path: Path, loaded: tuple
) -> None:
    _, roster, datasets, matches_paths = loaded
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    absolute_capture_paths(index)
    index["profiles"]["48"]["follow_files_sha256"]["normalized/player_match_metrics.json"] = "0" * 64
    index_path = tmp_path / "profiles.json"
    index_path.write_text(json.dumps(index), encoding="utf-8")
    follow = load_team_follow_registry(index_path, datasets=datasets, matches_paths=matches_paths, roster_registry=roster)
    assert 48 in follow.profile_errors
    assert 48 not in follow.profiles
    assert 49 in follow.profiles
    assert 49 in roster.profiles
    with pytest.raises(HTTPException) as error:
        invoke_follow_endpoint(follow, 48)
    assert error.value.status_code == 503
    assert error.value.detail["code"] == "follow_invalid"


def test_duplicate_metric_is_rejected_even_when_the_index_hash_is_updated(
    tmp_path: Path, loaded: tuple
) -> None:
    _, roster, datasets, matches_paths = loaded
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    absolute_capture_paths(index)
    selected = tmp_path / RACING_CAPTURE.name
    shutil.copytree(RACING_CAPTURE, selected)
    metrics_path = selected / "normalized/player_match_metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics["records"].append(metrics["records"][0])
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False), encoding="utf-8")
    index["profiles"]["48"]["directory"] = str(selected)
    index["profiles"]["48"]["follow_files_sha256"]["normalized/player_match_metrics.json"] = hashlib.sha256(metrics_path.read_bytes()).hexdigest()
    index_path = tmp_path / "profiles-duplicate.json"
    index_path.write_text(json.dumps(index), encoding="utf-8")

    follow = load_team_follow_registry(index_path, datasets=datasets, matches_paths=matches_paths, roster_registry=roster)
    assert 48 in follow.profile_errors
    assert "duplican jugador-partido-tipo" in follow.profile_errors[48]
    assert 49 in follow.profiles
