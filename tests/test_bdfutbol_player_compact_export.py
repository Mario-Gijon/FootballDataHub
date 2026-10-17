from __future__ import annotations

import hashlib
import gzip
import json
from pathlib import Path

from football_data_hub.providers.bdfutbol.players.capture_store import PlayerCaptureStore
from football_data_hub.providers.bdfutbol.players.batch import load_verified_compact_sample
from football_data_hub.providers.bdfutbol.players.compact_export import (
    build_compact_player_generation,
    compact_player_page,
)
from football_data_hub.providers.bdfutbol.players.models import PlayerMatchesPage


def _save_view(root: Path, view: str) -> str:
    urls = {
        "profile": "https://www.bdfutbol.com/es/j/j12345.html",
        "statistics": "https://www.bdfutbol.com/es/j/j12345.html?p=stats",
        "matches": "https://www.bdfutbol.com/es/p/j12345.html",
        "rivals": "https://www.bdfutbol.com/es/p/jr12345.html",
    }
    match_table = (
        "<table id='tpartits'><thead><tr><th>Fecha</th><th>Local</th>"
        "<th>Marcador</th><th>Visitante</th></tr></thead><tbody></tbody></table>"
        "<script>window.P=[];</script>"
        if view == "matches" else ""
    )
    html = (
        "<html><head><title>Test Player | BDFutbol</title></head>"
        f"<body><h1>Test Player</h1>{match_table}</body></html>"
    )
    store = PlayerCaptureStore(root, capture_id=f"run-{view}")
    store.save_snapshot(
        player_id=12345,
        view=view,
        requested_url=urls[view],
        final_url=urls[view],
        http_status=200,
        page_title="Test Player | BDFutbol",
        html=html,
        browser={"backend": "fixture"},
    )
    store.mark_complete()
    return store.capture_id


def test_compact_projection_separates_appearances_and_calls_without_dom_layout() -> None:
    page = PlayerMatchesPage(
        player_id=12345,
        source_player_key="j12345",
        view="matches",
        requested_url="https://www.bdfutbol.com/es/p/j12345.html",
        final_url="https://www.bdfutbol.com/es/p/j12345.html",
        page_title_raw="Test Player",
        source={},
        filter_controls=[{"id": "cat", "options": [{"value": "1rf"}]}],
        tables=[{"table_id": "tpartits", "cells": ["verbose"]}],
        relationships=[],
        coverage={"detail_scope": "snapshot"},
        summary_rows=[],
        individual_matches=[
            {
                "match_id": "271000",
                "player_appearance_status": "APPEARED_PER_SOURCE_FLAGS",
                "player_summoned_status": "NOT_MARKED_AS_SUMMONED",
                "source_values_raw": [1, 2, 3],
                "source_snapshot": {"path": "raw.html.gz"},
            },
            {
                "match_id": "271001",
                "player_appearance_status": "NO_APPEARANCE_PER_SOURCE_FLAGS",
                "player_summoned_status": "SUMMONED_WITHOUT_APPEARANCE_PER_SOURCE_FLAG",
                "source_values_raw": [4, 5, 6],
                "source_snapshot": {"path": "raw.html.gz"},
            },
        ],
        individual_matches_source="WINDOW_P",
        window_p_parse_status="PARSED_27_FIELD_TUPLES",
        window_p_record_count=2,
        detail_coverage="base snapshot",
        filter_parameters={},
        filtered_view=False,
        exhaustiveness_status="SNAPSHOT_SCOPE_ONLY_NOT_CERTIFIED_COMPLETE",
    )
    compact = compact_player_page(page, {"html_sha256": "a" * 64})

    assert [row["match_id"] for row in compact["individual_matches"]] == ["271000"]
    assert [row["match_id"] for row in compact["summoned_without_participation"]] == ["271001"]
    assert compact["record_counts"] == {
        "individual_matches": 1,
        "summoned_without_participation": 1,
        "other_match_records": 0,
    }
    assert "source_values_raw" not in compact["individual_matches"][0]
    assert "source_snapshot" not in compact["individual_matches"][0]
    assert "tables" not in compact
    assert "filter_controls" not in compact
    assert compact["exhaustiveness_status"] == "SNAPSHOT_SCOPE_ONLY_NOT_CERTIFIED_COMPLETE"


def test_generation_consolidates_verified_views_across_runs_atomically(tmp_path: Path) -> None:
    capture_root = tmp_path / "captures"
    source_capture_ids = {
        view: _save_view(capture_root, view)
        for view in ("profile", "statistics", "matches", "rivals")
    }
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({
        "metadata": {"season": "2026-27"},
        "records": [{
            "player_id": 12345,
            "display_name": "Test Player",
            "full_name": "Test Full Name",
            "profile_url": "https://www.bdfutbol.com/es/j/j12345.html",
            "membership_count": 1,
            "team_associations": [{"team_id": 49, "group": "II", "team_name": "Jaén"}],
            "identity_conflicts": [],
        }],
    }), encoding="utf-8")

    result = build_compact_player_generation(
        inventory_path=inventory,
        capture_root=capture_root,
        output_root=tmp_path / "compact",
        max_workers=1,
    )

    player_path = Path(result["generation_dir"]) / "players/12345.json.gz"
    document = json.loads(gzip.decompress(player_path.read_bytes()))
    pointer = json.loads((tmp_path / "compact/current.json").read_text(encoding="utf-8"))
    assert document["status"] == "COMPLETE_BASE_VIEWS"
    assert document["base_view_completeness_certifies_historical_exhaustiveness"] is False
    assert set(document["views"]) == {"profile", "statistics", "matches", "rivals"}
    assert {item["capture_id"] for item in document["view_sources"].values()} == set(source_capture_ids.values())
    assert all(item["metadata_sha256"] for item in document["view_sources"].values())
    assert result["complete_player_count"] == 1
    assert result["partial_player_count"] == 0
    assert result["compact_json_gzip_bytes"] == player_path.stat().st_size
    assert result["compact_json_uncompressed_bytes"] > result["compact_json_gzip_bytes"]
    assert pointer["generation_id"] == result["generation_id"]
    assert hashlib.sha256(player_path.read_bytes()).hexdigest() == next(
        item["sha256"] for item in json.loads(
            (Path(result["generation_dir"]) / "manifest.json").read_text(encoding="utf-8")
        )["entries"]
    )
    verified_manifest, verified_entries = load_verified_compact_sample(tmp_path / "compact")
    assert verified_manifest["generation_id"] == result["generation_id"]
    assert verified_entries[0]["compression"] == "gzip"


def test_compact_generation_keeps_player_partial_when_a_base_view_is_missing(tmp_path: Path) -> None:
    capture_root = tmp_path / "captures"
    for view in ("profile", "statistics", "matches"):
        _save_view(capture_root, view)
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({
        "metadata": {"season": "2026-27"},
        "records": [{
            "player_id": 12345,
            "display_name": "Test Player",
            "membership_count": 1,
            "identity_conflicts": [],
        }],
    }), encoding="utf-8")

    result = build_compact_player_generation(
        inventory_path=inventory,
        capture_root=capture_root,
        output_root=tmp_path / "compact",
        max_workers=1,
    )
    player_path = Path(result["generation_dir"]) / "players/12345.json.gz"
    document = json.loads(gzip.decompress(player_path.read_bytes()))
    assert document["status"] == "PARTIAL_BASE_VIEWS"
    assert document["views_missing"] == ["rivals"]
    assert result["complete_player_count"] == 0
    assert result["partial_player_count"] == 1


def test_generation_refuses_progress_index_for_another_inventory(tmp_path: Path) -> None:
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"metadata": {}, "records": []}), encoding="utf-8")
    progress = {
        "inventory": {"sha256": "0" * 64},
        "capture_root": str((tmp_path / "captures").resolve()),
        "players": [],
    }
    try:
        build_compact_player_generation(
            inventory_path=inventory,
            capture_root=tmp_path / "captures",
            output_root=tmp_path / "compact",
            progress_index=progress,
        )
    except ValueError as exc:
        assert "otro inventario" in str(exc)
    else:
        raise AssertionError("Se aceptó un índice de progreso para otro inventario")
