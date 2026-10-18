"""Read-only verification of kickoff times already present in local match HTML."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import urllib.request
from pathlib import Path

import pytest

from football_data_hub.providers.bdfutbol.match_details.campaign_artifact import parse_campaign_saved_artifact
from football_data_hub.providers.bdfutbol.match_details.inventory import build_match_detail_inventory, load_verified_match_generation
from football_data_hub_api.match_details_dataset import load_published_match_details
from football_data_hub_api.match_results_dataset import load_match_results_dataset
from football_data_hub_api.player_dataset import load_player_directory

pytestmark = pytest.mark.skipif(
    os.environ.get("FDH_MATCH_04B_INTEGRATION") != "1",
    reason="Opt-in offline regression; set FDH_MATCH_04B_INTEGRATION=1",
)

DATA_ROOT = Path(os.environ.get("FDH_MATCH_04B_DATA_ROOT", Path.home() / "FootballDataHub-data")).expanduser()
GENERATION_ID = "match-00-4ad1d610507e425d"
CAMPAIGN_ID = "match-detail-sample-campaign-67fdc4b4fac66b82"
ARTIFACTS = {
    "272525": ("discovery-20261018T112656Z-4543b211", "21:15"),
    "272517": ("discovery-20261018T155340Z-dd7ad2cb", "19:15"),
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hash_tree(paths: list[Path]) -> dict[str, str]:
    files = []
    for path in paths:
        files.extend([path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file()))
    return {str(path): _sha(path) for path in files}


def test_published_match_times_are_rederived_from_immutable_html_without_writes(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("MATCH-04B integration must remain offline")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    generation_root = DATA_ROOT / "matches/generations" / GENERATION_ID
    campaign_root = DATA_ROOT / "matches/details/campaigns" / CAMPAIGN_ID
    published_root = DATA_ROOT / "matches/details/published"
    player_inputs = [
        DATA_ROOT / "players/inventory-2026-27",
        DATA_ROOT / "players/compact-2026-27",
        DATA_ROOT / "team-captures",
        DATA_ROOT / "published/team_profiles_2026-27.json",
    ]
    if not generation_root.is_dir() or not campaign_root.is_dir() or not published_root.is_dir() or not all(path.exists() for path in player_inputs):
        pytest.skip("Faltan artefactos locales; esta prueba no adquiere ni genera datos.")

    verified = load_verified_match_generation(generation_root, data_root=DATA_ROOT)
    source_paths = [
        DATA_ROOT / entry["path"]
        for source in verified.manifest_payload["source_captures"]
        for entry in source["files"].values()
    ]
    paths = [generation_root, campaign_root, published_root, *source_paths]
    before = _hash_tree(paths)
    inventory = build_match_detail_inventory(verified)
    by_id = {item["source_match_id"]: item for item in inventory["matches"]}
    for match_id, (artifact_id, expected_time) in ARTIFACTS.items():
        internal_id = f"pf-2026-27-group-ii-bdfutbol-{match_id}"
        artifact = campaign_root / "candidates" / internal_id / "artifacts" / artifact_id
        observation = parse_campaign_saved_artifact(
            artifact,
            expected_match=by_id[match_id],
            verified_generation=verified,
            data_root=DATA_ROOT,
        )
        assert observation.validation.semantic_valid is True
        assert observation.kickoff_time_local.value == expected_time
        assert observation.kickoff_time_local.state == "observed"
        assert observation.timezone.value is None
        assert observation.kickoff_time_local.raw_value
        assert observation.source.source_html_sha256 == json.loads((artifact / "manifest.json").read_text())["files"]["source.html"]["sha256"]

    bundle = load_match_results_dataset(generation_root, data_root=DATA_ROOT)
    player_directory = load_player_directory(
        inventory_root=player_inputs[0], compact_root=player_inputs[1],
        team_captures_root=player_inputs[2], published_index_path=player_inputs[3],
    )
    published = load_published_match_details(
        published_root,
        store_root=DATA_ROOT / "matches/details",
        generation_root=generation_root,
        data_root=DATA_ROOT,
        match_bundle=bundle,
        player_ids=set(player_directory.players_by_id),
    )
    assert published["pf-2026-27-group-ii-bdfutbol-272525"].kickoff_time_local == "21:15"
    assert published["pf-2026-27-group-ii-bdfutbol-272517"].kickoff_time_local == "19:15"
    assert all(item.kickoff_source_html_sha256 == item.source_html_sha256 for item in published.values())
    assert _hash_tree(paths) == before
