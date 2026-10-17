"""Opt-in, offline integration against verified datasets stored outside Git."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from football_data_hub_api.match_results_dataset import load_match_results_dataset
from football_data_hub_api.player_dataset import load_player_directory


DATA_ROOT = Path(os.environ.get(
    "FDH_UI01_LOCAL_DATA_ROOT", str(Path.home() / "FootballDataHub-data")
)).expanduser()
RUN_LOCAL_INTEGRATION = os.environ.get("FDH_UI01_RUN_LOCAL_INTEGRATION") == "1"
MATCH_ROOT = Path(os.environ.get(
    "FDH_UI01_MATCH_GENERATION_ROOT",
    str(DATA_ROOT / "matches/generations/match-00-4ad1d610507e425d"),
)).expanduser()
INVENTORY_ROOT = Path(os.environ.get(
    "FDH_UI01_PLAYER_INVENTORY_ROOT",
    str(DATA_ROOT / "players/inventory-2026-27"),
)).expanduser()
PLAYER_CAPTURE_ROOT = Path(os.environ.get(
    "FDH_UI01_PLAYER_CAPTURE_ROOT",
    str(DATA_ROOT / "players/player-captures"),
)).expanduser()
COMPACT_ROOT = Path(os.environ.get(
    "FDH_UI01_PLAYER_COMPACT_ROOT",
    str(DATA_ROOT / "players/compact-2026-27"),
)).expanduser()
TEAM_CAPTURE_ROOT = Path(os.environ.get(
    "FDH_UI01_TEAM_CAPTURES_ROOT", str(DATA_ROOT / "team-captures")
)).expanduser()
PUBLISHED_INDEX = Path(os.environ.get(
    "FDH_UI01_PUBLISHED_TEAM_INDEX",
    str(DATA_ROOT / "published/team_profiles_2026-27.json"),
)).expanduser()


@pytest.mark.integration
def test_match_00_real_generation_is_verified_and_keeps_unplayed_scores_null() -> None:
    if not RUN_LOCAL_INTEGRATION:
        pytest.skip("Activa FDH_UI01_RUN_LOCAL_INTEGRATION=1 para leer datasets locales externos a Git.")
    if not MATCH_ROOT.is_dir():
        pytest.skip("No está configurada la generación local MATCH-00.")
    bundle = load_match_results_dataset(MATCH_ROOT, data_root=DATA_ROOT)
    assert bundle.bootstrap.metadata.team_count == 40
    assert bundle.bootstrap.metadata.match_count == 760
    assert bundle.bootstrap.metadata.played_count == 140
    assert bundle.bootstrap.metadata.unplayed_count == 620
    for group in bundle.bootstrap.groups.values():
        assert len(group.teams) == 20
        assert len(group.matches) == 380
        assert len({match.internal_id for match in group.matches}) == 380
        assert sum(match.status == "played" for match in group.matches) == 70
        assert all(
            match.home_goals is None and match.away_goals is None
            for match in group.matches if match.status == "unplayed"
        )
        assert sum(match.source_match_url is not None for match in group.matches) >= 70


@pytest.mark.integration
def test_real_player_inventory_compact_and_three_verified_cases() -> None:
    if not RUN_LOCAL_INTEGRATION:
        pytest.skip("Activa FDH_UI01_RUN_LOCAL_INTEGRATION=1 para leer datasets locales externos a Git.")
    required = (
        INVENTORY_ROOT / "players.json",
        COMPACT_ROOT / "current.json",
        TEAM_CAPTURE_ROOT,
        PUBLISHED_INDEX,
        PLAYER_CAPTURE_ROOT / "acquisition-progress-2026-27.json",
    )
    if not all(path.exists() for path in required):
        pytest.skip("Faltan fuentes locales verificadas de PLAYER para la integración UI-01.")

    progress = json.loads((PLAYER_CAPTURE_ROOT / "acquisition-progress-2026-27.json").read_text())
    pointer = json.loads((COMPACT_ROOT / "current.json").read_text())
    generation_manifest = json.loads(
        (COMPACT_ROOT / pointer["manifest_path"]).read_text()
    )
    bundle = load_player_directory(
        inventory_root=INVENTORY_ROOT,
        compact_root=COMPACT_ROOT,
        team_captures_root=TEAM_CAPTURE_ROOT,
        published_index_path=PUBLISHED_INDEX,
    )

    assert len(bundle.players) == 1709
    assert bundle.metadata.inventory_player_count == 1709
    assert bundle.metadata.complete_individual_profile_count == generation_manifest["complete_player_count"]
    acquisition_complete_count = sum(
        record.get("status") == "COMPLETE_BASE_VIEWS" for record in progress["players"]
    )
    assert acquisition_complete_count == 1708
    assert bundle.metadata.complete_individual_profile_count == 4
    assert bundle.metadata.inventory_only_count == 1705
    nacho = bundle.list_players(query="Nacho Castillo", page_size=5)
    assert nacho.total == 1
    assert nacho.players[0].player_id == 28577

    roster = next(player for player in bundle.players if player["association_status"] == "roster_membership_observed")
    transfer_only = next(player for player in bundle.players if player["association_status"] == "transfer_reference_only")
    complete = next(
        player for player in bundle.players
        if bundle.compact_documents.get(player["player_id"], {}).get("status") == "COMPLETE_BASE_VIEWS"
    )
    assert bundle.detail(roster["player_id"]) is not None
    transfer_detail = bundle.detail(transfer_only["player_id"])
    assert transfer_detail is not None
    assert transfer_detail.player.association_status == "transfer_reference_only"
    complete_detail = bundle.detail(complete["player_id"])
    assert complete_detail is not None
    assert complete_detail.player.profile_status == "four_views_verified"
    assert {view.view for view in complete_detail.verified_individual_views} == {
        "profile", "statistics", "matches", "rivals"
    }

    for player_id in (23751, 28577, 209629):
        detail = bundle.detail(player_id)
        assert detail is not None
        assert detail.player.profile_status == "four_views_verified"
        assert len(detail.verified_individual_views) == 4

    transfer_only_detail = bundle.detail(transfer_only["player_id"])
    assert transfer_only_detail is not None
    assert transfer_only_detail.player.association_status == "transfer_reference_only"
    assert transfer_only_detail.verified_individual_views == []
