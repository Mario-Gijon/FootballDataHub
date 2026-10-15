from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import football_data_hub.providers.bdfutbol.players.acquisition as acquisition
from football_data_hub.providers.bdfutbol.access import (
    AccessAssessment,
    AccessStatus,
    BDFutbolVisit,
)
from football_data_hub.providers.bdfutbol.players.acquisition import (
    PLAYER_VIEWS,
    PlayerAcquisitionStopped,
    STOP_ON_UNVERIFIED_HTTP_ERROR,
    access_policy_is_complete,
    access_policy_matrix,
    acquire_player_views,
    enforce_access_policy,
    player_view_url,
)


def _assessment(status: AccessStatus, http_status: int | None) -> AccessAssessment:
    url = player_view_url(501, "profile")
    return AccessAssessment(
        status=status,
        requested_url=url,
        final_url=url,
        http_status=http_status,
        page_title="Jugador de prueba" if status is AccessStatus.VALID else "Error",
        reason=f"HTTP {http_status}" if http_status is not None else "sin estado HTTP",
        missing_dom_evidence=("ID de jugador contradictorio",)
        if status is AccessStatus.INVALID_CONTENT else (),
    )


def test_http_policy_is_exhaustive_and_only_valid_http_200_can_continue() -> None:
    assert access_policy_is_complete()
    matrix = access_policy_matrix()
    assert matrix[AccessStatus.VALID.value] == "CONTINUE_ONLY_WITH_HTTP_200"
    assert all(value == "STOP" for key, value in matrix.items() if key != AccessStatus.VALID.value)
    enforce_access_policy(
        _assessment(AccessStatus.VALID, 200),
        player_id=501,
        view="profile",
        requested_url=player_view_url(501, "profile"),
        visit_available=True,
    )


@pytest.mark.parametrize(
    ("status", "http_status", "error_code"),
    [
        (AccessStatus.HTTP_ERROR, 404, "HTTP_404_STOPPED"),
        (AccessStatus.HTTP_ERROR, 503, "HTTP_503_STOPPED"),
        (AccessStatus.HTTP_ERROR, 403, "HTTP_403_STOPPED"),
        (AccessStatus.HTTP_ERROR, 429, "HTTP_429_STOPPED"),
        (AccessStatus.HTTP_ERROR, None, AccessStatus.HTTP_ERROR.value),
        (AccessStatus.CHALLENGE_REQUIRED, 200, AccessStatus.CHALLENGE_REQUIRED.value),
        (AccessStatus.INVALID_CONTENT, 200, AccessStatus.INVALID_CONTENT.value),
        (AccessStatus.NAVIGATION_ERROR, None, AccessStatus.NAVIGATION_ERROR.value),
    ],
)
def test_every_unverified_access_result_stops(status, http_status, error_code) -> None:
    url = player_view_url(501, "profile")
    with pytest.raises(PlayerAcquisitionStopped) as exc_info:
        enforce_access_policy(
            _assessment(status, http_status),
            player_id=501,
            view="profile",
            requested_url=url,
            visit_available=False,
        )
    assert exc_info.value.error_code == error_code
    assert exc_info.value.diagnostic["policy"] == STOP_ON_UNVERIFIED_HTTP_ERROR
    assert exc_info.value.diagnostic["player_id"] == 501
    assert exc_info.value.diagnostic["view"] == "profile"
    assert exc_info.value.diagnostic["requested_url"] == url
    assert exc_info.value.diagnostic["http_status"] == http_status
    assert exc_info.value.diagnostic["recorded_at_utc"]
    assert exc_info.value.diagnostic["stop_acquisition"] is True
    assert exc_info.value.diagnostic["classification"] == "unverified_http_or_content_error"


def test_identity_contradiction_stops_even_when_http_is_200() -> None:
    url = player_view_url(501, "profile")
    with pytest.raises(PlayerAcquisitionStopped) as exc_info:
        enforce_access_policy(
            _assessment(AccessStatus.INVALID_CONTENT, 200),
            player_id=501,
            view="profile",
            requested_url=url,
            visit_available=True,
        )
    assert exc_info.value.diagnostic["missing_dom_evidence"] == ["ID de jugador contradictorio"]


def test_http_404_records_checkpoint_and_does_not_visit_next_player_or_mutate_old_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture_root = tmp_path / "captures"
    old_raw = capture_root / "old-capture" / "raw" / "previous.html.gz"
    old_raw.parent.mkdir(parents=True)
    old_raw.write_bytes(b"immutable-old-capture")
    old_hash = hashlib.sha256(old_raw.read_bytes()).hexdigest()
    inventory_path = tmp_path / "inventory.json"
    records = [
        {"player_id": 501, "display_name": "Jugador 501", "full_name": None},
        {"player_id": 502, "display_name": "Jugador 502", "full_name": None},
    ]
    inventory_raw = json.dumps({"metadata": {"season": "2026-27"}, "records": records}).encode()
    inventory_path.write_bytes(inventory_raw)
    progress = {
        "inventory": {"sha256": hashlib.sha256(inventory_raw).hexdigest()},
        "capture_root": str(capture_root.resolve()),
        "players": [
            {"player_id": player_id, "view_snapshots": {view: None for view in PLAYER_VIEWS}}
            for player_id in (501, 502)
        ],
        "pending_views": [
            {"player_id": player_id, "view": "profile"} for player_id in (501, 502)
        ],
    }

    class FakeSessionManager:
        def __init__(self, _config):
            self.info = None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    calls: list[str] = []

    class FakeAccess:
        def __init__(self, _session):
            pass

        def open(self, url, **_kwargs):
            calls.append(url)
            return BDFutbolVisit(_assessment(AccessStatus.HTTP_ERROR, 404), None)

    monkeypatch.setattr(acquisition, "BrowserSessionManager", FakeSessionManager)
    monkeypatch.setattr(acquisition, "BDFutbolAccess", FakeAccess)

    with pytest.raises(PlayerAcquisitionStopped) as exc_info:
        acquire_player_views(
            player_ids=[501, 502],
            inventory_path=inventory_path,
            capture_root=capture_root,
            profile_dir=tmp_path / "profile",
            capture_id="http404-policy",
            settle_ms=0,
            pause_seconds=0,
            explore_filters=False,
            views=("profile",),
            progress_index=progress,
        )

    assert len(calls) == 1
    assert calls == [player_view_url(501, "profile")]
    assert exc_info.value.error_code == "HTTP_404_STOPPED"
    manifest_path = capture_root / "http404-policy" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    diagnostic = manifest["diagnostics"][-1]
    assert manifest["status"] == "stopped"
    assert diagnostic["player_id"] == 501
    assert diagnostic["view"] == "profile"
    assert diagnostic["requested_url"] == player_view_url(501, "profile")
    assert diagnostic["http_status"] == 404
    assert diagnostic["access_status"] == AccessStatus.HTTP_ERROR.value
    assert diagnostic["error_code"] == "HTTP_404_STOPPED"
    assert diagnostic["classification"] == "unverified_http_or_content_error"
    assert manifest["snapshots"] == []
    assert hashlib.sha256(old_raw.read_bytes()).hexdigest() == old_hash


def test_document_read_failure_is_attributed_and_preserves_existing_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture_root = tmp_path / "captures"
    old_raw = capture_root / "old-capture" / "raw" / "verified.html.gz"
    old_raw.parent.mkdir(parents=True)
    old_raw.write_bytes(b"previous verified capture")
    old_hash = hashlib.sha256(old_raw.read_bytes()).hexdigest()
    inventory_path = tmp_path / "inventory.json"
    inventory_raw = json.dumps({
        "metadata": {"season": "2026-27"},
        "records": [
            {"player_id": player_id, "display_name": f"Jugador {player_id}", "full_name": None}
            for player_id in (501, 502)
        ],
    }).encode()
    inventory_path.write_bytes(inventory_raw)
    progress = {
        "inventory": {"sha256": hashlib.sha256(inventory_raw).hexdigest()},
        "capture_root": str(capture_root.resolve()),
        "players": [
            {"player_id": player_id, "view_snapshots": {view: None for view in PLAYER_VIEWS}}
            for player_id in (501, 502)
        ],
        "pending_views": [
            {"player_id": player_id, "view": "profile"} for player_id in (501, 502)
        ],
    }

    class FakeSessionManager:
        def __init__(self, _config):
            self.info = None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    calls: list[str] = []

    class FakeAccess:
        def __init__(self, _session):
            pass

        def open(self, url, **_kwargs):
            calls.append(url)
            assessment = AccessAssessment(
                status=AccessStatus.DOCUMENT_ERROR,
                requested_url=url,
                final_url=url,
                http_status=200,
                page_title="Jugador de prueba",
                reason="No se pudo inspeccionar el DOM: Element {body} timeout",
            )
            return BDFutbolVisit(assessment, None)

    monkeypatch.setattr(acquisition, "BrowserSessionManager", FakeSessionManager)
    monkeypatch.setattr(acquisition, "BDFutbolAccess", FakeAccess)

    with pytest.raises(PlayerAcquisitionStopped) as exc_info:
        acquire_player_views(
            player_ids=[501, 502],
            inventory_path=inventory_path,
            capture_root=capture_root,
            profile_dir=tmp_path / "profile",
            capture_id="document-read-stop",
            settle_ms=0,
            pause_seconds=0,
            explore_filters=False,
            views=("profile",),
            progress_index=progress,
        )

    assert calls == [player_view_url(501, "profile")]
    assert exc_info.value.status == f"{AccessStatus.DOCUMENT_ERROR.value} (200)"
    manifest = json.loads((capture_root / "document-read-stop" / "manifest.json").read_text())
    diagnostic = manifest["diagnostics"][-1]
    assert manifest["status"] == "stopped"
    assert diagnostic["player_id"] == 501
    assert diagnostic["view"] == "profile"
    assert diagnostic["requested_url"] == player_view_url(501, "profile")
    assert diagnostic["http_status"] == 200
    assert diagnostic["access_status"] == AccessStatus.DOCUMENT_ERROR.value
    assert diagnostic["classification"] == "document_inspection_error"
    assert diagnostic["failure_stage"] == "document_inspection"
    assert manifest["snapshots"] == []
    assert hashlib.sha256(old_raw.read_bytes()).hexdigest() == old_hash
