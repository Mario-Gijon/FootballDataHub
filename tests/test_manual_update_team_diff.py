"""Regression tests for comparing team captures against split published hashes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from football_data_hub_api.manual_updates import ManualUpdateError, _team_change_details, _team_data_changes


def _write_json(path: Path, payload: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def _captures(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    prior = tmp_path / "captures" / "20261012T131457.209360Z-602005d8"
    candidate = tmp_path / "candidate"
    core_path = "normalized/players.json"
    follow_path = "normalized/player_match_metrics.json"
    core_hash = _write_json(prior / core_path, {"players": [{"player_id": 1}]})
    follow_hash = _write_json(prior / follow_path, {"records": [{"goals": 1}]})
    _write_json(candidate / core_path, {"players": [{"player_id": 1}]})
    _write_json(candidate / follow_path, {"records": [{"goals": 2}]})
    entry: dict[str, object] = {
        "capture_id": prior.name,
        "directory": str(prior),
        "files_sha256": {core_path: core_hash},
        "normalized_files_sha256": {core_path: core_hash, follow_path: follow_hash},
        "follow_files_sha256": {
            follow_path: follow_hash,
            "raw/follow_states/go.html.gz": "a" * 64,
        },
    }
    return prior, candidate, entry


def test_team_diff_reads_follow_hashes_from_published_index_maps(tmp_path: Path) -> None:
    _prior, candidate, entry = _captures(tmp_path)

    changes = _team_data_changes(candidate, entry, tmp_path / "index.json")

    assert changes == ["normalized/player_match_metrics.json"]


def test_team_diff_rejects_conflicting_duplicate_hashes(tmp_path: Path) -> None:
    _prior, candidate, entry = _captures(tmp_path)
    entry["follow_files_sha256"] = {"normalized/player_match_metrics.json": "b" * 64}

    with pytest.raises(ManualUpdateError, match="hashes contradictorios"):
        _team_data_changes(candidate, entry, tmp_path / "index.json")


def test_team_diff_rejects_unindexed_prior_normalized_file(tmp_path: Path) -> None:
    prior, candidate, entry = _captures(tmp_path)
    _write_json(prior / "normalized/untracked.json", {"source": "historical"})
    _write_json(candidate / "normalized/untracked.json", {"source": "historical"})

    with pytest.raises(ManualUpdateError, match="no tiene un hash verificable"):
        _team_data_changes(candidate, entry, tmp_path / "index.json")


def test_team_diff_rejects_modified_published_follow_snapshot(tmp_path: Path) -> None:
    prior, candidate, entry = _captures(tmp_path)
    (prior / "normalized/player_match_metrics.json").write_text('{"records": []}', encoding="utf-8")

    with pytest.raises(ManualUpdateError, match="comprobación de integridad"):
        _team_data_changes(candidate, entry, tmp_path / "index.json")


def test_team_diff_ignores_order_only_changes_in_transfer_records(tmp_path: Path) -> None:
    prior, candidate, entry = _captures(tmp_path)
    rows = [
        {"direction": "incoming", "player_id": 202, "other_team_name": "Club A"},
        {"direction": "outgoing", "player_id": 101, "other_team_name": "Club B"},
    ]
    path = "normalized/transfers.json"
    digest = _write_json(prior / path, {"records": rows})
    _write_json(candidate / path, {"records": list(reversed(rows))})
    entry["normalized_files_sha256"][path] = digest
    entry["transfers_files_sha256"] = {path: digest}

    changes = _team_data_changes(candidate, entry, tmp_path / "index.json")

    assert path not in changes


def test_team_diff_rejects_duplicate_transfer_identity(tmp_path: Path) -> None:
    prior, candidate, entry = _captures(tmp_path)
    rows = [
        {"direction": "incoming", "player_id": 202},
        {"direction": "incoming", "player_id": 202},
    ]
    path = "normalized/transfers.json"
    digest = _write_json(prior / path, {"records": rows})
    _write_json(candidate / path, {"records": rows})
    entry["normalized_files_sha256"][path] = digest

    with pytest.raises(ManualUpdateError, match="duplicados"):
        _team_data_changes(candidate, entry, tmp_path / "index.json")


def test_team_change_details_explain_player_match_and_coach_changes(tmp_path: Path) -> None:
    prior = tmp_path / "prior"
    candidate = tmp_path / "candidate"
    _write_json(prior / "normalized/players.json", {"records": [{"player_id": 7, "display_name": "Delantero"}]})
    _write_json(candidate / "normalized/players.json", {"records": [{"player_id": 7, "display_name": "Delantero"}]})
    _write_json(prior / "normalized/memberships.json", {"records": [{"player_id": 7, "jersey_number": 9}]})
    _write_json(candidate / "normalized/memberships.json", {"records": [{"player_id": 7, "jersey_number": 10}]})
    _write_json(prior / "normalized/player_statistics.json", {"records": [{"player_id": 7, "matches_played": 1}]})
    _write_json(candidate / "normalized/player_statistics.json", {"records": [{"player_id": 7, "matches_played": 2}]})
    _write_json(prior / "normalized/player_match_minutes.json", {"records": []})
    _write_json(candidate / "normalized/player_match_minutes.json", {"records": [{"player_id": 7, "match_id": "123", "matchday": 1, "metric": "minutes_played"}]})
    _write_json(prior / "normalized/player_match_metrics.json", {"records": []})
    _write_json(candidate / "normalized/player_match_metrics.json", {"records": [{"player_id": 7, "match_id": "123", "matchday": 1, "metric": "goals"}]})
    _write_json(prior / "normalized/profile_references.json", {"match_ids_from_profile": ["100"]})
    _write_json(candidate / "normalized/profile_references.json", {"match_ids_from_profile": ["100", "123"]})
    coach = {"coach_id": 2, "display_name": "Entrenador", "matches_managed": 1, "coached_matchdays_source": "1"}
    _write_json(prior / "normalized/team_season.json", {"record": {"coaches": [coach]}})
    updated_coach = {**coach, "matches_managed": 2, "coached_matchdays_source": "1-2"}
    _write_json(candidate / "normalized/team_season.json", {"record": {"coaches": [updated_coach]}})

    details = _team_change_details(candidate, prior, [
        "normalized/memberships.json", "normalized/player_statistics.json",
        "normalized/player_match_minutes.json", "normalized/player_match_metrics.json",
        "normalized/profile_references.json", "normalized/team_season.json",
    ])
    rendered = " ".join(item for section in details for item in section["items"])

    assert "Delantero (#7): dorsal 9 → 10" in rendered
    assert "partidos jugados 1 → 2" in rendered
    assert "Jornada 1, partido 123" in rendered
    assert "1 gol" in rendered
    assert "Nuevos partidos referenciados: 123" in rendered
    assert "partidos dirigidos 1 → 2" in rendered
