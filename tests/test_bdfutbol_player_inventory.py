from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from football_data_hub.providers.bdfutbol.teams.player_inventory import (
    PlayerInventoryError,
    build_player_inventory,
    write_inventory_atomic,
)


def _write_json(path: Path, payload: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _build_fixture(root: Path, *, conflicting_name: bool = False) -> tuple[Path, dict[str, Path]]:
    profiles = {}
    for team_id, group, team_name in ((10, "I", "Equipo Uno"), (20, "II", "Equipo Dos")):
        capture_id = f"capture-{team_id}"
        capture_dir = root / "captures" / str(team_id) / capture_id
        metadata = {
            "source": "BDFutbol",
            "season": "2026-27",
            "team_id": team_id,
            "group": group,
            "capture_id": capture_id,
            "captured_at_utc": f"2026-10-{team_id:02d}T12:00:00+00:00",
        }
        validation = {"valid": True, "issues": []}
        identity = {"metadata": {"capture_id": capture_id}, "record": {"team_id": team_id, "name": team_name}}
        player = {
            "player_id": 100,
            "display_name": "Jugador" if not (conflicting_name and team_id == 20) else "Identidad distinta",
            "full_name": None,
            "profile_url": "https://www.bdfutbol.com/es/j/j100.html",
            "photo_url": None,
            "age_years": None,
            "birth_date": None,
            "birthplace": None,
            "birthplace_province": None,
            "nationality_flag_url": None,
            "source_position_code": "4",
            "verified_indicators": [],
            "source_views": ["squad"],
        }
        roster = [player]
        if team_id == 10:
            roster.append(
                {
                    **player,
                    "player_id": 101,
                    "display_name": "Jugador Nulo",
                    "profile_url": "https://www.bdfutbol.com/es/j/j101.html",
                }
            )
        memberships = [
            {
                "player_id": item["player_id"],
                "team_id": team_id,
                "season": "2026-27",
                "competition": "Primera Federación",
                "group": group,
                "jersey_number": None,
                "squad_group_label": None,
                "source_views": ["squad"],
            }
            for item in roster
        ]
        stats = [
            {
                "player_id": 100,
                "team_id": team_id,
                "season": "2026-27",
                "competition": "Primera Federación",
                "group": group,
                "matches_played": 0,
                "minutes_played": None,
                "goals": 0,
                "source_view": "statistics",
            }
        ]
        transfer_records = []
        if team_id == 10:
            transfer_records = [
                {
                    "player_id": 100,
                    "player_display_name": "Jugador",
                    "player_full_name": None,
                    "player_profile_url": "https://www.bdfutbol.com/es/j/j100.html",
                    "player_photo_url": None,
                    "team_id": team_id,
                    "season": "2026-27",
                    "competition": "Primera Federación",
                    "group": group,
                    "direction": "incoming",
                    "source_position_code": None,
                },
                {
                    "player_id": 200,
                    "player_display_name": "Solo traspaso",
                    "player_full_name": None,
                    "player_profile_url": "https://www.bdfutbol.com/es/j/j200.html",
                    "player_photo_url": None,
                    "team_id": team_id,
                    "season": "2026-27",
                    "competition": "Primera Federación",
                    "group": group,
                    "direction": "outgoing",
                    "source_position_code": None,
                }
            ]
        docs = {
            "metadata/capture.json": metadata,
            "validation/results.json": validation,
            "normalized/team_identity.json": identity,
            "normalized/players.json": {"metadata": {"capture_id": capture_id, "team_id": team_id, "season": "2026-27", "group": group}, "records": roster},
            "normalized/memberships.json": {"metadata": {"capture_id": capture_id}, "records": memberships},
            "normalized/player_statistics.json": {"metadata": {"capture_id": capture_id}, "records": stats},
            "normalized/player_match_minutes.json": {"metadata": {"capture_id": capture_id}, "records": []},
            "normalized/player_match_metrics.json": {"metadata": {"capture_id": capture_id}, "records": []},
            "normalized/transfers.json": {"metadata": {"capture_id": capture_id}, "records": transfer_records},
        }
        hashes = {relative: _write_json(capture_dir / relative, payload) for relative, payload in docs.items()}
        profiles[str(team_id)] = {
            "capture_id": capture_id,
            "directory": str(capture_dir),
            "files_sha256": hashes,
            "publication_validation": {
                "classification": "complete",
                "active_catalog_compatible": True,
                "capture_id": capture_id,
            },
        }
    index_path = root / "published.json"
    _write_json(index_path, {"schema_version": 1, "season": "2026-27", "profiles": profiles})
    return index_path, {"10": root / "captures/10/capture-10", "20": root / "captures/20/capture-20"}


def _build(index_path: Path):
    return build_player_inventory(
        index_path,
        expected_profile_count=2,
        expected_group_counts={"I": 1, "II": 1},
    )


def test_deduplicates_only_by_player_id_and_keeps_each_membership(tmp_path: Path) -> None:
    index_path, _ = _build_fixture(tmp_path)
    players, memberships, report, _ = _build(index_path)
    player = next(row for row in players["records"] if row["player_id"] == 100)
    assert len(players["records"]) == 3  # Two roster IDs plus a transfer-only ID.
    assert player["membership_count"] == 2
    assert {item["team_id"] for item in memberships["records"] if item["player_id"] == 100} == {10, 20}
    association = next(item for item in player["team_associations"] if item["team_id"] == 10)
    assert association["evidence_types"] == ["membership", "transfer_reference"]
    assert report["counts"]["roster_player_records"] == 3
    assert report["counts"]["unique_roster_player_ids"] == 2
    assert report["counts"]["unique_transfer_only_player_ids"] == 1


def test_preserves_nulls_zeroes_and_transfer_only_status(tmp_path: Path) -> None:
    index_path, _ = _build_fixture(tmp_path)
    players, _, report, _ = _build(index_path)
    by_id = {row["player_id"]: row for row in players["records"]}
    assert by_id[100]["full_name"] is None
    assert by_id[100]["photo_url"] is None
    assert by_id[100]["season_statistics"][0]["record"]["matches_played"] == 0
    assert by_id[100]["season_statistics"][0]["record"]["minutes_played"] is None
    assert by_id[200]["association_status"] == "transfer_reference_only"
    assert by_id[200]["membership_count"] == 0
    assert report["counts"]["players_without_photo_url"] == 3


def test_conflicting_identity_is_preserved_and_not_merged_by_name(tmp_path: Path) -> None:
    index_path, _ = _build_fixture(tmp_path, conflicting_name=True)
    players, _, report, _ = _build(index_path)
    player = next(row for row in players["records"] if row["player_id"] == 100)
    assert player["display_name"] is None
    assert player["identity_conflicts"][0]["field"] == "display_name"
    assert report["counts"]["identity_conflicts"] == 1
    assert len(player["identity_conflicts"][0]["observations"]) == 3


def test_provenance_contains_capture_ids_and_hashed_source_paths(tmp_path: Path) -> None:
    index_path, _ = _build_fixture(tmp_path)
    players, memberships, _, manifest = _build(index_path)
    player = next(row for row in players["records"] if row["player_id"] == 100)
    assert {ref["capture_id"] for ref in player["source_refs"]} == {"capture-10", "capture-20", "capture-10"}
    assert all(len(ref["sha256"]) == 64 and ref["path"].endswith(".json") for ref in player["source_refs"])
    assert len(memberships["records"][0]["source_ref"]["sha256"]) == 64
    assert manifest["generation_policy"]["external_access_used"] is False
    assert manifest["verified_team_capture_files"] > 0


def test_hash_mismatch_is_rejected_before_inventory_build(tmp_path: Path) -> None:
    index_path, capture_dirs = _build_fixture(tmp_path)
    players_path = capture_dirs["10"] / "normalized/players.json"
    players_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(PlayerInventoryError, match="SHA-256 incorrecto"):
        _build(index_path)


def test_repeated_build_is_reproducible_for_inventory_payloads(tmp_path: Path) -> None:
    index_path, _ = _build_fixture(tmp_path)
    first = _build(index_path)
    second = _build(index_path)
    assert first[:3] == second[:3]
    assert first[3]["team_captures"] == second[3]["team_captures"]
    assert first[3]["source_index"] == second[3]["source_index"]


def test_validated_top_snapshot_supplements_nationality_by_id(tmp_path: Path) -> None:
    index_path, _ = _build_fixture(tmp_path)
    root = tmp_path / "top-group-I"
    raw_path = root / "raw/source.html"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("<!-- synthetic fixture -->", encoding="utf-8")
    raw_hash = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    capture_id = "top-capture-I"
    _write_json(
        root / "metadata/capture.json",
        {
            "source": "BDFutbol",
            "season": "2026-27",
            "group": "I",
            "capture_id": capture_id,
            "captured_at_utc": "2026-10-10T20:25:10+00:00",
            "source_snapshot_sha256": raw_hash,
        },
    )
    _write_json(root / "validation/results.json", {"valid": True, "issues": []})
    _write_json(
        root / "normalized/players.json",
        {
            "metadata": {
                "capture_id": capture_id,
                "season": "2026-27",
                "group": "I",
                "source_snapshot_sha256": raw_hash,
            },
            "records": [
                {
                    "player_id": 100,
                    "nationality": "España",
                    "nationality_code": "espanya",
                    "position_name": "Defensa",
                    "position_code": "def",
                    "age_years": 25,
                    "team_id": 10,
                    "team_name": "Equipo Uno",
                }
            ],
        },
    )
    players, _, report, manifest = build_player_inventory(
        index_path,
        top_roots={"I": root},
        expected_profile_count=2,
        expected_group_counts={"I": 1, "II": 1},
    )
    player = next(row for row in players["records"] if row["player_id"] == 100)
    assert player["nationality"] == "España"
    assert player["nationality_code"] == "espanya"
    assert player["position_name"] == "Defensa"
    assert player["team_ids"] == [10, 20]  # Top's team_id is not treated as a new membership.
    assert player["nationality_source_refs"][0]["capture_id"] == capture_id
    assert report["counts"]["top_player_ids_matched_by_player_id"] == 1
    assert manifest["supplemental_top_captures"][0]["source_snapshot_sha256"] == raw_hash


def test_atomic_writer_publishes_complete_set_and_refuses_overwrite(tmp_path: Path) -> None:
    index_path, _ = _build_fixture(tmp_path)
    players, memberships, report, manifest = _build(index_path)
    destination = tmp_path / "inventory"
    hashes = write_inventory_atomic(destination, players, memberships, report, manifest)
    assert set(hashes) == {"players.json", "memberships.json", "inventory_report.json", "manifest.json"}
    assert {path.name for path in destination.iterdir()} == set(hashes)
    with pytest.raises(PlayerInventoryError, match="no se sobrescribirá"):
        write_inventory_atomic(destination, players, memberships, report, manifest)
