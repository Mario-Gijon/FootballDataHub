from __future__ import annotations

import json
from pathlib import Path

import pytest

from football_data_hub.providers.bdfutbol.teams.batch import (
    BatchAccessDenied,
    BatchStop,
    BatchTeamOutcome,
    find_valid_capture,
    run_team_batch,
    write_batch_manifest,
)


def _team(team_id: int) -> dict[str, object]:
    return {"team_id": team_id, "name": f"Equipo {team_id}"}


def test_batch_skips_complete_capture_and_continues_after_local_error():
    calls: list[int] = []

    def process(group: int, team: dict, views: tuple[str, ...]) -> BatchTeamOutcome:
        calls.append(int(team["team_id"]))
        if team["team_id"] == 2:
            raise ValueError("estructura local inválida")
        return BatchTeamOutcome("capture-3", views)

    manifest = run_team_batch(
        teams_by_group={1: [_team(1), _team(2)], 2: [_team(3)]},
        groups=(1, 2),
        requested_views=("alignment", "statistics"),
        find_complete_capture=lambda group, team_id, views: "capture-1" if team_id == 1 else None,
        find_partial_capture=lambda group, team_id: None,
        process_team=process,
    )
    assert calls == [2, 3]
    assert [item["status"] for item in manifest["teams"]] == ["complete", "failed", "complete"]
    assert manifest["teams"][0]["reused_existing_capture"] is True
    assert manifest["teams"][1]["failure_class"] == "local_acquisition_or_validation"
    assert manifest["stopped_on_access_denial"] is False


def test_batch_denial_stops_future_navigation_and_leaves_pending_teams():
    calls: list[int] = []

    def process(group: int, team: dict, views: tuple[str, ...]) -> BatchTeamOutcome:
        team_id = int(team["team_id"])
        calls.append(team_id)
        if team_id == 2:
            raise BatchAccessDenied("HTTP 403; CHALLENGE_REQUIRED")
        return BatchTeamOutcome(f"capture-{team_id}", views)

    manifest = run_team_batch(
        teams_by_group={1: [_team(1), _team(2), _team(3), _team(4)]},
        groups=(1,),
        requested_views=("alignment", "follow"),
        find_complete_capture=lambda *_args: None,
        find_partial_capture=lambda group, team_id: "old-partial" if team_id == 2 else None,
        process_team=process,
    )
    assert calls == [1, 2]
    assert [item["status"] for item in manifest["teams"]] == ["complete", "incomplete", "pending", "pending"]
    assert manifest["teams"][1]["capture_id"] == "old-partial"
    assert manifest["teams"][1]["failure_class"] == "access_denied"
    assert manifest["stop_reason"]["team_id"] == 2


def test_batch_stops_after_environment_failure_without_calling_next_team():
    calls: list[int] = []

    def process(group: int, team: dict, views: tuple[str, ...]) -> BatchTeamOutcome:
        calls.append(int(team["team_id"]))
        raise BatchStop("Xvfb no disponible", kind="browser_environment_error")

    manifest = run_team_batch(
        teams_by_group={1: [_team(1), _team(2)]},
        groups=(1,),
        requested_views=("alignment",),
        find_complete_capture=lambda *_args: None,
        find_partial_capture=lambda *_args: None,
        process_team=process,
    )
    assert calls == [1]
    assert [item["status"] for item in manifest["teams"]] == ["failed", "pending"]
    assert manifest["stopped_on_access_denial"] is False


def test_batch_manifest_is_versioned_create_only(tmp_path: Path):
    manifest = {
        "run_id": "batch-test",
        "teams": [],
    }
    path = write_batch_manifest(tmp_path, manifest)
    assert json.loads(path.read_text()) == manifest
    with pytest.raises(FileExistsError):
        write_batch_manifest(tmp_path, manifest)


def test_complete_capture_resume_checks_full_view_set_hashes(tmp_path: Path):
    run = tmp_path / "2026-27" / "48" / "capture-1"
    (run / "metadata").mkdir(parents=True)
    (run / "validation").mkdir()
    (run / "raw").mkdir()
    raw = b"<html>valid source</html>"
    (run / "raw" / "alignment.html").write_bytes(raw)
    metadata = {
        "capture_id": "capture-1",
        "team_id": 48,
        "created_at_utc": "2026-10-11T10:00:00+00:00",
        "requested_views": ["alignment"],
        "source_snapshots": {
            "alignment": {
                "path": "raw/alignment.html",
                "sha256": __import__("hashlib").sha256(raw).hexdigest(),
                "http_status": 200,
                "access_status": "VALID",
            }
        },
    }
    (run / "metadata" / "capture.json").write_text(json.dumps(metadata))
    (run / "validation" / "results.json").write_text(json.dumps({"valid": True}))
    assert find_valid_capture(tmp_path, season="2026-27", team_id=48, required_views=("alignment",))[0] == "capture-1"
    assert find_valid_capture(tmp_path, season="2026-27", team_id=48, required_views=("alignment", "statistics")) is None
    (run / "raw" / "alignment.html").write_bytes(b"changed")
    assert find_valid_capture(tmp_path, season="2026-27", team_id=48, required_views=("alignment",)) is None
