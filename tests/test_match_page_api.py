"""Contract and route coverage for the read-only MATCH-00 match page."""

from __future__ import annotations

from fastapi import HTTPException, Request, Response
from football_data_hub_api.config import ApiSettings
from football_data_hub_api.main import create_app
from football_data_hub_api.match_results_dataset import MatchResultsBundle
from football_data_hub_api.schemas import MatchGenerationBootstrapResponse


def _team(team_id: int, name: str) -> dict[str, object]:
    return {"team_id": team_id, "name": name, "team_url": None, "crest_url": None}


def _match(
    group: str,
    source_id: str,
    home_id: int,
    away_id: int,
    *,
    status: str,
    home_goals: int | None,
    away_goals: int | None,
    source_match_date: str | None = "2026-10-10",
) -> dict[str, object]:
    return {
        "internal_id": f"pf-2026-27-group-{group.lower()}-bdfutbol-{source_id}",
        "source_match_id": source_id,
        "matchday": 6,
        "matchday_date": "2026-10-10",
        "source_match_date": source_match_date,
        "home_team_id": home_id,
        "away_team_id": away_id,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "home_yellow_cards": None,
        "away_yellow_cards": None,
        "home_red_cards": None,
        "away_red_cards": None,
        "status": status,
        "unplayed_state": "scheduled" if status == "unplayed" else None,
        "postponed_by_source_rule": None,
        "source_match_url": (
            f"https://www.bdfutbol.com/es/p/p.php?id={source_id}"
            if status == "played"
            else None
        ),
        "stadium_id": None,
        "stadium_name": None,
        "stadium_url": None,
        "referee_id": None,
        "referee_name": None,
        "referee_url": None,
    }


def _bundle() -> MatchResultsBundle:
    group_one_matches = [
        _match("I", "272582", 1, 2, status="unplayed", home_goals=None, away_goals=None, source_match_date=None)
    ]
    group_two_matches = [
        _match("II", "272582", 49, 88, status="played", home_goals=3, away_goals=3),
        _match("II", "272525", 49, 89, status="played", home_goals=0, away_goals=0, source_match_date="2026-08-31"),
    ]

    def group(code: str, teams: list[dict[str, object]], matches: list[dict[str, object]]) -> dict[str, object]:
        return {
            "group": code,
            "source_capture_id": f"capture-{code}",
            "source_captured_at": "2026-10-14T10:00:00+00:00",
            "teams": teams,
            "matches": matches,
            "scheduled_matchdays": [6],
            "counts": {
                "teams": len(teams),
                "matches": len(matches),
                "played": sum(match["status"] == "played" for match in matches),
                "unplayed": sum(match["status"] == "unplayed" for match in matches),
                "incomplete": sum(match["status"] == "incomplete" for match in matches),
            },
        }

    bootstrap = MatchGenerationBootstrapResponse.model_validate({
        "metadata": {
            "schema_version": 1,
            "source": "BDFutbol",
            "competition": "Primera Federación",
            "season": "2026-27",
            "generation_id": "match-00-test-generation",
            "generation_sha256": "a" * 64,
            "captured_at": "2026-10-14T10:00:00+00:00",
            "team_count": 5,
            "match_count": 3,
            "played_count": 2,
            "unplayed_count": 1,
            "incomplete_count": 0,
        },
        "groups": {
            "I": group("I", [_team(1, "Pontevedra"), _team(2, "Zamora")], group_one_matches),
            "II": group("II", [_team(49, "Real Jaén"), _team(88, "Villarreal B"), _team(89, "Real Madrid Castilla")], group_two_matches),
        },
    })
    return MatchResultsBundle(bootstrap=bootstrap, etag='"match-generation"')


def _app():
    app = create_app(ApiSettings.from_env())
    app.state.match_results = _bundle()
    return app


def _call_endpoint(app, internal_id: str, if_none_match: str | None = None):
    route = next(route for route in app.routes if getattr(route, "path", None) == "/api/v1/matches/{internal_id}")
    headers = [(b"host", b"test")]
    if if_none_match:
        headers.append((b"if-none-match", if_none_match.encode("ascii")))
    path = f"/api/v1/matches/{internal_id}"
    request = Request({
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": headers,
        "client": ("test", 1234),
        "server": ("test", 80),
        "root_path": "",
        "app": app,
    })
    response = Response()
    result = route.endpoint(internal_id, request, response)
    return result, response


def test_match_page_serves_verified_scores_zero_zero_and_pending_without_details() -> None:
    app = _app()
    jaen, _ = _call_endpoint(app, "pf-2026-27-group-ii-bdfutbol-272582")
    nil_nil, _ = _call_endpoint(app, "pf-2026-27-group-ii-bdfutbol-272525")
    pending, _ = _call_endpoint(app, "pf-2026-27-group-i-bdfutbol-272582")

    assert jaen.match.home_goals == jaen.match.away_goals == 3
    assert jaen.details is None
    assert jaen.detail_status == "not_available"
    assert nil_nil.match.home_goals == nil_nil.match.away_goals == 0
    assert pending.metadata.group == "I"
    assert pending.match.home_goals is None
    assert pending.match.away_goals is None
    assert pending.match.status == "unplayed"
    assert pending.match.source_match_date is None


def test_match_page_uses_group_namespaced_identity_and_etag() -> None:
    app = _app()
    group_ii, group_ii_response = _call_endpoint(app, "pf-2026-27-group-ii-bdfutbol-272582")
    group_i, group_i_response = _call_endpoint(app, "pf-2026-27-group-i-bdfutbol-272582")
    cached, cached_response = _call_endpoint(
        app,
        "pf-2026-27-group-ii-bdfutbol-272582",
        group_ii_response.headers["ETag"],
    )

    assert group_ii.match.home_team.name == "Real Jaén"
    assert group_i.match.home_team.name == "Pontevedra"
    assert group_i_response.headers["ETag"] != group_ii_response.headers["ETag"]
    assert isinstance(cached, Response)
    assert cached.status_code == 304
    assert cached_response.headers["ETag"] == group_ii_response.headers["ETag"]
    try:
        _call_endpoint(app, "pf-2026-27-group-ii-bdfutbol-999999")
    except HTTPException as error:
        assert error.status_code == 404
    else:
        raise AssertionError("Un partido desconocido debe responder 404.")
