"""Opt-in, offline integration against verified datasets stored outside Git."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path

import pytest

from football_data_hub_api.match_results_dataset import load_match_results_dataset
from football_data_hub_api.player_dataset import PlayerDatasetLoadError, load_player_directory
from football_data_hub.providers.bdfutbol.players.parsers import parse_snapshot


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
def test_real_player_inventory_compact_and_diverse_twenty_player_sample() -> None:
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

    api_accessible_player_ids: list[int] = []
    projection_failures: list[str] = []
    for player in bundle.players:
        player_id = player["player_id"]
        if bundle.compact_statuses.get(player_id) != "COMPLETE_BASE_VIEWS":
            continue
        try:
            detail = bundle.detail(player_id)
        except PlayerDatasetLoadError as exc:
            # Preserve the exact player/reason for a failed published projection.
            projection_failures.append(f"{player_id}: {type(exc).__name__}: {exc}")
            continue
        if detail is None or {view.view for view in detail.verified_individual_views} != {
            "profile", "statistics", "matches", "rivals"
        }:
            projection_failures.append(f"{player_id}: faltan vistas verificadas en la API")
            continue
        api_accessible_player_ids.append(player_id)
    assert not projection_failures, projection_failures[:10]
    assert len(api_accessible_player_ids) == 1708

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

    # Exercise a stable, diverse sample through the same verified directory/API projection.
    selected_ids = {110652, 23751}
    complete_players = [
        player for player in bundle.players
        if bundle.compact_statuses.get(player["player_id"]) == "COMPLETE_BASE_VIEWS"
    ]
    for group in ("I", "II"):
        group_candidates = [player for player in complete_players if group in player.get("groups", [])]
        while sum(group in bundle.players_by_id[player_id].get("groups", []) for player_id in selected_ids) < 10:
            candidate = next(
                player for player in group_candidates
                if player["player_id"] not in selected_ids
            )
            selected_ids.add(candidate["player_id"])
    while len(selected_ids) < 20:
        candidate = next(player for player in complete_players if player["player_id"] not in selected_ids)
        selected_ids.add(candidate["player_id"])

    assert len(selected_ids) >= 20
    assert sum("I" in bundle.players_by_id[player_id].get("groups", []) for player_id in selected_ids) >= 10
    assert sum("II" in bundle.players_by_id[player_id].get("groups", []) for player_id in selected_ids) >= 10
    assert any(bundle.players_by_id[player_id].get("association_status") == "transfer_reference_only" for player_id in selected_ids)
    assert any(
        len(bundle.memberships_by_player.get(player_id, ())) > 1
        for player_id in selected_ids
    )
    for player_id in selected_ids:
        detail = bundle.detail(player_id)
        assert detail is not None
        projected = {view.view: view for view in detail.verified_individual_views}
        assert set(projected) == {"profile", "statistics", "matches", "rivals"}
        assert all(view.source_url and view.source_sha256 for view in projected.values())
        compact = bundle.compact_documents[player_id]
        for view_name in ("profile", "statistics", "matches", "rivals"):
            source = compact["views"][view_name]
            source_tables = (
                source.get("career_tables", []) + source.get("career_totals_tables", [])
                if view_name == "profile" else
                source.get("statistics_tables", []) if view_name == "statistics" else
                source.get("summary_tables", []) if view_name == "matches" else
                source.get("rival_tables", [])
            )
            # Some valid rival pages contain no normalized rival rows; the API must
            # preserve that empty source view rather than inventing a table.
            assert len(projected[view_name].tables) == len(source_tables)

    # The source's row uses colspan for its label. These observed totals stay under PJ/Min.
    observed_totals = {23751: (100, 7846), 28577: (78, 4785), 110652: (51, 2850)}
    for player_id, (matches_played, minutes) in observed_totals.items():
        detail = bundle.detail(player_id)
        assert detail is not None
        profile = next(view for view in detail.verified_individual_views if view.view == "profile")
        table = next(table for table in profile.tables if table.table_role == "career_totals")
        row = table.rows[0]
        assert row.source_fields["row_role"] == "total"
        assert row.source_fields["summary_label_raw"] == "Total"
        assert row.source_fields["summary_label_span"] == 6
        column_indexes = {column.label: index for index, column in enumerate(table.columns)}
        assert row.cells[column_indexes["Partidos Jugados"]].raw_value == str(matches_played)
        assert row.cells[column_indexes["Minutos"]].raw_value == str(minutes)

        progress_record = next(item for item in progress["players"] if item["player_id"] == player_id)
        snapshot = progress_record["view_snapshots"]["profile"]
        capture_dir = PLAYER_CAPTURE_ROOT / snapshot["capture_id"]
        capture_manifest = json.loads((capture_dir / "manifest.json").read_text())
        manifest_snapshot = next(
            item for item in capture_manifest["snapshots"]
            if item["snapshot_id"] == snapshot["snapshot_id"]
        )
        inventory_record = bundle.players_by_id[player_id]
        names = tuple(
            str(value).strip()
            for value in (inventory_record.get("display_name"), inventory_record.get("full_name"))
            if value
        )
        source_page = parse_snapshot(
            capture_dir, manifest_snapshot, expected_player_id=player_id, expected_names=names,
        )
        source_total = source_page.career_totals[0]
        assert source_total["summary_label_raw"] == "Total"
        assert source_total["summary_label_span"] == 6
        assert source_total["columns"][6]["raw_value"] == str(matches_played)
        assert source_total["columns"][17]["raw_value"] == str(minutes)

    aaron_progress = next(record for record in progress["players"] if record["player_id"] == 110652)
    aaron_compact = bundle.compact_documents[110652]
    assert aaron_progress["status"] == "COMPLETE_BASE_VIEWS"
    for view_name, snapshot in aaron_progress["view_snapshots"].items():
        capture_dir = PLAYER_CAPTURE_ROOT / snapshot["capture_id"]
        snapshot_dir = capture_dir / f"j110652/{view_name}/{snapshot['snapshot_id']}"
        raw_html = gzip.decompress((snapshot_dir / "source.html.gz").read_bytes())
        metadata_raw = (snapshot_dir / "metadata.json").read_bytes()
        capture_manifest = json.loads((capture_dir / "manifest.json").read_text())
        manifest_snapshot = next(
            item for item in capture_manifest["snapshots"]
            if item["snapshot_id"] == snapshot["snapshot_id"]
        )
        assert hashlib.sha256(raw_html).hexdigest() == snapshot["html_sha256"]
        assert hashlib.sha256(metadata_raw).hexdigest() == snapshot["metadata_sha256"]
        assert manifest_snapshot["html_sha256"] == snapshot["html_sha256"]
        assert aaron_compact["view_sources"][view_name]["html_sha256"] == snapshot["html_sha256"]
        assert aaron_compact["views"][view_name]

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
