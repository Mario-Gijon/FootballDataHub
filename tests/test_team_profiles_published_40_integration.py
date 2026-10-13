"""Opt-in integration against the external, explicitly published 40-team index.

Run with FDH_TEAM_PROFILES_INDEX and current Group I/II data paths set. The
normal offline test suite skips this module unless explicitly enabled.
"""

from __future__ import annotations

import json
import os

import pytest
from fastapi import Request, Response

from football_data_hub_api.config import ApiSettings
from football_data_hub_api.dataset import load_dataset
from football_data_hub_api.main import create_app
from football_data_hub_api.team_follow_dataset import load_team_follow_registry
from football_data_hub_api.team_roster_dataset import load_team_roster_registry
from football_data_hub_api.team_transfers_dataset import load_team_transfers_registry

pytestmark = pytest.mark.skipif(
    os.getenv("FDH_RUN_40_TEAM_PROFILE_INTEGRATION") != "1",
    reason="requiere el índice externo y los catálogos locales publicados",
)


def _invoke(app: object, route_path: str, **params: object) -> tuple[object, Response]:
    route = next(item for item in app.routes if getattr(item, "path", None) == route_path)
    actual_path = route_path
    for name in ("group", "team_id", "season"):
        if name in params:
            actual_path = actual_path.replace("{" + name + "}", str(params[name]))
    request = Request({
        "type": "http",
        "method": "GET",
        "scheme": "http",
        "path": actual_path,
        "raw_path": actual_path.encode("ascii"),
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
        "root_path": "",
        "app": app,
    })
    response = Response()
    return route.endpoint(**params, request=request, response=response), response


def test_all_40_team_profiles_and_competition_bootstraps_are_available() -> None:
    settings = ApiSettings.from_env()
    index_path = settings.team_profiles_index_path
    assert index_path is not None and index_path.is_file()
    profiles = json.loads(index_path.read_text(encoding="utf-8"))["profiles"]
    assert len(profiles) == 40

    group_settings = {group: settings.for_group(group) for group in ("1", "2")}
    datasets = {group: load_dataset(group_settings[group]) for group in group_settings}
    matches_paths = {group: group_settings[group].matches_path for group in group_settings}
    roster = load_team_roster_registry(
        index_path, datasets=datasets, matches_paths=matches_paths
    )
    follow = load_team_follow_registry(
        index_path,
        datasets=datasets,
        matches_paths=matches_paths,
        roster_registry=roster,
    )
    transfers = load_team_transfers_registry(index_path, roster_registry=roster)
    app = create_app(settings)
    app.state.datasets = datasets
    app.state.team_roster_registry = roster
    app.state.team_follow_registry = follow
    app.state.team_transfers_registry = transfers

    assert roster.index_error is None and roster.profile_errors == {}
    assert follow.index_error is None and follow.profile_errors == {}
    assert transfers.index_error is None and transfers.profile_errors == {}
    expected_ids = {int(team_id) for team_id in profiles}
    assert set(roster.profiles) == set(follow.profiles) == set(transfers.profiles) == expected_ids

    bootstrap_team_ids: dict[str, set[int]] = {}
    bootstrap_by_group: dict[str, dict] = {}
    for group_number, group in (("1", "I"), ("2", "II")):
        payload, _ = _invoke(
            app, "/api/v1/groups/{group}/bootstrap", group=group_number
        )
        assert len(payload.teams) == 20
        assert len(payload.matches) == 380
        bootstrap_team_ids[group] = {team.team_id for team in payload.teams}
        bootstrap_by_group[group] = payload.model_dump(mode="json")

    for team_id_text, selected in profiles.items():
        team_id = int(team_id_text)
        assert selected["publication_validation"]["classification"] == "complete"
        assert selected["publication_validation"]["active_catalog_compatible"] is True
        group = "I" if team_id in bootstrap_team_ids["I"] else "II"
        assert team_id in bootstrap_team_ids[group]
        active_matches = {
            str(match["match_id"]): match
            for match in bootstrap_by_group[group]["matches"]
        }
        assert any(
            team_id in {match["home_team_id"], match["away_team_id"]}
            for match in active_matches.values()
        )

        for section in ("roster", "follow", "transfers"):
            result, _ = _invoke(
                app,
                f"/api/v1/teams/{{team_id}}/seasons/{{season}}/{section}",
                team_id=team_id,
                season="2026-27",
            )
            assert result.status == "available"
            assert result.metadata.team_id == team_id
            assert result.metadata.group == group
            assert result.metadata.capture_id == selected["capture_id"]

        follow_data, _ = _invoke(
            app,
            "/api/v1/teams/{team_id}/seasons/{season}/follow",
            team_id=team_id,
            season="2026-27",
        )
        referenced_ids = {item.match_id for item in follow_data.minutes}
        referenced_ids.update(item.match_id for item in follow_data.metrics)
        assert referenced_ids.issubset(active_matches)
        assert all(active_matches[match_id]["status"] == "played" for match_id in referenced_ids)
