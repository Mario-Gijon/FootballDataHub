from __future__ import annotations

import json
import shutil
from pathlib import Path

from football_data_hub.providers.bdfutbol.context import get_competition_context
from football_data_hub.providers.bdfutbol.teams import batch_cli
from football_data_hub.providers.bdfutbol.teams.acquisition import DEFAULT_VIEWS, FOLLOW_STATES
from football_data_hub.providers.bdfutbol.teams.capture_store import inspect_team_capture
from football_data_hub.providers.bdfutbol.teams.catalog import load_team_catalog

ROOT = Path(__file__).resolve().parents[1]
GROUP_CATALOGS = {
    1: ROOT / "data/exports/bdfutbol/group1_classification/20261010T202500.293648Z-b770724f/normalized/matches.json",
    2: ROOT / "data/exports/bdfutbol/group2_classification/derived-res01-20261010T102656Z/normalized/matches.json",
}
PROFILE_RUNS = {
    1: ROOT / "data/exports/bdfutbol/teams/2026-27/48/20261011T123240.190812Z-8f307d1c",
    2: ROOT / "data/exports/bdfutbol/teams/2026-27/49/team01a-group2-49-source-evidence",
}
DERIVED_PROFILE_RUNS = {
    1: ROOT / "data/exports/bdfutbol/teams/2026-27/48/20261012T131518.543469Z-43ff1122",
    2: ROOT / "data/exports/bdfutbol/teams/2026-27/49/20261012T131457.209360Z-602005d8",
}


def _inspect(capture: Path, group: int, team_id: int):
    context = get_competition_context(group=group)
    teams, matches, reference = load_team_catalog(GROUP_CATALOGS[group], competition=context)
    record = next(item for item in teams if int(item["team_id"]) == team_id)
    return inspect_team_capture(
        capture,
        team_catalog_record=record,
        competition=context,
        team_catalog_reference=reference,
        group_team_catalog=teams,
        known_matches=matches,
    )


def test_transfer_reparse_keeps_original_as_seed_and_derived_capture_complete():
    racing_original = _inspect(PROFILE_RUNS[1], 1, 48)
    racing_derived = _inspect(DERIVED_PROFILE_RUNS[1], 1, 48)
    jaen = _inspect(PROFILE_RUNS[2], 2, 49)

    # The immutable source snapshot still has the pre-fix transfer direction.
    assert racing_original.classification == "reusable_seed"
    assert racing_original.valid_for_original_scope is True
    assert racing_original.complete_for_current_policy is False
    assert racing_original.valid_views == DEFAULT_VIEWS
    assert racing_original.valid_follow_states == FOLLOW_STATES
    assert racing_original.normalized_valid is False
    assert any("normalized/transfers.json" in reason for reason in racing_original.reasons)

    assert racing_derived.classification == "complete"
    assert racing_derived.valid_for_original_scope is True
    assert racing_derived.complete_for_current_policy is True
    assert racing_derived.valid_views == DEFAULT_VIEWS
    assert racing_derived.valid_follow_states == FOLLOW_STATES
    assert racing_derived.normalized_valid is True

    assert jaen.classification == "reusable_seed"
    assert jaen.valid_for_original_scope is True
    assert jaen.complete_for_current_policy is False
    assert jaen.valid_views == DEFAULT_VIEWS
    assert jaen.valid_follow_states == ("p",)
    assert jaen.missing_follow_states == ("t", "go", "tot")
    assert "Falta JSON normalizado: normalized/player_match_metrics.json" in jaen.reasons


def test_corrupt_follow_state_is_excluded_from_verified_coverage(tmp_path: Path):
    source = PROFILE_RUNS[1]
    capture = tmp_path / "capture"
    shutil.copytree(source, capture)
    metadata_path = capture / "metadata/capture.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    evidence = metadata["follow_states"]["t"]
    (capture / evidence["path"]).write_bytes(b"corrupted gzip data")

    result = _inspect(capture, 1, 48)

    assert result.reusable_as_seed is True
    assert result.complete_for_current_policy is False
    assert "t" not in result.valid_follow_states
    assert "t" in result.missing_follow_states
    assert any("Estado Seguimiento t no reutilizable" in reason for reason in result.reasons)


def test_missing_source_hash_and_wrong_scope_are_not_reusable(tmp_path: Path):
    source = PROFILE_RUNS[1]
    missing_hash = tmp_path / "missing-hash"
    shutil.copytree(source, missing_hash)
    metadata_path = missing_hash / "metadata/capture.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["source_snapshots"]["alignment"].pop("sha256")
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    result = _inspect(missing_hash, 1, 48)
    assert result.complete_for_current_policy is False
    assert result.reusable_as_seed is False
    assert "alignment" in result.missing_views

    wrong_scope = tmp_path / "wrong-scope"
    shutil.copytree(source, wrong_scope)
    metadata_path = wrong_scope / "metadata/capture.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["group"] = "II"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    result = _inspect(wrong_scope, 1, 48)
    assert result.classification == "invalid"
    assert result.reusable_as_seed is False

    wrong_season = tmp_path / "wrong-season"
    shutil.copytree(source, wrong_season)
    metadata_path = wrong_season / "metadata/capture.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["season"] = "2025-26"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    result = _inspect(wrong_season, 1, 48)
    assert result.classification == "invalid"
    assert result.reusable_as_seed is False

    wrong_catalog = tmp_path / "wrong-catalog"
    shutil.copytree(source, wrong_catalog)
    metadata_path = wrong_catalog / "metadata/capture.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["related_team_catalog"]["source_capture_id"] = "unrelated-source"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    result = _inspect(wrong_catalog, 1, 48)
    assert result.classification == "invalid"
    assert result.reusable_as_seed is False


def test_normalized_files_are_required_for_current_completeness(tmp_path: Path):
    source = PROFILE_RUNS[1]
    capture = tmp_path / "capture"
    shutil.copytree(source, capture)
    (capture / "normalized/player_match_metrics.json").unlink()

    result = _inspect(capture, 1, 48)

    assert result.reusable_as_seed is True
    assert result.complete_for_current_policy is False
    assert result.normalized_valid is False
    assert any("player_match_metrics.json" in reason for reason in result.reasons)


def test_batch_team_selection_is_catalog_scoped_and_limit_is_global():
    records = {
        1: [{"team_id": 48}, {"team_id": 18}],
        2: [{"team_id": 49}, {"team_id": 17}],
    }
    selected = batch_cli.select_team_records(
        records, groups=(1, 2), team_ids=[49, 48], limit=1
    )
    assert [item["team_id"] for item in selected[1]] == [48]
    assert selected[2] == []

    try:
        batch_cli.select_team_records(records, groups=(1,), team_ids=[49])
    except ValueError as exc:
        assert "no pertenecen" in str(exc)
    else:
        raise AssertionError("ID de otro grupo aceptado")

    try:
        batch_cli.select_team_records(records, groups=(1,), team_ids=[48, 48])
    except ValueError as exc:
        assert "no puede repetirse" in str(exc)
    else:
        raise AssertionError("ID repetido aceptado")

    assert batch_cli.covers_full_catalog_scope(
        {1: records[1], 2: records[2]}, records, groups=(1, 2)
    )
    assert not batch_cli.covers_full_catalog_scope(
        {1: records[1][:1], 2: []}, records, groups=(1, 2)
    )
    complete_entries = [{"status": "complete"} for _ in range(4)]
    assert batch_cli.is_complete_batch(
        full_catalog_scope=True, groups=(1, 2), entries=complete_entries
    )
    assert not batch_cli.is_complete_batch(
        full_catalog_scope=True, groups=(1,), entries=complete_entries
    )
    assert not batch_cli.is_complete_batch(
        full_catalog_scope=True,
        groups=(1, 2),
        entries=[*complete_entries[:-1], {"status": "pending"}],
    )


def test_batch_dry_run_reports_plan_without_starting_acquisition(monkeypatch, capsys):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("dry-run intentó iniciar una adquisición")

    monkeypatch.setattr(batch_cli, "acquire_team_profile", forbidden)
    result = batch_cli.main([
        "--season", "2026-27",
        "--groups", "I",
        "--team-id", "48",
        "--dry-run",
        "--pause-seconds", "0",
    ])
    plan = json.loads(capsys.readouterr().out)

    assert result == 0
    assert plan["browser_started"] is False
    assert plan["teams_selected"] == 1
    assert plan["full_catalog_scope"] is False
    assert plan["teams"][0]["action"] == "skip_complete"
