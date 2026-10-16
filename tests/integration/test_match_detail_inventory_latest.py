from __future__ import annotations

import hashlib
import json
import os
import socket
import urllib.request
from pathlib import Path

import pytest

from football_data_hub.providers.bdfutbol.match_details.inventory import (
    build_match_detail_inventory,
    load_verified_match_generation,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("FDH_MATCH_01A_INTEGRATION") != "1",
    reason="Requiere el almacén local externo de MATCH-00 del 14/10/2026",
)


def test_latest_match_generation_yields_140_offline_detail_targets(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Esta integración no debe utilizar la red")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)

    data_root = Path(
        os.environ.get("FDH_MATCH_01A_DATA_ROOT", Path.home() / "FootballDataHub-data")
    )
    generation_root = data_root / "matches/generations/match-00-4ad1d610507e425d"
    manifest_path = generation_root / "manifest.json"
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_files = [
        manifest_path,
        generation_root / "matches.json",
        generation_root / "validation.json",
    ]
    source_files.extend(
        data_root / capture["files"][key]["path"]
        for capture in manifest_payload["source_captures"]
        for key in ("capture_metadata", "source_html", "normalized_matches")
    )
    source_hashes_before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files
    }
    verified = load_verified_match_generation(generation_root, data_root=data_root)
    inventory = build_match_detail_inventory(verified)

    assert verified.generation_id == "match-00-4ad1d610507e425d"
    assert inventory["counts"] == {
        "matches": 140,
        "groups": {"I": 70, "II": 70},
        "unique_internal_ids": 140,
        "unique_source_ids": 140,
        "unique_urls": 140,
        "played_without_explicit_url": 0,
    }
    assert len({record["source_match_id"] for record in inventory["matches"]}) == 140
    assert all(record["acquisition_status"] == "pending" for record in inventory["matches"])
    assert all(record["validation_status"] == "not_acquired" for record in inventory["matches"])
    assert all(
        record["source_match_url"].startswith("https://www.bdfutbol.com/es/p/p.php?id=")
        for record in inventory["matches"]
    )
    assert source_hashes_before == {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files
    }
