from __future__ import annotations

from pathlib import Path

import pytest

from football_data_hub.providers.bdfutbol.players.batch import (
    PlayerBatchAlreadyRunning,
    PlayerBatchLock,
    estimate_acquisition_storage,
    ordered_player_ids,
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
        inventory_player_count=1,
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
