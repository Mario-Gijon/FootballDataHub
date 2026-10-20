"""Administrative route auth is checked without opening sockets or starting jobs."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request

from football_data_hub_api.config import ApiSettings
from football_data_hub_api.main import create_app


class FakeManager:
    enabled = True

    def __init__(self) -> None:
        self.started = False
        self.start_requests: list[dict[str, object]] = []

    def authenticate(self, supplied: str | None) -> bool:
        return supplied == "test-admin-secret"

    def scope_enabled(self, scope: str) -> bool:
        return scope in {"competition", "team"}

    def public_status(self, scope: str, team_id: int | None = None) -> dict[str, object]:
        return {
            "scope": scope,
            "team_id": team_id,
            "last_updated_at": None,
            "last_unchanged_check_at": None,
            "last_checked_at": None,
        }

    def start(self, **_kwargs: object) -> dict[str, object]:
        self.started = True
        self.start_requests.append(dict(_kwargs))
        return {"status": "queued"}


def _app_and_manager():
    app = create_app(ApiSettings.from_env())
    manager = FakeManager()
    app.state.manual_update_manager = manager
    return app, manager


def _request(app, token: str | None = None) -> Request:
    headers = [(b"host", b"test")]
    if token is not None:
        headers.append((b"x-fdh-admin-token", token.encode()))
    return Request({
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": headers,
        "client": ("test", 1),
        "server": ("test", 80),
        "root_path": "",
        "app": app,
    })


def _route(app, path: str):
    return next(route for route in app.routes if getattr(route, "path", None) == path).endpoint


def test_public_visitors_cannot_query_admin_capabilities_status_or_start_jobs() -> None:
    app, manager = _app_and_manager()
    request = _request(app)
    for endpoint in (
        _route(app, "/api/v1/admin/updates/capabilities"),
        lambda req: _route(app, "/api/v1/admin/updates/status")("competition", req, None),
        _route(app, "/api/v1/admin/updates/competition"),
    ):
        with pytest.raises(HTTPException) as caught:
            endpoint(request)
        assert caught.value.status_code == 401
        assert caught.value.detail["code"] == "admin_auth_required"
    assert manager.started is False
    assert not any(getattr(route, "path", "").startswith("/api/v1/updates/") for route in app.routes)


def test_admin_can_query_only_authenticated_capabilities_and_status() -> None:
    app, _manager = _app_and_manager()
    request = _request(app, "test-admin-secret")
    capabilities = _route(app, "/api/v1/admin/updates/capabilities")(request)
    status = _route(app, "/api/v1/admin/updates/status")("team", request, 49)

    assert capabilities == {"enabled": True, "scopes": ["competition", "team"]}
    assert status["scope"] == "team"
    assert status["team_id"] == 49

    wrong_token_request = _request(app, "wrong")
    with pytest.raises(HTTPException) as caught:
        _route(app, "/api/v1/admin/updates/capabilities")(wrong_token_request)
    assert caught.value.status_code == 401


def test_competition_button_starts_only_competition_scope_without_running_acquisition() -> None:
    app, manager = _app_and_manager()
    request = _request(app, "test-admin-secret")

    result = _route(app, "/api/v1/admin/updates/competition")(request)

    assert result == {"status": "queued"}
    assert manager.start_requests == [{"scope": "competition"}]


def test_team_button_resolves_and_starts_only_the_selected_catalog_team() -> None:
    app, manager = _app_and_manager()
    app.state.datasets = {
        "2": SimpleNamespace(bootstrap=SimpleNamespace(teams=[SimpleNamespace(team_id=49)])),
    }
    request = _request(app, "test-admin-secret")

    result = _route(app, "/api/v1/admin/updates/teams/{team_id}")(49, request)

    assert result == {"status": "queued"}
    assert manager.start_requests == [{"scope": "team", "team_id": 49, "group": "II"}]
