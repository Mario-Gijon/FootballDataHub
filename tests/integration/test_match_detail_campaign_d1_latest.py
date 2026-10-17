"""Opt-in, read-only verification of the actual historical stop evidence."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import urllib.request
from pathlib import Path

import pytest

from football_data_hub.providers.bdfutbol.match_details.historical_review import (
    verify_historical_stop_evidence,
)
from football_data_hub.providers.bdfutbol.match_details.sampling_plan import (
    build_offline_sample_plan,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("FDH_MATCH_01C_D1_INTEGRATION") != "1",
    reason="Opt-in local-only verification; no download or browser is used",
)


def _tree_hashes(paths: list[Path]) -> dict[str, str]:
    result: dict[str, str] = {}
    for root in paths:
        if root.is_file():
            result[str(root)] = hashlib.sha256(root.read_bytes()).hexdigest()
            continue
        if root.is_dir():
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    result[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def test_current_272582_evidence_is_verified_offline_without_mutation(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("D1 evidence verification must not perform network I/O")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    data_root = Path(
        os.environ.get("FDH_MATCH_01C_DATA_ROOT", Path.home() / "FootballDataHub-data")
    ).expanduser()
    generation_root = data_root / "matches/generations/match-00-4ad1d610507e425d"
    inventory_dir = (
        data_root
        / "matches/details/inventories/match-detail-inventory-8cf339654c80c0ef"
    )
    store_root = data_root / "matches/details"
    artifact_root = (
        store_root
        / "diagnostics/match-detail-inventory-8cf339654c80c0ef"
        / "20261016T163942.933046Z-eb9b59e1"
    )
    state_path = store_root / "states/match-detail-inventory-8cf339654c80c0ef.json"
    if not all(path.exists() for path in (generation_root, inventory_dir, artifact_root, state_path)):
        pytest.skip("No existe el conjunto local; no se descarga ni se crea")
    generation_manifest = json.loads((generation_root / "manifest.json").read_text())
    source_paths = [generation_root, inventory_dir, artifact_root, state_path]
    for source in generation_manifest["source_captures"]:
        for key in ("capture_metadata", "source_html", "normalized_matches"):
            source_paths.append(data_root / source["files"][key]["path"])
    before = _tree_hashes(source_paths)
    plan = build_offline_sample_plan(
        generation_root=generation_root,
        inventory_dir=inventory_dir,
        data_root=data_root,
        store_root=store_root,
    )

    evidence = verify_historical_stop_evidence(
        plan,
        data_root=data_root,
        generation_root=generation_root,
        inventory_dir=inventory_dir,
        store_root=store_root,
    )

    assert evidence["source_match_id"] == "272582"
    assert evidence["semantic_valid"] is True
    assert evidence["promotion_eligible"] is False
    assert evidence["checkpoint_sha256"] == "d129476f2caebe1a9876fefe3a86cf6facf7254c96262a1ee4996855713e06f0"
    assert evidence["source_html_sha256"] == "9242edad00b43a4e83c649ddad006edb0d1172e0d88640082312a0fe1cf16997"
    assert before == _tree_hashes(source_paths)
