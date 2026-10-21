"""Offline regression coverage for shared incremental competition sections."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from football_data_hub_api.manual_updates import (
    ManualUpdateError,
    ManualUpdateManager,
    _legacy_statistics_section_identity,
    _activate_group_data_pointer,
    _candidate_sha256,
    _related_section_content_sha256,
    _tree_sha256,
    apply_active_group_section,
)


def test_legacy_statistics_identity_requires_exact_group_stats_url_and_http_evidence(tmp_path: Path) -> None:
    root = tmp_path / "capture"
    (root / "raw").mkdir(parents=True)
    expected_url = "https://www.bdfutbol.com/es/t/t2026-271rf1.html?tab=stats"
    metadata = {
        "section": None,
        "requested_url": expected_url,
        "final_url": expected_url,
        "http_status": 200,
    }
    (root / "raw/access.json").write_text(json.dumps({
        "status": "VALID", "requested_url": expected_url,
        "final_url": expected_url, "http_status": 200,
    }), encoding="utf-8")
    validation = {"source_page": {
        "access_status": "VALID", "http_status": 200,
        "requested_url": expected_url, "final_url": expected_url,
    }}

    assert _legacy_statistics_section_identity(root, metadata, validation, "I") is True
    assert _legacy_statistics_section_identity(root, metadata, validation, "II") is False
    assert _legacy_statistics_section_identity(
        root, metadata, {"source_page": {**validation["source_page"], "http_status": 403}}, "I"
    ) is False


def _manager(tmp_path: Path, *, related: dict[str, object] | None = None) -> ManualUpdateManager:
    project = tmp_path / "project"
    data = tmp_path / "external"
    profile = tmp_path / "profile"
    project.mkdir()
    data.mkdir()
    profile.mkdir()
    paths: dict[str, Path] = {}
    for group in ("I", "II"):
        for kind in ("matches", "classification", "progress"):
            path = data / f"{group}-{kind}.json"
            path.write_text("{}", encoding="utf-8")
            paths[f"{group}-{kind}"] = path
    generation = data / "matches/generations"
    generation.mkdir(parents=True)
    details = data / "matches/details"
    details.mkdir()
    return ManualUpdateManager(
        project_root=project,
        data_root=data,
        profile_dir=profile,
        browser_executable=None,
        group_match_paths={group: paths[f"{group}-matches"] for group in ("I", "II")},
        group_classification_paths={group: paths[f"{group}-classification"] for group in ("I", "II")},
        group_progress_paths={group: paths[f"{group}-progress"] for group in ("I", "II")},
        team_profiles_index=None,
        match_generation_root=generation,
        match_details_store_root=details,
        player_inventory_root=None,
        player_compact_root=None,
        player_team_captures_root=None,
        player_published_index_path=None,
        group_related_settings=related,  # type: ignore[arg-type]
    )


def _write_capture(root: Path, section: str, group: str | None, *, value: int = 1) -> Path:
    root.mkdir(parents=True)
    (root / "metadata").mkdir()
    (root / "normalized").mkdir()
    (root / "validation").mkdir()
    capture = {
        "capture_id": root.name,
        "source": "BDFutbol",
        "competition": "Primera Federación",
        "season": "2026-27",
        "group": group or "I/II",
        "section": section,
    }
    (root / "metadata/capture.json").write_text(json.dumps(capture), encoding="utf-8")
    (root / "validation/results.json").write_text(json.dumps({"valid": True}), encoding="utf-8")
    names = {
        "top": ("players", "rankings", "progress", "foreigners"),
        "statistics": ("derived_statistics", "exclusive_statistics"),
        "referees": ("referees", "statistics", "filter_options"),
    }[section]
    for name in names:
        (root / f"normalized/{name}.json").write_text(
            json.dumps({"records": [{"id": name, "value": value}], "metadata": {"capture_id": root.name}}),
            encoding="utf-8",
        )
    return root


def test_related_capture_comparison_ignores_capture_only_metadata(tmp_path: Path) -> None:
    first = _write_capture(tmp_path / "one", "top", "I")
    second = _write_capture(tmp_path / "two", "top", "I")
    assert _related_section_content_sha256(first, "top") == _related_section_content_sha256(second, "top")


def test_related_capture_comparison_detects_normalized_sports_changes(tmp_path: Path) -> None:
    first = _write_capture(tmp_path / "one", "statistics", "I", value=1)
    second = _write_capture(tmp_path / "two", "statistics", "I", value=2)
    assert _related_section_content_sha256(first, "statistics") != _related_section_content_sha256(second, "statistics")


def test_related_sections_activate_atomically_without_replacing_core_results(tmp_path: Path) -> None:
    data = tmp_path / "data"
    capture = _write_capture(data / "operations/capture-top", "top", "I")
    pointer_dir = data / "operations/manual-updates"
    pointer_dir.mkdir(parents=True)
    original_pointer = {
        "schema_version": "football_data_hub.manual_group_data.v1",
        "season": "2026-27",
        "groups": {"I": {"matches": {"path": "preserved/matches.json", "sha256": "x"}}},
    }
    (pointer_dir / "active-group-data.json").write_text(json.dumps(original_pointer), encoding="utf-8")
    candidate = {
        "no_changes": True,
        "no_competition_changes": True,
        "related_sections": {
            "groups": {
                "I": {
                    "top": {
                        "path": str(capture),
                        "sha256": _tree_sha256(capture),
                        "capture_id": capture.name,
                    }
                }
            }
        },
    }

    _activate_group_data_pointer(data, candidate)

    pointer = json.loads((pointer_dir / "active-group-data.json").read_text())
    assert pointer["schema_version"] == "football_data_hub.manual_group_data.v2"
    assert pointer["groups"] == original_pointer["groups"]
    assert pointer["sections"]["groups"]["I"]["top"]["capture_id"] == capture.name
    assert list((pointer_dir / "active-group-data-history").glob("*.json"))


def test_active_section_hash_corruption_is_rejected_without_affecting_core_pointer(tmp_path: Path) -> None:
    from football_data_hub.providers.bdfutbol.context import get_competition_context
    from football_data_hub_api.config import GroupDatasetSettings

    data = tmp_path / "data"
    capture = _write_capture(data / "captures/top", "top", "I")
    _activate_group_data_pointer(data, {
        "no_changes": True,
        "related_sections": {"groups": {"I": {"top": {
            "path": str(capture), "sha256": _tree_sha256(capture), "capture_id": capture.name,
        }}}},
    })
    settings = GroupDatasetSettings(
        context=get_competition_context(group=1),
        matches_path=tmp_path / "matches.json",
        classification_path=tmp_path / "classification.json",
        progress_path=tmp_path / "progress.json",
        capture_metadata_path=tmp_path / "capture.json",
    )
    (capture / "normalized/players.json").write_text("corrupt", encoding="utf-8")

    with pytest.raises(ManualUpdateError, match="hash de una captura activa"):
        apply_active_group_section(settings, "I", data, "top")
    assert json.loads((data / "operations/manual-updates/active-group-data.json").read_text())["groups"] == {}


def test_related_capture_failure_stops_following_browser_commands_and_keeps_prior_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager(tmp_path)
    calls: list[list[str]] = []
    monkeypatch.setattr("football_data_hub_api.manual_updates.time.sleep", lambda _seconds: None)

    def fail_first(args, _log, *, timeout):
        calls.append(args)
        raise ManualUpdateError("fuente denegada")

    monkeypatch.setattr(manager, "_command", fail_first)
    monkeypatch.setattr(manager, "_validate_related_capture", lambda *_args: None)
    output, status = manager._capture_related_sections(
        {"job_id": str(uuid.uuid4())},
        tmp_path / "worker.log",
        roots={"I": tmp_path, "II": tmp_path},
        normalized={"I": tmp_path / "i.json", "II": tmp_path / "ii.json"},
    )

    assert calls and len(calls) == 1
    assert output == {"groups": {}}
    assert status["groups"]["I"]["top"]["status"] == "error"
    assert status["groups"]["I"]["statistics"]["status"] == "not_attempted"
    assert status["groups"]["II"]["top"]["status"] == "not_attempted"
    assert status["referees"]["status"] == "not_attempted"
    manager.close()


def test_no_results_changes_can_apply_only_changed_related_sections_and_reload_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager(tmp_path)
    capture = _write_capture(manager.data_root / "operations/top", "top", "I")  # type: ignore[operator]
    candidate = {
        "kind": "competition_generation",
        "no_changes": True,
        "no_competition_changes": True,
        "related_sections_changed": True,
        "related_sections": {"groups": {"I": {"top": {
            "path": str(capture), "sha256": _tree_sha256(capture), "capture_id": capture.name,
        }}}},
        "related_section_status": {"groups": {"I": {"top": {"status": "changed"}}}},
        "changed_groups": {"I": [], "II": []},
    }
    digest = _candidate_sha256(candidate)
    candidate["candidate_sha256"] = digest
    job = {
        "job_id": str(uuid.uuid4()), "candidate": candidate, "candidate_sha256": digest,
        "scope": "competition", "status": "running",
    }
    reloads: list[str] = []
    monkeypatch.setattr(manager, "_safe_process_new_match_details", lambda _job: {"match_details_published_count": 0})
    manager.on_competition_applied = lambda _job: reloads.append("reloaded")

    manager._finish_competition_update(job, tmp_path / "worker.log", no_changes=True)

    assert job["status"] == "applied"
    assert reloads == ["reloaded"]
    pointer = json.loads((manager.data_root / "operations/manual-updates/active-group-data.json").read_text())  # type: ignore[operator]
    assert pointer["sections"]["groups"]["I"]["top"]["capture_id"] == capture.name
    assert {item.name for item in (manager.root / "reviews").glob("*.json")} == {  # type: ignore[operator]
        f"{job['job_id']}-sections-apply-started.json", f"{job['job_id']}-sections-applied.json",
    }
    manager.close()


def test_related_source_error_is_recorded_as_partial_when_another_source_was_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
    assert manager.data_root is not None
    capture = _write_capture(manager.data_root / "top-capture", "top", "I")
    candidate = {
        "kind": "competition_generation",
        "no_changes": True,
        "no_competition_changes": True,
        "related_sections_changed": True,
        "related_sections": {"groups": {"I": {"top": {
            "path": str(capture), "sha256": _tree_sha256(capture), "capture_id": capture.name,
        }}}},
        "related_section_status": {"groups": {"I": {
            "top": {"status": "changed", "capture_id": capture.name},
            "statistics": {"status": "error", "reason": "La metadata no declaraba la sección."},
        }, "II": {
            "top": {"status": "not_attempted", "reason": "falló Estadísticas Grupo I"},
        }}, "referees": {"status": "not_attempted", "reason": "falló Estadísticas Grupo I"}},
        "changed_groups": {"I": [], "II": []},
    }
    candidate_digest = _candidate_sha256(candidate)
    candidate["candidate_sha256"] = candidate_digest
    job = {
        "job_id": str(uuid.uuid4()),
        "candidate": candidate,
        "candidate_sha256": candidate_digest,
        "scope": "competition",
        "status": "running",
    }
    monkeypatch.setattr(manager, "_safe_process_new_match_details", lambda _job: {
        "match_details_candidate_count": 0,
        "match_details_pending_count": 0,
        "match_details_published_count": 0,
        "match_details_error": "ScalableCampaignError: Entrada inesperada en review v2",
        "match_details_stopped": True,
    })

    manager._finish_competition_update(job, tmp_path / "worker.log", no_changes=True)

    assert job["status"] == "applied"
    assert job["summary"]["outcome"] == "partial"
    assert job["summary"]["message"].startswith("Actualización parcial")
    assert job["summary"]["related_section_status"]["groups"]["I"]["statistics"]["status"] == "error"
    assert json.loads((manager.data_root / "operations/manual-updates/active-group-data.json").read_text())["sections"]["groups"]["I"]["top"]["capture_id"] == capture.name  # type: ignore[operator]
    manager.close()


def test_related_only_reload_does_not_revalidate_existing_published_match_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from football_data_hub_api import main as api_main
    from football_data_hub_api.config import ApiSettings

    requested: list[set[str] | None] = []
    new_document = object()

    def load_details(*_args, internal_ids=None, **_kwargs):
        requested.append(internal_ids)
        return {"new-publication": new_document}

    monkeypatch.setattr(api_main, "load_published_match_details", load_details)
    app = SimpleNamespace(state=SimpleNamespace(
        match_results=object(),
        player_directory=None,
        match_detail_documents={"existing-publication": object()},
        match_detail_publication_error="old error",
    ))
    configured = ApiSettings(
        matches_path=tmp_path / "matches.json",
        classification_path=tmp_path / "classification.json",
        progress_path=tmp_path / "progress.json",
        capture_metadata_path=tmp_path / "capture.json",
        match_details_published_root=tmp_path / "published",
        match_details_store_root=tmp_path / "store",
        match_generation_root=tmp_path / "generation",
        local_data_root=tmp_path / "data",
    )

    api_main._reload_match_details_after_manual_update(
        app, configured, SimpleNamespace(),
        {"_match_details_published_internal_ids": ["new-publication"]},
    )

    assert requested == [{"new-publication"}]
    assert set(app.state.match_detail_documents) == {
        "existing-publication", "new-publication",
    }
    assert app.state.match_detail_documents["new-publication"] is new_document
    assert app.state.match_detail_publication_error is None


def test_related_only_api_reload_skips_core_generation_and_team_registries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from football_data_hub_api import main as api_main
    from football_data_hub_api.config import ApiSettings, GroupDatasetSettings
    from football_data_hub.providers.bdfutbol.context import get_competition_context

    base = GroupDatasetSettings(
        context=get_competition_context(group=1),
        matches_path=tmp_path / "matches.json",
        classification_path=tmp_path / "classification.json",
        progress_path=tmp_path / "progress.json",
        capture_metadata_path=tmp_path / "capture.json",
    )
    active = SimpleNamespace(bootstrap=SimpleNamespace(
        teams=[], metadata=SimpleNamespace(capture_id="core-capture")
    ))
    loaded_top = object()
    monkeypatch.setattr(api_main, "apply_active_group_section", lambda settings, *_args: settings)
    monkeypatch.setattr(api_main, "load_top_dataset", lambda *_args, **_kwargs: loaded_top)
    monkeypatch.setattr(api_main, "load_dataset", lambda *_args: pytest.fail("core dataset reloaded"))
    monkeypatch.setattr(api_main, "load_match_results_dataset", lambda *_args, **_kwargs: pytest.fail("MATCH generation reloaded"))
    monkeypatch.setattr(api_main, "load_team_roster_registry", lambda *_args, **_kwargs: pytest.fail("team roster reloaded"))

    prior_details = {"published": object()}
    app = SimpleNamespace(state=SimpleNamespace(
        datasets={"1": active, "2": active},
        group_settings={"1": base, "2": base},
        top_datasets={"1": object(), "2": object()},
        top_dataset_errors={},
        statistics_datasets={"1": object(), "2": object()},
        statistics_dataset_errors={},
        referee_dataset=object(),
        referee_dataset_error=None,
        referee_group_errors={},
        match_results=object(),
        match_detail_documents=prior_details,
        team_roster_registry=object(),
        team_follow_registry=object(),
        team_transfers_registry=object(),
        dataset_errors={},
        player_directory=None,
        match_results_error=None,
        match_detail_publication_error=None,
    ))
    manager = SimpleNamespace(
        group_related_settings={"I": base, "II": base},
        group_match_paths={}, group_classification_paths={}, group_progress_paths={},
    )
    configured = ApiSettings(
        matches_path=base.matches_path,
        classification_path=base.classification_path,
        progress_path=base.progress_path,
        capture_metadata_path=base.capture_metadata_path,
        local_data_root=tmp_path,
    )
    job = {"scope": "competition", "candidate": {
        "no_changes": True,
        "no_competition_changes": True,
        "related_sections": {"groups": {"I": {"top": {"capture_id": "new-top"}}}},
    }}

    api_main._reload_after_manual_update(app, configured, manager, job)

    assert app.state.top_datasets["1"] is loaded_top
    assert app.state.top_datasets["2"] is not loaded_top
    assert app.state.match_results is not None
    assert app.state.match_detail_documents is prior_details
    assert manager.group_match_paths == {}
