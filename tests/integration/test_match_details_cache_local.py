"""Opt-in, read-only source validation of all local match publications."""

import os

import pytest

from football_data_hub_api.config import ApiSettings, PROJECT_ROOT
from football_data_hub_api.match_details_cache import load_cached_published_match_details
from football_data_hub_api.match_results_dataset import load_match_results_dataset
from football_data_hub_api.player_dataset import load_player_directory


@pytest.mark.skipif(
    os.environ.get("FDH_MATCH_DETAILS_CACHE_INTEGRATION") != "1",
    reason="Set FDH_MATCH_DETAILS_CACHE_INTEGRATION=1 for the local offline 160-report check.",
)
def test_all_published_reports_survive_a_warm_cached_reload(tmp_path):
    settings = ApiSettings.from_env()
    matches = load_match_results_dataset(
        settings.match_generation_root, data_root=settings.local_data_root,
    )
    players = load_player_directory(
        inventory_root=settings.player_inventory_root,
        compact_root=settings.player_compact_root,
        team_captures_root=settings.player_team_captures_root,
        published_index_path=settings.player_published_index_path,
    )
    arguments = {
        "store_root": settings.match_details_store_root,
        "generation_root": settings.match_generation_root,
        "data_root": settings.local_data_root,
        "match_bundle": matches,
        "player_ids": set(players.players_by_id),
        "cache_root": tmp_path / "verified-cache",
        "project_root": PROJECT_ROOT,
    }
    first = load_cached_published_match_details(settings.match_details_published_root, **arguments)
    second = load_cached_published_match_details(settings.match_details_published_root, **arguments)
    assert len(first) == len(second) == 160
    assert first.keys() == second.keys()
    assert arguments["cache_root"].joinpath("published-match-details.json").is_file()
