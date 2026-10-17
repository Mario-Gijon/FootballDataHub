"""Opt-in validation of the UI-02.2 projection against saved real profiles."""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path

import pytest

from football_data_hub_api.player_dataset import load_player_directory


DATA_ROOT = Path.home() / "FootballDataHub-data"
RUN_INTEGRATION = os.environ.get("FDH_UI022_RUN_REAL_PROFILE_INTEGRATION") == "1"
COMPACT_ROOT = Path(os.environ.get("FDH_UI022_REAL_COMPACT_ROOT", "")).expanduser()
INVENTORY_ROOT = Path(os.environ.get(
    "FDH_UI022_PLAYER_INVENTORY_ROOT", str(DATA_ROOT / "players/inventory-2026-27")
)).expanduser()
TEAM_CAPTURE_ROOT = Path(os.environ.get(
    "FDH_UI022_TEAM_CAPTURES_ROOT", str(DATA_ROOT / "team-captures")
)).expanduser()
PUBLISHED_INDEX = Path(os.environ.get(
    "FDH_UI022_PUBLISHED_TEAM_INDEX", str(DATA_ROOT / "published/team_profiles_2026-27.json")
)).expanduser()

TABLES_BY_VIEW = {
    "profile": ("career_tables", "career_totals_tables"),
    "statistics": ("statistics_tables",),
    "matches": ("summary_tables",),
    "rivals": ("rival_tables",),
}
SPORTS_TABLE_ROLES = {
    "career_trajectory", "career_totals", "statistics_by_competition", "statistics_by_team",
    "milestone_matches", "match_summary_by_competition", "match_summary_by_season",
    "match_summary_by_team", "match_summary_by_opponent", "opponent_player_statistics",
    "opponent_coach_statistics", "opponent_team_statistics",
}


@pytest.mark.integration
def test_three_saved_profiles_keep_all_real_columns_and_semantic_views() -> None:
    if not RUN_INTEGRATION:
        pytest.skip("Activa FDH_UI022_RUN_REAL_PROFILE_INTEGRATION=1 para leer los perfiles locales seleccionados.")
    required = (
        COMPACT_ROOT / "current.json", INVENTORY_ROOT / "players.json",
        TEAM_CAPTURE_ROOT, PUBLISHED_INDEX,
    )
    if not COMPACT_ROOT or not all(path.exists() for path in required):
        pytest.skip("Configura la generación compacta derivada y las fuentes verificadas locales.")

    pointer = json.loads((COMPACT_ROOT / "current.json").read_text())
    generation_root = COMPACT_ROOT / "generations" / pointer["generation_id"]
    manifest = json.loads((generation_root / "manifest.json").read_text())
    bundle = load_player_directory(
        inventory_root=INVENTORY_ROOT,
        compact_root=COMPACT_ROOT,
        team_captures_root=TEAM_CAPTURE_ROOT,
        published_index_path=PUBLISHED_INDEX,
    )
    expected_profiles = {
        23751: ("Manu Pedreño", "2000-10-09", "Los Garres", "Murcia", "España", None, "Central", 190, 81),
        28577: ("Nacho Castillo", "2000-07-03", "Miranda de Ebro", "Burgos", "España", "España", "Centrocampista", 183, 79),
        19269: ("Salvi", "2000-06-25", "Málaga", "Málaga", "España", None, "Portero", 192, 82),
    }
    entries = {entry["player_id"]: entry for entry in manifest["entries"]}

    for player_id, expected in expected_profiles.items():
        display_name, birth_date, birth_place, province, country, nationality, position, height, weight = expected
        assert player_id in entries
        compact_entry = entries[player_id]
        document = json.loads(gzip.decompress((generation_root / compact_entry["path"]).read_bytes()))
        detail = bundle.detail(player_id)
        assert detail is not None
        assert detail.identity.display_name == display_name
        assert detail.identity.birth_date.isoformat() == birth_date
        assert (detail.identity.birth_place, detail.identity.birthplace_province) == (birth_place, province)
        assert detail.identity.country_of_birth == country
        assert detail.identity.nationality == nationality
        assert detail.identity.position_name == position
        assert (detail.identity.height_cm, detail.identity.weight_kg) == (height, weight)
        assert {view.view for view in detail.verified_individual_views} == set(TABLES_BY_VIEW)
        projected_views = {view.view: view for view in detail.verified_individual_views}

        for view_name, source_table_keys in TABLES_BY_VIEW.items():
            source_view = document["views"][view_name]
            source_tables = [table for key in source_table_keys for table in source_view.get(key, [])]
            projected_tables = projected_views[view_name].tables
            assert len(projected_tables) == len(source_tables)
            for projected, source in zip(projected_tables, source_tables, strict=True):
                assert projected.table_role in SPORTS_TABLE_ROLES
                assert len(projected.columns) == len(source["columns"])
                assert all(column.label.strip() for column in projected.columns)
                assert len(projected.rows) == len(source.get("records", []))
                assert all(
                    len(row.cells) == len(source_row.get("column_values", []))
                    for row, source_row in zip(projected.rows, source.get("records", []), strict=True)
                )

        match_view = projected_views["matches"]
        source_matches = document["views"]["matches"]["individual_matches"]
        assert len(match_view.historical_matches) == len(source_matches)
        assert all(
            statistic.label.strip()
            for record in match_view.historical_matches
            for statistic in record.match_statistics
        )
