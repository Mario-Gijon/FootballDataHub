from __future__ import annotations

import socket
import urllib.request
from pathlib import Path
import hashlib
import json

import pytest

from football_data_hub.providers.bdfutbol.match_details.cli import build_offline_plan
from football_data_hub.providers.bdfutbol.match_details.inventory import (
    MatchDetailInventoryError,
    _data_file,
    build_match_detail_inventory,
    write_inventory_immutable,
)
from tests.match_detail_fixtures import make_inventory, make_verified_generation


def test_inventory_selects_only_played_matches_with_explicit_urls_and_is_deterministic():
    first = build_match_detail_inventory(make_verified_generation())
    second = build_match_detail_inventory(make_verified_generation())

    assert first == second
    assert first["counts"] == {
        "matches": 2,
        "groups": {"I": 1, "II": 1},
        "unique_internal_ids": 2,
        "unique_source_ids": 2,
        "unique_urls": 2,
        "played_without_explicit_url": 0,
    }
    assert all(item["acquisition_status"] == "pending" for item in first["matches"])
    assert all(item["validation_status"] == "not_acquired" for item in first["matches"])
    assert all(item["reference_result"] == {"home_goals": 0, "away_goals": 0} for item in first["matches"])
    assert first["matches"][0]["source_match_url"].startswith(
        "https://www.bdfutbol.com/es/p/p.php?id="
    )


def test_duplicate_match_ids_are_rejected():
    with pytest.raises(MatchDetailInventoryError, match="duplicado"):
        build_match_detail_inventory(make_verified_generation(duplicate_source_id=True))


def test_duplicate_bdfutbol_id_across_groups_is_rejected():
    with pytest.raises(MatchDetailInventoryError, match="duplicado"):
        build_match_detail_inventory(
            make_verified_generation(duplicate_across_groups=True)
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://www.bdfutbol.com/es/p/p.php?id=269400",
        "https://evil.example/es/p/p.php?id=269400",
        "https://www.bdfutbol.com/es/p/p.php?id=1",
        "https://www.bdfutbol.com/es/p/p.php?id=269400&foo=x",
        "https://www.bdfutbol.com/es/p/../p.php?id=269400",
    ],
)
def test_invalid_match_url_is_rejected(url):
    verified = make_verified_generation()
    verified.matches_payload["groups"]["I"]["matches"][0]["source_match_url"] = url
    with pytest.raises(MatchDetailInventoryError, match="URL individual"):
        build_match_detail_inventory(verified)


def test_immutable_inventory_write_is_idempotent_and_refuses_overwrite(tmp_path):
    inventory = make_inventory()
    target = tmp_path / "inventory.json"
    assert write_inventory_immutable(target, inventory) == target
    before = target.read_bytes()
    assert write_inventory_immutable(target, inventory) == target
    assert target.read_bytes() == before

    target.write_text("{}\n", encoding="utf-8")
    corrupted = target.read_bytes()
    with pytest.raises(FileExistsError, match="No se sobrescribe"):
        write_inventory_immutable(target, inventory)
    assert target.read_bytes() == corrupted


def test_immutable_inventory_output_rejects_symlink_target(tmp_path):
    inventory = make_inventory()
    actual = tmp_path / "actual.json"
    actual.write_text("existing", encoding="utf-8")
    alias = tmp_path / "alias.json"
    alias.symlink_to(actual)

    with pytest.raises(FileExistsError, match="symlink"):
        write_inventory_immutable(alias, inventory)
    assert actual.read_text(encoding="utf-8") == "existing"


def test_source_paths_reject_parent_traversal_and_symlinks(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    link = data_root / "source.json"
    link.symlink_to(outside)

    with pytest.raises(MatchDetailInventoryError, match="no segura"):
        _data_file(data_root, "../outside.json", label="test")
    with pytest.raises(MatchDetailInventoryError, match="symlink"):
        _data_file(data_root, "source.json", label="test")


def test_inventory_generation_outside_data_root_is_rejected(tmp_path):
    from football_data_hub.providers.bdfutbol.match_details.inventory import (
        load_verified_match_generation,
    )

    data_root = tmp_path / "data"
    data_root.mkdir()
    with pytest.raises(MatchDetailInventoryError, match="dentro de data_root"):
        load_verified_match_generation(
            tmp_path / "external-generation",
            data_root=data_root,
        )


def test_generation_artifact_hash_and_symlink_are_rejected(tmp_path):
    from football_data_hub.providers.bdfutbol.match_details.inventory import (
        load_verified_match_generation,
    )

    data_root = tmp_path / "data"
    generation = data_root / "matches/generations/generation-test"
    generation.mkdir(parents=True)
    matches = b"{}\n"
    validation = b"{}\n"
    (generation / "matches.json").write_bytes(matches)
    (generation / "validation.json").write_bytes(validation)
    manifest = {
        "schema_version": 1,
        "source": "BDFutbol",
        "competition": "Primera Federación",
        "season": "2026-27",
        "generation_id": generation.name,
        "artifacts": {
            "matches.json": {"sha256": "0" * 64, "bytes": len(matches)},
            "validation.json": {
                "sha256": hashlib.sha256(validation).hexdigest(),
                "bytes": len(validation),
            },
        },
    }
    (generation / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(MatchDetailInventoryError, match="SHA-256"):
        load_verified_match_generation(generation, data_root=data_root)

    target = tmp_path / "external-generation"
    target.mkdir()
    alias = data_root / "matches/generations/alias-generation"
    alias.symlink_to(target, target_is_directory=True)
    with pytest.raises(MatchDetailInventoryError, match="symlink"):
        load_verified_match_generation(alias, data_root=data_root)


def test_offline_cli_plan_never_calls_network_apis(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("MATCH-01A no debe utilizar la red")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    report, inventory = build_offline_plan(
        generation_root=Path("/unused"),
        data_root=Path("/unused"),
        store_root=tmp_path / "store",
        verified_generation=make_verified_generation(),
    )

    assert report["http_enabled"] is False
    assert report["browser_enabled"] is False
    assert report["status"] == "READY"
    assert report["counts"]["eligible"] == 2
    assert report["counts"]["pending"] == 2
    assert report["inventory_id"] == inventory["inventory_id"]


def test_invalid_snapshots_and_stop_diagnostics_block_the_plan(tmp_path):
    store_root = tmp_path / "store"
    inventory = make_inventory()
    (
        store_root
        / "captures"
        / inventory["inventory_id"]
        / "broken-capture"
    ).mkdir(parents=True)

    report, _ = build_offline_plan(
        generation_root=Path("/unused"),
        data_root=Path("/unused"),
        store_root=store_root,
        verified_generation=make_verified_generation(),
    )
    assert report["status"] == "BLOCKED"
    assert report["counts"]["invalid_snapshots"] == 1
