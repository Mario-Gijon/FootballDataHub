"""The only exposed update write is the loopback-only global competition action."""

from __future__ import annotations

from fastapi import HTTPException, Request

from football_data_hub_api.config import ApiSettings
from football_data_hub_api.main import create_app


class FakeManager:
    enabled = True

    def __init__(self) -> None:
        self.started = False

    def public_status(self, scope: str, team_id: int | None = None) -> dict[str, object]:
        return {"scope": scope, "team_id": team_id, "last_updated_at": None,
                "last_unchanged_check_at": None, "last_checked_at": None}

    def latest(self, scope: str, team_id: int | None = None) -> dict[str, object] | None:
        return {"job_id": "job-a", "scope": scope, "status": "applied", "stage": "completed",
                "summary": {"message": "Actualización aplicada"}, "candidate": {"path": "/private"},
                "candidate_sha256": "secret-hash", "error": None}

    def start(self, **kwargs: object) -> dict[str, object]:
        self.started = True
        assert kwargs == {"scope": "competition"}
        return {"job_id": "job-a", "scope": "competition", "team_id": None, "group": None,
                "status": "queued", "stage": "queued", "created_at": "now", "updated_at": "now",
                "finished_at": None, "summary": None, "error": None, "candidate": {"path": "/private"},
                "candidate_sha256": "secret-hash"}

    def get_job(self, _job_id: str) -> dict[str, object]:
        return self.latest("competition") or {}


def _app_and_manager():
    app = create_app(ApiSettings.from_env())
    manager = FakeManager()
    app.state.manual_update_manager = manager
    return app, manager


def _request(
    app,
    *,
    client: tuple[str, int] = ("127.0.0.1", 5000),
    host: str = "127.0.0.1:8003",
    origin: str | None = "http://127.0.0.1:5178",
    extra_headers: tuple[tuple[bytes, bytes], ...] = (),
) -> Request:
    headers = [(b"host", host.encode())]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    headers.extend(extra_headers)
    return Request({
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "GET", "scheme": "http", "path": "/", "raw_path": b"/",
        "query_string": b"", "headers": headers, "client": client,
        "server": ("127.0.0.1", 8003), "root_path": "", "app": app,
    })


def _route(app, path: str):
    return next(route for route in app.routes if getattr(route, "path", None) == path).endpoint


def test_local_visitor_can_start_and_read_the_global_update_without_credentials() -> None:
    app, manager = _app_and_manager()
    request = _request(app)

    assert _route(app, "/api/v1/updates/status")(request)["scope"] == "competition"
    started = _route(app, "/api/v1/updates/competition")(request)
    assert started["status"] == "queued"
    assert "candidate" not in started and "candidate_sha256" not in started
    latest = _route(app, "/api/v1/updates/latest")(request)
    assert latest["status"] == "applied"
    assert "candidate" not in latest and "candidate_sha256" not in latest
    assert manager.started


def test_update_api_exposes_no_team_update_or_human_approval_routes() -> None:
    app, _manager = _app_and_manager()
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/v1/updates/competition" in paths
    assert "/api/v1/updates/teams/{team_id}" not in paths
    assert "/api/v1/updates/jobs/{job_id}/approve" not in paths
    assert not any(path and path.startswith("/api/v1/admin/updates/") for path in paths)
    assert not hasattr(ApiSettings.from_env(), "update_admin_token")


def test_nonlocal_requests_cannot_read_or_start_updates() -> None:
    app, manager = _app_and_manager()
    requests = [
        _request(app, client=("192.0.2.8", 4321)),
        _request(app, host="updates.example.org"),
        _request(app, origin="https://updates.example.org"),
        _request(app, extra_headers=((b"x-forwarded-for", b"192.0.2.8"),)),
        _request(app, extra_headers=((b"sec-fetch-site", b"cross-site"),)),
    ]
    endpoints = (
        _route(app, "/api/v1/updates/status"),
        _route(app, "/api/v1/updates/competition"),
        _route(app, "/api/v1/updates/latest"),
        lambda request: _route(app, "/api/v1/updates/jobs/{job_id}")("job-a", request),
    )
    for request in requests:
        for endpoint in endpoints:
            try:
                endpoint(request)
            except HTTPException as exc:
                assert exc.status_code == 403
                assert exc.detail["code"] == "local_updates_only"
            else:
                raise AssertionError("Se permitió una petición de actualización no local")
    assert not manager.started


def test_local_host_alias_is_allowed_for_the_global_competition_action() -> None:
    app, manager = _app_and_manager()
    result = _route(app, "/api/v1/updates/competition")(
        _request(app, host="localhost:8003", origin="http://localhost:5178")
    )
    assert result["status"] == "queued"
    assert manager.started
