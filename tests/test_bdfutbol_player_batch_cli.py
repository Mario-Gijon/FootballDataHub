from __future__ import annotations

import json
from pathlib import Path

import acquire_bdfutbol_players as batch_cli


def _plan_and_progress() -> tuple[dict, dict, dict[int, str]]:
    summary = {
        "inventory_players": 1,
        "roster_players": 1,
        "transfer_only_players": 0,
        "players_with_all_base_views": 0,
        "captured_valid_base_views": 0,
        "base_view_navigations_pending": 1,
    }
    progress = {
        "players": [{"player_id": 501, "status": "PENDING"}],
        "pending_views": [{"player_id": 501, "view": "profile"}],
        "summary": summary,
    }
    return {"status": "READY_FOR_EXPLICIT_EXECUTION"}, progress, {501: "roster"}


def test_mass_cli_checkpoints_ctrl_c_and_resumes_same_capture_without_replanning_navigation(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    capture_root = tmp_path / "captures"
    status_path = tmp_path / "status.json"
    progress_path = tmp_path / "progress.json"
    monkeypatch.setattr(batch_cli, "_make_plan", lambda **_: _plan_and_progress())
    calls: list[dict] = []

    def interrupt(**kwargs: dict) -> None:
        calls.append(kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(batch_cli, "acquire_player_views", interrupt)
    interrupted_code = batch_cli.main([
        "--execute",
        "--capture-root", str(capture_root),
        "--progress-output", str(progress_path),
        "--status-file", str(status_path),
    ])
    assert interrupted_code == 130
    interrupted = json.loads(status_path.read_text(encoding="utf-8"))
    capture_id = interrupted["capture_id"]
    assert interrupted["status"] == "interrupted"
    assert (capture_root / capture_id / "manifest.json").is_file()

    def resume_without_browser(**kwargs: dict) -> dict:
        calls.append(kwargs)
        assert kwargs["capture_id"] == capture_id
        assert kwargs["progress_index"]["pending_views"] == [
            {"player_id": 501, "view": "profile"}
        ]
        return {
            "capture_id": capture_id,
            "capture_dir": str(capture_root / capture_id),
            "snapshot_count": 0,
            "navigation_count": 0,
            "verified_navigation_count_total": 0,
            "status": "complete",
            "filter_variants": 0,
            "reused_snapshot_count": 0,
        }

    monkeypatch.setattr(batch_cli, "acquire_player_views", resume_without_browser)
    monkeypatch.setattr(
        batch_cli,
        "build_player_acquisition_progress",
        lambda **_: {"summary": _plan_and_progress()[1]["summary"]},
    )
    resumed_code = batch_cli.main([
        "--execute",
        "--resume", capture_id,
        "--capture-root", str(capture_root),
        "--progress-output", str(progress_path),
        "--status-file", str(status_path),
    ])
    resumed = json.loads(status_path.read_text(encoding="utf-8"))
    assert resumed_code == 0
    assert resumed["status"] == "complete"
    assert resumed["capture_id"] == capture_id
    assert len(calls) == 2
    capsys.readouterr()
