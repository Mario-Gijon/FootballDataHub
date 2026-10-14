from __future__ import annotations

import json
from pathlib import Path

import pytest
from types import SimpleNamespace

from football_data_hub.providers.bdfutbol.players.batch import (
    PlayerBatchAlreadyRunning,
    PlayerBatchLock,
    PlayerDiskSpaceGuard,
    PlayerDiskSpaceLow,
    estimate_acquisition_storage,
    ordered_player_ids,
    validate_player_batch_completion,
)


def test_player_order_is_roster_then_transfer_only_each_by_id() -> None:
    inventory = {"records": [
        {"player_id": 40, "membership_count": 0},
        {"player_id": 11, "membership_count": 2},
        {"player_id": 9, "membership_count": 1},
        {"player_id": 30, "membership_count": 0},
    ]}

    ordered, cohorts = ordered_player_ids(inventory)

    assert ordered == [9, 11, 30, 40]
    assert [cohorts[player_id] for player_id in ordered] == [
        "roster", "roster", "transfer_only", "transfer_only",
    ]


def test_player_order_rejects_duplicate_or_missing_ids() -> None:
    with pytest.raises(ValueError, match="duplicado"):
        ordered_player_ids({"records": [
            {"player_id": 7, "membership_count": 1},
            {"player_id": 7, "membership_count": 0},
        ]})
    with pytest.raises(ValueError, match="sin player_id"):
        ordered_player_ids({"records": [{"membership_count": 1}]})


def test_mass_acquisition_lock_rejects_a_second_owner(tmp_path: Path) -> None:
    root = tmp_path / "captures"
    with PlayerBatchLock(root):
        with pytest.raises(PlayerBatchAlreadyRunning, match="Ya existe una adquisición"):
            with PlayerBatchLock(root):
                pass


def test_storage_estimate_uses_all_views_and_honors_free_space_reserve() -> None:
    views = ("profile", "statistics", "matches", "rivals")
    reference = {"compressed_bytes": 100, "metadata_bytes": 50}
    player = {
        "views_pending": [],
        "view_snapshots": {view: reference for view in views},
    }
    estimate = estimate_acquisition_storage(
        progress={"players": [player]},
        inventory_player_count=2,
        compact_entries=[{"bytes": 1000}, {"bytes": 1200}],
        available_bytes=4 * 1024**3,
        reserved_free_bytes=1024**3,
        overhead_bytes=64 * 1024**2,
    )
    assert estimate["pending_by_view"] == {view: 0 for view in views}
    assert estimate["estimated_raw_and_metadata_bytes"] == 0
    assert estimate["compact_sample_mean_bytes"] == 1100
    assert estimate["sufficient_margin"] is True

    blocked = estimate_acquisition_storage(
        progress={"players": [{**player, "views_pending": list(views)}]},
        inventory_player_count=1000,
        compact_entries=[{"bytes": 1_000_000}],
        available_bytes=2 * 1024**3,
        reserved_free_bytes=1024**3,
        overhead_bytes=64 * 1024**2,
    )
    assert blocked["sufficient_margin"] is False


def test_dynamic_disk_guard_stops_before_navigation_when_free_space_falls(tmp_path: Path) -> None:
    free_bytes = iter((2 * 1024**3, 100 * 1024**2))
    guard = PlayerDiskSpaceGuard(
        capture_root=tmp_path,
        inventory_player_count=2,
        compact_entries=[{"bytes": 1000}],
        reserved_free_bytes=1024**3,
        usage_provider=lambda _path: SimpleNamespace(free=next(free_bytes)),
    )
    progress = {
        "players": [{
            "views_pending": ["profile"],
            "view_snapshots": {
                "statistics": {"compressed_bytes": 100, "metadata_bytes": 100},
                "matches": {"compressed_bytes": 100, "metadata_bytes": 100},
                "rivals": {"compressed_bytes": 100, "metadata_bytes": 100},
            },
        }, {
            "views_pending": [],
            "view_snapshots": {
                "profile": {"compressed_bytes": 100, "metadata_bytes": 100},
            },
        }],
    }
    assert guard.check_before_navigation(
        progress=progress,
        player_id=501,
        view="profile",
        requested_url="https://www.bdfutbol.com/es/j/j501.html",
    )["sufficient_margin"]
    with pytest.raises(PlayerDiskSpaceLow) as exc_info:
        guard.check_before_navigation(
            progress=progress,
            player_id=501,
            view="profile",
            requested_url="https://www.bdfutbol.com/es/j/j501.html",
        )
    assert exc_info.value.error_code == "DISK_SPACE_LOW"
    assert exc_info.value.diagnostic["available_bytes"] == 100 * 1024**2
    assert exc_info.value.diagnostic["required_reserved_bytes"] == 1024**3


def test_dynamic_disk_guard_refuses_snapshot_that_would_consume_reserve(tmp_path: Path) -> None:
    guard = PlayerDiskSpaceGuard(
        capture_root=tmp_path,
        inventory_player_count=1,
        compact_entries=[{"bytes": 1000}],
        reserved_free_bytes=1024**3,
        usage_provider=lambda _path: SimpleNamespace(free=1024**3 + 32 * 1024),
    )
    with pytest.raises(PlayerDiskSpaceLow) as exc_info:
        guard.check_before_snapshot(
            html="<html>payload</html>",
            player_id=501,
            view="profile",
            requested_url="https://www.bdfutbol.com/es/j/j501.html",
        )
    assert exc_info.value.diagnostic["stage"] == "before_snapshot_write"


def test_global_completion_requires_all_expected_players_and_four_verified_views() -> None:
    views = ("profile", "statistics", "matches", "rivals")
    complete = {
        "summary": {
            "inventory_players": 1,
            "players_with_all_base_views": 1,
            "players_pending": 0,
            "base_view_navigations_pending": 0,
            "captured_valid_base_views": 4,
            "players_with_access_errors": 0,
            "blocked_base_views": 0,
        },
        "players": [{
            "player_id": 501,
            "status": "COMPLETE_BASE_VIEWS",
            "views_pending": [],
            "view_snapshots": {
                view: {
                    "http_status": 200,
                    "access_status": "VALID",
                    "parse_validation": {"status": "VALID"},
                    "html_sha256": f"{index:064x}",
                }
                for index, view in enumerate(views, start=1)
            },
        }],
        "corrupt_manifests": [],
    }
    report = validate_player_batch_completion(complete, expected_player_count=1)
    assert report["valid"] is True
    assert report["verified_player_view_pairs"] == 4

    incomplete = json.loads(json.dumps(complete))
    incomplete["players"][0]["view_snapshots"]["rivals"] = None
    incomplete["summary"].update({
        "players_with_all_base_views": 0,
        "players_pending": 1,
        "base_view_navigations_pending": 1,
        "captured_valid_base_views": 3,
    })
    report = validate_player_batch_completion(incomplete, expected_player_count=1)
    assert report["valid"] is False
    assert report["verified_player_view_pairs"] == 3
    assert {item["view"] for item in report["missing_player_view_pairs"]} == {"rivals"}


def test_corrupt_manifest_blocks_global_completion_even_if_capture_run_is_complete() -> None:
    progress = {
        "summary": {
            "inventory_players": 0,
            "players_with_all_base_views": 0,
            "players_pending": 0,
            "base_view_navigations_pending": 0,
            "captured_valid_base_views": 0,
            "players_with_access_errors": 0,
            "blocked_base_views": 0,
        },
        "players": [],
        "corrupt_manifests": ["capture-corrupt"],
    }
    assert not validate_player_batch_completion(progress, expected_player_count=0)["valid"]
