"""Offline tests for automatic, validated competition refresh and shared fixtures."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from football_data_hub_api.main import _assert_group_catalogs_match_generation
from football_data_hub_api.manual_updates import (
    ManualUpdateError,
    ManualUpdateManager,
    _candidate_sha256,
    public_manual_update_job,
)


def _manager(tmp_path: Path) -> ManualUpdateManager:
    project = tmp_path / "project"
    data = tmp_path / "external-data"
    profile = tmp_path / "profile"
    project.mkdir()
    data.mkdir()
    profile.mkdir()
    source_paths: dict[str, Path] = {}
    for group in ("I", "II"):
        for name in ("matches", "classification", "progress"):
            path = data / f"{group}-{name}.json"
            path.write_text("{}", encoding="utf-8")
            source_paths[f"{group}-{name}"] = path
    generation = data / "matches" / "generations"
    generation.mkdir(parents=True)
    details_store = data / "matches" / "details"
    details_store.mkdir()
    return ManualUpdateManager(
        project_root=project,
        data_root=data,
        profile_dir=profile,
        browser_executable=None,
        group_match_paths={g: source_paths[f"{g}-matches"] for g in ("I", "II")},
        group_classification_paths={g: source_paths[f"{g}-classification"] for g in ("I", "II")},
        group_progress_paths={g: source_paths[f"{g}-progress"] for g in ("I", "II")},
        team_profiles_index=None,
        match_generation_root=generation,
        match_details_store_root=details_store,
        player_inventory_root=None,
        player_compact_root=None,
        player_team_captures_root=None,
        player_published_index_path=None,
    )


def _candidate(*, no_changes: bool = False, hard_conflicts: int = 0, played_to_unplayed: int = 0):
    return {
        "kind": "competition_generation",
        "no_changes": no_changes,
        "candidate_generation_id": "generation-candidate",
        "report_sha256": "a" * 64,
        "changed_groups": {"I": ["results_calendar"], "II": []},
        "summary": {
            "hard_conflicts": hard_conflicts,
            "played_to_unplayed_conflicts": played_to_unplayed,
            "newly_played": 2,
            "result_corrected": 1,
            "fixture_updated": 3,
            "played_without_approved_details": 2,
        },
    }


def _job(candidate: dict[str, object]) -> dict[str, object]:
    digest = _candidate_sha256(candidate)
    return {
        "schema_version": 1,
        "job_id": str(uuid.uuid4()),
        "scope": "competition",
        "scope_key": "competition-2026-27",
        "team_id": None,
        "group": None,
        "season": "2026-27",
        "status": "running",
        "stage": "comparing_candidate",
        "created_at": "2026-10-20T10:00:00Z",
        "updated_at": "2026-10-20T10:00:00Z",
        "finished_at": None,
        "summary": None,
        "candidate": {**candidate, "candidate_sha256": digest},
        "candidate_sha256": digest,
        "error": None,
        "log_tail": None,
    }


def test_valid_competition_candidate_is_applied_and_audited_without_human_approval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager(tmp_path)
    job = _job(_candidate())
    activations: list[str] = []
    reloads: list[str] = []
    monkeypatch.setattr(manager, "_preflight", lambda: None)
    monkeypatch.setattr(manager, "_update_competition", lambda _job, _log: _candidate())
    monkeypatch.setattr(manager, "_activate_competition", lambda _job, actor, _log: activations.append(actor) or {"status": "activated", "generation_id": "generation-candidate"})
    manager.on_competition_applied = lambda value: reloads.append(str(value["job_id"]))

    job["candidate"] = _candidate()
    manager._run(job)

    assert job["status"] == "applied"
    assert job["summary"]["message"] == "Actualización aplicada"
    assert job["summary"]["played_without_approved_details"] == 2
    assert activations == ["football-data-hub-local-update-service"]
    assert reloads == [job["job_id"]]
    events = list((manager.root / "reviews").glob("*.json"))
    assert {path.name for path in events} == {
        f"{job['job_id']}-auto-apply-started.json", f"{job['job_id']}-auto-applied.json"
    }
    event = json.loads((manager.root / "reviews" / f"{job['job_id']}-auto-applied.json").read_text())
    assert event["event"] == "COMPETITION_AUTO_APPLIED"
    assert "reviewer" not in event
    assert not (manager.root / "reviews" / f"{job['job_id']}-approval.json").exists()
    saved = json.loads((manager._jobs_dir() / f"{job['job_id']}.json").read_text())
    assert saved["status"] == "applied"
    manager.close()


def test_equal_group_snapshots_report_sin_cambios_without_activation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager(tmp_path)
    job = _job(_candidate(no_changes=True))
    monkeypatch.setattr(manager, "_activate_competition", lambda *_args: pytest.fail("No debe activarse una captura sin cambios"))
    manager._finish_competition_update(job, manager._jobs_dir() / job["job_id"] / "worker.log", no_changes=True)
    assert job["status"] == "completed"
    assert job["summary"]["message"] == "Sin cambios"
    assert not (manager.root / "reviews").exists()
    manager.close()


@pytest.mark.parametrize(
    ("hard_conflicts", "played_to_unplayed"),
    [(1, 0), (0, 1)],
)
def test_conflicted_candidates_are_not_automatically_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hard_conflicts: int, played_to_unplayed: int
) -> None:
    manager = _manager(tmp_path)
    job = _job(_candidate(hard_conflicts=hard_conflicts, played_to_unplayed=played_to_unplayed))
    monkeypatch.setattr(manager, "_activate_competition", lambda *_args: pytest.fail("No se debe activar un conflicto"))
    with pytest.raises(ManualUpdateError):
        manager._finish_competition_update(job, manager._jobs_dir() / job["job_id"] / "worker.log", no_changes=False)
    manager.close()


def test_public_job_hides_internal_candidate_paths_hashes_and_logs() -> None:
    projected = public_manual_update_job({
        "job_id": "job-a", "scope": "competition", "status": "applied", "stage": "completed",
        "summary": {"message": "Actualización aplicada"}, "candidate": {"path": "/private"},
        "candidate_sha256": "sensitive", "log_tail": "command with source paths", "error": None,
    })
    assert projected is not None
    assert projected["summary"] == {"message": "Actualización aplicada"}
    assert "candidate" not in projected and "candidate_sha256" not in projected and "log_tail" not in projected


def _match_record(source_id: str, **changes: object) -> SimpleNamespace:
    fields = {
        "match_id": source_id, "source_match_id": source_id, "matchday": 1,
        "matchday_date": None, "source_match_date": None, "home_team_id": 11,
        "away_team_id": 12, "home_goals": 1, "away_goals": 0,
        "status": "played", "unplayed_state": None, "postponed_by_source_rule": False,
        "source_match_url": None, "stadium_id": None, "stadium_name": None,
        "stadium_url": None, "referee_id": None, "referee_name": None, "referee_url": None,
    }
    fields.update(changes)
    return SimpleNamespace(**fields)


def test_team_fixture_catalog_and_match_detail_generation_share_one_result_by_id() -> None:
    datasets = {
        "1": SimpleNamespace(bootstrap=SimpleNamespace(matches=[_match_record("123")])),
        "2": SimpleNamespace(bootstrap=SimpleNamespace(matches=[_match_record("456")])),
    }
    generated = SimpleNamespace(bootstrap=SimpleNamespace(groups={
        "I": SimpleNamespace(matches=[_match_record("123")]),
        "II": SimpleNamespace(matches=[_match_record("456")]),
    }))
    _assert_group_catalogs_match_generation(datasets, generated)

    datasets["2"].bootstrap.matches[0].home_goals = 2
    with pytest.raises(ManualUpdateError, match="discrepa entre el catálogo"):
        _assert_group_catalogs_match_generation(datasets, generated)
