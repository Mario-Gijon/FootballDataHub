"""Opt-in, offline, read-only regression against the saved 272582 artifact."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import urllib.request
from pathlib import Path

import pytest

from football_data_hub.providers.bdfutbol.match_details.inventory import (
    build_match_detail_inventory,
    load_verified_match_generation,
)
from football_data_hub.providers.bdfutbol.match_details.semantic_parser import (
    parse_saved_artifact,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("FDH_MATCH_01C_INTEGRATION") != "1",
    reason="Opt-in local-artifact test; set FDH_MATCH_01C_INTEGRATION=1",
)

GENERATION_ID = "match-00-4ad1d610507e425d"
INVENTORY_ID = "match-detail-inventory-8cf339654c80c0ef"
DISCOVERY_ID = "20261016T163942.933046Z-eb9b59e1"
MATCH_ID = "272582"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _existing_files(paths: list[Path]) -> dict[Path, str]:
    return {
        file: _sha256(file)
        for path in paths
        for file in ([path] if path.is_file() else sorted(path.rglob("*")))
        if file.is_file()
    }


def test_saved_272582_artifact_is_semantically_readable_without_mutation(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("MATCH-01C integration must remain offline")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)

    data_root = Path(
        os.environ.get("FDH_MATCH_01C_DATA_ROOT", Path.home() / "FootballDataHub-data")
    ).expanduser()
    generation_root = data_root / "matches/generations" / GENERATION_ID
    artifact = (
        Path(os.environ.get("FDH_MATCH_01C_ARTIFACT_DIR", "" )).expanduser()
        if os.environ.get("FDH_MATCH_01C_ARTIFACT_DIR")
        else data_root
        / "matches/details/diagnostics"
        / INVENTORY_ID
        / DISCOVERY_ID
    )
    state_path = data_root / "matches/details/states" / f"{INVENTORY_ID}.json"
    if not generation_root.is_dir() or not artifact.is_dir():
        pytest.skip("El artefacto/generación local no existe; no se descarga ni recrea")

    manifest_path = generation_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_paths = [manifest_path, generation_root]
    for source_capture in manifest["source_captures"]:
        for key in ("capture_metadata", "source_html", "normalized_matches"):
            source_paths.append(data_root / source_capture["files"][key]["path"])
    source_paths.extend([artifact, state_path])
    before = _existing_files(source_paths)

    verified = load_verified_match_generation(generation_root, data_root=data_root)
    inventory = build_match_detail_inventory(verified)
    expected = next(
        record
        for record in inventory["matches"]
        if record["source_match_id"] == MATCH_ID
    )
    assert inventory["inventory_id"] == INVENTORY_ID
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["status"] == "stopped"
    assert any(
        item.get("source_match_id") == MATCH_ID
        and item.get("access_status") == "INVALID_CONTENT"
        and item.get("stop_acquisition") is True
        for item in state["diagnostics"]
    )

    observation = parse_saved_artifact(artifact, expected_match=expected)

    assert observation.validation.semantic_valid is True
    assert observation.validation.promotion_eligible is False
    assert observation.source.promotion_eligible is False
    assert observation.source.artifact_access_status == "INVALID_CONTENT"
    assert observation.source.discovery_id == DISCOVERY_ID
    assert observation.source.inventory_id == INVENTORY_ID
    assert observation.source.source_html_sha256 == (
        "9242edad00b43a4e83c649ddad006edb0d1172e0d88640082312a0fe1cf16997"
    )
    assert (observation.home.team.team_id, observation.away.team.team_id) == (49, 94)
    assert observation.score.home_goals == observation.score.away_goals == 3
    assert observation.match_date.value == "2026-10-10"
    assert observation.kickoff_time_local.value == "18:45"
    assert observation.context.matchday.value == 7
    assert observation.context.group.value == "II"
    assert observation.context.group.state == "not_observed"
    assert len(observation.home.starters or ()) == 11
    assert len(observation.away.starters or ()) == 11
    assert len(observation.home.substitutes or ()) == 12
    assert len(observation.away.substitutes or ()) == 9
    assert observation.home.coach and observation.home.coach.name == "Manolo Herrero"
    assert observation.away.coach and observation.away.coach.name == "Albelda"
    assert observation.stadium_id.value == 100355
    assert observation.referee_id.value == 601083
    assert observation.referee_name.value == "Campos Salinas"
    assert sum(
        event.event_type in {"goal", "penalty_goal"} for event in observation.events
    ) == 6
    assert sum(event.side == "home" and event.event_type == "yellow_card" for event in observation.events) == 2
    assert sum(event.side == "away" and event.event_type == "yellow_card" for event in observation.events) == 5
    assert sum(event.event_type == "red_card" for event in observation.events) == 0
    assert sum(event.event_type == "substitution_in" for event in observation.events) == 10
    assert sum(event.event_type == "substitution_out" for event in observation.events) == 10
    assert not any(
        warning.startswith("substitution_event_balance_mismatch:")
        for warning in observation.validation.warnings
    )
    assert any(
        check.check == "goal_score_progression_is_chronologically_consistent"
        and check.passed
        for check in observation.validation.checks
    )
    assert observation.aggregate_statistics_state == "explicitly_absent"
    assert any(note.note_type == "ephemeris" for note in observation.additional_notes)
    assert before == _existing_files(source_paths)
