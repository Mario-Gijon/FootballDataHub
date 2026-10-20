"""Shared API contracts for the 2026/27 Primera Federación groups."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Awaitable, Callable

import fastapi.routing

from football_data_hub_api.config import ApiSettings
from football_data_hub_api.main import create_app


class _ASGIResponse:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        start = next(message for message in messages if message["type"] == "http.response.start")
        self.status_code = int(start["status"])
        self.headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in start.get("headers", [])
        }
        self._body = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )

    def json(self) -> Any:
        return json.loads(self._body)


class _InProcessASGIClient:
    """Small ASGI caller that avoids AnyIO's broken portal startup in this env."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def get(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> _ASGIResponse:
        messages: list[dict[str, Any]] = []
        request_sent = False
        response_complete = asyncio.Event()
        request_headers = [(b"host", b"testserver")]
        request_headers.extend(
            (key.lower().encode("latin-1"), value.encode("latin-1"))
            for key, value in (headers or {}).items()
        )

        async def receive() -> dict[str, Any]:
            nonlocal request_sent
            if request_sent:
                await response_complete.wait()
                return {"type": "http.disconnect"}
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict[str, Any]) -> None:
            messages.append(message)
            if (
                message["type"] == "http.response.body"
                and not message.get("more_body", False)
            ):
                response_complete.set()

        await self.app(
            {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.3"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": path,
                "raw_path": path.encode("ascii"),
                "query_string": b"",
                "headers": request_headers,
                "client": ("testclient", 50000),
                "server": ("testserver", 80),
                "state": {},
            },
            receive,
            send,
        )
        return _ASGIResponse(messages)


def _run_with_api(
    app: Any,
    exercise: Callable[[_InProcessASGIClient], Awaitable[None]],
) -> None:
    # The current Python 3.14 / AnyIO 4.15 test environment deadlocks in both
    # BlockingPortal.start_task_soon (used by Starlette TestClient) and AnyIO's
    # worker-thread dispatcher (used for sync endpoints). This test concerns
    # routing and group data, so run those sync endpoints inline in this
    # test-only ASGI harness; production dispatch remains untouched.
    original_run_in_threadpool = fastapi.routing.run_in_threadpool

    async def run_inline(target: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return target(*args, **kwargs)

    fastapi.routing.run_in_threadpool = run_inline

    async def run() -> None:
        async with app.router.lifespan_context(app):
            await exercise(_InProcessASGIClient(app))

    try:
        asyncio.run(run())
    finally:
        fastapi.routing.run_in_threadpool = original_run_in_threadpool


def _played_match_count(settings: ApiSettings, group: str) -> int:
    matches_path = settings.for_group(group).matches_path
    payload = json.loads(matches_path.read_text(encoding="utf-8"))
    matches = payload.get("matches")
    if not isinstance(matches, list):
        raise AssertionError(f"El catálogo configurado no contiene matches: {matches_path}")
    return sum(match.get("status") == "played" for match in matches)


def test_group_bootstraps_are_separate_and_use_real_captures() -> None:
    settings = ApiSettings.from_env()

    async def exercise(client: _InProcessASGIClient) -> None:
        one = await client.get("/api/v1/groups/1/bootstrap")
        two = await client.get("/api/v1/groups/2/bootstrap")
        assert one.status_code == two.status_code == 200

        group1 = one.json()
        group2 = two.json()
        assert (group1["metadata"]["group"], group2["metadata"]["group"]) == ("I", "II")
        assert len(group1["teams"]) == len(group2["teams"]) == 20
        assert len(group1["matches"]) == len(group2["matches"]) == 380
        assert group1["metadata"]["availability"]["played_matches"] == _played_match_count(settings, "1")
        assert group2["metadata"]["availability"]["played_matches"] == _played_match_count(settings, "2")
        assert {team["team_id"] for team in group1["teams"]}.isdisjoint(
            {team["team_id"] for team in group2["teams"]}
        )
        assert one.headers["etag"] != two.headers["etag"]
        assert one.headers["etag"].startswith('"group-1-classification-v1-')
        assert two.headers["etag"].startswith('"group-2-classification-v1-')
        not_modified = await client.get(
            "/api/v1/groups/1/bootstrap", headers={"If-None-Match": one.headers["etag"]}
        )
        assert not_modified.status_code == 304

    _run_with_api(create_app(settings), exercise)


def test_group_top_bootstraps_preserve_documented_group_one_exceptions() -> None:
    async def exercise(client: _InProcessASGIClient) -> None:
        one_response = await client.get("/api/v1/groups/1/top/bootstrap")
        two_response = await client.get("/api/v1/groups/2/top/bootstrap")
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
        assert one_response.headers["etag"].startswith('"top-player-inventory-v1-')
        assert two_response.headers["etag"].startswith('"top-player-inventory-v1-')

        # The previous generic api1 validator could incorrectly return a 304
        # after TOP's public contract changed while source files stayed fixed.
        stale_top_etags = (
            f'"group-2-top-api1-{two["metadata"]["dataset_version"]}"',
            f'"group-2-top-v2-{two["metadata"]["dataset_version"]}"',
        )
        for stale_etag in stale_top_etags:
            refreshed = await client.get(
                "/api/v1/groups/2/top/bootstrap",
                headers={"If-None-Match": stale_etag},
            )
            assert refreshed.status_code == 200
            assert refreshed.headers["etag"] == two_response.headers["etag"]
            assert refreshed.json()["foreigners_summary"] == two["foreigners_summary"]
        current = await client.get(
            "/api/v1/groups/2/top/bootstrap",
            headers={"If-None-Match": two_response.headers["etag"]},
        )
        assert current.status_code == 304

        # The legacy alias shares the projected inventory validator too.
        legacy = await client.get("/api/v1/group2/top/bootstrap")
        assert legacy.status_code == 200
        assert legacy.headers["etag"].startswith('"top-player-inventory-v1-')
        legacy_current = await client.get(
            "/api/v1/group2/top/bootstrap",
            headers={"If-None-Match": legacy.headers["etag"]},
        )
        assert legacy_current.status_code == 304

    _run_with_api(create_app(ApiSettings.from_env()), exercise)


def test_shared_referees_keep_group_specific_counts_and_exact_match_provenance() -> None:
    async def exercise(client: _InProcessASGIClient) -> None:
        one = await client.get("/api/v1/groups/1/referees/bootstrap")
        two = await client.get("/api/v1/groups/2/referees/bootstrap")
        assert one.status_code == two.status_code == 200
        payload = one.json()
        counts = payload["availability"]["scope_counts"]
        assert payload["metadata"]["group"] == "I/II"
        assert counts["group1"]["referee_count"] == 43
        assert counts["group2"]["referee_count"] == 42
        assert counts["all"]["referee_count"] == 60
        assert one.headers["etag"].startswith('"group-1-referees-v1-')
        assert two.headers["etag"].startswith('"group-2-referees-v1-')
        assert payload["metadata"]["related_match_datasets"]["I"]["capture_id"] == (
            "20261010T202500.293648Z-b770724f"
        )
        assert payload["metadata"]["related_match_datasets"]["II"]["capture_id"] == (
            "20261010T102656.252222Z-72f200ad"
        )
        assert one.headers["etag"] != two.headers["etag"]

    _run_with_api(create_app(ApiSettings.from_env()), exercise)


def test_statistics_are_bound_to_the_matching_group_and_legacy_aliases_stay_live() -> None:
    settings = ApiSettings.from_env()

    async def exercise(client: _InProcessASGIClient) -> None:
        one = await client.get("/api/v1/groups/1/statistics/bootstrap")
        two = await client.get("/api/v1/groups/2/statistics/bootstrap")
        legacy = await client.get("/api/v1/group2/bootstrap")
        assert one.status_code == two.status_code == legacy.status_code == 200
        assert one.json()["statistics"]["group"] == "I"
        assert one.headers["etag"].startswith('"group-1-statistics-v1-')
        assert one.json()["statistics"]["played_matches"] == _played_match_count(settings, "1")
        assert one.json()["statistics"]["goals"] == 156
        assert one.json()["statistics"]["home_wins"] == 29
        assert one.json()["statistics"]["away_wins"] == 16
        assert one.json()["statistics"]["draws"] == 15
        assert one.json()["statistics"]["yellow_cards"] == 273
        assert one.json()["statistics"]["red_cards"] == 20
        assert two.json()["statistics"]["group"] == "II"
        assert two.headers["etag"].startswith('"group-2-statistics-v1-')
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

    _run_with_api(create_app(settings), exercise)


def test_unknown_groups_and_group_specific_section_failures_are_isolated(tmp_path: Path) -> None:
    configured = ApiSettings.from_env()
    assert configured.group1_settings is not None
    broken_group1 = replace(
        configured.group1_settings,
        top_players_path=tmp_path / "missing-group1-players.json",
    )
    isolated = replace(configured, group1_settings=broken_group1)
    async def exercise(client: _InProcessASGIClient) -> None:
        assert (await client.get("/api/v1/groups/3/bootstrap")).status_code == 404
        assert (await client.get("/api/v1/groups/1/bootstrap")).status_code == 200
        assert (await client.get("/api/v1/groups/2/bootstrap")).status_code == 200
        assert (await client.get("/api/v1/groups/1/top/bootstrap")).status_code == 503
        assert (await client.get("/api/v1/groups/2/top/bootstrap")).status_code == 200
        assert (await client.get("/api/v1/groups/1/statistics/bootstrap")).status_code == 200

    _run_with_api(create_app(isolated), exercise)


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
    async def exercise(client: _InProcessASGIClient) -> None:
        assert (await client.get("/api/v1/groups/1/bootstrap")).status_code == 503
        assert (await client.get("/api/v1/groups/2/bootstrap")).status_code == 200
        assert (await client.get("/api/v1/groups/1/referees/bootstrap")).status_code == 503
        group2_referees = await client.get("/api/v1/groups/2/referees/bootstrap")
        assert group2_referees.status_code == 200
        assert group2_referees.json()["metadata"]["group"] == "I/II"
        assert set(group2_referees.json()["metadata"]["related_match_datasets"]) == {"II"}

    _run_with_api(create_app(isolated), exercise)


def test_group_one_top_catalog_is_resolved_through_configured_group_paths() -> None:
    settings = ApiSettings.from_env()
    group1 = settings.for_group("1")
    assert group1.top_team_catalog_path == group1.matches_path
    assert group1.top_team_catalog_path is not None
    assert group1.top_team_catalog_path.name == "matches.json"
