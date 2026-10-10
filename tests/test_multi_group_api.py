"""Shared API contracts for the 2026/27 Primera Federación groups."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from football_data_hub_api.config import ApiSettings
from football_data_hub_api.main import create_app


def test_group_bootstraps_are_separate_and_use_real_captures() -> None:
    with TestClient(create_app(ApiSettings.from_env())) as client:
        one = client.get("/api/v1/groups/1/bootstrap")
        two = client.get("/api/v1/groups/2/bootstrap")
        assert one.status_code == two.status_code == 200

        group1 = one.json()
        group2 = two.json()
        assert (group1["metadata"]["group"], group2["metadata"]["group"]) == ("I", "II")
        assert len(group1["teams"]) == len(group2["teams"]) == 20
        assert len(group1["matches"]) == len(group2["matches"]) == 380
        assert group1["metadata"]["availability"]["played_matches"] == 60
        assert group2["metadata"]["availability"]["played_matches"] == 59
        assert {team["team_id"] for team in group1["teams"]}.isdisjoint(
            {team["team_id"] for team in group2["teams"]}
        )
        assert one.headers["etag"] != two.headers["etag"]
        assert client.get(
            "/api/v1/groups/1/bootstrap", headers={"If-None-Match": one.headers["etag"]}
        ).status_code == 304


def test_group_top_bootstraps_preserve_documented_group_one_exceptions() -> None:
    with TestClient(create_app(ApiSettings.from_env())) as client:
        one_response = client.get("/api/v1/groups/1/top/bootstrap")
        two_response = client.get("/api/v1/groups/2/top/bootstrap")
        assert one_response.status_code == two_response.status_code == 200

        one = one_response.json()
        two = two_response.json()
        assert one["metadata"]["group"] == "I"
        assert two["metadata"]["group"] == "II"
        assert one["availability"]["players"] == 180
        assert one["availability"]["ranking_records"] == 149
        assert one["availability"]["foreign_players"] == 59
        assert one["foreigners_summary"]["source_count"] == 60
        assert len(one["foreigners"]) == 59
        ambiguous = next(player for player in one["players"] if player["player_id"] == 304291)
        assert ambiguous["team_id"] is None
        assert ambiguous["team_name"] is None
        assert any(row["player_id"] == 304291 for row in one["rankings"])
        assert any(series["player_id"] == 304291 for series in one["progress"])
        assert any(row["player_id"] == 304291 for row in one["foreigners"])
        assert one["affiliation_conflicts"][0]["player_id"] == 304291
        assert any("59 registros" in warning for warning in one["warnings"])
        assert two["availability"]["players"] == 217
        assert two["availability"]["ranking_records"] == 157
        assert two["availability"]["foreign_players"] == 101
        assert two["affiliation_conflicts"] == []
        assert one_response.headers["etag"] != two_response.headers["etag"]


def test_shared_referees_keep_group_specific_counts_and_exact_match_provenance() -> None:
    with TestClient(create_app(ApiSettings.from_env())) as client:
        one = client.get("/api/v1/groups/1/referees/bootstrap")
        two = client.get("/api/v1/groups/2/referees/bootstrap")
        assert one.status_code == two.status_code == 200
        payload = one.json()
        counts = payload["availability"]["scope_counts"]
        assert payload["metadata"]["group"] == "I/II"
        assert counts["group1"]["referee_count"] == 43
        assert counts["group2"]["referee_count"] == 42
        assert counts["all"]["referee_count"] == 60
        assert payload["metadata"]["related_match_datasets"]["I"]["capture_id"] == (
            "20261010T202500.293648Z-b770724f"
        )
        assert payload["metadata"]["related_match_datasets"]["II"]["capture_id"] == (
            "20261010T102656.252222Z-72f200ad"
        )
        assert one.headers["etag"] != two.headers["etag"]


def test_statistics_are_bound_to_the_matching_group_and_legacy_aliases_stay_live() -> None:
    with TestClient(create_app(ApiSettings.from_env())) as client:
        one = client.get("/api/v1/groups/1/statistics/bootstrap")
        two = client.get("/api/v1/groups/2/statistics/bootstrap")
        legacy = client.get("/api/v1/group2/bootstrap")
        assert one.status_code == two.status_code == legacy.status_code == 200
        assert one.json()["statistics"]["group"] == "I"
        assert one.json()["statistics"]["played_matches"] == 60
        assert one.json()["statistics"]["goals"] == 156
        assert one.json()["statistics"]["home_wins"] == 29
        assert one.json()["statistics"]["away_wins"] == 16
        assert one.json()["statistics"]["draws"] == 15
        assert one.json()["statistics"]["yellow_cards"] == 273
        assert one.json()["statistics"]["red_cards"] == 20
        assert two.json()["statistics"]["group"] == "II"
        assert any(
            item["matchday"] == 5 and item["difference_published_minus_calculated"] == -2
            for item in two.json()["reconciliation"]["round_series"]
            if item["statistic"] == "goals"
        )
        assert all(
            item["difference_published_minus_calculated"] != -2
            for item in one.json()["reconciliation"]["round_series"]
            if item["matchday"] == 5 and item["statistic"] == "goals"
        )
        assert legacy.json()["metadata"]["group"] == "II"


def test_unknown_groups_and_group_specific_section_failures_are_isolated(tmp_path: Path) -> None:
    configured = ApiSettings.from_env()
    assert configured.group1_settings is not None
    broken_group1 = replace(
        configured.group1_settings,
        top_players_path=tmp_path / "missing-group1-players.json",
    )
    isolated = replace(configured, group1_settings=broken_group1)
    with TestClient(create_app(isolated)) as client:
        assert client.get("/api/v1/groups/3/bootstrap").status_code == 404
        assert client.get("/api/v1/groups/1/bootstrap").status_code == 200
        assert client.get("/api/v1/groups/2/bootstrap").status_code == 200
        assert client.get("/api/v1/groups/1/top/bootstrap").status_code == 503
        assert client.get("/api/v1/groups/2/top/bootstrap").status_code == 200
        assert client.get("/api/v1/groups/1/statistics/bootstrap").status_code == 200


def test_group_one_results_failure_does_not_disable_group_two_or_shared_referees(
    tmp_path: Path,
) -> None:
    configured = ApiSettings.from_env()
    assert configured.group1_settings is not None
    broken_group1 = replace(
        configured.group1_settings,
        matches_path=tmp_path / "missing-group1-matches.json",
    )
    isolated = replace(configured, group1_settings=broken_group1)
    with TestClient(create_app(isolated)) as client:
        assert client.get("/api/v1/groups/1/bootstrap").status_code == 503
        assert client.get("/api/v1/groups/2/bootstrap").status_code == 200
        assert client.get("/api/v1/groups/1/referees/bootstrap").status_code == 503
        group2_referees = client.get("/api/v1/groups/2/referees/bootstrap")
        assert group2_referees.status_code == 200
        assert group2_referees.json()["metadata"]["group"] == "I/II"
        assert set(group2_referees.json()["metadata"]["related_match_datasets"]) == {"II"}


def test_group_one_top_catalog_is_resolved_through_configured_group_paths() -> None:
    settings = ApiSettings.from_env()
    group1 = settings.for_group("1")
    assert group1.top_team_catalog_path == group1.matches_path
    assert group1.top_team_catalog_path is not None
    assert group1.top_team_catalog_path.name == "matches.json"
