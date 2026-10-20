"""Offline tests for automatic, validated competition refresh and shared fixtures."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from football_data_hub_api.main import _assert_group_catalogs_match_generation
from football_data_hub_api.manual_updates import (
    ManualUpdateError,
    ManualUpdateManager,
    _candidate_sha256,
    _last_json_object,
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
    pending_report_checks: list[str] = []
    monkeypatch.setattr(
        manager,
        "_safe_process_new_match_details",
        lambda current: pending_report_checks.append(current["job_id"]) or {
            "match_details_published_count": 0,
            "match_details_pending_count": 0,
        },
    )
    monkeypatch.setattr(manager, "_activate_competition", lambda *_args: pytest.fail("No debe activarse una captura sin cambios"))
    manager._finish_competition_update(job, manager._jobs_dir() / job["job_id"] / "worker.log", no_changes=True)
    assert job["status"] == "completed"
    assert job["summary"]["message"] == "Sin cambios"
    assert pending_report_checks == [job["job_id"]]
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


def test_public_failed_job_explains_existing_match_validation_collision_without_paths() -> None:
    private_path = "/home/private/update/normalized/validation/matches.json"
    projected = public_manual_update_job({
        "job_id": "failed-job", "scope": "competition", "status": "failed", "stage": "failed",
        "error": "ManualUpdateError: El proceso terminó con código 1; no se reintentó.",
        "log_tail": (
            "$ python scripts/extract_bdfutbol_matches.py --snapshot group-ii/raw/source.html\n"
            f"FileExistsError: [Errno 17] File exists: '{private_path}'\n"
        ),
    })

    assert projected is not None
    assert projected["error"] == (
        "Falló la normalización de partidos del Grupo II: el informe de validación ya "
        "existía en una ruta compartida. Las capturas se conservaron y no se reintentó "
        "la adquisición."
    )
    assert private_path not in str(projected)


def test_subprocess_failure_includes_a_concise_exception_diagnostic(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    with pytest.raises(ManualUpdateError, match="RuntimeError: datos de prueba"):
        manager._command(
            [sys.executable, "-c", "raise RuntimeError('datos de prueba')"],
            tmp_path / "worker.log",
            timeout=10,
        )
    manager.close()


def test_last_json_object_selects_small_activation_receipt_after_larger_capture_receipts() -> None:
    earlier_group_receipt = json.dumps({
        "group": "II",
        "files": {"raw_snapshot": "/external/path/" + "x" * 400, "metadata": "capture.json"},
        "validation": {"checks": 8, "failures": 0},
    }, indent=2)
    activation_receipt = json.dumps({
        "activation_id": "activation-123",
        "generation_id": "match-00-candidate",
        "report_sha256": "a" * 64,
        "status": "activated",
    }, indent=2)

    assert _last_json_object(
        f"first capture\n{earlier_group_receipt}\nactivated\n{activation_receipt}\n"
    ) == json.loads(activation_receipt)


def test_last_json_object_returns_outer_receipt_when_it_contains_nested_objects() -> None:
    receipt = {"status": "complete", "details": {"checks": 4, "valid": True}}
    assert _last_json_object(f"prefix\n{json.dumps(receipt, indent=2)}\n") == receipt


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


def test_auto_detail_pipeline_targets_only_unpublished_unblocked_played_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from football_data_hub.providers.bdfutbol.match_details import (
        campaign_operations,
        operational_campaign,
        scalable_campaign_cli,
        scalable_campaigns,
        supervised_acquisition,
    )

    manager = _manager(tmp_path)
    data = manager.data_root
    assert data is not None
    # Production config may give the manager the MATCH store root (which has
    # active-generation.json); _load_report resolves it to this concrete path.
    manager.match_generation_root = data / "matches"
    resolved_generation_root = data / "matches" / "generations" / "match-00-verified-active"
    resolved_generation_root.mkdir(parents=True)
    manager.match_details_published_root = data / "matches/details/published"
    manager.match_details_published_root.mkdir(parents=True)
    manager.player_inventory_root = data / "players/inventory-2026-27"
    manager.player_inventory_root.mkdir(parents=True)
    manager.player_compact_root = data / "players/compact-2026-27"
    manager.player_compact_root.mkdir(parents=True)
    manager.player_team_captures_root = data / "team-captures"
    manager.player_team_captures_root.mkdir()
    manager.player_published_index_path = data / "published/team_profiles_2026-27.json"
    manager.player_published_index_path.parent.mkdir()
    manager.player_published_index_path.write_text("{}", encoding="utf-8")

    def fixture(source_id: str, status: str) -> dict[str, object]:
        return {
            "internal_id": f"pf-2026-27-group-ii-bdfutbol-{source_id}",
            "source_match_id": source_id,
            "source_match_url": f"https://www.bdfutbol.com/es/p/p.php?id={source_id}",
            "group": "II",
            "matchday": 8,
            "matchday_date": "2026-10-18",
            "home_team_id": 49,
            "away_team_id": 16,
            "reference_result": {"home_goals": 1, "away_goals": 0},
            "status": "played",
            "detail_status": status,
            "blocked_reasons": [],
        }

    pending = fixture("272590", "played_pending_acquisition")
    legacy_unstarted = fixture("272591", "included_in_existing_campaign")
    blocked = fixture("272582", "blocked_requires_human_review")
    published = fixture("270001", "published_approved")
    blocked["blocked_reasons"] = ["historical_access_block"]
    rows = [pending, legacy_unstarted, blocked, published]
    context = {
        "generation_root": resolved_generation_root,
        "published_ids": {published["internal_id"]},
        "captured_ids": set(),
        "blocked_ids": {blocked["internal_id"]},
    }
    monkeypatch.setattr(scalable_campaign_cli, "_load_report", lambda _args: ({"matches": rows}, [], context))

    proposal: dict[str, object] = {}
    campaign_id = "match-detail-campaign-v2-0123456789abcdef"

    def build_proposal(_report, *, internal_ids):
        proposal["ids"] = list(internal_ids)
        return {"campaign_id": campaign_id, "candidate_count": len(internal_ids)}

    monkeypatch.setattr(scalable_campaigns, "build_match_campaign_proposal", build_proposal)
    monkeypatch.setattr(scalable_campaigns, "write_match_campaign_proposal", lambda *_args: tmp_path / "proposal")

    class FakeLedger:
        def __init__(self, root: Path):
            self.root = root

        def initialize(self, **kwargs):
            assert kwargs["generation_root"] == resolved_generation_root
            return {"status": "CAMPAIGN_INITIALIZED"}

        def source_inventory(self, _campaign_id):
            return {"matches": []}

    monkeypatch.setattr(operational_campaign, "OperationalMatchCampaignLedger", FakeLedger)

    def acquire(**kwargs):
        assert kwargs["campaign_id"] == campaign_id
        assert kwargs["context"]["blocked_ids"] == {blocked["internal_id"]}
        return {"captured_count": 2, "navigation_requests": 2, "stop_acquisition": False}

    monkeypatch.setattr(supervised_acquisition, "run_competition_update_detail_acquisition", acquire)

    def process_offline(**kwargs):
        assert kwargs["auto_publish_policy"] is True
        assert kwargs["published_root"] == manager.match_details_published_root
        return {"published_count": 1, "policy_pending_count": 1}

    monkeypatch.setattr(campaign_operations, "run_offline_batch", process_offline)
    reloads: list[bool] = []
    manager.on_match_details_published = lambda _job: reloads.append(True)

    result = manager._process_new_match_details({"job_id": str(uuid.uuid4())})

    assert proposal["ids"] == [pending["internal_id"], legacy_unstarted["internal_id"]]
    assert blocked["internal_id"] not in proposal["ids"]
    assert published["internal_id"] not in proposal["ids"]
    assert result["match_details_candidate_count"] == 2
    assert result["match_details_captured_count"] == 2
    assert result["match_details_navigation_count"] == 2
    assert result["match_details_published_count"] == 1
    assert result["match_details_pending_count"] == 1
    assert result["match_details_blocked_excluded_count"] == 1
    assert reloads == [True]
    manager.close()


def test_auto_detail_pipeline_reuses_exact_unstarted_proposal_without_duplicate_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from football_data_hub.providers.bdfutbol.match_details import (
        campaign_operations,
        operational_campaign,
        scalable_campaign_cli,
        scalable_campaigns,
        supervised_acquisition,
    )

    manager = _manager(tmp_path)
    data = manager.data_root
    assert data is not None
    manager.match_generation_root = data / "matches"
    generation = data / "matches/generations/match-00-verified-active"
    generation.mkdir(parents=True)
    manager.match_details_published_root = data / "matches/details/published"
    manager.match_details_published_root.mkdir(parents=True)
    manager.player_inventory_root = data / "players/inventory-2026-27"
    manager.player_inventory_root.mkdir(parents=True)
    manager.player_compact_root = data / "players/compact-2026-27"
    manager.player_compact_root.mkdir(parents=True)
    manager.player_team_captures_root = data / "team-captures"
    manager.player_team_captures_root.mkdir()
    manager.player_published_index_path = data / "published/team_profiles_2026-27.json"
    manager.player_published_index_path.parent.mkdir()
    manager.player_published_index_path.write_text("{}", encoding="utf-8")

    def fixture(source_id: str, status: str) -> dict[str, object]:
        return {
            "internal_id": f"pf-2026-27-group-i-bdfutbol-{source_id}",
            "source_match_id": source_id,
            "source_match_url": f"https://www.bdfutbol.com/es/p/p.php?id={source_id}",
            "group": "I",
            "matchday": 8,
            "matchday_date": "2026-10-18",
            "home_team_id": 20,
            "away_team_id": 21,
            "reference_result": {"home_goals": 0, "away_goals": 1},
            "status": "played",
            "detail_status": status,
            "blocked_reasons": [],
        }

    rows = [fixture("269478", "included_in_existing_campaign"), fixture("269479", "included_in_existing_campaign")]
    campaign_id = "match-detail-campaign-v2-0123456789abcdef"
    proposal_id = "match-detail-campaign-plan-0123456789abcdef"
    proposal_dir = manager.match_details_store_root / "campaign-proposals/plans" / proposal_id
    plan = {
        "campaign_id": campaign_id,
        "proposal_id": proposal_id,
        "source": {"generation_id": generation.name},
        "authorization": {"status": "NOT_AUTHORIZED", "is_authorization": False},
        "candidates": [{"internal_id": row["internal_id"]} for row in rows],
        "candidate_count": len(rows),
    }
    context = {
        "generation_root": generation,
        "published_ids": set(),
        "captured_ids": set(),
        "blocked_ids": set(),
    }
    monkeypatch.setattr(
        scalable_campaign_cli,
        "_load_report",
        lambda _args: ({"matches": rows}, [plan], context),
    )
    monkeypatch.setattr(
        scalable_campaigns,
        "build_match_campaign_proposal",
        lambda *_args, **_kwargs: pytest.fail("No debe duplicar una propuesta idéntica"),
    )
    monkeypatch.setattr(
        scalable_campaigns,
        "write_match_campaign_proposal",
        lambda *_args, **_kwargs: pytest.fail("No debe escribir un segundo plan"),
    )

    initialized: list[dict[str, object]] = []

    class FakeLedger:
        def __init__(self, root: Path):
            self.root = root

        def initialize(self, **kwargs):
            initialized.append(kwargs)
            assert kwargs["proposal_dir"] == proposal_dir
            assert kwargs["generation_root"] == generation
            return {"status": "CAMPAIGN_INITIALIZED_NOT_AUTHORIZED", "candidate_count": 2}

        def source_inventory(self, _campaign_id):
            return {"matches": []}

    monkeypatch.setattr(operational_campaign, "OperationalMatchCampaignLedger", FakeLedger)

    def acquire(**kwargs):
        assert kwargs["campaign_id"] == campaign_id
        # This unit test only verifies orchestration; no browser adapter is called.
        return {"captured_count": 0, "navigation_requests": 0, "stop_acquisition": False}

    monkeypatch.setattr(supervised_acquisition, "run_competition_update_detail_acquisition", acquire)
    monkeypatch.setattr(
        campaign_operations,
        "run_offline_batch",
        lambda **_kwargs: pytest.fail("No hay capturas que procesar en esta prueba"),
    )

    result = manager._process_new_match_details({"job_id": str(uuid.uuid4())})

    assert len(initialized) == 1
    assert result["match_details_candidate_count"] == 2
    assert result["match_details_navigation_count"] == 0
    manager.close()


def test_global_update_processes_saved_auto_authorized_campaign_before_acquisition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from football_data_hub.providers.bdfutbol.match_details import (
        campaign_operations,
        operational_campaign,
        scalable_campaign_cli,
        supervised_acquisition,
    )

    manager = _manager(tmp_path)
    data = manager.data_root
    assert data is not None
    manager.match_generation_root = data / "matches"
    generation = data / "matches/generations/match-00-active"
    generation.mkdir(parents=True)
    manager.match_details_store_root = data / "matches/details"
    manager.match_details_store_root.mkdir(parents=True, exist_ok=True)
    manager.match_details_published_root = data / "matches/details/published"
    manager.match_details_published_root.mkdir(parents=True)
    manager.player_inventory_root = data / "players/inventory"
    manager.player_inventory_root.mkdir(parents=True)
    manager.player_compact_root = data / "players/compact"
    manager.player_compact_root.mkdir(parents=True)
    manager.player_team_captures_root = data / "team-captures"
    manager.player_team_captures_root.mkdir()
    manager.player_published_index_path = data / "published/teams.json"
    manager.player_published_index_path.parent.mkdir(parents=True)
    manager.player_published_index_path.write_text("{}\n", encoding="utf-8")

    internal_id = "pf-2026-27-group-ii-bdfutbol-272590"
    campaign_id = "match-detail-campaign-v2-0123456789abcdef"
    (manager.match_details_store_root / "campaigns" / campaign_id).mkdir(parents=True)
    row = {
        "internal_id": internal_id,
        "source_match_id": "272590",
        "source_match_url": "https://www.bdfutbol.com/es/p/p.php?id=272590",
        "group": "II",
        "matchday": 8,
        "status": "played",
        "detail_status": "included_in_existing_campaign",
        "blocked_reasons": [],
    }
    proposal = {"campaign_id": campaign_id, "source": {"generation_id": generation.name}}
    context_before = {
        "generation_root": generation,
        "active_generation_id": generation.name,
        "active_generation_manifest_sha256": "a" * 64,
        "published_ids": set(),
        "captured_ids": {internal_id},
        "blocked_ids": set(),
        "match_bundle": None,
        "player_ids": set(),
    }
    reports = [({"matches": [row]}, [proposal], context_before)]
    monkeypatch.setattr(scalable_campaign_cli, "_load_report", lambda _args: reports.pop(0))

    class FakeLedger:
        def __init__(self, root: Path):
            self.root = root

        def preflight(self, _campaign_id):
            return {
                "source_generation_id": generation.name,
                "source_generation_manifest_sha256": "a" * 64,
                "candidates": [{
                    "internal_id": internal_id,
                    "authorization_mode": "competition_update_auto_policy",
                    "state": "VALIDATION_FAILED",
                    "artifact": {"artifact_id": "saved", "source_html_sha256": "b" * 64},
                }],
            }

    monkeypatch.setattr(operational_campaign, "OperationalMatchCampaignLedger", FakeLedger)
    offline_calls = []

    def process_saved(**kwargs):
        offline_calls.append(kwargs)
        return {
            "published_count": 1,
            "policy_pending_count": 0,
            "validation_failed_count": 0,
            "error_count": 0,
            "candidates": [{"internal_id": internal_id, "status": "PUBLISHED_VERIFIED"}],
        }

    monkeypatch.setattr(campaign_operations, "run_offline_batch", process_saved)
    monkeypatch.setattr(
        supervised_acquisition,
        "run_competition_update_detail_acquisition",
        lambda **_kwargs: pytest.fail("Una captura guardada válida no debe navegar otra vez"),
    )
    reloads = []
    manager.on_match_details_published = lambda _job: reloads.append(True)

    result = manager._process_new_match_details({"job_id": str(uuid.uuid4())})

    assert result["match_details_published_count"] == 1
    assert result["match_details_navigation_count"] == 0
    assert result["match_details_campaigns_processed"] == [campaign_id]
    assert offline_calls[0]["internal_ids"] == {internal_id}
    assert offline_calls[0]["auto_publish_policy"] is True
    assert reloads == [True]
    assert reports == []
    manager.close()
