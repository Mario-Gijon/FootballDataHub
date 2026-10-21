"""Historical player inventory remains tied to its exact published team index."""

import hashlib
import json

import pytest

from football_data_hub_api.player_dataset import (
    PlayerDatasetLoadError,
    _verify_inventory_source_index,
)


def _index(capture_id: str, *, team_ids=range(1, 41)) -> bytes:
    return json.dumps({
        "schema_version": 1, "season": "2026-27",
        "profiles": {str(team_id): {"capture_id": capture_id} for team_id in team_ids},
    }, sort_keys=True).encode()


def test_inventory_accepts_exact_historical_backup_after_team_publication(tmp_path):
    path = tmp_path / "team_profiles_2026-27.json"
    original = _index("old")
    path.write_bytes(_index("new"))
    (tmp_path / f"{path.name}.20261021T180000.000000Z.bak").write_bytes(original)
    _verify_inventory_source_index(path, {
        "sha256": hashlib.sha256(original).hexdigest(), "bytes": len(original),
    })


def test_inventory_rejects_missing_or_corrupt_backup(tmp_path):
    path = tmp_path / "team_profiles_2026-27.json"
    original = _index("old")
    path.write_bytes(_index("new"))
    spec = {"sha256": hashlib.sha256(original).hexdigest(), "bytes": len(original)}
    with pytest.raises(PlayerDatasetLoadError, match="copia histórica íntegra"):
        _verify_inventory_source_index(path, spec)
    (tmp_path / f"{path.name}.20261021T180000.000000Z.bak").write_bytes(_index("bad"))
    with pytest.raises(PlayerDatasetLoadError, match="copia histórica íntegra"):
        _verify_inventory_source_index(path, spec)


def test_inventory_rejects_changed_team_identity_even_with_valid_backup(tmp_path):
    path = tmp_path / "team_profiles_2026-27.json"
    original = _index("old")
    path.write_bytes(_index("new", team_ids=range(2, 42)))
    (tmp_path / f"{path.name}.20261021T180000.000000Z.bak").write_bytes(original)
    with pytest.raises(PlayerDatasetLoadError, match="copia histórica íntegra"):
        _verify_inventory_source_index(path, {
            "sha256": hashlib.sha256(original).hexdigest(), "bytes": len(original),
        })
