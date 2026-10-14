from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import pytest

from football_data_hub.providers.bdfutbol.players.acquisition import (
    PLAYER_VIEWS,
    _non_default_option,
    _identity_evidence,
    load_inventory_players,
    player_view_url,
)
from football_data_hub.providers.bdfutbol.players.capture_store import PlayerCaptureStore


def test_player_view_urls_are_explicit_and_semantic() -> None:
    assert PLAYER_VIEWS == ("profile", "statistics", "matches", "rivals")
    assert player_view_url(23751, "profile") == "https://www.bdfutbol.com/es/j/j23751.html"
    assert player_view_url("23751", "statistics") == "https://www.bdfutbol.com/es/j/j23751.html?p=stats"
    assert player_view_url(23751, "matches") == "https://www.bdfutbol.com/es/p/j23751.html"
    assert player_view_url(23751, "rivals") == "https://www.bdfutbol.com/es/p/jr23751.html"
    with pytest.raises(ValueError):
        player_view_url("../23751", "profile")


def test_inventory_resolution_checks_all_requested_player_ids(tmp_path: Path) -> None:
    path = tmp_path / "players.json"
    path.write_text(json.dumps({"records": [
        {"player_id": 23751, "display_name": "Manu Pedreño"},
        {"player_id": 28577, "display_name": "Nacho Castillo"},
    ]}), encoding="utf-8")
    assert load_inventory_players(path, [28577])[28577]["display_name"] == "Nacho Castillo"
    with pytest.raises(ValueError, match="no presentes"):
        load_inventory_players(path, [28577, 209629])


def test_identity_validation_requires_name_and_player_specific_dom_reference() -> None:
    good = '<title>Manu Pedreño | BDFutbol</title><h1>Manu Pedreño</h1><a href="/es/j/j23751.html">Perfil</a>'
    wrong_name = '<title>Otro jugador | BDFutbol</title><h1>Otro jugador</h1><a href="/es/j/j23751.html">Perfil</a>'
    wrong_id = '<title>Manu Pedreño | BDFutbol</title><h1>Manu Pedreño</h1><a href="/es/j/j00001.html">Perfil</a>'
    assert _identity_evidence(good, 23751, "Manu Pedreño") == ()
    assert _identity_evidence(wrong_name, 23751, "Manu Pedreño")
    assert _identity_evidence(wrong_id, 23751, "Manu Pedreño")


def test_filter_probe_skips_all_rows_before_selecting_a_real_filter_value() -> None:
    options = [
        {"value": "*", "text": "Todos"},
        {"value": "2025-26", "text": "2025-26"},
    ]
    assert _non_default_option(options, "") == options[1]
    assert _non_default_option([{"value": "-", "text": "-"}], "-") is None


def test_capture_store_saves_immutable_gzip_and_recoverable_manifest(tmp_path: Path) -> None:
    store = PlayerCaptureStore(tmp_path, capture_id="pilot-001")
    html = "<html><title>Player</title></html>"
    metadata = store.save_snapshot(
        player_id=23751,
        view="profile",
        requested_url="https://www.bdfutbol.com/es/j/j23751.html",
        final_url="https://www.bdfutbol.com/es/j/j23751.html",
        http_status=200,
        page_title="Player",
        html=html,
        browser={"backend": "seleniumbase-pure-cdp", "uses_xvfb": True},
        controls=[],
    )
    raw_path = store.run_dir / metadata["raw_path"]
    assert gzip.decompress(raw_path.read_bytes()).decode() == html
    assert metadata["html_sha256"] == hashlib.sha256(html.encode()).hexdigest()

    resumed = PlayerCaptureStore(tmp_path, capture_id="pilot-001")
    assert resumed.manifest["snapshots"][0]["html_sha256"] == metadata["html_sha256"]
    resumed.record_diagnostic({"reason": "parser failure", "stop_acquisition": False})
    manifest = json.loads((resumed.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["snapshots"][0]["raw_path"] == metadata["raw_path"]
    assert manifest["diagnostics"][0]["reason"] == "parser failure"


def test_resume_refuses_manifest_for_a_different_capture_id(tmp_path: Path) -> None:
    store = PlayerCaptureStore(tmp_path, capture_id="pilot-002")
    manifest_path = store.run_dir / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["capture_id"] = "wrong-id"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="no coincide"):
        PlayerCaptureStore(tmp_path, capture_id="pilot-002")


def test_navigation_ledger_reconciles_only_from_saved_evidence(tmp_path: Path) -> None:
    store = PlayerCaptureStore(tmp_path, capture_id="ledger-001")
    url = "https://www.bdfutbol.com/es/j/j23751.html"
    for html in ("<h1>First</h1>", "<h1>Second</h1>"):
        store.save_snapshot(
            player_id=23751,
            view="profile",
            requested_url=url,
            final_url=url,
            http_status=200,
            page_title="Player",
            html=html,
            browser={"backend": "seleniumbase-pure-cdp"},
        )
    store.record_navigation({
        "player_id": 23751,
        "view": "profile",
        "requested_url": url,
        "final_url": url,
        "http_status": 200,
        "access_status": "VALID",
        "captured_at_utc": "2026-10-14T00:00:00Z",
    })
    store.record_diagnostic({
        "player_id": 23751,
        "view": "rivals",
        "requested_url": "https://www.bdfutbol.com/es/p/jr23751.html",
        "final_url": "https://www.bdfutbol.com/es/p/jr23751.html",
        "http_status": 200,
        "access_status": "INVALID_CONTENT",
        "captured_at_utc": "2026-10-14T00:00:01Z",
        "stop_acquisition": True,
    })
    store.reconcile_navigation_ledger()
    assert store.manifest["navigation_count_total"] == 3
    assert store.manifest["successful_navigation_count"] == 2
    assert store.manifest["non_valid_navigation_count"] == 1
