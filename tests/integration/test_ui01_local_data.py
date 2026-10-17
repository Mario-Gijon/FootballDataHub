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
    assert bundle.metadata.complete_individual_profile_count == generation_manifest["complete_player_count"] == 1708
    acquisition_complete_count = sum(
        record.get("status") == "COMPLETE_BASE_VIEWS" for record in progress["players"]
    )
    assert acquisition_complete_count == 1708
    assert bundle.metadata.complete_individual_profile_count == 1708
    assert bundle.metadata.partial_individual_profile_count == 0
    assert bundle.metadata.inventory_only_count == 1
    nacho = bundle.list_players(query="Nacho Castillo", page_size=5)
    assert nacho.total == 1
    assert nacho.players[0].player_id == 28577

    roster = next(player for player in bundle.players if player["association_status"] == "roster_membership_observed")
    transfer_only = next(player for player in bundle.players if player["association_status"] == "transfer_reference_only")
    complete = next(
        player for player in bundle.players
        if bundle.compact_statuses.get(player["player_id"]) == "COMPLETE_BASE_VIEWS"
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

    for player_id in (110652, 28577, 23751, 19269, 209629, 729168):
        detail = bundle.detail(player_id)
        assert detail is not None
        assert detail.player.profile_status == "four_views_verified"
        assert len(detail.verified_individual_views) == 4
        compact = bundle.compact_documents[player_id]
        projected = {view.view: view for view in detail.verified_individual_views}
        assert set(projected) == {"profile", "statistics", "matches", "rivals"}
        for view_name in ("profile", "statistics", "matches", "rivals"):
            source = compact["views"][view_name]
            view = projected[view_name]
            source_tables = (
                source.get("career_tables", []) + source.get("career_totals_tables", [])
                if view_name == "profile" else
                source.get("statistics_tables", []) if view_name == "statistics" else
                source.get("summary_tables", []) if view_name == "matches" else
                source.get("rival_tables", [])
            )
            assert len(view.tables) == len(source_tables)
            for api_table, source_table in zip(view.tables, source_tables, strict=True):
                assert len(api_table.rows) == len(source_table.get("records", []))
                if api_table.rows and source_table.get("records"):
                    assert api_table.rows[0].cells[0].raw_value == source_table["records"][0]["column_values"][0][0]
                    assert api_table.rows[0].source_fields.get("season_raw") == source_table["records"][0].get("season_raw")
        original_matches = compact["views"]["matches"]
        assert len(projected["matches"].historical_matches) == len(original_matches.get("individual_matches", []))
        assert len(projected["matches"].summoned_without_participation) == len(original_matches.get("summoned_without_participation", []))
        assert len(projected["matches"].other_match_records) == len(original_matches.get("other_match_records", []))
        for source_key, api_key in (
            ("individual_matches", "historical_matches"),
            ("summoned_without_participation", "summoned_without_participation"),
            ("other_match_records", "other_match_records"),
        ):
            source_records = original_matches.get(source_key, [])
            api_records = getattr(projected["matches"], api_key)
            if source_records:
                assert api_records[0].source_fields == source_records[0]
                assert api_records[0].minutes == source_records[0].get("minutes")
        assert projected["profile"].profile == compact["views"]["profile"]["profile"]

    manu = bundle.detail(23751)
    assert manu is not None
    assert manu.identity.display_name == "Manu Pedreño"
    assert manu.identity.full_name == "Antonio Manuel Moñino Pedreño"
    assert manu.identity.birth_date.isoformat() == "2000-10-09"
    assert manu.identity.birth_place == "Los Garres"
    assert manu.identity.birth_place_raw == "Los Garres ( Murcia )"
    assert manu.identity.birthplace_province == "Murcia"
    assert manu.identity.country_of_birth == "España"
    assert manu.identity.nationality is None
    assert manu.identity.position_name == "Central"
    assert manu.identity.height_cm == 190
    assert manu.identity.weight_kg == 81
    assert manu.identity.individual_profile_sha256 == "a0c34d3186881bb61c443fd378516e5d216955a1a17f43eaf48853c35203b870"
    assert manu.club_reference.status == "not_confirmed"
    assert manu.club_reference.team_id is None
    assert sorted((item.team_id, item.team_name, item.group) for item in manu.membership_history) == [
        (178, "UD Logroñés", "I"),
        (414, "UD Ibiza", "II"),
    ]
    assert manu.last_observed_movement is not None
    assert (
        manu.last_observed_movement.from_team_id,
        manu.last_observed_movement.from_team_name,
        manu.last_observed_movement.from_group,
        manu.last_observed_movement.to_team_id,
        manu.last_observed_movement.to_team_name,
        manu.last_observed_movement.to_group,
    ) == (414, "UD Ibiza", "II", 178, "UD Logroñés", "I")
    assert manu.last_observed_movement.transfer_date is None
    assert len(manu.transfer_references) == 2
    assert all(item.transfer_date is None for item in manu.transfer_references)
    assert not manu.identity.conflicts

    transfer_only_detail = bundle.detail(transfer_only["player_id"])
    assert transfer_only_detail is not None
    assert transfer_only_detail.player.association_status == "transfer_reference_only"
    if transfer_only_detail.player.profile_status == "four_views_verified":
        assert {view.view for view in transfer_only_detail.verified_individual_views} == {
            "profile", "statistics", "matches", "rivals"
        }
    else:
        assert transfer_only_detail.verified_individual_views == []
