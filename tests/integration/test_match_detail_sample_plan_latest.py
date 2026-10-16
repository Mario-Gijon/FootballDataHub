from __future__ import annotations

import os
import socket
import urllib.request
from pathlib import Path

import pytest

from football_data_hub.providers.bdfutbol.match_details.sampling_plan import (
    build_offline_sample_plan,
    tree_sha256,
)


pytestmark = pytest.mark.integration


def test_latest_verified_generation_produces_expected_offline_sample(monkeypatch):
    if os.environ.get("FDH_MATCH_01C_C_INTEGRATION") != "1":
        pytest.skip("Activa FDH_MATCH_01C_C_INTEGRATION=1 para usar el almacén local")

    def forbidden(*args, **kwargs):
        raise AssertionError("La preparación MATCH-01C-C no puede acceder a la red")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)

    data_root = Path(
        os.environ.get("FDH_MATCH_01C_C_DATA_ROOT", Path.home() / "FootballDataHub-data")
    ).expanduser()
    generation_root = data_root / "matches/generations/match-00-4ad1d610507e425d"
    inventory_dir = (
        data_root
        / "matches/details/inventories/match-detail-inventory-8cf339654c80c0ef"
    )
    store_root = data_root / "matches/details"
    before = {
        "generation": tree_sha256(generation_root),
        "inventory": tree_sha256(inventory_dir),
        "store": tree_sha256(store_root),
    }

    report = build_offline_sample_plan(
        generation_root=generation_root,
        inventory_dir=inventory_dir,
        data_root=data_root,
        store_root=store_root,
    )

    after = {
        "generation": tree_sha256(generation_root),
        "inventory": tree_sha256(inventory_dir),
        "store": tree_sha256(store_root),
    }
    assert before == after
    assert report["source"]["generation_id"] == "match-00-4ad1d610507e425d"
    assert report["source"]["record_count"] == 140
    assert report["source"]["inventory_id"] == "match-detail-inventory-8cf339654c80c0ef"
    assert [item["source_match_id"] for item in report["candidates"]] == [
        "272525",
        "272517",
        "272577",
        "272524",
        "269411",
    ]
    assert report["status"] == "BLOCKED"
    assert report["store"]["active_stop"] is True
    assert report["store"]["checkpoint_status"] == "stopped"
    assert report["campaign"]["legacy_pilot_stop"]["diagnostic"]["error_code"] == (
        "IDENTITY_OR_CONTENT_UNVERIFIED"
    )
