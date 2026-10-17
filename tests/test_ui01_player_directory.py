"""Offline tests for the bounded player directory projection."""

from __future__ import annotations

from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from football_data_hub_api.config import ApiSettings, PROJECT_ROOT
from football_data_hub_api.main import create_app
from football_data_hub_api.player_dataset import (
    CompactDocumentStore,
    PlayerDatasetLoadError,
    PlayerDirectoryBundle,
    _project_individual_views,
)
from football_data_hub_api.schemas import (
    MatchGenerationRecordResponse,
    PlayerDirectoryMetadataResponse,
    PlayerTeamFilterResponse,
)


def _metadata() -> PlayerDirectoryMetadataResponse:
    return PlayerDirectoryMetadataResponse(
        season="2026-27",
        inventory_generated_at=datetime(2026, 10, 14, tzinfo=timezone.utc),
        inventory_player_count=3,
        complete_individual_profile_count=0,
        partial_individual_profile_count=0,
        inventory_only_count=3,
        roster_membership_count=2,
        transfer_only_count=1,
        compact_generation_id=None,
        compact_generated_at=None,
        inventory_sha256="a" * 64,
    )


def _player(
    player_id: int,
    name: str,
    *,
    team_id: int | None,
    group: str = "II",
    association_status: str = "roster_membership_observed",
) -> dict:
    associations = [] if team_id is None else [{
        "team_id": team_id,
        "team_name": "Real Jaén" if team_id == 49 else "Racing de Ferrol",
        "group": group,
        "evidence_types": ["membership" if association_status == "roster_membership_observed" else "transfer_reference"],
    }]
    return {
        "player_id": player_id,
        "display_name": name,
        "full_name": None,
        "profile_url": f"https://www.bdfutbol.com/es/j/j{player_id}.html",
        "photo_url": None,
        "birth_date": None,
        "age_years": None,
        "nationality": None,
        "position_name": None,
        "groups": [group] if team_id else [],
        "association_status": association_status,
        "team_associations": associations,
    }


def _bundle() -> PlayerDirectoryBundle:
    players = (
        _player(100, "Álex Demo", team_id=49),
        _player(101, "Beta Jugador", team_id=48, group="I"),
        _player(102, "Gamma", team_id=49, association_status="transfer_reference_only"),
    )
    by_id = {item["player_id"]: item for item in players}
    memberships = {
        100: ({"team_id": 49, "team_name": "Real Jaén", "group": "II"},),
        101: ({"team_id": 48, "team_name": "Racing de Ferrol", "group": "I"},),
        102: (),
    }
    return PlayerDirectoryBundle(
        metadata=_metadata(),
        players=players,
        players_by_id=by_id,
        memberships_by_player=memberships,
        teams=(
            PlayerTeamFilterResponse(team_id=48, team_name="Racing de Ferrol", group="I"),
            PlayerTeamFilterResponse(team_id=49, team_name="Real Jaén", group="II"),
        ),
        compact_documents={},
        etag='"fixture"',
    )


def test_player_directory_search_is_accent_insensitive_and_paged() -> None:
    bundle = _bundle()

    first = bundle.list_players(query="alex", page=1, page_size=1)
    assert first.total == 1
    assert first.players[0].player_id == 100

    page = bundle.list_players(page=2, page_size=2)
    assert page.total == 3
    assert [item.player_id for item in page.players] == [102]


def test_group_and_team_filters_use_observed_memberships_only() -> None:
    bundle = _bundle()

    group_one = bundle.list_players(group="I")
    assert [item.player_id for item in group_one.players] == [101]
    jaen = bundle.list_players(team_id=49)
    assert [item.player_id for item in jaen.players] == [100, 102]
    assert jaen.players[1].association_status == "transfer_reference_only"


def test_inventory_only_player_keeps_missing_values_null() -> None:
    response = _bundle().list_players(query="Gamma").players[0]
    assert response.profile_status == "inventory_only"
    assert response.profile_url == "https://www.bdfutbol.com/es/j/j102.html"
    assert response.photo_url is None
    assert response.birth_date is None
    assert response.age_years is None


def test_compact_store_loads_on_demand_and_rechecks_hash_even_when_cached(tmp_path: Path) -> None:
    document = {
        "schema_version": "football_data_hub.bdfutbol.player_compact_profile.v1",
        "player_id": 100,
        "status": "COMPLETE_BASE_VIEWS",
        "season_context": "2026-27",
        "views": {name: {} for name in ("profile", "statistics", "matches", "rivals")},
    }
    path = tmp_path / "players/100.json.gz"
    path.parent.mkdir(parents=True)
    compressed = gzip.compress(json.dumps(document).encode())
    path.write_bytes(compressed)
    entry = {
        "path": "players/100.json.gz", "sha256": hashlib.sha256(compressed).hexdigest(),
        "bytes": len(compressed), "status": "COMPLETE_BASE_VIEWS", "compression": "gzip",
    }
    store = CompactDocumentStore(tmp_path, {100: entry}, cache_size=1)
    assert store.statuses == {100: "COMPLETE_BASE_VIEWS"}
    assert len(store.cache) == 0
    assert store[100]["player_id"] == 100
    assert len(store.cache) == 1

    path.write_bytes(compressed + b"changed")
    with pytest.raises(PlayerDatasetLoadError, match="SHA-256"):
        store[100]


def test_view_projection_preserves_profile_match_summaries_auxiliary_records_and_row_fields() -> None:
    row = {
        "season_raw": "2025-26", "team_name_raw": "Real Jaén", "source_row_index": 3,
        "column_values": [["10", 10, "NORMALIZED_INTEGER"]],
    }
    table = {
        "table_id": "career", "schema_id": "schema-1", "table_role": "career_trajectory",
        "source_table_index": 2,
        "columns": [{"source_index": 0, "header_original": "PJ", "group_header_raw": "Totales", "data_colid_raw": "pj"}],
        "records": [row],
    }
    summary_table = {**table, "table_role": None, "records": [{**row, "summary_dimension": "match_summary_by_season"}]}
    match_row = {"match_id": "m1", "player_appearance_status": "SUMMONED", "minutes": None, "source_record_index": 8}
    sources = {
        name: {"requested_url": f"https://www.bdfutbol.com/es/j/j100.html?view={name}", "html_sha256": "a" * 64}
        for name in ("profile", "statistics", "matches", "rivals")
    }
    document = {"view_sources": sources, "views": {
        "profile": {"profile": {"height_raw": "183 cm"}, "coverage": {"data_scope": "observed"}, "career_tables": [table], "career_totals_tables": []},
        "statistics": {"statistics_tables": [table]},
        "matches": {
            "summary_tables": [summary_table], "individual_matches": [match_row],
            "summoned_without_participation": [match_row], "other_match_records": [],
            "record_counts": {"individual_matches": 1}, "coverage": {"parse_status": "PARSED"},
            "exhaustiveness_status": "NOT_CERTIFIED", "window_p_record_count": 8,
        },
        "rivals": {"rival_tables": [table]},
    }}
    projected = {item.view: item for item in _project_individual_views(document)}
    assert projected["profile"].profile == {"height_raw": "183 cm"}
    assert projected["profile"].tables[0].rows[0].source_fields["source_row_index"] == 3
    assert projected["profile"].tables[0].columns[0].group_header == "Totales"
    assert projected["matches"].tables[0].table_id == "career"
    assert projected["matches"].tables[0].table_role == "match_summary_by_season"
    assert projected["matches"].record_counts["individual_matches"] == 1
    assert projected["matches"].window_p_record_count == 8
    assert len(projected["matches"].summoned_without_participation) == 1
    assert projected["matches"].summoned_without_participation[0].source_fields["source_record_index"] == 8


def test_api_player_routes_support_search_detail_errors_and_etags() -> None:
    root = PROJECT_ROOT / "data/exports/bdfutbol/group2_classification"
    capture = root / "20261010T102656.252222Z-72f200ad"
    settings = ApiSettings(
        matches_path=root / "derived-res01-20261010T102656Z/normalized/matches.json",
        classification_path=capture / "normalized/classification.json",
        progress_path=capture / "normalized/progress.json",
        capture_metadata_path=capture / "metadata/capture.json",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        app.state.player_directory = _bundle()
        response = client.get("/api/v1/players?q=alex&page_size=1")
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert payload["players"][0]["player_id"] == 100
        assert response.headers["etag"]
        cached = client.get(
            "/api/v1/players?q=alex&page_size=1",
            headers={"If-None-Match": response.headers["etag"]},
        )
        assert cached.status_code == 304

        detail = client.get("/api/v1/players/100")
        assert detail.status_code == 200
        assert detail.json()["player"]["player_id"] == 100
        assert detail.json()["player"]["profile_status"] == "inventory_only"
        assert client.get("/api/v1/players/999").status_code == 404
        assert client.get("/api/v1/players?page=0").status_code == 422


@pytest.mark.parametrize(
    ("status", "goals"),
    [("played", (0, 0)), ("unplayed", (None, None))],
)
def test_match_result_contract_keeps_played_zero_zero_distinct_from_pending(
    status: str, goals: tuple[int | None, int | None]
) -> None:
    record = MatchGenerationRecordResponse.model_validate({
        "internal_id": "group-II:test-1",
        "source_match_id": "999",
        "matchday": 1,
        "matchday_date": None,
        "source_match_date": None,
        "home_team_id": 49,
        "away_team_id": 48,
        "home_goals": goals[0],
        "away_goals": goals[1],
        "home_yellow_cards": None,
        "away_yellow_cards": None,
        "home_red_cards": None,
        "away_red_cards": None,
        "status": status,
        "unplayed_state": None if status == "played" else "scheduled",
        "postponed_by_source_rule": None,
        "source_match_url": None,
        "stadium_id": None,
        "stadium_name": None,
        "stadium_url": None,
        "referee_id": None,
        "referee_name": None,
        "referee_url": None,
    })
    assert record.status == status
    assert (record.home_goals, record.away_goals) == goals
