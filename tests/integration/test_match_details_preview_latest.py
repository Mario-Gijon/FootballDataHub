"""Opt-in, offline presentation contract check for the historical 272582 artifact."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from football_data_hub_api.match_details_dataset import load_local_discovery_preview
from football_data_hub_api.match_results_dataset import build_match_page, load_match_results_dataset

pytestmark = pytest.mark.skipif(
    os.environ.get("FDH_MATCH_02_INTEGRATION") != "1",
    reason="Opt-in local preview test; set FDH_MATCH_02_INTEGRATION=1",
)

GENERATION_ID = "match-00-4ad1d610507e425d"
INTERNAL_ID = "pf-2026-27-group-ii-bdfutbol-272582"
INVENTORY_ID = "match-detail-inventory-8cf339654c80c0ef"
DISCOVERY_ID = "20261016T163942.933046Z-eb9b59e1"


def _hash_tree(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_local_preview_renders_real_events_without_publication_or_mutation() -> None:
    data_root = Path(os.environ.get("FDH_MATCH_02_DATA_ROOT", Path.home() / "FootballDataHub-data")).expanduser()
    generation_root = data_root / "matches/generations" / GENERATION_ID
    artifact = data_root / "matches/details/diagnostics" / INVENTORY_ID / DISCOVERY_ID
    if not generation_root.is_dir() or not artifact.is_dir():
        pytest.skip("No existe el artefacto local; no se descarga ni recrea.")
    before = _hash_tree(artifact)
    bundle = load_match_results_dataset(generation_root, data_root=data_root)

    public_page = build_match_page(bundle, INTERNAL_ID)
    preview = load_local_discovery_preview(
        artifact,
        internal_id=INTERNAL_ID,
        generation_root=generation_root,
        data_root=data_root,
        match_bundle=bundle,
        player_ids=set(),
    )

    assert public_page is not None
    assert public_page.detail_status == "not_available"
    assert public_page.details is None
    assert preview.detail_status == "preview_only"
    assert preview.details is not None
    assert preview.details.publication_status == "preview_only"
    assert preview.details.home_team_id == 49 and preview.details.away_team_id == 94
    assert len(preview.details.home.starters or []) == 11
    assert len(preview.details.away.starters or []) == 11
    assert len(preview.details.home.substitutes or []) == 12
    assert len(preview.details.away.substitutes or []) == 9
    assert preview.details.home.coach is not None
    assert preview.details.away.coach is not None
    assert sum(event.event_kind in {"goal", "penalty"} for event in preview.details.events or []) == 6
    assert sum(event.event_kind == "yellow_card" for event in preview.details.events or []) == 7
    assert sum(event.event_kind == "red_card" for event in preview.details.events or []) == 0
    assert sum(event.event_kind == "substitution_in" for event in preview.details.events or []) == 10
    assert sum(event.event_kind == "substitution_out" for event in preview.details.events or []) == 10
    assert all(event.minute is not None for event in preview.details.events or [])
    assert _hash_tree(artifact) == before
