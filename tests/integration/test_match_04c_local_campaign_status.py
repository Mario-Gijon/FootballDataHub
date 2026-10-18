"""Opt-in read-only integration against the local FootballDataHub-data store."""

from __future__ import annotations

import hashlib
import os
import socket
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from football_data_hub.providers.bdfutbol.match_details.scalable_campaign_cli import _load_report
from football_data_hub.providers.bdfutbol.match_details.scalable_campaigns import build_match_campaign_proposal

pytestmark = pytest.mark.skipif(
    os.environ.get("FDH_MATCH_04C_INTEGRATION") != "1",
    reason="Opt-in offline integration; set FDH_MATCH_04C_INTEGRATION=1",
)


def _tree_hash(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    paths = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file())
    return {
        item.relative_to(path).as_posix() if path.is_dir() else item.name:
        hashlib.sha256(item.read_bytes()).hexdigest()
        for item in paths
    }


def test_latest_local_inventory_and_publications_are_read_only_and_incremental(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("MATCH-04C status must not access the network")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    data_root = Path(os.environ.get("FDH_MATCH_04C_DATA_ROOT", Path.home() / "FootballDataHub-data")).expanduser()
    generation_root = data_root / "matches/generations/match-00-4ad1d610507e425d"
    store_root = data_root / "matches/details"
    published_root = store_root / "published"
    campaign_root = store_root / "campaigns"
    player_paths = (
        data_root / "players/inventory-2026-27",
        data_root / "players/compact-2026-27",
        data_root / "team-captures",
        data_root / "published/team_profiles_2026-27.json",
    )
    if not generation_root.is_dir() or not all(path.exists() for path in player_paths):
        pytest.skip("Faltan fuentes locales; no se descargan ni recrean.")
    targets = (generation_root, store_root, published_root, campaign_root, *player_paths)
    before = {str(path): _tree_hash(path) for path in targets}
    args = SimpleNamespace(
        data_root=data_root,
        generation_root=generation_root,
        store_root=store_root,
        published_root=published_root,
        player_inventory_root=player_paths[0],
        player_compact_root=player_paths[1],
        player_team_captures_root=player_paths[2],
        player_published_index=player_paths[3],
        previous_generation_root=None,
    )

    report, _proposals, _context = _load_report(args)
    by_id = {row["source_match_id"]: row for row in report["matches"]}
    proposal = build_match_campaign_proposal(report, groups=("I", "II"), limit=10)
    after = {str(path): _tree_hash(path) for path in targets}

    assert before == after
    assert report["source"]["generation_id"] == "match-00-4ad1d610507e425d"
    assert report["counts"]["unplayed"] == 620
    assert report["counts"]["published_approved"] == 2
    assert report["counts"]["review_completed"] == 2
    assert report["counts"]["blocked_requires_human_review"] == 1
    assert report["counts"]["included_in_existing_campaign"] == 3
    assert report["counts"]["played_pending_acquisition"] == 134
    for source_id in ("272525", "272517"):
        assert by_id[source_id]["published_approved"] is True
        assert by_id[source_id]["detail_status"] == "review_completed"
    for source_id in ("272577", "272524", "269411"):
        assert by_id[source_id]["detail_status"] == "included_in_existing_campaign"
        assert by_id[source_id]["campaign"]["authorization_consumed"] is False
    assert by_id["272582"]["detail_status"] == "blocked_requires_human_review"
    assert proposal["selection"]["available_candidates_before_limit"] == 134
    assert proposal["candidate_count"] == 10
    assert proposal["authorization"]["is_authorization"] is False
    assert all(item["source_match_id"] not in {"272525", "272517", "272577", "272524", "269411", "272582"} for item in proposal["candidates"])
